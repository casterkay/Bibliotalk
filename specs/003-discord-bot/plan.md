# Implementation Plan: Bibliotalk Discord Bot (Text + Voice)

**Branch**: `003-discord-bot`
**Created**: 2026-03-07
**Last updated**: 2026-03-24
**Spec**: [spec.md](spec.md)

This plan reflects the current repository reality: Discord text is implemented in `services/discord_service/`, and voice is bridged through `services/voip_service/` to `services/agents_service/` Live Sessions backed by Gemini Live.

## Current State (as of 2026-03-24)

Shipped (US1–US3):
- YouTube ingestion → SQLite evidence cache + EverMemOS memorization (`services/memory_service/`)
- Grounded agent responses with inline memory links + validation (`services/agents_service/`)
- Discord feed publishing + DM `/talk` + private thread routing (`services/discord_service/`)
- Public memory pages served by `memory_service` (`/memories/{id}`)

Implemented in current branch (US4: Discord voice):
- Agent-core Live Sessions (text + voice): `services/agents_service/src/api/live.py`
- Gemini Live bidi audio + transcription backend: `services/agents_service/src/live/gemini_live_backend.py`
- Multi-platform bridge manager + Matrix bridge: `services/voip_service/src/voip/bridge_manager.js`, `services/voip_service/src/voip/matrix_livekit_bridge.js`
- Discord voice bridge + gateway-proxy WS endpoint: `services/voip_service/src/voip/discord_bridge.js`, `services/voip_service/src/server.js`
- Discord control-plane proxy + slash commands `/voice join|leave|status`: `services/discord_service/src/bot/voice_gateway_proxy.py`, `services/discord_service/src/bot/client.py`
- Transcript posting (coalesced rolling edits): `services/discord_service/src/bot/voice_transcripts.py`

Remaining work (US4 polish / ship-quality):

- Harden reconnect semantics (fail-closed + visible status) and add a manual test checklist for barge-in/reconnect.
- Decide and implement the voice grounding/citations strategy (two-track vs demo-only single-track).

## Architecture Decisions (non-negotiable for Discord voice)

### 1) Discord gateway stays in `discord_service`

`services/discord_service/` is the only process that logs in with `DISCORD_TOKEN`.

Rationale:
- Discord treats concurrent gateway sessions for the same token as hostile/buggy.
- Text + voice UX (commands, authorization, transcript posting) belongs with the gateway.

### 2) Media-plane stays in `voip_service`

`services/voip_service/` owns:
- Opus encode/decode, PCM resampling
- Real-time send/receive loops
- Bridging to `agents_service` Live Session WS protocol (same as Matrix voice)

### 3) Gateway-proxy bridge (`discord_service` ⇄ `voip_service`)

To enable voice transport without a second gateway client:
- `discord_service` forwards gateway dispatch payloads needed for voice transport:
  - `VOICE_STATE_UPDATE`
  - `VOICE_SERVER_UPDATE`
- `voip_service` asks `discord_service` to perform voice-state updates (join/leave) on its behalf.

This makes `voip_service` a platform-agnostic voice bridge rather than a second Discord bot.

## Interfaces (operational truth)

### A) `agents_service` Live Sessions (voice)

`voip_service` creates a Live Session with:
- `modality="voice"`
- `platform="discord"`
- `room_id="{guild_id}:{voice_channel_id}"`

Then streams:
- `input.audio.chunk` with `pcm16k_b64`
- receives `output.audio.chunk` with `pcm24k_b64`
- receives `output.transcription.input` / `output.transcription.output`
- citations are appended out-of-band to finalized transcript messages based on Gemini Live tool-calling outputs

Reference: `services/agents_service/src/api/live.py`

### B) `voip_service` control endpoints

Operational request shape:
- `POST /v1/voip/ensure` with `platform="discord"` + `{guild_id, voice_channel_id, agent_id, initiator_user_id, text_channel_id?, text_thread_id?}`
- `POST /v1/voip/stop` with optional `{bridge_id, guild_id, room_id, reason}`
- internal gateway channel: `ws /v1/discord/gateway/ws?bridge_id=...`

Backwards compatibility: existing Matrix payloads continue working.

## Work Breakdown (phases)

### Phase V0 — Docs + Contracts (fast, unblock)

- Update `DESIGN.md` to treat Discord as first-class and describe the gateway-proxy pattern.
- Update `specs/003-discord-bot/spec.md` to include US4 + FRs + success criteria.
- Update `specs/003-discord-bot/tasks.md` with Phase 7 / US4 tasks.
- Reconcile the drift between `specs/001-matrix-mvp/contracts/voice-bridge.md` and the actual message types used by `agents_service`/`voip_service` (document the source of truth and plan the fix).

### Phase V1 — Discord UX + Routing (Python)

In `services/discord_service/`:
- Add slash commands `/voice join`, `/voice leave`, `/voice status` ✅
- Persist voice binding via `PlatformRoute` (`platform="discord"`, `purpose="voice"`, `container_id=voice_channel_id`, `config_json={text_channel_id,...}`)
- Call `voip_service` to ensure/stop the voice bridge ✅
- Post transcripts (input/output) into the configured text channel/thread ✅

### Phase V2 — `voip_service` Discord bridge skeleton (Node)

In `services/voip_service/`:
- Add a `DiscordBridge` alongside the existing Matrix/LiveKit bridge ✅
- Add an internal websocket for the gateway-proxy channel:
  - inbound: `gateway.voice_state_update` / `gateway.voice_server_update` ✅
  - outbound: `gateway.request_change_voice_state` (join/leave) ✅
- Keep the audio bridge identical to Matrix voice:
  - inbound audio → resample to PCM16k → `input.audio.chunk`
  - outbound `output.audio.chunk` → resample to 48k → Opus playback

### Phase V3 — Voice quality + barge-in

- Implement a robust barge-in strategy:
  - stop audio player immediately
  - clear ring buffer
  - optionally send `input.audio.stream_end` on turn boundaries
- Add jitter buffering on playback (small ring buffer) and chunking control

### Phase V4 — Grounding integration (recommended, but separable for first demo)

Target design: Gemini Live supplies transcription + audio I/O, while the Spirit’s *content* is governed by the grounded agent core.

Implementation choices (pick one and document):
1. **Two-track** (preferred): use input transcripts to drive the grounded text agent, then send the resulting response text to Gemini Live for TTS audio output.
2. **Single-track** (demo-only): let Gemini Live generate content directly, but this violates grounding-first and should not be shipped as “truth layer”.

### Phase V5 — Ops + Testing + Deployment

- Add local runtime wiring for `voip_service` (docker-compose or a dev script)
- Add structured logs with correlation ids:
  - `voice_session_id`, `turn_id`, `guild_id`, `voice_channel_id`, `agent_id`
- Add unit tests for:
  - voice route config parsing
  - envelope encoding/decoding
  - barge-in buffer clearing behavior
- Provide a manual test checklist for Discord voice (join, talk, barge-in, leave, reconnect)

## Key Risks / Decisions

- Node runtime: Discord voice libraries may require a newer Node version than other Node services. Prefer upgrading `voip_service` independently rather than uplifting the entire repo’s Node baseline.
- Discord voice receive: validate that the chosen voice stack reliably supports inbound audio receive on the target deployment platform (macOS/Linux).
- Audio resampling: naive 2× upsampling is acceptable for deterministic demo-grade output but should be replaced for production fidelity.
