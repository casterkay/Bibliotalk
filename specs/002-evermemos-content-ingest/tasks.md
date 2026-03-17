---

description: "Tasks for EverMemOS Content Ingestion Package"
---

# Tasks: EverMemOS Content Ingestion Package

**Input**: Design documents from `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/`
**Prerequisites**: `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/plan.md`, `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`

**Docs available**: `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Unit tests live in `services/memory_service/tests/`. EverMemOS response-shape contract tests live in `packages/bt_common/tests/contract/`.

## Format: `- [ ] T### [P?] [US?] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[US?]**: Which user story this task belongs to (`[US1]`, `[US2]`, `[US3]`)
- Setup/Foundational/Polish tasks MUST NOT include `[US?]`
- Every task line includes at least one concrete file path

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the standalone package skeleton and align repo packaging config.

- [X] T001 Create package directories `services/memory_service/src/` and `services/memory_service/src/adapters/`
- [X] T002 [P] Create module skeleton files `services/memory_service/src/__init__.py` and `services/memory_service/src/__main__.py`
- [X] T003 Update packaging config to include `memory_service` in `services/memory_service/pyproject.toml`
- [X] T004 Add runtime dependencies for CLI + manifest parsing in `services/memory_service/pyproject.toml` (add `typer`, `rich`, `PyYAML`)
- [X] T005 Add optional runtime dependencies for non-interactive adapters in `services/memory_service/pyproject.toml` (add `youtube-transcript-api`)
- [X] T006 [P] Add a minimal package README for operators in `services/memory_service/README.md`
- [X] T007 [P] Add `.gitignore` entries for local ingestion index/report outputs in `.gitignore`

**Checkpoint**: `uv run --package memory_service -m memory_service --help` runs (even if commands are stubbed).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core primitives required by all user stories (IDs, chunking, EverMemOS IO, reporting, idempotency).

**⚠️ CRITICAL**: No user story work should start until this phase is complete.

- [X] T008 Create typed exceptions for ingest failures in `services/memory_service/src/domain/errors.py`
- [X] T009 Implement config loading from env + CLI overrides in `services/memory_service/src/runtime/config.py`
- [X] T010 Define core Pydantic models (Source, Segment, reports) aligned to `contracts/report-format.md` in `services/memory_service/src/domain/models.py`
- [X] T011 Implement stable ID builders (`group_id`, `message_id`) per `contracts/evermemos-api.md` in `services/memory_service/src/domain/ids.py`
- [X] T012 Implement deterministic chunking for plain text + time-coded transcripts in `services/memory_service/src/pipeline/chunking.py`
- [X] T013 Implement EverMemOS client wrapper (memorize + conversation-meta + retries + redaction) in `packages/bt_common/src/evermemos_client.py`
- [X] T014 Implement local SQLite ingestion index schema + CRUD in `services/memory_service/src/pipeline/index.py`
- [X] T015 Implement report writer (JSON v1) + redaction rules in `services/memory_service/src/runtime/reporting.py`
- [X] T016 Implement ingestion pipeline entrypoint (`ingest_source`, shared helpers) in `services/memory_service/src/pipeline/ingest.py`

**Checkpoint**: Ingestion pipeline can ingest a pre-segmented in-memory Source+Segments through the EverMemOS client wrapper and produce a JSON report object (no CLI yet).

---

## Phase 3: User Story 1 - Ingest A Single Source For A Spirit (Priority: P1) 🎯 MVP

**Goal**: Ingest one operator-provided source (text or local file) into EverMemOS as grouped, ordered segments with a clear per-source report.

**Independent Test**:
- Run `uv run --package memory_service -m memory_service ingest text ... --report-path ...` and confirm:
  - segments are created deterministically
  - EverMemOS receives one conversation-meta call + N memorize calls for the source
  - report JSON contains `group_id`, per-segment `message_id`s, and success counts

### Implementation (US1)

- [X] T017 [P] [US1] Define adapter interface and adapter result types in `services/memory_service/src/adapters/base.py`
- [X] T018 [P] [US1] Implement local text/file adapter (read, normalize, yield Source content) in `services/memory_service/src/adapters/local_text.py`
- [X] T019 [US1] Implement CLI root and `ingest` command group in `services/memory_service/src/__main__.py`
- [X] T020 [US1] Implement `ingest text` command (args per `contracts/cli.md`) in `services/memory_service/src/__main__.py`
- [X] T021 [US1] Implement `ingest file` command (args per `contracts/cli.md`) in `services/memory_service/src/__main__.py`
- [X] T022 [US1] Wire CLI → adapter → chunking → ingestion pipeline in `services/memory_service/src/__main__.py`
- [X] T023 [US1] Implement report file emission + exit codes for single-source runs in `services/memory_service/src/__main__.py`

**Checkpoint**: US1 delivers a complete end-to-end ingest for local inputs with actionable errors and no secret leakage.

---

## Phase 4: User Story 2 - Safe Re-Run Without Duplicates (Priority: P2)

**Goal**: Re-running ingestion for the same source is safe (no duplicates) and reports `unchanged` vs `updated` outcomes.

