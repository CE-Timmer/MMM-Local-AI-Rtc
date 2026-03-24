#!/usr/bin/env python3
"""
Wake-word to AI RTC bridge for MMM-Local-AI-Rtc.

Docs checked on 2026-03-23:
https://ai-rtc.cetimmer-web.nl/docs
https://pypi.org/project/openwakeword/

The published AI RTC OpenAPI advertises:
- POST /rtc/offer
- bearer token auth
- offer payload fields: sdp, type, conversation_id, stt_language, voiceprint_gate

The openWakeWord docs indicate:
- `Model.predict(frame)` accepts 16-bit 16 kHz PCM frames
- 80 ms frames are recommended for low-latency streaming use

This script:
- keeps a WebRTC connection open to ai-rtc.cetimmer-web.nl
- uses openWakeWord on a shared 16 kHz microphone stream
- gates microphone audio to the RTC until the wake word is detected
- hides the bubble after 30 seconds of inactivity
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import audioop
import json
import os
import pathlib
import queue
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import sounddevice as sd
from av import AudioFrame, AudioResampler
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
import openwakeword
from openwakeword.model import Model as OpenWakeWordModel


SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_MS = 80
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)
FRAME_BYTES = FRAME_SAMPLES * 2
WAKEWORD_COOLDOWN_SECONDS = 2.0
DOWNLOAD_DIR = pathlib.Path(os.getenv("LOCAL_AI_RTC_CACHE_DIR", pathlib.Path.home() / ".cache" / "local-ai-rtc"))


@dataclass
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 3210
    path: str = "/api/events"
    token: str = ""
    identifier: str = ""
    idle_timeout: float = 30.0

    @property
    def events_url(self) -> str:
        return f"http://{self.host}:{self.port}{self.path}"


@dataclass
class RtcServiceConfig:
    base_url: str = "https://ai-rtc.cetimmer-web.nl"
    token: str = ""
    conversation_id: Optional[str] = None
    stt_language: Optional[str] = None
    voiceprint_gate: Optional[bool] = None
    output_device: Optional[str] = None
    play_remote_audio: bool = False

    @property
    def offer_url(self) -> str:
        return self.base_url.rstrip("/") + "/rtc/offer"

    @property
    def voiceprint_status_url(self) -> str:
        return self.base_url.rstrip("/") + "/voiceprint/status"

    @property
    def voiceprint_enroll_url(self) -> str:
        return self.base_url.rstrip("/") + "/voiceprint/enroll"

    @property
    def voiceprint_delete_url(self) -> str:
        return self.base_url.rstrip("/") + "/voiceprint"


@dataclass
class WakeWordConfig:
    model_name: str = "auto"
    model_file: Optional[str] = None
    model_url: Optional[str] = None
    threshold: float = 0.5
    vad_threshold: Optional[float] = 0.5


@dataclass
class VoiceprintConfig:
    check_status: bool = False
    delete_before_enroll: bool = False
    enroll_audio_path: Optional[str] = None
    enroll_audio_url: Optional[str] = None


class MagicMirrorBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config

    def send_event(self, event: Dict[str, Any]) -> None:
        payload: Dict[str, Any] = {"event": event}
        if self.config.identifier:
            payload["identifier"] = self.config.identifier

        request = urllib.request.Request(
            self.config.events_url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                **(
                    {"Authorization": f"Bearer {self.config.token}"}
                    if self.config.token
                    else {}
                ),
            },
        )

        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                response.read()
        except urllib.error.URLError as error:
            print(f"[bridge] failed to send event {event.get('type')}: {error}")


def ensure_download_dir() -> pathlib.Path:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return DOWNLOAD_DIR


def download_to_cache(url: str, prefix: str) -> pathlib.Path:
    cache_dir = ensure_download_dir()
    parsed = urllib.parse.urlparse(url)
    suffix = pathlib.Path(parsed.path).suffix or ".bin"
    filename = f"{prefix}-{abs(hash(url))}{suffix}"
    target = cache_dir / filename

    if target.exists():
        return target

    request = urllib.request.Request(url, headers={"User-Agent": "local-ai-rtc-bridge"})
    with urllib.request.urlopen(request, timeout=30) as response:
        target.write_bytes(response.read())
    return target


class SharedMicrophone:
    def __init__(self, device: Optional[str] = None) -> None:
        self.device = device if device not in {"", None} else None
        self._buffer = bytearray()
        self._frame_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=200)
        self._stream = None

    def start(self) -> None:
        if self._stream is not None:
            return

        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=self.device,
            callback=self._audio_callback
        )
        self._stream.start()
        print("[mic] shared microphone started")

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read_frame(self, timeout: float = 1.0) -> bytes:
        return self._frame_queue.get(timeout=timeout)

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[mic] status: {status}")

        self._buffer.extend(indata)
        while len(self._buffer) >= FRAME_BYTES:
            frame = bytes(self._buffer[:FRAME_BYTES])
            del self._buffer[:FRAME_BYTES]
            try:
                self._frame_queue.put_nowait(frame)
            except queue.Full:
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    pass
                self._frame_queue.put_nowait(frame)


class OpenWakeWordEngine:
    def __init__(self, microphone: SharedMicrophone, config: WakeWordConfig) -> None:
        self.microphone = microphone
        self.config = config
        self.last_trigger_at = 0.0

        openwakeword.utils.download_models()
        model_kwargs = {"vad_threshold": config.vad_threshold}
        custom_model_path = self._resolve_custom_model_path()
        if custom_model_path is not None:
            model_kwargs["wakeword_models"] = [str(custom_model_path)]

        self.model = OpenWakeWordModel(**model_kwargs)
        self.active_model_name = None
        print(f"[wakeword] openWakeWord ready with model '{config.model_name}'")

    def wait_for_wake_word(self) -> bool:
        while True:
            frame_bytes = self.microphone.read_frame()
            frame = np.frombuffer(frame_bytes, dtype=np.int16)
            predictions = self.model.predict(frame)

            if self._is_triggered(predictions):
                self.last_trigger_at = time.time()
                return True

    def _is_triggered(self, predictions: Dict[str, float]) -> bool:
        now = time.time()
        if now - self.last_trigger_at < WAKEWORD_COOLDOWN_SECONDS:
            return False

        for model_name, score in predictions.items():
            if self.config.model_name not in {"all", "auto", "", None} and model_name != self.config.model_name:
                continue
            if float(score) >= self.config.threshold:
                self.active_model_name = model_name
                print(f"[wakeword] detected '{model_name}' with score {score:.3f}")
                return True
        return False

    def _resolve_custom_model_path(self) -> Optional[pathlib.Path]:
        if self.config.model_url:
            path = download_to_cache(self.config.model_url, "wakeword-model")
            print(f"[wakeword] downloaded custom model from {self.config.model_url} to {path}")
            return path

        if self.config.model_file:
            path = pathlib.Path(self.config.model_file).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"Wake-word model file not found: {path}")
            return path

        return None


class SharedMicAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, microphone: SharedMicrophone, user_event_queue: "queue.Queue[Dict[str, Any]]") -> None:
        super().__init__()
        self.microphone = microphone
        self.user_event_queue = user_event_queue
        self.enabled = False
        self.pts = 0
        self.last_user_event_at = 0.0

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    async def recv(self) -> AudioFrame:
        frame_bytes = await asyncio.to_thread(self.microphone.read_frame, 1.0)
        pcm = np.frombuffer(frame_bytes, dtype=np.int16)
        now = time.time()

        if self.enabled:
            level = pcm_level(pcm)
            if level > 0.02 and (now - self.last_user_event_at) > 0.2:
                self.last_user_event_at = now
                self.user_event_queue.put({"type": "user_speaking", "level": level})
        else:
            pcm = np.zeros_like(pcm)

        frame = AudioFrame(format="s16", layout="mono", samples=len(pcm))
        frame.sample_rate = SAMPLE_RATE
        frame.planes[0].update(pcm.tobytes())
        frame.pts = self.pts
        frame.time_base = fractions_per_second(SAMPLE_RATE)
        self.pts += len(pcm)
        return frame


class AiRtcClient:
    def __init__(self, config: RtcServiceConfig, microphone: SharedMicrophone) -> None:
        self.config = config
        self.microphone = microphone
        self.connected = False
        self.listening = False
        self._event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._runtime_error: Optional[Exception] = None

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._pc: Optional[RTCPeerConnection] = None
        self._track: Optional[SharedMicAudioTrack] = None
        self._remote_audio_tasks = []
        self._speaker: Optional[RemoteSpeaker] = None

    def connect(self) -> None:
        if self.connected:
            return
        try:
            self._run_sync(self._connect())
        except Exception as error:
            self._runtime_error = error
            raise
        self.connected = True
        print(f"[rtc] connected to {self.config.base_url}")

    def start_listening(self) -> None:
        self._ensure_runtime_ok()
        self.listening = True
        if self._track is not None:
            self._track.set_enabled(True)
        self._event_queue.put({"type": "listening", "level": 0.08})
        print("[rtc] microphone gate opened")

    def stop_listening(self) -> None:
        self.listening = False
        if self._track is not None:
            self._track.set_enabled(False)
        self._event_queue.put({"type": "idle", "level": 0})
        print("[rtc] microphone gate closed")

    def iter_events(self):
        self._ensure_runtime_ok()
        while True:
            try:
                yield self._event_queue.get_nowait()
            except queue.Empty:
                break

    def close(self) -> None:
        try:
            self._run_sync(self._close())
        finally:
            self.connected = False
            self.listening = False

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_sync(self, coroutine):
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result()

    async def _connect(self) -> None:
        self._pc = RTCPeerConnection()

        @self._pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            state = self._pc.connectionState
            print(f"[rtc] connection state: {state}")
            if state in {"failed", "closed", "disconnected"}:
                self._event_queue.put({"type": "inactive", "level": 0})

        @self._pc.on("track")
        def on_track(track) -> None:
            if track.kind == "audio":
                if self.config.play_remote_audio:
                    self._speaker = RemoteSpeaker(self.config.output_device)
                task = asyncio.create_task(self._consume_remote_audio(track))
                self._remote_audio_tasks.append(task)

        self._track = SharedMicAudioTrack(self.microphone, self._event_queue)
        self._pc.addTrack(self._track)

        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)

        answer_payload = await asyncio.to_thread(self._post_offer, {
            "sdp": self._pc.localDescription.sdp,
            "type": self._pc.localDescription.type,
            "conversation_id": self.config.conversation_id,
            "stt_language": self.config.stt_language,
            "voiceprint_gate": self.config.voiceprint_gate
        })

        answer_sdp = answer_payload.get("sdp")
        answer_type = answer_payload.get("type")
        if not answer_sdp or not answer_type:
            raise RuntimeError(
                "RTC offer response did not include 'sdp' and 'type'. "
                "This is inferred from the WebRTC offer flow; please verify the server response format if this fails."
            )

        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=answer_sdp, type=answer_type)
        )

    async def _close(self) -> None:
        if self._track is not None:
            self._track.set_enabled(False)
        for task in self._remote_audio_tasks:
            task.cancel()
        self._remote_audio_tasks = []
        if self._pc is not None:
            await self._pc.close()
            self._pc = None
        if self._speaker is not None:
            self._speaker.close()
            self._speaker = None

    async def _consume_remote_audio(self, track) -> None:
        assistant_active = False
        last_voice_at = 0.0

        while True:
            frame = await track.recv()
            level = frame_audio_level(frame)
            now = time.time()

            if level > 0.02:
                assistant_active = True
                last_voice_at = now
                self._event_queue.put({"type": "assistant_speaking", "level": level})
            elif assistant_active and (now - last_voice_at) > 0.6:
                assistant_active = False
                self._event_queue.put({"type": "assistant_idle", "level": 0})

            if self._speaker is not None:
                self._speaker.play(frame)

    def _post_offer(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = {key: value for key, value in payload.items() if value is not None}
        if not self.config.token:
            raise RuntimeError("AI RTC bearer token is required.")

        request = urllib.request.Request(
            self.config.offer_url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.token}"
            }
        )

        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                response_data = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"RTC offer failed with HTTP {error.code}: {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"RTC offer request failed: {error}") from error

        return json.loads(response_data)

    def _ensure_runtime_ok(self) -> None:
        if self._runtime_error is not None:
            raise RuntimeError(str(self._runtime_error))

    def check_voiceprint_status(self) -> Dict[str, Any]:
        return self._request_json("GET", self.config.voiceprint_status_url)

    def delete_voiceprint(self) -> Dict[str, Any]:
        return self._request_json("DELETE", self.config.voiceprint_delete_url)

    def enroll_voiceprint(self, audio_bytes: bytes) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            self.config.voiceprint_enroll_url,
            {"audio_b64": base64.b64encode(audio_bytes).decode("ascii")}
        )

    def _request_json(self, method: str, url: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.config.token:
            raise RuntimeError("AI RTC bearer token is required.")

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.token}"
            }
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {url} failed with HTTP {error.code}: {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"{method} {url} failed: {error}") from error

        return json.loads(body) if body else {}


class RemoteSpeaker:
    def __init__(self, device: Optional[str]) -> None:
        self.device = device if device not in {"", None} else None
        self.stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            device=self.device,
            blocksize=FRAME_SAMPLES
        )
        self.stream.start()
        self.resampler = AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        print(f"[audio] remote output enabled on device '{self.device or 'default'}'")

    def play(self, frame: AudioFrame) -> None:
        try:
            resampled = self.resampler.resample(frame)
            frames = resampled if isinstance(resampled, list) else [resampled]
            for resampled_frame in frames:
                if resampled_frame is None:
                    continue
                mono = resampled_frame.to_ndarray()
                if mono.ndim > 1:
                    mono = mono[0]
                pcm = np.asarray(mono, dtype=np.int16)
                self.stream.write(pcm.tobytes())
        except Exception:
            pass

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


class LocalAiRtcController:
    def __init__(
        self,
        bridge: MagicMirrorBridge,
        wake_word_engine: OpenWakeWordEngine,
        rtc_client: AiRtcClient,
        idle_timeout: float,
        voiceprint_config: VoiceprintConfig,
    ) -> None:
        self.bridge = bridge
        self.wake_word_engine = wake_word_engine
        self.rtc_client = rtc_client
        self.idle_timeout = idle_timeout
        self.voiceprint_config = voiceprint_config
        self.last_activity_at = 0.0
        self.session_active = False

    def run(self) -> None:
        self._prepare_voiceprint()
        self.rtc_client.connect()
        self.bridge.send_event({"type": "inactive"})

        while True:
            self._drain_rtc_events()

            if self.session_active and self._session_timed_out():
                self.session_active = False
                self.rtc_client.stop_listening()
                self.bridge.send_event({"type": "inactive"})

            if not self.session_active:
                woke = self.wake_word_engine.wait_for_wake_word()
                if woke:
                    self._activate_session()
            else:
                time.sleep(0.1)

    def _activate_session(self) -> None:
        self.session_active = True
        self.last_activity_at = time.time()
        self.bridge.send_event({
            "type": "wakeword",
            "model": self.wake_word_engine.active_model_name
        })
        self.bridge.send_event({"type": "listening", "level": 0.08})
        self.rtc_client.start_listening()

    def _drain_rtc_events(self) -> None:
        for event in self.rtc_client.iter_events():
            normalized = self._normalize_rtc_event(event)
            if normalized is None:
                continue

            event_type = normalized["type"]
            if event_type in {"listening", "speaking", "idle"}:
                self.session_active = True
                self.last_activity_at = time.time()
            elif event_type == "inactive":
                self.session_active = False

            self.bridge.send_event(normalized)

    def _normalize_rtc_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        event_type = str(event.get("type", "")).lower()
        level = event.get("level")

        if event_type == "user_speaking":
            return {"type": "listening", "level": level if level is not None else 0.25}
        if event_type == "assistant_speaking":
            return {"type": "speaking", "level": level if level is not None else 0.75}
        if event_type in {"assistant_idle", "user_idle", "idle"}:
            return {"type": "idle", "level": 0}
        if event_type in {"inactive", "session_end"}:
            return {"type": "inactive", "level": 0}
        if event_type in {"wakeword", "listening", "speaking", "level", "state"}:
            return event
        return None

    def _session_timed_out(self) -> bool:
        return self.last_activity_at > 0 and (time.time() - self.last_activity_at) >= self.idle_timeout

    def _prepare_voiceprint(self) -> None:
        if self.voiceprint_config.delete_before_enroll:
            result = self.rtc_client.delete_voiceprint()
            print(f"[voiceprint] deleted existing voiceprint: {result}")

        enroll_audio = self._load_voiceprint_audio()
        if enroll_audio is not None:
            result = self.rtc_client.enroll_voiceprint(enroll_audio)
            print(f"[voiceprint] enrolled voiceprint: {result}")

        if self.voiceprint_config.check_status:
            result = self.rtc_client.check_voiceprint_status()
            print(f"[voiceprint] status: {result}")

    def _load_voiceprint_audio(self) -> Optional[bytes]:
        if self.voiceprint_config.enroll_audio_url:
            path = download_to_cache(self.voiceprint_config.enroll_audio_url, "voiceprint-audio")
            print(f"[voiceprint] downloaded enrollment audio from {self.voiceprint_config.enroll_audio_url} to {path}")
            return path.read_bytes()

        if self.voiceprint_config.enroll_audio_path:
            path = pathlib.Path(self.voiceprint_config.enroll_audio_path).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"Voiceprint enrollment audio file not found: {path}")
            return path.read_bytes()

        return None


def pcm_level(pcm: np.ndarray) -> float:
    raw = pcm.astype(np.int16, copy=False).tobytes()
    rms = audioop.rms(raw, 2)
    return max(0.0, min(1.0, rms / 32767.0))


def frame_audio_level(frame: AudioFrame) -> float:
    try:
        mono = frame.to_ndarray()
        if mono.ndim > 1:
            mono = mono[0]
        pcm = np.asarray(mono, dtype=np.int16)
        return pcm_level(pcm)
    except Exception:
        return 0.0


def fractions_per_second(sample_rate: int):
    from fractions import Fraction
    return Fraction(1, sample_rate)


def load_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Wake-word and AI RTC bridge for MMM-Local-AI-Rtc")
    parsed_bridge_url = urllib.parse.urlparse(os.getenv("MM_LOCAL_AI_RTC_URL", ""))
    parser.add_argument("--host", default=os.getenv("MM_LOCAL_AI_RTC_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MM_LOCAL_AI_RTC_PORT", "3210")))
    parser.add_argument("--path", default=os.getenv("MM_LOCAL_AI_RTC_PATH", "/api/events"))
    parser.add_argument("--token", default=os.getenv("MM_LOCAL_AI_RTC_TOKEN", ""))
    parser.add_argument("--identifier", default=os.getenv("MM_LOCAL_AI_RTC_IDENTIFIER", ""))
    parser.add_argument("--idle-timeout", type=float, default=float(os.getenv("MM_LOCAL_AI_RTC_IDLE_TIMEOUT", "30")))
    parser.add_argument("--rtc-base-url", default=os.getenv("AI_RTC_BASE_URL", "https://ai-rtc.cetimmer-web.nl"))
    parser.add_argument("--rtc-token", default=os.getenv("AI_RTC_TOKEN", ""))
    parser.add_argument("--conversation-id", default=os.getenv("AI_RTC_CONVERSATION_ID"))
    parser.add_argument("--stt-language", default=os.getenv("AI_RTC_STT_LANGUAGE"))
    parser.add_argument("--voiceprint-gate", choices=["true", "false"], default=os.getenv("AI_RTC_VOICEPRINT_GATE"))
    parser.add_argument("--voiceprint-check-status", choices=["true", "false"], default=os.getenv("AI_RTC_VOICEPRINT_CHECK_STATUS", "false"))
    parser.add_argument("--voiceprint-delete-before-enroll", choices=["true", "false"], default=os.getenv("AI_RTC_VOICEPRINT_DELETE_BEFORE_ENROLL", "false"))
    parser.add_argument("--voiceprint-enroll-audio-path", default=os.getenv("AI_RTC_VOICEPRINT_ENROLL_AUDIO_PATH"))
    parser.add_argument("--voiceprint-enroll-audio-url", default=os.getenv("AI_RTC_VOICEPRINT_ENROLL_AUDIO_URL"))
    parser.add_argument("--output-device", default=os.getenv("AI_RTC_OUTPUT_DEVICE"))
    parser.add_argument("--play-remote-audio", choices=["true", "false"], default=os.getenv("AI_RTC_PLAY_REMOTE_AUDIO", "false"))
    parser.add_argument("--wakeword-model", default=os.getenv("OWW_MODEL", "auto"))
    parser.add_argument("--wakeword-model-file", default=os.getenv("OWW_MODEL_FILE"))
    parser.add_argument("--wakeword-model-url", default=os.getenv("OWW_MODEL_URL"))
    parser.add_argument("--wakeword-threshold", type=float, default=float(os.getenv("OWW_THRESHOLD", "0.5")))
    parser.add_argument("--wakeword-vad-threshold", type=float, default=float(os.getenv("OWW_VAD_THRESHOLD", "0.5")))
    parser.add_argument("--mic-device", default=os.getenv("OWW_MIC_DEVICE"))
    args = parser.parse_args()

    if parsed_bridge_url.scheme and parsed_bridge_url.hostname:
        args.host = parsed_bridge_url.hostname
        if parsed_bridge_url.port:
            args.port = parsed_bridge_url.port
        elif parsed_bridge_url.scheme == "https":
            args.port = 443
        else:
            args.port = 80
        args.path = parsed_bridge_url.path or "/api/events"

    return args


def parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None or value == "":
        return None
    return value.lower() == "true"


def main() -> None:
    args = load_args()
    bridge_config = BridgeConfig(
        host=args.host,
        port=args.port,
        path=args.path,
        token=args.token,
        identifier=args.identifier,
        idle_timeout=args.idle_timeout,
    )
    rtc_config = RtcServiceConfig(
        base_url=args.rtc_base_url,
        token=args.rtc_token,
        conversation_id=args.conversation_id,
        stt_language=args.stt_language,
        voiceprint_gate=parse_bool(args.voiceprint_gate),
        output_device=args.output_device,
        play_remote_audio=parse_bool(args.play_remote_audio) is True,
    )
    wakeword_config = WakeWordConfig(
        model_name=args.wakeword_model,
        model_file=args.wakeword_model_file,
        model_url=args.wakeword_model_url,
        threshold=args.wakeword_threshold,
        vad_threshold=args.wakeword_vad_threshold,
    )
    voiceprint_config = VoiceprintConfig(
        check_status=parse_bool(args.voiceprint_check_status) is True,
        delete_before_enroll=parse_bool(args.voiceprint_delete_before_enroll) is True,
        enroll_audio_path=args.voiceprint_enroll_audio_path,
        enroll_audio_url=args.voiceprint_enroll_audio_url,
    )

    microphone = SharedMicrophone(device=args.mic_device)
    microphone.start()

    controller = LocalAiRtcController(
        bridge=MagicMirrorBridge(bridge_config),
        wake_word_engine=OpenWakeWordEngine(microphone, wakeword_config),
        rtc_client=AiRtcClient(rtc_config, microphone),
        idle_timeout=bridge_config.idle_timeout,
        voiceprint_config=voiceprint_config,
    )

    try:
        controller.run()
    finally:
        microphone.stop()


if __name__ == "__main__":
    main()
