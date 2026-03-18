# Implementation Plan: YouTube → EverMemOS → Discord Agent Bots

**Branch**: `003-discord-bot` | **Date**: 2026-03-07 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification at `specs/003-discord-bot/spec.md`

## Summary

Build the complete YouTube → EverMemOS → Discord agent-bot pipeline from the skeleton left after ruthlessly deleting all out-of-scope code (Matrix, voice, non-YouTube adapters, AWS Nova provider, SQLAdmin). The successor system has three runtime packages sharing one SQLite database through a shared infra layer in `bt_common`:

1. **Collector** (`memory_service`, trimmed but standalone): asyncio polling loop per subscription source, yt-dlp discovery, transcript fetch, chunking, SQLAlchemy-persisted evidence, and EverMemOS memorization.
2. **Agent runtime** (`agents_service`, trimmed): Gemini/ADK `LlmAgent` per agent, EverMemOS search, BM25 rerank, inline `memory_url` citation, and grounding validation.
3. **Discord runtime** (`discord_service`, new): one `discord.py` `Client` per deployment, feed channel + thread posting, DM slash commands (`/talk`, `/talks`), private talk-thread creation under `#bibliotalk`, and thread-message routing to character agents.
4. **Memories API** (`memory_service`, FastAPI): serves public memory pages (`/memories/{id}`) and the JSON API (`/v1/*`) for retrieval, search, and manual ingest triggers.

Code deletion is a hard prerequisite before any new code is written.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: `discord.py>=2.4`, `google-adk>=1.25`, `google-genai>=1.0`, `youtube-transcript-api>=0.6`, `yt-dlp`, `SQLAlchemy>=2.0`, `aiosqlite>=0.20`, `alembic`, `bt_common` (EverMemOS client + shared evidence-store infra), `pydantic>=2.8`, `tenacity`
**Storage**: SQLite via SQLAlchemy 2.x async ORM (`aiosqlite` driver) + Alembic migrations; single database shared across all runtime packages through `bt_common` infra modules
**Testing**: `pytest`, `pytest-asyncio`; unit tests for chunking/ID stability/dedup/citation validation; contract tests for EverMemOS calls and page resolution; integration tests for ingest + feed publish + talk-thread response journeys
**Target Platform**: macOS/Linux single host (Docker Compose or systemd), with memory pages deployable as a separate worker/runtime
**Project Type**: Four Python service packages + one shared library (`bt_common`)
**Performance Goals**: Poll cycle completes within the configured interval (15–60 min); per-video ingest < 30 s for a typical transcript; Discord feed posting is sequential and rate-limit-safe
**Constraints**: Single-bot runtime; no Matrix; no voice; no non-YouTube sources; secrets in env only; dedup by `video_id`; idempotent feed posting; bounded per-source ingest concurrency
**Scale/Scope**: 2–10 figures, each with 1–5 subscription sources; single-host MVP

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle                        | Gate                                                                                                                                                                                                                  | Status |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ |
| I. Design-First Architecture     | Spec + plan exist before coding; data models and contracts defined as Phase 1 artifacts                                                                                                                               | PASS   |
| II. Test-Driven Quality          | Unit tests for chunking, ID stability, dedup, BM25, citation validation, per-source concurrency; contract tests for EverMemOS, Discord message shapes, and memory pages; integration tests for all three user stories | PASS   |
| III. Contract-Driven Integration | Evidence/citation contract, Discord message shapes, EverMemOS API usage, and memory-page request/response shapes explicitly defined in `contracts/` before integration work begins                                    | PASS   |
| IV. Incremental Delivery         | Phase A (deletion) → Phase B (P1 ingest) → Phase C (P2 feed) → Phase D (P3 talk threads + pages); each phase independently deployable and testable                                                                   | PASS   |
| V. Observable Systems            | Structured logs with correlation IDs at all entry points (poll loop, ingest run, Discord handler, page handler); EMOS + yt-dlp call latency logged; citation validation decisions logged                              | PASS   |
| VI. Principled Simplicity        | SQLAlchemy justified by operator directive + migration tooling requirement; four packages justified by distinct runtimes and deployment boundaries; shared DB infra isolated in `bt_common`                           | PASS   |

**Post-Phase 1 Re-check**: PASS — data model and contracts introduce no new complexity violations.

## Code Deletion Plan *(prerequisite — complete before writing any new code)*

### `services/agents_service/` — delete

