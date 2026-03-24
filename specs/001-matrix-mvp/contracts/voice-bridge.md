# Contract: Live Voice Bridge Protocol (v1)

**Participants**:
- **Platform voice bridge** (`services/voip_service`): media I/O (MatrixRTC/LiveKit or Discord voice), Opus/PCM conversion, transport to agent core
- **Agent core** (`services/agents_service`): Live Session creation, Gemini Live audio + transcriptions, grounding/citations

**Transport**: bidirectional WebSocket (`agents_service` Live Session WS)

This contract is platform-agnostic and matches the operational message names implemented today in:
- `services/agents_service/src/api/live.py`
- `services/voip_service/src/voip/matrix_livekit_bridge.js`
- `services/voip_service/src/voip/discord_bridge.js`

---

## Audio Format Contract

### Voice bridge → agent core (`input.audio.chunk`)
- PCM16 mono
- 16 kHz
- 16-bit signed little-endian
- base64 encoded as `payload.pcm16k_b64`

### Agent core → voice bridge (`output.audio.chunk`)
- PCM24 mono
- 24 kHz
- 16-bit signed little-endian
- base64 encoded as `payload.pcm24k_b64`

Resampling to/from platform-native formats (e.g. Discord Opus 48 kHz) is adapter-owned.

---

## Session Lifecycle

### 1) Create Live Session (HTTP)

`POST /v1/agents/{agent_id}/live/sessions`

```json
{
  "platform": "matrix|discord",
  "room_id": "platform-room-identifier",
  "initiator_platform_user_id": "platform-user-id",
  "modality": "voice"
}
```

Per-platform `room_id` conventions:
- `platform="matrix"`: `room_id` is the Matrix room ID (e.g. `"!room:server"`).
- `platform="discord"`: `room_id` is `"{guild_id}:{voice_channel_id}"` (e.g. `"123:456"`).

Response:

```json
{
  "session_id": "uuid",
  "ws_url": "wss://.../v1/agents/live/ws?session_id=..."
}
```

### 2) Connect Live WS

Voice bridge connects to the returned `ws_url`.

---

## Envelope Shape

All WS messages use:

```json
{
  "type": "message.type",
  "ts": "2026-03-24T12:00:00+00:00",
  "turn_id": "uuid",
  "payload": {}
}
```

`ts` uses Python `datetime.now(UTC).isoformat()` format.

`turn_id` is required for turn-scoped events and may be empty for errors/session control.

---

## Voice Bridge → Agent Core

### `input.audio.chunk`

```json
{
  "type": "input.audio.chunk",
  "turn_id": "uuid",
  "payload": {
    "pcm16k_b64": "base64-pcm16k-mono"
  }
}
```

### `input.audio.stream_end`

```json
{
  "type": "input.audio.stream_end",
  "turn_id": "uuid",
  "payload": {}
}
```

### `input.cancel` (optional for voice)

```json
{
  "type": "input.cancel",
  "turn_id": "uuid",
  "payload": {}
}
```

---

## Agent Core → Voice Bridge

### `output.audio.chunk`

```json
{
  "type": "output.audio.chunk",
  "turn_id": "uuid",
  "payload": {
    "pcm24k_b64": "base64-pcm24k-mono"
  }
}
```

### `output.transcription.input`

```json
{
  "type": "output.transcription.input",
  "turn_id": "uuid",
  "payload": {
    "text": "user transcript",
    "is_final": true
  }
}
```

### `output.transcription.output`

```json
{
  "type": "output.transcription.output",
  "turn_id": "uuid",
  "payload": {
    "text": "assistant transcript",
    "is_final": true
  }
}
```

### `output.interrupted`

```json
{
  "type": "output.interrupted",
  "turn_id": "uuid",
  "payload": {
    "reason": "cancelled|superseded"
  }
}
```

### `output.turn.end`

```json
{
  "type": "output.turn.end",
  "turn_id": "uuid",
  "payload": {
    "no_evidence": false
  }
}
```

### Citations (out-of-band from Live WS)

Citations are not transported over the Live Session WS for `modality="voice"`. (Text Live Sessions may emit explicit
citation events; voice does not.)

For voice sessions, platform adapters append citations as footnotes to finalized transcript messages (input/output)
based on Gemini Live tool-calling outputs after each message is finalized.

### `error`

```json
{
  "type": "error",
  "turn_id": "uuid",
  "payload": {
    "code": "INTERNAL_ERROR",
    "message": "Safe human-readable message"
  }
}
```

---

## Reliability Requirements

- Voice bridge must handle WS disconnects and cleanly stop/recreate sessions.
- Agent core must emit `output.interrupted` when a turn is canceled/superseded.
- On fatal failures, agent core emits `error` and may close the WS.
- Voice bridge must fail closed (stop playback/recording) when WS is broken.
