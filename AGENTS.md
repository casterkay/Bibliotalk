# Bibliotalk Development Guidelines

## Coding Assistant Guidelines

- You are a top-tier designer and engineer. Excellence is in your blood. Mediocre work is unacceptable. Exert your highest intellectual and aesthetic capabilities in this project.
- Your technical competency should at least match a Google L8 engineer with over $1M package.
- Always put things in their right places! Use your common sense and artistic taste.
- Always maintain excellent abstraction design: modularity, generality, reusability, separation of concerns, elimination of abstraction leaks, etc. 
- Focus on my true intent instead of always literally following my words. If you are confident, you can propose alternatives or raise opposition before executing my commands.
- Choose the latest suitable modern designs in both backend and frontend.
- After you make edits, think and suggest updates to maintain consistency and integrity throughout docs and code. In particular, ensure dev context files are up to date and have full coverage. 
- When you find unexpected changes in code diverted from your read & write memory, always assume they are made by me and RESPECT them.
- Reduction over Multiplication: always consider lossless reduction of code or specs and avoid unnecessary multiplication.

## Active Technologies

- Python 3.11+ + `evermemos` (EverMemOS SDK), `httpx`, `pydantic`, `typer`, `rich`, `tenacity` (002-evermemos-content-ingest)
- Python 3.11+ + `litestar`, `sqlalchemy` (async), `aiosqlite` (local dev), `alembic` (migrations), `sqladmin` (admin UI) (001-agent-service)

## Project Structure

```text
services/
  agents_service/        # Python — appservice + agent runtime
    src/
      agent/             # agent factory, orchestration, tools, providers
      matrix/            # Matrix appservice handling + response formatting
      models/            # citation + segment domain models
      database/          # SQLAlchemy ORM + Store adapters (SQLite local / Postgres prod)
      voice/             # voice session + backend adapters
  ingestion_service/     # Python — content ingestion pipelines + CLI
    src/
      adapters/          # source adapters (gutenberg, youtube, local_text)
      domain/            # errors, ids, data models
      pipeline/          # chunking, manifest, ingest, index
      runtime/           # config + reporting
  voice_call_service/    # Node.js — MatrixRTC/WebRTC sidecar
packages/
  bt_common/             # Python — shared infra library (EMOS client, config, logging, exceptions)
specs/
docs/
```

## Commands

- Run all tests for a service (from its directory):
  - `python -m pytest`
- Run ingestion CLI:
  - `python -m ingestion_service --help`

## Code Style

Python 3.11+: Follow standard conventions

## Recent Changes

- 002-evermemos-content-ingest: Added Python 3.11+ + `evermemos` (EverMemOS SDK), `httpx`, `pydantic`, `typer`, `rich`, `tenacity`

<!-- MANUAL ADDITIONS START -->
## Manual Notes

### Architecture Boundaries

- Treat current repository file layout as the source of truth for imports and ownership.
- The single `format_ghost_response` implementation is in `services/agents_service/src/matrix/appservice.py`.
- Citation and segment domain models live in `services/agents_service/src/models/`.
- `bt_common` is infra-only (`evermemos_client`, `config`, `logging`, `exceptions`) and should not own agent-domain models.

### ingestion_service

- Standalone EverMemOS ingestion library + CLI (see `specs/002-evermemos-content-ingest/`).
- Local artifacts (gitignored): `.ingestion_service/` (SQLite index + JSON reports).

### agents_service (local dev)

- Local artifacts (gitignored): `.agents_service/` (SQLite DB + reports/caches as needed).

### Common Commands

- Sync deps (from each service/package directory):
  - `UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev`
- Run tests (from each service/package directory):
  - `python -m pytest`
- Ingestion CLI help:
  - `python -m ingestion_service --help`
<!-- MANUAL ADDITIONS END -->