| Path                              | Reason                                                                                           |
| --------------------------------- | ------------------------------------------------------------------------------------------------ |
| `src/matrix/`                     | Matrix transport — out of scope                                                                  |
| `src/voice/`                      | Voice pipeline — out of scope                                                                    |
| `src/admin/`                      | SQLAdmin UI — out of scope                                                                       |
| `src/agent/providers/aws_nova.py` | AWS Nova Sonic — Gemini only for MVP                                                             |
| `src/database/`                   | Old SQLAlchemy schema tied to Matrix era; replaced by shared evidence-store infra in `bt_common` |
| `src/server.py`                   | Litestar HTTP server — not needed for the agent library                                          |

### `services/agents_service/` — keep and adapt

| Path                                | Action                                                                                                          |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `src/agent/providers/gemini.py`     | Keep — Gemini provider                                                                                          |
| `src/agent/agent_factory.py`        | Adapt — update system prompt; wire new `Evidence` model                                                         |
| `src/agent/orchestrator.py`         | Adapt — replace Matrix DM context with Discord DM context                                                       |
| `src/agent/tools/memory_search.py`  | Adapt — agent-scoped `user_id`; import updated `Evidence`                                                       |
| `src/agent/tools/emit_citations.py` | Adapt — drop citation indices; emit inline `[text](memory_url)` links                                           |
| `src/models/citation.py`            | Rebuild — new `Evidence` shape with `memory_url`, `memory_user_id`, `memory_timestamp`; remove `Citation.index` |
| `src/models/segment.py`             | Keep unchanged — `Segment` + `bm25_rerank` reused directly                                                      |

### `services/memory_service/` — delete

| Path                         | Reason                                                                            |
| ---------------------------- | --------------------------------------------------------------------------------- |
| `src/adapters/blog_crawl.py` | Non-YouTube source                                                                |
| `src/adapters/document.py`   | Non-YouTube source                                                                |
| `src/adapters/gutenberg.py`  | Non-YouTube source                                                                |
| `src/adapters/http_fetch.py` | Non-YouTube source                                                                |
| `src/adapters/local_text.py` | Non-YouTube source                                                                |
| `src/adapters/url_tools.py`  | URL utilities for deleted adapters                                                |
| `src/adapters/web_page.py`   | Non-YouTube source                                                                |
| `src/server.py`              | FastAPI HTTP server — collector runs as a standalone process, not an HTTP service |
| `src/pipeline/manifest.py`   | Manifest-driven batch ingest — not MVP                                            |

### `services/memory_service/` — keep and adapt

| Path                                 | Action                                                                                 |
| ------------------------------------ | -------------------------------------------------------------------------------------- |
| `src/adapters/base.py`               | Keep — adapter interface                                                               |
| `src/adapters/youtube_transcript.py` | Adapt — trim non-YouTube metadata fields; keep transcript fetch + yt-dlp metadata      |
| `src/adapters/rss_feed.py`           | Keep — optional RSS fallback discovery (FR-015)                                        |
| `src/domain/`                        | Adapt — trim `models.py` to YouTube-relevant fields only                               |
| `src/pipeline/chunking.py`           | Keep unchanged — sentence-aware 1,200-char chunking                                    |
| `src/pipeline/discovery.py`          | Add — standalone subscription discovery with yt-dlp flat extraction and RSS fallback   |
| `src/pipeline/ingest.py`             | Adapt — replace raw SQLite access with shared SQLAlchemy session calls via `bt_common` |
| `src/pipeline/index.py`              | Adapt — replace raw `sqlite3` with SQLAlchemy ORM                                      |
| `src/runtime/config.py`              | Adapt — standalone collector config including per-source concurrency controls          |
| `src/runtime/poller.py`              | Add — standalone polling loop and retry/backoff handling                               |
| `src/__main__.py`                    | Adapt — run the collector as an independent process, separate from `discord_service`   |

## Project Structure

### Documentation (this feature)

```text
specs/003-discord-bot/
├── spec.md
├── plan.md              ← this file
├── research.md          ← Phase 0
├── data-model.md        ← Phase 1
├── quickstart.md        ← Phase 1
├── contracts/
│   ├── evidence.md            ← shared Evidence/Citation Pydantic contract
│   ├── discord-messages.md    ← Discord inbound/outbound message shapes
│   ├── collector-cli.md       ← collector entry point contract
│   ├── evermemos-api.md       ← EverMemOS memorize/search/delete contract
│   └── memories.md            ← public memory page request/response contract
└── tasks.md             ← Phase 2 (speckit.tasks — not created here)
```

