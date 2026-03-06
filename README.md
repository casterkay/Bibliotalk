# Bibliotalk

Bibliotalk is a Python monorepo for the Bibliotalk agent system (see `BLUEPRINT.md` for the full system design).

## Repo Layout

```text
services/
  agents_service/        # Litestar agent service (Matrix appservice, orchestration)
  ingestion_service/     # Standalone EverMemOS ingestion library + CLI
  voice_call_service/    # Node sidecar for MatrixRTC/WebRTC
packages/
  bt_common/             # Shared Python utilities (incl. EverMemOS client wrapper)
specs/                   # Feature specs/plans/tasks
docs/                    # Reference knowledge docs
```

## Development

- Sync deps (from each service/package directory):
  - `UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev`
- Run tests (from each service/package directory):
  - `python -m pytest`

## EverMemOS Ingestion CLI

Docs/spec/tasks live under `specs/002-evermemos-content-ingest/`.

Environment variables:

- `EMOS_BASE_URL` (required)
- `EMOS_API_KEY` (optional)
- `INGEST_INDEX_PATH` (optional)

Examples:

- Ingest inline text:
  - `python -m ingestion_service --emos-base-url "$EMOS_BASE_URL" ingest text --user-id <USER_ID> --platform local --external-id <ID> --title "<TITLE>" --text "<TEXT>"`
- Ingest a local file:
  - `python -m ingestion_service --emos-base-url "$EMOS_BASE_URL" ingest file --user-id <USER_ID> --platform local --external-id <ID> --title "<TITLE>" --path /absolute/path/to/file.txt`
- Batch ingest from a manifest:
  - `python -m ingestion_service --emos-base-url "$EMOS_BASE_URL" ingest manifest --path /absolute/path/to/manifest.yaml`

Local outputs (gitignored by default):

- `.ingestion_service/index.sqlite3`
- `.ingestion_service/reports/<run_id>.json`

## Local End-to-End: “Chat With Ghosts”

The local E2E dev flow (Synapse + Element Web + SQLite + `agents_service`) is specified in:
- `specs/001-agent-service/plan.md`

At a high level:
- Start local infra with `deploy/local/docker-compose.yml`
- Generate + enable the Synapse appservice (`deploy/local/bin/setup-appservice.sh`)
- Run `agents_service` on port 8009
- Use `ingestion_service` to ingest sources into EverMemOS and emit a segment cache
- Import the segment cache into SQLite (canonical segments for citations)
- Provision Matrix Space + rooms via the `agents_service.bootstrap` CLI
See `QUICKSTART.md` for a runnable step-by-step.
