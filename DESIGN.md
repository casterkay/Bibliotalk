# Bibliotalk Design Blueprint

Bibliotalk’s goal is to make real-time voice AI feel like a **research instrument**: fast, interruptible, and *auditable*.

This document defines the target system design for Bibliotalk’s **Matrix-first MVP** (Element UI), aligned with:
- `specs/001-matrix-mvp/spec.md`
- `specs/001-matrix-mvp/plan.md`
- `specs/001-matrix-mvp/contracts/`

Discord support is a **future adapter** and MAY temporarily break during the Matrix MVP refactor.

## Glossary

- **Agent / Spirit**: A persona that responds only using its own ingested evidence.
- **Archive Room**: Public, read-only, non-interactive. Per source: thread root = deterministic source summary from ingestion / EverMemOS metadata; replies = ordered verbatim transcript excerpts.
- **Dialogue Room**: Private, interactive room for grounded text chat and (MVP) 1:1 voice calls.

## Non-Negotiables

1. **Grounding-first**: Every eligible response searches memory before answering.
2. **No evidence → explicit**: If no relevant evidence exists, the Spirit must say so.
3. **Verifiable citations**: Every citation quote must be a substring of canonical stored segments for that agent.
4. **Strict isolation**: Cross-agent evidence leakage is always invalid.
5. **Archive is non-interactive**: Zero AI responses in Archive Rooms under all conditions.
6. **Idempotent publication**: Archive publishing is retry-safe (no duplicate thread roots/replies).
7. **Streaming-first UX**: Users can send messages while a Spirit is streaming output (cancel/supersede semantics).
8. **Voice transcripts come from Gemini Live**: Use Live API input/output transcription streams; do not reinvent ASR.

## MVP user experience (what “done” feels like)

- In a **Dialogue Room**, a user messages `@bt_socrates:server` and sees a Spirit response stream in-place (edits), with citations.
- The user interrupts mid-stream with a follow-up; the Spirit cancels and pivots.
- In an **Archive Room**, a new ingested source appears as a thread:
  - root = deterministic summary artifact (from ingestion/EverMemOS episodic memory)
  - replies = verbatim excerpt posts (segments)
- In an Element Call, the Spirit joins as a MatrixRTC participant and speaks; the room receives a paired transcript + citations.

## Service Topology (target)

```text
packages/
  bt_common/        # infra-only (config/logging/exceptions/EverMemOS client)
  bt_store/         # shared relational schema + migrations (SQLAlchemy + Alembic)

services/
  agents_service/       # Python: platform-agnostic agent core + Live Sessions
  ingestion_service/    # Python: ingestion pipeline; writes sources/segments + publish intents
  matrix_service/       # Node/TS: Matrix AppService adapter + publisher loop (matrix-js-sdk)
  voice_call_service/   # Node: MatrixRTC/WebRTC sidecar; audio bridge to agents_service
  memory_page_service/  # optional: public pages for evidence inspection (future UX)
```

### Why `matrix_service` is Node/TS

`matrix_service` is implemented in Node.js/TypeScript using `matrix-js-sdk` to align with the most actively used Matrix SDK ecosystem (Element’s primary stack) and reduce integration/maintenance risk.

### Why voice remains a separate sidecar

`voice_call_service` stays separate from `matrix_service` to reduce blast radius: real-time media + native deps must not take down text chat (see “voice failures must leave text chat functional” in MVP requirements).

### Implementation note (current repo state)

The voice sidecar currently lives at `services/voip_service/` in this repository. The design target name is `voice_call_service` to reflect its role more clearly; renaming is planned.

## Contracts (source of truth)

The Matrix MVP is contract-driven; treat these as normative:

