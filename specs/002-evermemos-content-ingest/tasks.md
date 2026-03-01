---

description: "Tasks for EverMemOS Content Ingestion Package"
---

# Tasks: EverMemOS Content Ingestion Package

**Input**: Design documents from `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/`  
**Prerequisites**: `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/plan.md`, `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`

**Docs available**: `research.md`, `data-model.md`, `contracts/`, `quickstart.md`

**Tests**: Not included (the feature spec did not request a TDD workflow).

## Format: `- [ ] T### [P?] [US?] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[US?]**: Which user story this task belongs to (`[US1]`, `[US2]`, `[US3]`)
- Setup/Foundational/Polish tasks MUST NOT include `[US?]`
- Every task line includes at least one concrete file path

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the standalone package skeleton and align repo packaging config.

- [ ] T001 Create package directories `evermemos_ingest/` and `evermemos_ingest/adapters/`
- [ ] T002 [P] Create module skeleton files `evermemos_ingest/__init__.py` and `evermemos_ingest/__main__.py`
- [ ] T003 Update packaging config to include `evermemos_ingest` in `pyproject.toml`
- [ ] T004 Add runtime dependencies for CLI + manifest parsing in `pyproject.toml` (add `typer`, `rich`, `PyYAML`)
- [ ] T005 Add optional runtime dependencies for non-interactive adapters in `pyproject.toml` (add `youtube-transcript-api`)
- [ ] T006 [P] Add a minimal package README for operators in `evermemos_ingest/README.md`
- [ ] T007 [P] Add `.gitignore` entries for local ingestion index/report outputs in `.gitignore`

**Checkpoint**: `python -m evermemos_ingest --help` runs (even if commands are stubbed).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core primitives required by all user stories (IDs, chunking, EverMemOS IO, reporting, idempotency).

**⚠️ CRITICAL**: No user story work should start until this phase is complete.

- [ ] T008 Create typed exceptions for ingest failures in `evermemos_ingest/errors.py`
- [ ] T009 Implement config loading from env + CLI overrides in `evermemos_ingest/config.py`
- [ ] T010 Define core Pydantic models (Source, Segment, reports) aligned to `contracts/report-format.md` in `evermemos_ingest/models.py`
- [ ] T011 Implement stable ID builders (`group_id`, `message_id`) per `contracts/evermemos-api.md` in `evermemos_ingest/ids.py`
- [ ] T012 Implement deterministic chunking for plain text + time-coded transcripts in `evermemos_ingest/chunking.py`
- [ ] T013 Implement EverMemOS client wrapper (memorize + conversation-meta + retries + redaction) in `evermemos_ingest/evermemos_client.py`
- [ ] T014 Implement local SQLite ingestion index schema + CRUD in `evermemos_ingest/index.py`
- [ ] T015 Implement report writer (JSON v1) + redaction rules in `evermemos_ingest/reporting.py`
- [ ] T016 Implement ingestion pipeline entrypoint (`ingest_source`, shared helpers) in `evermemos_ingest/ingest.py`

**Checkpoint**: Ingestion pipeline can ingest a pre-segmented in-memory Source+Segments through the EverMemOS client wrapper and produce a JSON report object (no CLI yet).

---

## Phase 3: User Story 1 - Ingest A Single Source For A Clone (Priority: P1) 🎯 MVP

**Goal**: Ingest one operator-provided source (text or local file) into EverMemOS as grouped, ordered segments with a clear per-source report.

**Independent Test**:
- Run `python -m evermemos_ingest ingest text ... --report-path ...` and confirm:
  - segments are created deterministically
  - EverMemOS receives one conversation-meta call + N memorize calls for the source
  - report JSON contains `group_id`, per-segment `message_id`s, and success counts

### Implementation (US1)

- [ ] T017 [P] [US1] Define adapter interface and adapter result types in `evermemos_ingest/adapters/base.py`
- [ ] T018 [P] [US1] Implement local text/file adapter (read, normalize, yield Source content) in `evermemos_ingest/adapters/local_text.py`
- [ ] T019 [US1] Implement CLI root and `ingest` command group in `evermemos_ingest/cli.py`
- [ ] T020 [US1] Implement `ingest text` command (args per `contracts/cli.md`) in `evermemos_ingest/cli.py`
- [ ] T021 [US1] Implement `ingest file` command (args per `contracts/cli.md`) in `evermemos_ingest/cli.py`
- [ ] T022 [US1] Wire CLI → adapter → chunking → ingestion pipeline in `evermemos_ingest/cli.py`
- [ ] T023 [US1] Implement report file emission + exit codes for single-source runs in `evermemos_ingest/cli.py`

