# MMM-Local-AI-Rtc

MagicMirror module that shows a reactive AI bubble for your local RTC assistant.

The bubble:

- fades away when the RTC is idle
- fades back in when the RTC is called
- changes shape while the AI is speaking
- reacts more strongly when you send a higher speech level
- can be driven directly by a local Python wake-word / RTC bridge

## Installation

Place the module in your MagicMirror `modules` folder:

```bash
cd ~/MagicMirror/modules
git clone https://github.com/your-name/MMM-Local-AI-Rtc.git
```

No extra npm packages are required for this version.

## What was added

This module now includes:

- a `node_helper.js` HTTP bridge for local RTC events
- a Python script at `scripts/local_ai_rtc_bridge.py`
- default 30 second idle fade-out behavior
- a direct RTC signaling target for `https://ai-rtc.cetimmer-web.nl`

The intended flow is:

1. your Python script keeps the RTC connected all the time
2. the wake word is detected locally
3. Python tells the module to show the bubble
4. Python tells your RTC to start listening
5. while user or assistant speech is happening, Python keeps sending updates
6. after 30 seconds of no activity, the script stops listening and hides the bubble

## Example config

```javascript
{
    module: "MMM-Local-AI-Rtc",
    position: "middle_center",
    config: {
        bubbleSize: 220,
        idleTimeout: 30000,
        label: "Local AI",
        bridge: {
            enabled: true,
            host: "127.0.0.1",
            port: 3210,
            token: "change-me"
        }
    }
},
```

## Config options

Option | Description | Default
--- | --- | ---
`bubbleSize` | Bubble size in pixels. | `180`
`idleTimeout` | Milliseconds before the bubble fades out after the last active event. | `30000`
`bridge.enabled` | Enables the local helper server for Python/RTC events. | `true`
`bridge.host` | Host for the local helper server. | `127.0.0.1`
`bridge.port` | Port for the local helper server. | `3210`
`bridge.path` | POST path for incoming RTC events. | `"/api/events"`
`bridge.token` | Optional bearer token for local authentication. | `""`
`fadeDuration` | Fade in/out speed in milliseconds. | `600`
`updateInterval` | Internal animation refresh speed. | `80`
`minScale` | Smallest base bubble scale. | `0.92`
`maxScale` | Largest base bubble scale when speaking strongly. | `1.18`
`glowStrength` | Extra glow while speaking. | `20`
`label` | Optional text under the bubble. | `""`
`notifications` | Override the notification names if your RTC already uses different ones. | See module file

The default `idleTimeout` is now `30000`, so the bubble disappears after 30 seconds of no activity.

## AI RTC service

As checked on **March 23, 2026**, the docs at `https://ai-rtc.cetimmer-web.nl/docs` publish an OpenAPI spec at `https://ai-rtc.cetimmer-web.nl/openapi.json` with:

- `POST /rtc/offer`
- bearer token auth
- request fields `sdp`, `type`, optional `conversation_id`, optional `stt_language`, optional `voiceprint_gate`

The Python bridge now targets that RTC service directly.

## Home Assistant add-on

There is now a Home Assistant add-on scaffold in:

[`home-assistant-addon/local-ai-rtc`](c:/Users/chris/Documents/GitHub/MMM-Local-AI-Rtc/home-assistant-addon/local-ai-rtc)

It includes:

- [`config.yaml`](c:/Users/chris/Documents/GitHub/MMM-Local-AI-Rtc/home-assistant-addon/local-ai-rtc/config.yaml)
- [`build.yaml`](c:/Users/chris/Documents/GitHub/MMM-Local-AI-Rtc/home-assistant-addon/local-ai-rtc/build.yaml)
- [`Dockerfile`](c:/Users/chris/Documents/GitHub/MMM-Local-AI-Rtc/home-assistant-addon/local-ai-rtc/Dockerfile)
- [`run.sh`](c:/Users/chris/Documents/GitHub/MMM-Local-AI-Rtc/home-assistant-addon/local-ai-rtc/run.sh)
- [`DOCS.md`](c:/Users/chris/Documents/GitHub/MMM-Local-AI-Rtc/home-assistant-addon/local-ai-rtc/DOCS.md)

This lets Home Assistant own the wake-word and RTC bridge process while MagicMirror remains only the UI layer.

## Notifications

Your AI RTC integration can control the module with MagicMirror notifications.

### 1. Full state update

```javascript
this.sendNotification("LOCAL_AI_RTC_STATE", {
    active: true,
    speaking: true,
    level: 0.72
});
```

Supported payload fields:

- `active`: shows or hides the bubble
- `speaking`: enables speech animation
- `level`: value from `0` to `1` for stronger or softer motion
- `visible`: also treated like `active: true`
- `called`: also treated like `active: true`
- `hide`: immediately hides the bubble

