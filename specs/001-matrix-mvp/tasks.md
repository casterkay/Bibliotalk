---
description: "Executable task list for 001-matrix-mvp"
---

# Tasks: Matrix MVP (Archive Rooms + Dialogue Rooms + Voice)

**Input**: Design documents from `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/`
**Prerequisites**: `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/plan.md`, `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/spec.md`, `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/data-model.md`, `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/contracts/`, `/Users/tcai/Projects/Bibliotalk/docs/knowledge/gemini-live-api.md`

**Tests**: Automated tests are not explicitly required by `spec.md`; each phase includes an **Independent Test** that must pass before moving on.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently (after Foundation).

## Format (strict)

Every task line MUST follow:

```text
TASK_LINE: - [ ] T### [P?] [US?] Description with absolute file path
```

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the missing packages/services required by the architecture and wire them into the workspace.

- [ ] T001 [P] Add workspace members for `bt_store`, `matrix_service`, `voip_service` in `/Users/tcai/Projects/Bibliotalk/pyproject.toml`
- [ ] T002 [P] Scaffold `bt_store` package (`/Users/tcai/Projects/Bibliotalk/packages/bt_store/pyproject.toml`)
- [ ] T003 [P] Scaffold `matrix_service` Node/TS service (`/Users/tcai/Projects/Bibliotalk/services/matrix_service/package.json`)
- [ ] T004 [P] Scaffold `voip_service` Node sidecar (`/Users/tcai/Projects/Bibliotalk/services/voip_service/package.json`)
- [ ] T005 [P] Add Matrix+voice env placeholders and documentation in `/Users/tcai/Projects/Bibliotalk/deploy/local/.env.example`
- [X] T006 [P] Add local Matrix dev stack skeleton (Synapse + Element + appservice registration) in `/Users/tcai/Projects/Bibliotalk/deploy/local/matrix/docker-compose.yml`
- [X] T007 [P] Add Synapse appservice registration template in `/Users/tcai/Projects/Bibliotalk/deploy/local/matrix/appservice/bibliotalk.yaml`
- [X] T008 [P] Add Matrix stack README for local dev in `/Users/tcai/Projects/Bibliotalk/deploy/local/matrix/README.md`
- [X] T009 Update quickstart compose path + prerequisites in `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/quickstart.md`
- [X] T010 Update repo structure overview in `/Users/tcai/Projects/Bibliotalk/CODEBASE.txt`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared schema + core APIs + invariants required by ALL user stories.

**⚠️ CRITICAL**: No user story work should begin until this phase is complete.

- [ ] T011 Create async DB engine + session helpers in `/Users/tcai/Projects/Bibliotalk/packages/bt_store/src/bt_store/engine.py`
- [ ] T012 [P] Define SQLAlchemy models for `Agent`, `AgentPlatformIdentity`, `Room` in `/Users/tcai/Projects/Bibliotalk/packages/bt_store/src/bt_store/models_core.py`
- [ ] T013 [P] Define SQLAlchemy models for `Source`, `Segment` in `/Users/tcai/Projects/Bibliotalk/packages/bt_store/src/bt_store/models_evidence.py`
- [ ] T014 [P] Define SQLAlchemy models for `ChatHistory`, `PlatformPost` in `/Users/tcai/Projects/Bibliotalk/packages/bt_store/src/bt_store/models_runtime.py`
- [ ] T015 Add Alembic config + env for `bt_store` migrations in `/Users/tcai/Projects/Bibliotalk/packages/bt_store/alembic.ini`
- [ ] T016 Create initial schema migration per `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/data-model.md` in `/Users/tcai/Projects/Bibliotalk/packages/bt_store/alembic/versions/0001_initial_schema.py`
- [ ] T017 Add citation validation utility (quote substring + agent isolation) in `/Users/tcai/Projects/Bibliotalk/packages/bt_store/src/bt_store/citations.py`
- [ ] T018 Add settings for Matrix appservice + Spirit namespace in `/Users/tcai/Projects/Bibliotalk/packages/bt_common/src/config.py`
- [ ] T019 Create `agents_service` HTTP app skeleton (FastAPI) in `/Users/tcai/Projects/Bibliotalk/services/agents_service/src/agents_service/server.py`
- [ ] T020 Implement non-streaming fallback `POST /v1/agents/{agent_id}/turn` per `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/contracts/agent-turn-api.md` in `/Users/tcai/Projects/Bibliotalk/services/agents_service/src/agents_service/api/turns.py`
- [ ] T021 Implement Live Sessions create+WS endpoints per `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/contracts/agent-turn-api.md` in `/Users/tcai/Projects/Bibliotalk/services/agents_service/src/agents_service/api/live.py`
- [ ] T022 Implement Live-session cancellation/supersede semantics (turn-level cancel; last-turn-wins) in `/Users/tcai/Projects/Bibliotalk/services/agents_service/src/agents_service/live/session_manager.py`
- [ ] T023 Implement voice Live integration with Gemini Live (audio in/out + transcription forwarding) grounded on `/Users/tcai/Projects/Bibliotalk/docs/knowledge/gemini-live-api.md` in `/Users/tcai/Projects/Bibliotalk/services/agents_service/src/agents_service/live/gemini_live_backend.py`
- [ ] T024 Persist `ChatHistory` for both user inputs and Spirit outputs in `/Users/tcai/Projects/Bibliotalk/services/agents_service/src/agents_service/audit/chat_history.py`
- [ ] T025 Add stable error codes + error shape mapping in `/Users/tcai/Projects/Bibliotalk/services/agents_service/src/agents_service/api/errors.py`

