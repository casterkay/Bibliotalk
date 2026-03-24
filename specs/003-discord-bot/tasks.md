# Tasks: YouTube → EverMemOS → Discord Agent Bots

**Input**: Design documents from `/specs/003-discord-bot/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Include unit, contract, and integration tests because the plan and constitution require test coverage for chunking, dedup, citation validation, EverMemOS interactions, page resolution, and critical end-to-end flows.

**Organization**: Tasks are grouped by phase and then by user story so each story can be implemented and validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Remove out-of-scope code, align package manifests, and create the new standalone runtimes.

- [X] T001 Delete Matrix transport code in `services/agents_service/src/matrix/`
- [X] T002 Delete voice runtime code in `services/agents_service/src/voice/`
- [X] T003 Delete SQLAdmin UI code in `services/agents_service/src/admin/`
- [X] T004 Delete legacy database layer in `services/agents_service/src/database/`
- [X] T005 Delete unused Gemini alternatives and legacy server entrypoint code in `services/agents_service/src/agents_service/server.py`
- [X] T006 Delete non-YouTube adapters in `services/memory_service/src/adapters/blog_crawl.py`, `services/memory_service/src/adapters/document.py`, `services/memory_service/src/adapters/gutenberg.py`, `services/memory_service/src/adapters/http_fetch.py`, `services/memory_service/src/adapters/local_text.py`, `services/memory_service/src/adapters/url_tools.py`, and `services/memory_service/src/adapters/web_page.py`
- [X] T007 Delete non-MVP ingestion entrypoints in `services/memory_service/src/server.py` and `services/memory_service/src/pipeline/manifest.py`
- [X] T008 Update retained package dependencies in `services/memory_service/pyproject.toml` and `services/agents_service/pyproject.toml` to match the trimmed MVP scope
- [X] T009 Create the shared evidence-store package skeleton in `packages/bt_common/src/evidence_store/__init__.py`, `packages/bt_common/src/evidence_store/engine.py`, and `packages/bt_common/src/evidence_store/models.py`
- [X] T010 [P] Create the new Discord runtime package skeleton in `services/discord_service/pyproject.toml`, `services/discord_service/src/__init__.py`, `services/discord_service/src/__main__.py`, and `services/discord_service/tests/__init__.py`
- [X] T011 [P] Create the unified Memories API (FastAPI) inside `services/memory_service/src/api/` (HTML `/memories/{id}` + JSON `/v1/*`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the shared database, configuration, runtime wiring, and reusable library boundaries that all user stories depend on.

**⚠️ CRITICAL**: No user story work should begin until this phase is complete.

- [X] T012 Create the SQLAlchemy async engine and session factory in `packages/bt_common/src/evidence_store/engine.py`
- [X] T013 Create the shared ORM schema in `packages/bt_common/src/evidence_store/models.py`
- [X] T014 Create the initial Alembic environment and first migration in `services/memory_service/alembic/env.py` and `services/memory_service/alembic/versions/0001_initial_schema.py`
- [X] T015 [P] Create standalone collector configuration models in `services/memory_service/src/runtime/config.py`
- [X] T016 [P] Create Discord runtime configuration models in `services/discord_service/src/config.py`
- [X] T017 [P] Add structured logging bootstrap for the collector and Discord runtimes in `services/memory_service/src/runtime/reporting.py` and `services/discord_service/src/runtime.py`
- [X] T018 Refactor `services/memory_service/src/pipeline/index.py` to use `AsyncSession` from `packages/bt_common/src/evidence_store/engine.py`
- [X] T019 Refactor `services/memory_service/src/domain/models.py` to keep only YouTube and evidence-cache fields needed by the MVP in `services/memory_service/src/domain/models.py`
- [X] T020 Refactor `services/agents_service/src/models/citation.py` to the new `Evidence` and link-validation contract from `specs/003-discord-bot/contracts/evidence.md`
- [X] T021 Create the standalone collector process bootstrap in `services/memory_service/src/__main__.py` and `services/memory_service/src/runtime/poller.py`
- [X] T022 Create the Discord bot process bootstrap in `services/discord_service/src/runtime.py` and `services/discord_service/src/__main__.py`
- [X] T023 [P] Add foundational database and startup tests in `packages/bt_common/tests/test_evidence_store_models.py`, `services/memory_service/tests/integration/test_runtime_startup.py`, and `services/discord_service/tests/integration/test_runtime_startup.py`

**Checkpoint**: Shared DB infra, collector runtime, and Discord runtime boundaries are ready for story implementation.

---

## Phase 3: User Story 1 - Ingest a YouTube Channel Into EverMemOS (Priority: P1) 🎯 MVP

**Goal**: Discover new YouTube videos for an agent, ingest transcripts into SQLite and EverMemOS, derive transcript batches, and support clean manual re-ingest.

**Independent Test**: Configure one agent with one subscription source, run a poll once, and verify `sources`, `segments`, and `transcript_batches` are created while EverMemOS receives stable `group_id` and `message_id` values. Poll again and confirm the same `video_id` is skipped.

### Tests for User Story 1

- [X] T024 [P] [US1] Add unit tests for YouTube discovery delta logic in `services/memory_service/tests/unit/test_discovery.py`
- [X] T025 [P] [US1] Add unit tests for SQLAlchemy-backed ingest index behavior in `services/memory_service/tests/unit/test_index.py`
- [X] T026 [P] [US1] Add unit tests for per-source concurrency gates keyed by `subscription_id` in `services/memory_service/tests/unit/test_poller_concurrency.py`
- [X] T027 [P] [US1] Add integration tests for ingest, transcript-batch derivation, dedup, and manual re-ingest in `services/memory_service/tests/integration/test_ingest_pipeline.py`
- [X] T028 [P] [US1] Add contract tests for EverMemOS memorize, conversation-meta, and delete-by-group-id calls in `packages/bt_common/tests/test_evermemos_client_contract.py`

### Implementation for User Story 1

- [X] T029 [P] [US1] Implement yt-dlp flat extraction and RSS fallback discovery in `services/memory_service/src/pipeline/discovery.py`
- [X] T030 [P] [US1] Adapt transcript and metadata loading for the trimmed MVP in `services/memory_service/src/adapters/youtube_transcript.py` and `services/memory_service/src/adapters/rss_feed.py`
- [X] T031 [P] [US1] Preserve stable YouTube identifier builders in `services/memory_service/src/domain/ids.py`
- [X] T032 [US1] Refactor the ingest pipeline to persist `Source`, `Segment`, and `TranscriptBatch` rows through SQLAlchemy in `services/memory_service/src/pipeline/ingest.py`
- [X] T033 [US1] Implement standalone collector orchestration for subscription polling, queueing, backoff, and per-source concurrency controls in `services/memory_service/src/runtime/poller.py`
- [X] T034 [US1] Implement end-to-end collector workflow and manual re-ingest handling in `services/memory_service/src/pipeline/ingest.py` and `services/memory_service/src/runtime/poller.py`
- [X] T035 [US1] Wire the collector into the standalone ingestion process in `services/memory_service/src/__main__.py`
- [X] T036 [US1] Add ingest-specific structured logs and failure state updates in `services/memory_service/src/runtime/poller.py` and `services/memory_service/src/pipeline/ingest.py`

**Checkpoint**: User Story 1 is functional when a single agent can discover, ingest, derive transcript batches, deduplicate, enforce per-source concurrency, and manually re-ingest YouTube videos without any Discord feed or DM chat features enabled.

---

## Phase 4: User Story 2 - Publish Video Feed Into a Discord Channel Thread (Priority: P2)

**Goal**: Post one parent feed message and one per-video thread with ordered transcript batches, without duplicate posts on retry.

**Independent Test**: After a successful ingest, run the feed publisher and verify exactly one parent message, one thread, and one ordered set of batch posts are created. Re-run the publisher and verify nothing is duplicated.

### Tests for User Story 2

- [X] T037 [P] [US2] Add unit tests for transcript batching rules in `services/discord_service/tests/unit/test_batcher.py`
- [X] T038 [P] [US2] Add unit tests for Discord post idempotency state transitions in `services/discord_service/tests/unit/test_feed_publisher.py`
- [X] T039 [P] [US2] Add integration tests for parent-post, thread creation, retry, and resume behavior in `services/discord_service/tests/integration/test_feed_publication.py`
- [X] T040 [P] [US2] Add contract tests for Discord message shapes from `specs/003-discord-bot/contracts/discord-messages.md` in `services/discord_service/tests/contract/test_discord_message_models.py`

### Implementation for User Story 2

- [X] T041 [P] [US2] Implement transcript batch grouping in `services/discord_service/src/feed/batcher.py`
- [X] T042 [P] [US2] Implement typed Discord boundary models in `services/discord_service/src/bot/message_models.py`
- [X] T043 [US2] Implement feed parent-message and thread publisher logic in `services/discord_service/src/feed/publisher.py`
- [X] T044 [US2] Persist and resume `discord_posts` state during feed publication in `services/discord_service/src/feed/publisher.py` and `packages/bt_common/src/evidence_store/models.py`
- [X] T045 [US2] Trigger feed publication from newly ingested videos by reading shared ingest state in `services/discord_service/src/feed/publisher.py` and `services/discord_service/src/runtime.py`
- [X] T046 [US2] Add rate-limit handling and retry logging for Discord publication in `services/discord_service/src/feed/publisher.py`

**Checkpoint**: User Story 2 is functional when the system can publish feed content for already-ingested videos, retry safely, and avoid duplicate threads or messages.

---

## Phase 5: User Story 3 - Grounded DM Chat With an Agent Bot (Priority: P3)

**Goal**: Route Discord DMs through a Gemini/ADK agent runtime that retrieves evidence, emits inline memory links, validates links and quotes before sending, and resolves those links through the unified Memories API in `memory_service`.

**Independent Test**: DM an agent bot with a question that matches ingested transcript text and verify the response includes at least one valid inline `memory_url` link. Load the linked page and verify it resolves exactly one MemCell plus a timestamped source link when applicable. Ask a question without supporting evidence and verify the explicit no-evidence response.

### Tests for User Story 3

- [X] T047 [P] [US3] Add unit tests for BM25-backed evidence selection in `services/agents_service/tests/unit/test_memory_search.py`
- [X] T048 [P] [US3] Add unit tests for inline link and quote validation in `services/agents_service/tests/unit/test_citation_validation.py`
- [X] T049 [P] [US3] Add integration tests for talk-thread response generation and no-evidence fallback in `services/discord_service/tests/integration/test_talk_chat.py`
- [X] T050 [P] [US3] Add contract tests for `Evidence` construction and link validation in `services/agents_service/tests/contract/test_evidence_contract.py`
- [X] T051 [P] [US3] Add contract tests for EverMemOS search/retrieval calls in `packages/bt_common/tests/test_evermemos_search_contract.py`
- [X] T052 [P] [US3] Add contract and integration tests for public memory pages in `services/memory_service/tests/contract/test_memory_id_contract.py` and `services/memory_service/tests/integration/test_memories_api.py`

### Implementation for User Story 3

- [X] T053 [P] [US3] Adapt EverMemOS retrieval and BM25 reranking to the new evidence shape in `services/agents_service/src/agents_service/agent/tools/memory_search.py`
- [X] T054 [P] [US3] Replace citation-index emission with inline `memory_url` emission in `services/agents_service/src/agents_service/agent/tools/emit_citations.py`
- [X] T055 [P] [US3] Adapt Gemini agent construction for agent personas and evidence-only responses in `services/agents_service/src/agents_service/agent/agent_factory.py` and `services/agents_service/src/agents_service/agent/providers/gemini.py`
- [X] T056 [US3] Adapt agent orchestration for Discord DM context in `services/agents_service/src/agents_service/agent/orchestrator.py`
- [X] T057 [US3] Implement the talk-thread chat service and routing in `services/discord_service/src/talks/service.py`
- [X] T058 [US3] Implement the Discord client subclass (DM `/talk` + thread routing) in `services/discord_service/src/bot/client.py`
- [X] T059 [US3] Implement the memory page resolver and HTTP handler in `services/memory_service/src/api/memories_service.py` and `services/memory_service/src/api/app.py`
- [X] T060 [US3] Add final link-validation, quote-validation, no-evidence fallback, and page-resolution enforcement in `services/discord_service/src/talks/service.py`, `services/agents_service/src/agents_service/models/citation.py`, and `services/memory_service/src/api/app.py`

**Checkpoint**: User Story 3 is functional when an agent bot can answer supported questions with valid inline memory links, linked pages resolve correctly, and unsupported questions are declined without cross-agent leakage.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Finalize operational readiness, documentation, and full-system validation.

- [X] T061 [P] Update deployment and local runtime docs in `README.md`, `DESIGN.md`, and `deploy/local/docker-compose.yml`
- [X] T062 [P] Add developer seed and manual-ingest helper scripts in `services/discord_service/scripts/seed_agent.py` and `services/memory_service/scripts/trigger_ingest.py`
- [X] T063 Add end-to-end quickstart validation coverage in `services/discord_service/tests/integration/test_quickstart_flow.py` and `services/memory_service/tests/integration/test_memories_api.py`
- [X] T064 Run and fix the documented quickstart workflow in `specs/003-discord-bot/quickstart.md`
- [X] T065 Remove stale references to Matrix, voice, and non-YouTube ingestion from `AGENTS.md`, `README.md`, and `.github/agents/copilot-instructions.md`

---

## Phase 7: User Story 4 - Discord Voice Channels (Gemini Live) 🎙️

**Purpose**: Add Discord voice-channel conversations driven by Gemini Live, while keeping `discord_service` as the only Discord gateway client and using `voip_service` as the media-plane bridge.

**Independent Test**: In a test guild, run `/voice join` from a user connected to a voice channel, speak a short question, confirm the bot responds in audio, confirm barge-in interrupts playback, and confirm transcripts are posted to the configured text channel/thread.

### Docs + Contracts

- [X] T066 [P] [US4] Update system and Discord bot docs to treat Discord voice as first-class in `DESIGN.md`, `specs/003-discord-bot/spec.md`, `specs/003-discord-bot/plan.md`, and `specs/003-discord-bot/tasks.md`
- [ ] T067 [P] [US4] Reconcile voice-bridge contract drift (document the operational truth and plan the fix) in `specs/001-matrix-mvp/contracts/voice-bridge.md` and `services/agents_service/src/agents_service/api/live.py`

### Discord UX + Control Plane (`discord_service`, Python)

- [ ] T068 [P] [US4] Add Discord voice runtime config (voip_service URL, transcript channel defaults) in `services/discord_service/src/config.py`
- [ ] T069 [US4] Add `/voice join|leave|status` commands and authorization checks in `services/discord_service/src/bot/client.py`
- [ ] T070 [US4] Persist Discord voice bindings via `PlatformRoute` (`purpose="voice"`) in `services/discord_service/src/talks/service.py` and `packages/bt_store/src/models_runtime.py`
- [ ] T071 [US4] Implement the gateway-proxy client (forward `VOICE_*` dispatches; execute join/leave requests) in `services/discord_service/src/bot/voice_gateway_proxy.py`
- [ ] T072 [P] [US4] Add unit tests for voice route parsing and command gating in `services/discord_service/tests/unit/test_voice_routes.py`

### Media Plane (`voip_service`, Node)

- [ ] T073 [P] [US4] Extend `POST /v1/voip/ensure` request model to support `platform="discord"` in `services/voip_service/src/voip/http_models.js` and `services/voip_service/src/server.js`
- [ ] T074 [US4] Add internal WS endpoint for gateway-proxy events (VOICE_SERVER/STATE updates; request voice-state changes) in `services/voip_service/src/server.js` and `services/voip_service/src/voip/discord_gateway_proxy.js`
- [ ] T075 [US4] Implement Discord voice bridge (Opus in/out, resampling, Live Session WS) in `services/voip_service/src/voip/discord_bridge.js` and `services/voip_service/src/voip/bridge_manager.js`
- [ ] T076 [US4] Implement barge-in behavior (stop playback + clear ring buffer) in `services/voip_service/src/voip/discord_bridge.js` and `services/voip_service/src/voip/pcm.js`

### Transcript Artifacts

- [ ] T077 [US4] Post coalesced input/output transcripts into the configured Discord text channel/thread in `services/discord_service/src/bot/voice_transcripts.py`
- [ ] T078 [P] [US4] Add integration-ish tests for transcript coalescing and rate-limit-safe posting in `services/discord_service/tests/integration/test_voice_transcripts.py`

### Deployment

- [ ] T079 [P] [US4] Add local dev wiring for `voip_service` alongside Discord in `deploy/local/docker-compose.yml` and document required env vars in `README.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1: Setup**: No dependencies; start immediately.
- **Phase 2: Foundational**: Depends on Phase 1; blocks all user stories.
- **Phase 3: User Story 1**: Depends on Phase 2; delivers the standalone ingest core.
- **Phase 4: User Story 2**: Depends on Phase 2 and reuses ingested `transcript_batches`; should be built after US1 for a working feed path.
- **Phase 5: User Story 3**: Depends on Phase 2, on US1 producing ingested evidence, and on the memory-page service resolving `memory_url` pages.
- **Phase 6: Polish**: Depends on the user stories selected for delivery.
- **Phase 7: User Story 4**: Depends on Phase 2 and the existing Live Session voice plumbing; must not break Discord text UX.

### User Story Dependencies

- **User Story 1 (P1)**: No dependency on other user stories.
- **User Story 2 (P2)**: Depends on User Story 1 producing ingested `Source`, `Segment`, and `TranscriptBatch` data in the shared evidence store.
- **User Story 3 (P3)**: Depends on User Story 1 producing ingested evidence; does not depend on User Story 2.
- **User Story 4 (P4)**: Depends on `agents_service` Live Sessions (`modality="voice"`) + `voip_service` media-plane bridge; does not require feed publishing.

### Within Each User Story

- Tests should be written before or alongside implementation and must fail before the feature is considered complete.
- Discovery, models, and library adapters come before orchestration.
- Runtime wiring comes after the lower-level library behavior is proven.
- Integration tests close each story before moving to the next phase.

## Parallel Opportunities

- In **Phase 1**, deletion tasks `T001` to `T007` can be split across contributors because they affect separate directories.
- In **Phase 2**, `T015`, `T016`, `T017`, and `T023` are parallel once the package skeleton exists.
- In **US1**, tests `T024` to `T028` and low-level adapter tasks `T029` to `T031` can run in parallel.
- In **US2**, tests `T037` to `T040` and implementation tasks `T041` and `T042` can run in parallel.
- In **US3**, tests `T047` to `T052` and implementation tasks `T053` to `T055` can run in parallel.

## Parallel Example: User Story 1

```bash
Task: "T024 [US1] Add unit tests for YouTube discovery delta logic in services/memory_service/tests/unit/test_discovery.py"
Task: "T025 [US1] Add unit tests for SQLAlchemy-backed ingest index behavior in services/memory_service/tests/unit/test_index.py"
Task: "T028 [US1] Add contract tests for EverMemOS memorize, conversation-meta, and delete-by-group-id calls in packages/bt_common/tests/test_evermemos_client_contract.py"

Task: "T029 [US1] Implement yt-dlp flat extraction and RSS fallback discovery in services/memory_service/src/pipeline/discovery.py"
Task: "T030 [US1] Adapt transcript and metadata loading for the trimmed MVP in services/memory_service/src/adapters/youtube_transcript.py and services/memory_service/src/adapters/rss_feed.py"
Task: "T031 [US1] Preserve stable YouTube identifier builders in services/memory_service/src/domain/ids.py"
```

## Parallel Example: User Story 2

```bash
Task: "T037 [US2] Add unit tests for transcript batching rules in services/discord_service/tests/unit/test_batcher.py"
Task: "T038 [US2] Add unit tests for Discord post idempotency state transitions in services/discord_service/tests/unit/test_feed_publisher.py"
Task: "T040 [US2] Add contract tests for Discord message shapes in services/discord_service/tests/contract/test_discord_message_models.py"

Task: "T041 [US2] Implement transcript batch grouping in services/discord_service/src/feed/batcher.py"
Task: "T042 [US2] Implement typed Discord boundary models in services/discord_service/src/bot/message_models.py"
```

## Parallel Example: User Story 3

```bash
Task: "T047 [US3] Add unit tests for BM25-backed evidence selection in services/agents_service/tests/unit/test_memory_search.py"
Task: "T048 [US3] Add unit tests for inline link and quote validation in services/agents_service/tests/unit/test_citation_validation.py"
Task: "T052 [US3] Add contract and integration tests for public memory pages in services/memory_service/tests/contract/test_memory_id_contract.py and services/memory_service/tests/integration/test_memories_api.py"

Task: "T053 [US3] Adapt EverMemOS retrieval and BM25 reranking to the new evidence shape in services/agents_service/src/agents_service/agent/tools/memory_search.py"
Task: "T054 [US3] Replace citation-index emission with inline memory_url emission in services/agents_service/src/agents_service/agent/tools/emit_citations.py"
Task: "T059 [US3] Implement the memory page resolver and HTTP handler in services/memory_service/src/api/memories_service.py and services/memory_service/src/api/app.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and remove out-of-scope code.
2. Complete Phase 2 and establish the shared database and runtime foundation.
3. Complete Phase 3 and validate ingest, dedup, transcript-batch derivation, manual re-ingest, and per-source concurrency end to end.
4. Stop and verify the P1 ingest workflow before starting feed or DM chat.

### Incremental Delivery

1. Deliver **US1** to prove agent-scoped ingest and evidence persistence.
2. Deliver **US2** to expose ingested videos in Discord threads with idempotent retries.
3. Deliver **US3** to add grounded DM chat and public memory-page resolution on top of the already-proven evidence store.
4. Finish with Phase 6 operational cleanup, deployment wiring, and documentation.

### Suggested MVP Scope

- **Strict MVP cut**: Phase 1, Phase 2, and Phase 3 only.
- **Next increment**: Phase 4 for feed publication.
- **Final MVP-complete increment**: Phase 5 for grounded DM chat plus public memory-page resolution.

## Format Validation

- All tasks use the required checklist format: `- [ ] T### [P?] [US?] Description with file path`
- Setup and Foundational tasks intentionally omit story labels.
- User story tasks all include `[US1]`, `[US2]`, or `[US3]`.
- Every task description includes at least one concrete file path.