### 2. Simple active/inactive events

```javascript
this.sendNotification("LOCAL_AI_RTC_ACTIVE");
this.sendNotification("LOCAL_AI_RTC_INACTIVE");
```

### 3. Speaking events

```javascript
this.sendNotification("LOCAL_AI_RTC_SPEAKING", true);

this.sendNotification("LOCAL_AI_RTC_SPEAKING", {
    speaking: true,
    level: 0.55
});
```

### 4. Level-only updates

If your RTC stack can output audio intensity or VAD values, send them directly:

```javascript
this.sendNotification("LOCAL_AI_RTC_LEVEL", 0.63);
```

When level is above zero, the module automatically wakes up and animates as speaking.

## Suggested integration flow

When the user wakes the assistant:

```javascript
this.sendNotification("LOCAL_AI_RTC_ACTIVE");
```

While the AI is speaking:

```javascript
this.sendNotification("LOCAL_AI_RTC_STATE", {
    active: true,
    speaking: true,
    level: 0.8
});
```

When speech ends but the session is still open:

```javascript
this.sendNotification("LOCAL_AI_RTC_STATE", {
    active: true,
    speaking: false,
    level: 0
});
```

When the RTC session is closed:

```javascript
this.sendNotification("LOCAL_AI_RTC_INACTIVE");
```

If you do not send an inactive notification, the module fades itself away after `idleTimeout`.

## Python bridge

The included Python script is:

`scripts/local_ai_rtc_bridge.py`

Install the Python dependencies first:

```bash
pip install -r requirements.txt
```

Then run it like this:

```bash
python scripts/local_ai_rtc_bridge.py --token change-me --rtc-token YOUR_AI_RTC_TOKEN
```

By default it connects to:

- `http://127.0.0.1:3210/api/events`
- idle timeout: `30` seconds
- RTC base URL: `https://ai-rtc.cetimmer-web.nl`

Environment variables are also supported:

```bash
MM_LOCAL_AI_RTC_HOST=127.0.0.1
MM_LOCAL_AI_RTC_PORT=3210
MM_LOCAL_AI_RTC_PATH=/api/events
MM_LOCAL_AI_RTC_TOKEN=change-me
MM_LOCAL_AI_RTC_IDLE_TIMEOUT=30
AI_RTC_BASE_URL=https://ai-rtc.cetimmer-web.nl
AI_RTC_TOKEN=your-bearer-token
AI_RTC_CONVERSATION_ID=
AI_RTC_STT_LANGUAGE=en
AI_RTC_VOICEPRINT_GATE=false
OWW_MODEL=hey jarvis
OWW_THRESHOLD=0.5
OWW_VAD_THRESHOLD=0.5
OWW_MIC_DEVICE=
```

### Current Python behavior

The script already handles the session flow:

- keeps the RTC client connected all the time
- waits for a wake word
- shows the bubble when the wake word is detected
- tells the RTC client to start listening
- forwards listening/speaking/idle state changes to MagicMirror
- hides the bubble after 30 seconds of inactivity

Right now the script ships with:

- `openWakeWord` wake-word detection
- a real RTC client for `ai-rtc.cetimmer-web.nl`
- one shared microphone stream for both wake-word detection and RTC audio
- microphone gating so the RTC connection can stay open while the mic stays effectively muted until the wake word

### Wake-word behavior

By default the script uses:

- model: `hey jarvis`
- threshold: `0.5`
- VAD threshold: `0.5`

You can change that with:

```bash
python scripts/local_ai_rtc_bridge.py \
  --token change-me \
  --rtc-token YOUR_AI_RTC_TOKEN \
  --wakeword-model "hey jarvis" \
  --wakeword-threshold 0.55
```

Or through environment variables:

```bash
OWW_MODEL=hey jarvis
OWW_THRESHOLD=0.5
OWW_VAD_THRESHOLD=0.5
OWW_MIC_DEVICE=
```

### RTC behavior

The RTC client now:

- creates a WebRTC offer locally
- sends it to `https://ai-rtc.cetimmer-web.nl/rtc/offer`
- authenticates with a bearer token
- keeps the peer connection open
- shares the same 16 kHz microphone stream with openWakeWord
- forwards remote audio energy into bubble speaking animation
- gates local microphone audio on wake word

The controller understands these RTC-side event types:

- `user_speaking`
- `assistant_speaking`
- `assistant_idle`
- `inactive`

Those get translated into module bubble events automatically.

### Important note

The docs expose the signaling endpoint, but they do not document the exact response body example for `POST /rtc/offer` beyond the WebRTC offer/answer flow. The script assumes the response includes:

```json
{
  "sdp": "...",
  "type": "answer"
}
```

If your RTC returns additional fields or wraps the SDP differently, we can adjust that quickly once you share one real response sample.