**Checkpoint**: DB schema migrates cleanly; `agents_service` exposes both fallback turn API and Live Sessions API; citation validation is enforced.

---

## Phase 3: User Story 1 — Grounded Spirit Text Chat in a Dialogue Room (Priority: P1) 🎯 MVP

**Goal**: In Element, users can message a Spirit in a private Dialogue Room and receive grounded, cited responses; responses may stream; users can message while Spirit is streaming (cancel/supersede).

**Independent Test** (manual): Create a private room, invite a Spirit, send a question with known evidence, observe a cited reply; then send a second message while the first reply is streaming and verify supersede/cancel behavior. See `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/spec.md`.

- [ ] T026 [US1] Create `matrix_service` Node/TS app skeleton and health endpoint in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/server.ts`
- [ ] T027 [US1] Implement AppService auth verification (`hs_token`) per `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/contracts/matrix-events.md` in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/matrix/auth.ts`
- [ ] T028 [P] [US1] Implement inbound Matrix event parsing/models per contract in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/matrix/events.ts`
- [ ] T029 [US1] Implement inbound event guardrails (ignore edits, bots, non-text, Archive Rooms) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/matrix/guards.ts`
- [ ] T030 [US1] Implement routing rules (mentions → addressed Spirit(s); DM single-Spirit fallback; else no reply) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/matrix/routing.ts`
- [ ] T031 [US1] Implement Spirit virtual user join-on-invite + membership index maintenance in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/matrix/membership.ts`
- [ ] T032 [US1] Implement Matrix client wrapper (as_token masquerade send + edit) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/matrix/client.ts`
- [ ] T033 [US1] Implement outbound message renderer (Matrix formatting + `com.bibliotalk.citations`) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/render/matrix_message.ts`
- [ ] T034 [US1] Implement streaming delivery via message edits (`m.replace`) per `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/contracts/matrix-events.md` in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/render/streaming_edits.ts`
- [ ] T035 [US1] Implement `/_matrix/app/v1/transactions/{txn_id}` handler (parse → route → call `agents_service` Live Sessions/turn fallback → post) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/matrix/appservice.ts`
- [ ] T036 [US1] Persist Dialogue Room messages + Spirit responses to `ChatHistory` (audit trail) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/audit/write_chat_history.ts`
- [ ] T037 [P] [US1] Add operator CLI command to run matrix_service in `/Users/tcai/Projects/Bibliotalk/packages/bt_cli/src/main.py`
- [ ] T038 [US1] Validate US1 end-to-end via local Element + Synapse stack using `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/quickstart.md`

---

## Phase 4: User Story 2 — Browse a Spirit’s Archive Room in the Bibliotalk Space (Priority: P2)

**Goal**: Archive Rooms are public + read-only; ingestion publishes per-source threads idempotently (root summary + verbatim replies); zero AI replies in Archive Rooms.

**Independent Test** (manual): Open a Spirit’s Archive Room from the Space, confirm read-only for humans, confirm a source appears as a single thread root + ordered replies and retries do not duplicate. See `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/spec.md`.

- [ ] T039 [P] [US2] Add `Room.kind` enforcement helpers (archive vs dialogue) in `/Users/tcai/Projects/Bibliotalk/packages/bt_store/src/bt_store/rooms.py`
- [ ] T040 [US2] Add `PlatformPost` idempotency key helpers per `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/contracts/archive-publication.md` in `/Users/tcai/Projects/Bibliotalk/packages/bt_store/src/bt_store/platform_posts.py`
- [ ] T041 [US2] Update ingestion pipeline to write `Source` + `Segment` into `bt_store` and store deterministic root summary (from ingestion/EverMemOS metadata) in `/Users/tcai/Projects/Bibliotalk/services/ingestion_service/src/ingestion_service/pipeline/ingest.py`
- [ ] T042 [US2] Emit Archive publication intents (`PlatformPost`: `archive.thread_root` + `archive.thread_reply`) during/after ingest in `/Users/tcai/Projects/Bibliotalk/services/ingestion_service/src/ingestion_service/pipeline/ingest.py`
- [ ] T043 [US2] Implement Matrix provisioning (Space + per-agent Archive Room + power levels for read-only) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/provisioning/archive_rooms.ts`
- [ ] T044 [US2] Implement Archive publisher loop (fetch pending posts → send root/reply thread messages → mark posted) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/publish/archive_publisher.ts`
- [ ] T045 [US2] Ensure Archive publication is retry-safe (no duplicate root/replies; resume partial) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/publish/archive_publisher.ts`
- [ ] T046 [US2] Add CLI command to run Archive publisher once/loop in `/Users/tcai/Projects/Bibliotalk/packages/bt_cli/src/main.py`
- [ ] T047 [US2] Validate US2 end-to-end using `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/quickstart.md`

