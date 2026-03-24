# Local AI RTC Bridge

This Home Assistant add-on runs:

- `openWakeWord` for local wake-word detection
- a persistent RTC connection to `https://ai-rtc.cetimmer-web.nl`
- a bridge that sends bubble state updates to `MMM-Local-AI-Rtc`

## What it does

The add-on keeps the RTC session open, but keeps the microphone gated until your wake word is heard. When the wake word is detected:

1. the add-on sends a `wakeword` event to MagicMirror
2. the bubble appears
3. microphone audio is allowed through to the RTC
4. assistant/user speaking activity updates the bubble
5. after the configured idle timeout, the mic is gated again and the bubble hides

## Requirements

- Home Assistant OS or Home Assistant Supervised
- a working microphone device available to the add-on
- the `MMM-Local-AI-Rtc` MagicMirror module running with its `node_helper` bridge enabled
- a valid bearer token for `ai-rtc.cetimmer-web.nl`

## MagicMirror setup

In your MagicMirror config, enable the bridge and choose a token:

```javascript
{
    module: "MMM-Local-AI-Rtc",
    position: "middle_center",
    config: {
        idleTimeout: 30000,
        bridge: {
            enabled: true,
            host: "0.0.0.0",
            port: 3210,
            token: "change-me"
        }
    }
}
```

Then point the add-on at that URL, for example:

- `mirror_bridge_url`: `http://192.168.1.50:3210/api/events`
- `mirror_bridge_token`: `change-me`

## Add-on options

- `mirror_bridge_url`: full URL to the MagicMirror bridge endpoint
- `mirror_bridge_token`: bearer token expected by the MagicMirror bridge
- `mirror_identifier`: optional MagicMirror module instance identifier
- `idle_timeout`: seconds before hiding/gating after inactivity
- `rtc_base_url`: AI RTC server base URL
- `rtc_token`: bearer token for the RTC server
- `conversation_id`: optional conversation id
- `stt_language`: optional speech-to-text language
- `voiceprint_gate`: optional voiceprint gate flag
- `voiceprint_check_status`: check voiceprint status at startup
- `voiceprint_delete_before_enroll`: remove an existing voiceprint before enrolling
- `voiceprint_enroll_audio_path`: local file path for voiceprint enrollment audio
- `voiceprint_enroll_audio_url`: URL for voiceprint enrollment audio
- `output_device`: optional output device for assistant audio playback
- `play_remote_audio`: play assistant audio to the configured output device
- `wakeword_model`: model key to match, or `auto` to accept the downloaded/custom model result directly
- `wakeword_model_file`: optional local wake-word model file
- `wakeword_model_url`: URL to a wake-word model file, including GitHub raw URLs
- `wakeword_threshold`: wake-word activation threshold
- `wakeword_vad_threshold`: VAD threshold
- `mic_device`: optional `sounddevice` input device name/index

## Notes

- The add-on assumes the RTC offer response contains `sdp` and `type`.
- `openWakeWord` works on 16 kHz PCM frames and this add-on uses 80 ms chunks.
- If the microphone device name differs on your system, set `mic_device` explicitly.
- For custom wake-word files, `wakeword_model_url` is the easiest option in the Home Assistant config UI.
