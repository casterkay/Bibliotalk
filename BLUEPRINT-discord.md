# Blueprint: Discord ↔ ADK ↔ Gemini Live Multi‑Agent Voice Chat (Single Human, Distinct Agent Voices)

## Summary

Build a low-latency, full‑duplex voice bridge between Discord voice and Gemini Live API using:

- Node.js Discord Edge Gateway: “dumb” VOIP + audio DSP + barge‑in signals + transport.
- Python Orchestration Router (ADK): sessions/memory/tools + multi‑agent floor control + Live streaming loops.
- One Live session per agent to get distinct voices (Aoede/Charon/Fenrir/Kore/Puck), while the router guarantees only one agent
speaks at a time.

———

## Goals (v1)

- Sub‑second conversational latency with barge‑in (user interruption).
- Single human in a Discord voice channel; multiple agents present.
- Distinct voices per agent, with stable mapping agent_id → voice.
- Long-running calls with Live connection rotation (session resumption) without dropping the Discord voice connection.
- Clear separation of concerns: Node handles VOIP; Python handles “AI”.

## Non‑Goals (v1)

- Mixing multiple humans simultaneously (assume exactly one human speaker).
- Overlapping agent speech (Discord plays one stream cleanly; no crosstalk).
- Perfect diarization / speaker identification (single human makes this simpler).

———

## High‑Level Architecture

Discord Voice (Opus 48k)
    ↕
Node “Edge Gateway”
- join/leave voice
- Opus decode/encode
- resample 48k↔16k/24k
- VAD/barge-in events
- WS transport (binary PCM + JSON control)
    ↕
Python “ChannelRouter” (ADK)
- per-channel state + memory
- per-agent Live session (voice fixed)
- upstream fan-out (human audio → all agents)
- downstream fan-in (agent audio → 1 floor holder)
- session resumption + reconnect
    ↕
Gemini Live API (BIDI audio)

———

## Audio Formats (hard requirements + decisions)

### Inbound (Human → Model)

- Discord provides Opus @ 48kHz.
- Node decodes to PCM and converts to:
    - PCM16 (signed 16-bit little-endian), mono, 16kHz
    - MIME for ADK: audio/pcm;rate=16000

### Outbound (Model → Human)

- Model returns:
    - PCM16, mono, 24kHz (audio/pcm;rate=24000)
- Node converts to Discord playback path:
    - resample 24kHz → 48kHz
    - encode to Opus for Discord

### Chunking (latency/overhead trade)

- Choose 20ms chunks end-to-end.
    - 16kHz mono PCM16: 16000 * 0.02 * 2 = 640 bytes/chunk
    - 24kHz mono PCM16: 24000 * 0.02 * 2 = 960 bytes/chunk
- Rule: keep chunk size consistent per stream; drop rather than buffer seconds.

———

## Node.js Discord Edge Gateway

### Responsibilities

- Join voice channel; subscribe to the human’s incoming audio.
- Decode Opus → PCM48k; downmix mono; resample to PCM16k; ship upstream immediately.
- Play downstream audio: receive PCM24k from Python, resample to 48k, encode Opus, send to Discord.
- Detect barge‑in: when human starts speaking, immediately signal Python to interrupt agent playback.

### Key behaviors

- Barge‑in policy: on vad.start:
    - stop current Discord playback immediately
    - send vad.start to Python with latest sequence number
- Backpressure policy:
    - If Python/WS is slow: drop oldest inbound audio chunks (never let latency balloon).
- Jitter buffer (downstream):
    - small target (e.g., 60–120ms) to smooth WS jitter
    - flush instantly on playback.clear

### VAD / speaking detection

Preferred order:

1. Use Discord/voice receiver speaking indicators if reliable in your stack.
2. Otherwise compute energy-based VAD on PCM (RMS + hangover) tuned for ~20ms frames.
3. Optional: WebRTC VAD library for better robustness.

———

## Node ↔ Python Transport (WebSocket, versioned)

One persistent WS per voice channel:

- JSON text frames: control/events
- Binary frames: PCM chunks with a tiny header

### Control message set (minimal, stable)

Node → Python:

- hello: declares channel + audio formats (for compatibility checks)
- voice.joined / voice.left
- vad.start / vad.end
- heartbeat (optional metrics + liveness)

Python → Node:

- agents: roster + voice mapping (for UI/logging; Node remains “dumb”)
- floor.grant / floor.revoke
- playback.clear (must be acted on immediately)
- status: per-agent listening|thinking|speaking|reconnecting

### Binary audio frame header (recommend)

Little-endian:

- u8 kind (1=human_pcm16k, 2=agent_pcm24k)
- u8 stream (0=human, 1..255=agent_index)
- u32 seq
- u64 ts_ms
- payload: raw PCM16LE mono

This lets you measure latency, detect drops, and implement jitter buffering deterministically.

———

## Python ADK Orchestration: ChannelRouter

### Responsibilities

- Own per-channel state, including:
    - current human presence
    - active agents
    - floor ownership (who may speak)
    - memory handles + summaries
    - per-agent Live connection lifecycle (resumption handles)
- Run full-duplex loops:
    - upstream: human audio fan-out to all agents
    - downstream: each agent’s event stream → router → Node (only floor holder audio forwarded)

### Concurrency model (per channel)