---

## Phase 5: User Story 3 — 1:1 Voice Call With a Spirit in a Dialogue Room (Priority: P3)

**Goal**: In Element Call, a Spirit joins a 1:1 voice call, speaks back with grounded content, and posts a paired text transcript + citations to the Dialogue Room. Voice transcripts come from Gemini Live transcription streams.

**Independent Test** (manual): Start an Element Call in a Dialogue Room, invoke “call start” for a Spirit, confirm bidirectional audio and that each Spirit turn posts transcript + citations. See `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/spec.md`.

- [ ] T048 [US3] Implement `!bt call start/stop` command parsing and dispatch in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/commands/bt_call.ts`
- [ ] T049 [US3] Implement `matrix_service` voice session registry (room ↔ agent ↔ sidecar session) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/voice/session_registry.ts`
- [ ] T050 [US3] Implement `matrix_service` internal endpoint for sidecar callbacks (join status, transcript+citations delivery) in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/voice/sidecar_callbacks.ts`
- [ ] T051 [P] [US3] Implement Node sidecar MatrixRTC join + media plumbing skeleton in `/Users/tcai/Projects/Bibliotalk/services/voip_service/src/matrixrtc.js`
- [ ] T052 [US3] Implement Opus decode (remote → PCM16k) and encode (PCM24k → Opus) in `/Users/tcai/Projects/Bibliotalk/services/voip_service/src/audio_bridge.js`
- [ ] T053 [US3] Implement sidecar ↔ agent core WS bridge per `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/contracts/voice-bridge.md` in `/Users/tcai/Projects/Bibliotalk/services/voip_service/src/index.js`
- [ ] T054 [US3] Implement sidecar → matrix_service callback delivery for final transcript+citations per `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/voice/sidecar_callbacks.ts` in `/Users/tcai/Projects/Bibliotalk/services/voip_service/src/index.js`
- [ ] T055 [US3] Ensure barge-in / interruption stops playback immediately and supersedes generation (Gemini Live interruption aligned) in `/Users/tcai/Projects/Bibliotalk/services/voip_service/src/audio_bridge.js`
- [ ] T056 [US3] Add CLI command to run `voip_service` (dev convenience wrapper) in `/Users/tcai/Projects/Bibliotalk/packages/bt_cli/src/main.py`
- [ ] T057 [US3] Validate US3 end-to-end using `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/quickstart.md`

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Reduce operational risk and keep the repo coherent while Discord support is allowed to temporarily break.

- [ ] T058 Document Discord “may break” posture + migration plan in `/Users/tcai/Projects/Bibliotalk/README.md`
- [ ] T059 Add structured logging + correlation IDs across Matrix transactions and agent turns in `/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/obs/logging.ts`
- [ ] T060 Add secrets redaction for logs and persisted errors in `/Users/tcai/Projects/Bibliotalk/packages/bt_common/src/logging.py`
- [ ] T061 Add one-shot backfill script (legacy `bt_common.evidence_store` → `bt_store`) in `/Users/tcai/Projects/Bibliotalk/scripts/backfill_bt_store_v2.py`
- [ ] T062 Remove or quarantine `bt_common.evidence_store` to keep `bt_common` infra-only in `/Users/tcai/Projects/Bibliotalk/packages/bt_common/src/evidence_store/__init__.py`
- [ ] T063 Final docs consistency pass (spec/plan/contracts/quickstart) in `/Users/tcai/Projects/Bibliotalk/specs/001-matrix-mvp/spec.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 → Phase 2 is required.
- Phase 2 blocks all user stories.
- After Phase 2:
  - US1 (P1) is the MVP slice and should ship first.
  - US2 (P2) can proceed after Phase 2, but is easiest once Matrix client + provisioning primitives exist (from US1).
  - US3 (P3) depends on US1 (Matrix adapter + Spirit identity + posting) and the Phase 2 Live Sessions foundation.

### User Story completion order (recommended)

1) US1 → 2) US2 → 3) US3

---

## Parallel Execution Examples

### US1 parallelizable clusters

- Implement parsing/guards/routing in parallel: T028, T029, T030 (`/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/matrix/`)
- Implement Matrix client + renderer in parallel: T032, T033, T034 (`/Users/tcai/Projects/Bibliotalk/services/matrix_service/src/`)

### US2 parallelizable clusters

- Ingestion intents and Matrix publishing can proceed in parallel after schema exists: T041–T042 vs T043–T046

### US3 parallelizable clusters

- Node sidecar RTC + audio bridge can proceed in parallel: T051 vs T052 (`/Users/tcai/Projects/Bibliotalk/services/voip_service/src/`)

---

## Implementation Strategy (MVP-first)

1. Complete Phase 1 + Phase 2.
2. Implement US1 (Phase 3) and stop to validate.
3. Add US2 (Phase 4) for trust foundation (Archive Rooms).
4. Add US3 (Phase 5) for the voice demo.