**Independent Test**:
- Ingest a source twice with identical content and confirm the second run reports skipped/unchanged segments without re-sending unchanged segments.
- Modify the source content and confirm changed segments are re-sent and the report indicates updates.

### Implementation (US2)

- [X] T024 [US2] Extend ingestion index to record per-segment sha/status and detect unchanged segments in `services/memory_service/src/pipeline/index.py`
- [X] T025 [US2] Update ingestion pipeline to skip unchanged segments and increment `segments_skipped_unchanged` in `services/memory_service/src/pipeline/ingest.py`
- [X] T026 [US2] Implement “changed content” behavior for same `message_id` (re-memorize + update index) in `services/memory_service/src/pipeline/ingest.py`
- [X] T027 [US2] Add CLI options `--index-path` and default index path behavior in `services/memory_service/src/runtime/config.py`
- [X] T028 [US2] Ensure report output includes skip/update counts per `contracts/report-format.md` in `services/memory_service/src/runtime/reporting.py`

**Checkpoint**: US2 reruns produce 0 duplicates and clear reporting for unchanged vs updated sources.

---

## Phase 5: User Story 3 - Batch Ingest From A Curated Roster (Priority: P3)

**Goal**: Batch ingest multiple curated sources with per-source isolation, consolidated reporting, and explicit failure when interactive crawling would be required.

**Independent Test**:
- Run `ingest manifest` with 3 sources where 1 fails; confirm the other 2 succeed and the final report includes all 3 outcomes.
- Include an unsupported source type; confirm it fails with an actionable message explaining “non-interactive only”.

### Implementation (US3)

- [X] T029 [P] [US3] Define manifest schema models + validation per `contracts/ingest-manifest.md` in `services/memory_service/src/pipeline/manifest.py`
- [X] T030 [US3] Implement `ingest manifest` command in `services/memory_service/src/__main__.py`
- [X] T031 [US3] Implement adapter selection + allowlist for manifest sources in `services/memory_service/src/pipeline/ingest.py`
- [X] T032 [P] [US3] Implement Project Gutenberg adapter (plain text download only) in `services/memory_service/src/adapters/gutenberg.py`
- [X] T033 [P] [US3] Implement YouTube transcript adapter (no browser automation) in `services/memory_service/src/adapters/youtube_transcript.py`
- [X] T034 [US3] Implement batch runner (continue-on-error) + consolidated report assembly in `services/memory_service/src/pipeline/ingest.py`
- [X] T035 [US3] Ensure unsupported/interactive-required sources fail with actionable errors in `services/memory_service/src/pipeline/manifest.py`
- [X] T036 [US3] Ensure CLI exits with code `1` when any source fails and still writes report in `services/memory_service/src/__main__.py`

**Checkpoint**: US3 supports manifest-driven batch ingest with clear per-source outcomes and no interactive crawling.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improve operability, consistency with contracts, and safety guarantees.

- [X] T037 [P] Add example manifest file to docs in `specs/002-evermemos-content-ingest/contracts/ingest-manifest.md`
- [X] T038 Add structured logging fields (`run_id`, `group_id`, `message_id`) in `services/memory_service/src/__main__.py`
- [X] T039 Harden redaction: scrub secrets from exception messages and reports in `services/memory_service/src/runtime/reporting.py`
- [X] T040 Add consistent error codes for common failures (auth, network, invalid input, unsupported source) in `services/memory_service/src/domain/errors.py`
- [X] T041 Ensure quickstart commands match implemented CLI flags in `specs/002-evermemos-content-ingest/quickstart.md`

---

## Dependencies & Execution Order

### Dependency Graph (High Level)

```text
Phase 1 (Setup)
  └─ Phase 2 (Foundational)
       └─ US1 (single source)
            ├─ US2 (safe rerun)
            └─ US3 (batch/manifest)
                 └─ Phase 6 (polish)
```

### Parallel Opportunities

- Phase 1: module skeleton + README + `.gitignore` updates can be done in parallel.
- Phase 2: models/IDs/chunking/client/index/reporting can be split across files and done in parallel once exceptions/config set conventions.
- US1: adapter interface + local adapter can be done in parallel; CLI wiring follows.
- US3: Gutenberg adapter + YouTube adapter can be done in parallel after adapter selection is implemented.

---

## Parallel Examples (Per User Story)

### US1

```bash
Task: "Define adapter interface in services/memory_service/src/adapters/base.py"
Task: "Implement local adapter in services/memory_service/src/adapters/local_text.py"
```

### US2

```bash
Task: "Extend SQLite index in services/memory_service/src/pipeline/index.py"
Task: "Update pipeline skip logic in services/memory_service/src/pipeline/ingest.py"
```

### US3

```bash
Task: "Implement Gutenberg adapter in services/memory_service/src/adapters/gutenberg.py"
Task: "Implement YouTube adapter in services/memory_service/src/adapters/youtube_transcript.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2
2. Complete Phase 3 (US1)
3. Validate US1 independently using the “Independent Test” steps in Phase 3

### Incremental Delivery

1. US1 → validate → usable ingest for local content
2. US2 → validate → safe re-runs for operators
3. US3 → validate → roster/manifest batch ingest
4. Polish