- Task A: ws_rx_loop (from Node): control + audio ingest
- Task B: ws_tx_loop (to Node): outgoing control + audio
- Task C: upstream_fanout_loop: audio queue → each agent LiveRequestQueue
- Task D[i]: agent_downstream_loop(agent_i): runner.run_live(...) consumer
- Task E: floor_arbiter_loop: grants/revokes floor based on VAD + tool calls + timeouts
- Task F[i]: agent_reconnect_loop(agent_i) (or integrated) for goAway/session rotation

### Upstream fan‑out

- Every inbound audio chunk becomes an ADK realtime audio blob:
    - mime_type="audio/pcm;rate=16000"
- Push to all agents’ LiveRequestQueue.send_realtime(...) immediately.

This ensures every agent “hears” the same conversation and can decide to request the floor.

———

## Multi‑Agent Turn Taking (“Floor Control”)

### Invariants

- Only one speaker output reaches Discord at a time.
- Human speech always has priority over any agent speech.

### Floor states

- FLOOR = HUMAN (barge-in active)
- FLOOR = NONE (silence / waiting)
- FLOOR = AGENT(agent_id) (that agent may stream audio to Node)

### Rules (decision-complete)

- On vad.start:
    - set FLOOR = HUMAN
    - send playback.clear to Node immediately
    - revoke any agent floor (floor.revoke, reason barge_in)
    - gate all downstream agent audio (drop or buffer max 100ms then drop)
- On vad.end:
    - after min_silence_ms = 400ms, set FLOOR = NONE and allow arbiter to pick next agent
- Agent eligibility:
    - an agent must call request_floor(reason) (tool) to enter the candidate queue
- Selection:
    - choose next speaker by priority (configured) then round-robin fairness among waiting candidates
- Talk limit:
    - max_talk_ms = 12000 per grant; after that revoke and allow others
- Handoff:
    - agents can call yield_floor(target_agent_id); arbiter revokes current then grants target (if waiting/eligible)

### Tools exposed to agents (router-intercepted)

- request_floor(reason: str) -> {granted: bool}
- yield_floor(target_agent_id: str, reason: str) -> {ok: bool}
- release_floor() -> {ok: bool} (agent signals it’s done speaking)

Prompt contract per agent:

- “You may only speak when granted the floor. If you want to respond, call request_floor. If the user starts speaking, stop
immediately and call release_floor.”

———

## Distinct Agent Voices (Gemini RealtimeModel voice)

### Per-agent configuration (fixed for the live connection)

Create one AgentSession per agent with its voice:

session = AgentSession(
    llm=google.realtime.RealtimeModel(
        model="gemini-2.5-flash-native-audio-preview-12-2025",
        voice="Aoede",  # Aoede | Charon | Fenrir | Kore | Puck
    ),
)

### Voice changes mid-call

Treat voice as connection-scoped:

- To change voice, recreate that agent’s RealtimeModel (and typically restart its live stream).
- Router behavior:
    - revoke floor if that agent is speaking
    - send playback.clear
    - reconnect agent session with new voice
    - agent can re-request the floor when ready

———

## Sessions, Memory, and Long Calls

### Memory layers

- Channel shared memory (applies to all agents):
    - call summary (rolling), user preferences, stable facts, “what we’re doing”
- Per-agent memory:
    - persona constraints, agent-specific notes, specialized context

### Session resumption / goAway handling

Per agent:

- enable ADK session resumption (when available in your RunConfig)
- persist:
    - latest resumption handle
    - compact rolling summary (for recovery if handle fails)

On goAway (or equivalent):

1. mark agent status=reconnecting
2. keep Node connection alive; keep ingesting human audio (fan-out continues)
3. tear down and recreate the Live stream using saved handle
4. when stable, mark agent status=listening
5. any pending floor requests remain queued; arbiter can grant when agent ready

### Context compression policy (practical)

- every N minutes or after M turns:
    - generate a short structured summary (facts, open tasks, user preferences)
    - store in channel memory
    - prune raw transcript from working set (keep last few turns verbatim)

———

## Reliability & Failure Modes (explicit policies)

- WS disconnect Node↔Python: Node keeps Discord voice connected; reconnect WS with exponential backoff; re-send hello + current
human presence.
- Discord voice reconnect: Node restarts audio pipelines; Python keeps agent sessions alive but gates output until Node
confirms ready.
- Agent Live session failure: mark agent unavailable; remove from floor queue; optionally fall back to text-only response
posted in a Discord text channel.
- Overload (CPU resampling / network jitter):
    - drop audio frames (oldest first)
    - shrink jitter buffer
    - reduce agent count or throttle candidate selection

———

## Observability (minimum viable)

Emit per channel + per agent metrics:

- end-to-end latency (human speech onset → first agent audio sample played)
- audio drop rate (in/out), jitter buffer depth
- floor events counts + durations
- reconnect counts + reasons
- VAD false start/stop rates (approx via heuristics)

Structured logs:

- channel_id, agent_id, seq, floor_state, event_type

———

## Testing & Acceptance Criteria

- Protocol unit tests: binary header parse/serialize; schema validation for control messages.
- DSP tests: resampler correctness (sample rate, channel count), chunk sizing.
- Integration tests (staging guild):
    - join/leave happy path
    - barge-in while agent speaking (playback stops <150ms)
    - floor fairness (A then B then C in round robin)
    - Live goAway rotation during a call (no Discord disconnect; agent recovers)
- Soak test: 2–3 hour call with periodic interruptions; memory summary updates; no unbounded queues.

Acceptance targets (v1):

- perceived response latency typically < 1s on stable network
- barge-in stops audio quickly and never “talks over” the user
- zero overlapping agent speech
