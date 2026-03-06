# Tasks: Agent Service

**Feature**: `001-agent-service`  
**Created**: 2026-02-28  
**Last Updated**: 2026-03-03  
**Input**: `BLUEPRINT.md` + `specs/001-agent-service/*`

This task list is a living checklist for bringing the implementation in `services/agents_service/` in line with `BLUEPRINT.md`.

## Conventions

- `[x]` = present in the repository (may still be scaffold/placeholder)
- `[ ]` = not yet implemented (or not yet wired end-to-end)

## Path Conventions (authoritative)

- `packages/bt_common/src/`: infra-only shared code (`evermemos_client`, `config`, `logging`, `exceptions`)
- `services/agents_service/src/`: agent runtime + Matrix formatting + citations + voice orchestration
- `services/voice_call_service/src/`: Node.js MatrixRTC/WebRTC sidecar (voice bridge)
- Tests live alongside their code:
  - `packages/bt_common/tests/`
  - `services/agents_service/tests/`

---

## Phase 0: Spec/Contract Sync

- [x] Align `specs/001-agent-service/` docs to `BLUEPRINT.md` ownership boundaries and repo layout

---

## US1 (P1): Private Text Chat With Grounded Citations

**Goal**: A Ghost can answer in private chat with evidence-backed citations; citations are verifiable against canonical segments.

- [x] EverMemOS client wrapper + retry/error mapping (`packages/bt_common/src/evermemos_client.py`)
- [x] Citation/Evidence models + validation helpers (`services/agents_service/src/models/citation.py`)
- [x] Source/Segment models + BM25 rerank (`services/agents_service/src/models/segment.py`)
- [x] Retrieval tool (`services/agents_service/src/agent/tools/memory_search.py`)
- [x] Citation emission + validation tool (`services/agents_service/src/agent/tools/emit_citations.py`)
- [x] Matrix response formatter (`services/agents_service/src/matrix/appservice.py#format_ghost_response`)
- [x] CLI harness for rapid iteration (`services/agents_service/src/__main__.py`)
- [x] Rate limiter guard (`services/agents_service/src/matrix/guards.py`)

Pending to match `BLUEPRINT.md` behavior:

- [x] Room classification: enforce “no AI in profile rooms” by checking `profile_rooms` (not just Matrix permissions)
- [x] Group room routing: respond only when directly addressed/mentioned (avoid reply storms) (DMs allowed when exactly one Ghost is joined)
- [x] Evidence mapping: use EverMemOS `group_id` → `sources/segments` narrowing before reranking (avoid reranking over all segments)
- [x] Citation marker policy: ensure inline markers exist (auto-append `[^N]` markers when missing)
- [x] Matrix send pipeline: send as the Ghost via Matrix CS API using the appservice `as_token`

Tests:

- [x] `bt_common` unit/contract tests exist (`packages/bt_common/tests/`)
- [x] `agents_service` unit/integration tests exist (`services/agents_service/tests/`)
- [x] Add targeted tests for appservice routing, marker behavior, and citation payload shape (`services/agents_service/tests/unit/test_matrix_appservice.py`)
- [x] ADK-backed Gemini provider wired into the agent runtime (`services/agents_service/src/agent/providers/gemini.py`, `services/agents_service/src/agent/agent_factory.py`)

---

## US2 (P2): Multi-Agent Text Discussions (Floor Control)

**Goal**: Multiple Ghosts can discuss a topic with strict turn-taking; user messages preempt immediately.

- [x] Basic discussion orchestrator scaffold exists (`services/agents_service/src/agent/orchestrator.py`)

Pending:

- [ ] Implement floor controller state machine per `contracts/discussion-floor-control.md`
- [ ] Add cancellation tokens and deterministic scheduling (mention boost + fairness + cooldowns)
- [ ] Stream text to Matrix via edits (placeholder → streaming → finalize)
- [ ] Add unit tests for force-preemption rules and cancellation timing

---

## US3 (P3): Voice Calls (MatrixRTC + Voice Backends)

**Goal**: A Ghost can participate in an unencrypted Element Call; audio turns produce a parallel transcript with citations.

- [x] VoiceBackend ABC (`services/agents_service/src/voice/backends/base.py`)
- [x] Placeholder backends (mockable local implementations)
  - `services/agents_service/src/voice/backends/nova_sonic.py`
  - `services/agents_service/src/voice/backends/gemini_live.py`
- [x] Voice session manager scaffold (`services/agents_service/src/voice/session_manager.py`)
- [x] Transcript collector scaffold (`services/agents_service/src/voice/transcript.py`)
- [x] Node sidecar scaffold (`services/voice_call_service/src/`)

Pending:

- [ ] Define a concrete WebSocket bridge protocol between `voice_call_service` and `agents_service`
- [ ] Implement Opus decode/encode and sample-rate conversion in the sidecar
- [ ] Implement real MatrixRTC join/signaling (matrix-js-sdk + Element Call flows)
- [ ] Add mid-stream tool-use plumbing for voice backends (ToolCall → tool result → resume)
- [ ] Post voice transcripts into a room thread with validated citations

---

## US4 (P4): Multi-Agent Voice Discussions

**Goal**: “Agentic podcasts” with multiple Ghosts in voice, strict floor gating, and user barge-in.

Pending:

- [ ] Integrate floor control with voice session manager (mute non-speakers; zero overlap)
- [ ] Support multiple concurrent voice backends per room
- [ ] Sidecar mixing/muting that enforces floor grants (only active speaker audio forwarded)
- [ ] Transcript captures all speaker turns with per-speaker citations

---

## Proposed Improvements (Non-Blocking)

- [x] Fix `services/voice_call_service/package.json` to run `src/index.js` via `npm start`
- [x] Make `.env` discovery robust (support repo-root `.env` even when running from service directories)
- [ ] Clarify EverMemOS API versioning in contracts (v0/v1 path strings) while keeping shape-based tests
- [ ] Add a dedicated Matrix event contract doc for appservice transactions and message send payloads

---

## Local E2E (Dev UX): Synapse + Element Web + SQLite

**Goal**: A single-command-ish local workflow that provisions Matrix + Ghosts + rooms + profile timelines so you can chat with Ghosts in Element.

Pending:

- [x] Add a DB abstraction and implement SQLAlchemy + SQLite backend for `agents_service`
- [x] Add appservice user query endpoint `GET /_matrix/app/v1/users/{userId}` for virtual user resolution
- [x] Add `agents_service.bootstrap` CLI:
  - [x] `seed-ghosts` (agents + agent_emos_config)
  - [x] `import-segment-cache` (`.ingestion_service/segment_cache/*.jsonl` → `sources`/`segments`)
  - [x] `provision-matrix` (Space + rooms + invites + power levels)
  - [x] `post-profile-timeline` (threads from canonical segments)
  - [x] `smoke-test` (DM → reply → citations)
- [x] Add `deploy/local/docker-compose.yml` for Synapse + Element Web
- [x] Add SQLAlchemy ORM schema under `services/agents_service/src/database/sqlalchemy_models.py`