### Source Code (repository root)

```text
packages/bt_common/src/
├── config.py
├── evidence_store/
│   ├── engine.py              # shared async engine + session factory
│   └── models.py              # shared ORM schema for evidence cache and post state
├── evermemos_client.py        # search, memorize, delete_by_group_id
├── exceptions.py
└── logging.py

services/memory_service/src/   # standalone collector / ingestion runtime
├── adapters/
│   ├── base.py
│   ├── youtube_transcript.py      # transcript fetch + yt-dlp metadata
│   └── rss_feed.py                # optional RSS fallback
├── domain/
│   ├── errors.py
│   ├── ids.py                     # stable group_id / message_id builders
│   └── models.py                  # trimmed to YouTube fields
├── runtime/
│   ├── config.py                  # poll interval + per-source concurrency controls
│   └── poller.py                  # standalone poll loop
└── pipeline/
    ├── chunking.py                # unchanged — 1,200-char sentence-aware chunks
    ├── discovery.py               # yt-dlp flat extraction + RSS fallback
    ├── ingest.py                  # adapted — SQLAlchemy persistence
    └── index.py                   # adapted — SQLAlchemy ORM

services/agents_service/src/      # trimmed: Gemini/ADK agent library
├── agent/
│   ├── agent_factory.py
│   ├── orchestrator.py
│   ├── providers/
│   │   └── gemini.py
│   └── tools/
│       ├── memory_search.py
│       └── emit_citations.py
└── models/
    ├── citation.py                # rebuilt — new Evidence shape, inline memory_url
    └── segment.py                 # unchanged — Segment + bm25_rerank

services/discord_service/
├── pyproject.toml
├── src/
│   ├── __init__.py
│   ├── __main__.py               # entry: python -m discord_service
│   ├── config.py                 # Discord runtime config (db path, token, command guild)
│   ├── runtime.py                # startup: load directory → start bot → publish feeds
│   ├── feed/
│   │   ├── batcher.py            # transcript_batch grouping rules
│   │   └── publisher.py          # Discord feed channel + thread posting
│   └── bot/
│       ├── client.py             # discord.Client subclass
│       └── concierge.py          # DM concierge for non-command messages
└── tests/
    ├── unit/
    └── integration/

services/memory_service/src/api/
├── pyproject.toml
├── src/
│   ├── __init__.py
│   ├── __main__.py               # local dev entrypoint
│   ├── app.py                    # HTTP/serverless handler
│   └── resolver.py               # resolve one memory page + timestamped video URL
└── tests/
    ├── contract/
    └── integration/
```

**Structure Decision**: `memory_service` owns the standalone collector runtime and write-path into the shared evidence store, plus the unified Memories API for public memory pages. `discord_service` owns only the Discord bot runtime, feed publication, DM slash commands (`/talk`, `/talks`), and private talk-thread routing. Shared SQLAlchemy engine/models live in `bt_store` so no service imports another service's runtime internals.

## Phased Delivery

| Phase          | Deliverable                                                                                                                                                                            | User Story   |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| A — Deletion   | Remove all out-of-scope code; existing tests still pass on retained modules                                                                                                            | Prerequisite |
| B — P1 Ingest  | standalone `memory_service`; shared ORM schema + Alembic in `bt_common`; yt-dlp discovery; transcript ingest pipeline; EverMemOS memorization; dedup; per-source concurrency limits | US-1         |
| C — P2 Feed    | Transcript batch grouping; Discord feed publisher; idempotent thread posting; `discord_posts` tracking                                                                                 | US-2         |
| D — P3 Talks   | Gemini/ADK agent; EverMemOS search; BM25 rerank; inline `memory_url` citations; citation validation; DM `/talk` + private threads; public memory pages via `memory_service`       | US-3         |
| E — Operations | Env-based config; structured logging; retry/backoff; Docker Compose deployment                                                                                                         | All          |

## Complexity Tracking

| Deviation                                                                               | Why Needed                                                                                                                                  | Simpler Alternative Rejected Because                                                                                              |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| SQLAlchemy ORM over raw `aiosqlite`                                                     | Operator directive; typed models, Alembic migration tooling, async session management, shared DB access across runtimes                     | Raw SQL would lose type safety and require manual schema management across packages reading the same DB                           |
| Three packages (memory_service, agents_service, discord_service) | Each has a distinct runtime and failure domain; the public memory page handler is served by `memory_service` | Merging Discord + ingestion is still avoided; the Memories API remains small and deterministic |