**Checkpoint**: US1 delivers a complete end-to-end ingest for local inputs with actionable errors and no secret leakage.

---

## Phase 4: User Story 2 - Safe Re-Run Without Duplicates (Priority: P2)

**Goal**: Re-running ingestion for the same source is safe (no duplicates) and reports `unchanged` vs `updated` outcomes.

**Independent Test**:
- Ingest a source twice with identical content and confirm the second run reports skipped/unchanged segments without re-sending unchanged segments.
- Modify the source content and confirm changed segments are re-sent and the report indicates updates.

### Implementation (US2)

- [ ] T024 [US2] Extend ingestion index to record per-segment sha/status and detect unchanged segments in `evermemos_ingest/index.py`
- [ ] T025 [US2] Update ingestion pipeline to skip unchanged segments and increment `segments_skipped_unchanged` in `evermemos_ingest/ingest.py`
- [ ] T026 [US2] Implement “changed content” behavior for same `message_id` (re-memorize + update index) in `evermemos_ingest/ingest.py`
- [ ] T027 [US2] Add CLI options `--index-path` and default index path behavior in `evermemos_ingest/config.py`
- [ ] T028 [US2] Ensure report output includes skip/update counts per `contracts/report-format.md` in `evermemos_ingest/reporting.py`

**Checkpoint**: US2 reruns produce 0 duplicates and clear reporting for unchanged vs updated sources.

---

## Phase 5: User Story 3 - Batch Ingest From A Curated Roster (Priority: P3)

**Goal**: Batch ingest multiple curated sources with per-source isolation, consolidated reporting, and explicit failure when interactive crawling would be required.

**Independent Test**:
- Run `ingest manifest` with 3 sources where 1 fails; confirm the other 2 succeed and the final report includes all 3 outcomes.
- Include an unsupported source type; confirm it fails with an actionable message explaining “non-interactive only”.

### Implementation (US3)

- [ ] T029 [P] [US3] Define manifest schema models + validation per `contracts/ingest-manifest.md` in `evermemos_ingest/manifest.py`
- [ ] T030 [US3] Implement `ingest manifest` command in `evermemos_ingest/cli.py`
- [ ] T031 [US3] Implement adapter selection + allowlist for manifest sources in `evermemos_ingest/ingest.py`
- [ ] T032 [P] [US3] Implement Project Gutenberg adapter (plain text download only) in `evermemos_ingest/adapters/gutenberg.py`
- [ ] T033 [P] [US3] Implement YouTube transcript adapter (no browser automation) in `evermemos_ingest/adapters/youtube_transcript.py`
- [ ] T034 [US3] Implement batch runner (continue-on-error) + consolidated report assembly in `evermemos_ingest/ingest.py`
- [ ] T035 [US3] Ensure unsupported/interactive-required sources fail with actionable errors in `evermemos_ingest/manifest.py`
- [ ] T036 [US3] Ensure CLI exits with code `1` when any source fails and still writes report in `evermemos_ingest/cli.py`

**Checkpoint**: US3 supports manifest-driven batch ingest with clear per-source outcomes and no interactive crawling.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improve operability, consistency with contracts, and safety guarantees.

- [ ] T037 [P] Add example manifest file to docs in `specs/002-evermemos-content-ingest/contracts/ingest-manifest.md`
- [ ] T038 Add structured logging fields (`run_id`, `group_id`, `message_id`) in `evermemos_ingest/cli.py`
- [ ] T039 Harden redaction: scrub secrets from exception messages and reports in `evermemos_ingest/reporting.py`
- [ ] T040 Add consistent error codes for common failures (auth, network, invalid input, unsupported source) in `evermemos_ingest/errors.py`
- [ ] T041 Ensure quickstart commands match implemented CLI flags in `specs/002-evermemos-content-ingest/quickstart.md`

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
Task: "Define adapter interface in evermemos_ingest/adapters/base.py"
Task: "Implement local adapter in evermemos_ingest/adapters/local_text.py"
```

### US2

```bash
Task: "Extend SQLite index in evermemos_ingest/index.py"
Task: "Update pipeline skip logic in evermemos_ingest/ingest.py"
```

### US3

```bash
Task: "Implement Gutenberg adapter in evermemos_ingest/adapters/gutenberg.py"
Task: "Implement YouTube adapter in evermemos_ingest/adapters/youtube_transcript.py"
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