- Agent interaction (streaming-first Live Sessions + fallback): `specs/001-matrix-mvp/contracts/agent-turn-api.md`
- Matrix inbound/outbound events + AppService auth (`hs_token`): `specs/001-matrix-mvp/contracts/matrix-events.md`
- Citation payload + validation: `specs/001-matrix-mvp/contracts/citation-schema.md`
- Archive publication intents + idempotency keys: `specs/001-matrix-mvp/contracts/archive-publication.md`
- Voice sidecar ↔ agent core protocol (audio + transcription + interruption): `specs/001-matrix-mvp/contracts/voice-bridge.md`

### Interaction model (streaming is the product)

For MVP, the “turn-based API” exists only as a **fallback** integration path. The first-class product experience is:

- **Text**: stream a Spirit’s response as deltas; allow user interruption; cancel/supersede in-progress output.
- **Voice**: full-duplex barge-in; keep transcripts and citations as durable artifacts in the Dialogue Room.

Hackathon advice: judges feel the difference immediately when the system behaves like a live conversation rather than a request/response bot.

### Citation rendering stance

Citation marker style is **adapter-owned and implementation-defined** per platform. The agent core emits:
- plain text, and
- structured citations (validated),
and the adapter formats markers for Matrix/Discord.

This is not just a UI preference: it prevents platform markup from leaking into the “truth layer”, and lets each adapter pick the best conventions (Matrix HTML vs Discord markdown).

## Storage Model (bt_store overview)

The unified relational schema (SQLite dev, Postgres prod) is owned by `bt_store` and shared across services.

Core tables (logical):
- **agents**: Spirit identity and persona settings
- **agent_platform_id**: per-platform Spirit IDs (e.g., Matrix virtual user ID)
- **rooms**: platform room registry (`archive` vs `dialogue`, immutable kind)
- **sources / segments**: canonical evidence backing grounding + citations and Archive Rooms
- **chat_history**: audit trail of Dialogue Room turns (text + voice transcripts + citations)
- **platform_posts**: durable publish intents (e.g., `archive.thread_root`, `archive.thread_reply`)

Idempotency:
- Archive publication uniqueness is enforced via deterministic `idempotency_key` per post intent, derived from `(agent_id, source_id, seq)` (see contract).

## Core Flows

### 1) Dialogue Room text chat (streaming-first)

```text
Synapse AppService txn
  -> matrix_service (auth + parse + routing + guardrails)
    -> agents_service Live Session (WS)
      -> grounded retrieval + citation validation
      -> stream output (text deltas) + final citations
    -> matrix_service streams to Matrix (message edits) + persists ChatHistory
```

Key invariants:
- ignore bot loops (Spirit-originated messages never trigger new turns)
- ignore edits for routing, but outbound edits are used to stream Spirit output
- users may send a new message during streaming; system cancels/supersedes the prior output

Design advice (to win on stage):
- Prefer **one** continuously edited Spirit message per turn (stream deltas), and then append a compact “Sources” footer at the end.
- If streaming fails, fall back to a non-streaming final message rather than hanging (demo resilience > perfection).
- Keep a tight latency loop: “first token fast” matters more than perfect formatting.

### 2) Archive publication (ingestion-backed, retry-safe)

```text
ingestion_service
  -> writes Source + Segment rows (canonical evidence)
  -> writes platform_posts intents:
       archive.thread_root (root summary from ingestion/EverMemOS metadata)
       archive.thread_reply (verbatim segment replies)

matrix_service publisher loop
  -> reads pending platform_posts
  -> posts to Archive Room as Spirit
  -> records platform_event_id + status
```

Archive Room semantics:
- root is a deterministic “source summary” artifact (not newly generated at publish time)
- replies are verbatim transcript excerpts, ordered by `Segment.seq`

### 3) Dialogue Room voice calls (1:1 MVP)

```text
Element Call (MatrixRTC)
  -> voice_call_service joins call as Spirit and receives Opus audio
  -> decode to PCM16k and stream to agents_service (WS bridge)
  -> agents_service uses Gemini Live for audio I/O + transcription streams
  -> grounded text reasoning remains authority for content + citations
  -> voice_call_service publishes Spirit audio back to call (Opus)
  -> matrix_service posts paired text transcript + citations to the Dialogue Room
```

