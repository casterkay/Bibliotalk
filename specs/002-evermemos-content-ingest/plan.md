# Implementation Plan: EverMemOS Content Ingestion Package

**Branch**: `002-evermemos-content-ingest` | **Date**: 2026-03-01 | **Spec**: `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`
**Input**: Feature specification at `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`

## Summary

Create a standalone Python library + CLI that ingests curated, operator-provided content into EverMemOS as citation-friendly segments grouped by source. The package supports non-interactive HTTP fetching + static extraction for blog posts and documents; it focuses on deterministic chunking, stable IDs, safe re-runs (no duplicates), and clear per-source reporting.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: `bt_common` (EverMemOS client wrapper), `httpx`, `pydantic`, `typer`, `rich`, `fastapi`
**Storage**: EverMemOS for memory storage; local SQLite ingestion index (default) for idempotency and reporting continuity
**Testing**: `pytest`, `pytest-asyncio`
**Target Platform**: CLI for macOS/Linux; library usable from `memory_service` or other Python services
**Project Type**: Python package (library + CLI)
**Performance Goals**: Ingest 50 typical sources in a single run with actionable reporting; segmenting throughput supports multi-hour transcripts without operator intervention
**Constraints**: No interactive browsing; deterministic segmentation; stable message/group IDs; secrets never logged; safe retries on transient EverMemOS failures
**Scale/Scope**: Batch ingestion for curated rosters (tens to low-hundreds of sources); per-source failures must not block the batch

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                        | Gate                                                                                 | Status |
| -------------------------------- | ------------------------------------------------------------------------------------ | ------ |
| I. Design-First Architecture     | Spec + plan exist before coding                                                      | PASS   |
| II. Test-Driven Quality          | Tests planned for chunking, ID stability, dedup, and EverMemOS client error handling | PASS   |
| III. Contract-Driven Integration | Explicit contracts for EverMemOS calls + CLI/manifest schemas                        | PASS   |
| IV. Incremental Delivery         | P1 single-source ingest → P2 idempotent reruns → P3 roster/batch ingest              | PASS   |
| V. Observable Systems            | Structured logs + per-source report artifacts without leaking secrets                | PASS   |
| VI. Principled Simplicity        | One package + small adapters; defer browser automation and unbounded crawling        | PASS   |

**Post-Phase 1 Re-check**: PASS (design artifacts produced and contracts defined; no principle violations introduced).

## Project Structure

### Documentation (this feature)

```text
/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── evermemos-api.md
│   ├── ingest-manifest.md
│   ├── cli.md
│   └── report-format.md
└── tasks.md
```

### Source Code (repository root)

```text
/Users/tcai/Projects/Bibliotalk/
services/memory_service/src/
├── __init__.py
├── __main__.py              # `uv run --package memory_service -m memory_service ...`
├── server.py                # FastAPI server (optional operator API)
├── adapters/
│   ├── base.py              # adapter interface for input sources
│   ├── local_text.py        # operator-provided text/file
│   ├── gutenberg.py         # Project Gutenberg text download (non-interactive)
│   └── youtube_transcript.py # YouTube transcript fetch (non-interactive)
├── domain/
│   ├── errors.py            # typed errors
│   ├── ids.py               # stable group_id / message_id builders
│   └── models.py            # typed entities + report schema
├── pipeline/
│   ├── chunking.py          # deterministic chunking strategies
│   ├── manifest.py          # manifest schema + resolution
│   ├── index.py             # local SQLite ingestion index (idempotency)
│   └── ingest.py            # ingest pipeline
└── runtime/
    ├── config.py            # env + CLI override loading
    └── reporting.py         # report emission + redaction

services/memory_service/tests/unit/
packages/bt_common/tests/contract/     # EverMemOS response-shape contract tests
```

**Structure Decision**: Single standalone package (`memory_service`) with a small adapter layer for supported non-interactive inputs. It is intentionally independent of Matrix/Supabase so it can be reused by `memory_service` or external operators.

## Phased Delivery (maps to spec priorities)

- **P1 (User Story 1)**: Ingest one operator-provided source into EverMemOS with deterministic segmentation, stable IDs, and a per-source report.
- **P2 (User Story 2)**: Local ingestion index enables safe re-runs (no duplicates) and clear “unchanged vs updated” reporting.
- **P3 (User Story 3)**: Manifest-driven batch ingestion; roster parsing is optional and must fail clearly when it requires interactive crawling.

## Complexity Tracking

No constitution violations required for this plan.