Notes:
- transcripts are forwarded from Gemini Live’s transcription streams
- interruption/barge-in is first-class; ongoing output must stop immediately

Design advice (to win on stage):
- Treat voice as a **state machine**: `idle → listening → thinking → speaking → idle`, and surface state transitions in logs.
- Always post the paired transcript + citations even if the call glitches (it’s the proof artifact the judges will remember).
- Pre-warm Gemini Live sessions where possible to avoid first-response cold-start during a demo.

## Matrix Room Taxonomy (MVP)

- Exactly two immutable kinds: **Archive** and **Dialogue**.
- Archive Rooms are public + read-only for humans (power levels), and non-interactive in the adapter.
- Dialogue Rooms are invite-only and interactive; calls are allowed.

## Security & abuse-resistance (minimum viable)

- **AppService auth is mandatory**: verify `hs_token` on every inbound transaction (see `specs/001-matrix-mvp/contracts/matrix-events.md`).
- **Loop prevention**: ignore events sent by Spirit virtual users.
- **Archive guardrail**: rooms marked `archive` are ignored for routing under all conditions.
- **Prompt injection posture**: sources are evidence, not instructions; system prompts must enforce “quote-and-cite, or decline”.

Hackathon reality: we don’t need perfect policy, but we do need predictable behavior under adversarial prompts.

## Observability (demo-grade)

Make the system legible in real time:

- Structured logs with a `turn_id` / `voice_session_id` that ties together:
  - Matrix event id → Live session → retrieval result count → citations validation → outbound Matrix edits.
- Record key timing points (`t0 recv`, `t1 retrieved`, `t2 first token`, `t3 final`, `t4 posted`) so we can optimize latency quickly.
- Emit “why no answer” reasons (`no_evidence`, `room_guardrail`, `not_addressed`, `rate_limited`).

If we do nothing else for engineering polish, do this: judges can *feel* robustness when debugging is easy.

## Latency & reliability targets (practical for demos)

- **Text**: show visible streaming within ~1s after user send (best-effort; depends on model/network).
- **Voice**: barge-in cancels output within ~250ms (best-effort); never “talk over” the user.
- **Degrade gracefully**:
  - if citations fail validation, respond with “no evidence” instead of hallucinating
  - if voice is down, text chat continues unaffected
  - if Matrix edits fail, send a final non-streaming message

## Migration Plan (from legacy Discord-era schema)

The repository currently contains a legacy schema under `bt_common.evidence_store` that is Discord-oriented.

Target state:
- Move shared relational schema ownership to `bt_store`.
- Provide a one-shot backfill script to map:
  - `figures` → `agents` (preserve UUIDs)
  - existing `sources/segments` → new evidence tables (agent_id = figure_id)
- Allow Discord to temporarily break during this migration; reintroduce as an adapter later.

## Local Development

Use the Matrix MVP quickstart as the canonical dev loop:

- `specs/001-matrix-mvp/quickstart.md`

## Demo plan (3 minutes)

1. **Archive**: open a Spirit’s Archive Room and show a thread: summary root + excerpt replies.
2. **Chat**: ask a question, show live streaming, then interrupt with a sharper follow-up.
3. **Proof**: click a citation and show the excerpt contains the quoted substring.
4. **Voice**: start an Element Call; Spirit speaks; point to posted transcript + citations.

This sequence tells a tight story: “voice is fun, but citations make it trustworthy.”

## Future Work (post-MVP)

- Group voice calls + floor control (see `_ref/matrix-feature/contracts/discussion-floor-control.md` for ideas)
- Voice E2EE (deferred)
- Discord adapter parity on top of the same `agents_service` + `bt_store` contracts
