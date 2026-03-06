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

- Sync deps (workspace; installs all Python members):
  - `UV_CACHE_DIR=/tmp/uv-cache uv sync --all-packages --all-extras`
- Run tests:
  - `uv --directory services/agents_service run --package agents_service -m pytest`
  - `uv --directory services/ingestion_service run --package ingestion_service -m pytest`
  - `uv --directory packages/bt_common run --package bt_common -m pytest`

Environment configuration:

- All Python packages (`bt_common`, `agents_service`, `ingestion_service`) load a shared repo-root `.env` file via `python-dotenv` (see `bt_common.config.load_repo_dotenv`).
- Values from the process environment still take precedence; `.env` is intended for local dev defaults.

## Admin Panel (agents_service)

- Enable: set `ADMIN_PASSWORD` (otherwise `/admin` returns 404 with a short message)
- Start server: `uv --directory services/agents_service run --package agents_service -m uvicorn agents_service.server:app --host 0.0.0.0 --port 8009`
- Admin Panel URL: `http://localhost:8009/admin`
- Login:
  - Username: `ADMIN_USERNAME` (default: `admin`)
  - Password: `ADMIN_PASSWORD`
- Session secret: set `ADMIN_SECRET_KEY` (fallbacks: `MATRIX_HS_TOKEN` → `dev-secret-key`)
- Database (default): `.agents_service/bibliotalk.sqlite` (override with `DATABASE_URL`)

## One-Shot Local E2E Setup

To bootstrap a full local “chat with ghosts” environment (Synapse + Element Web + SQLite + `agents_service` + ingestion into EverMemOS), run from the repo root:

```bash
chmod +x deploy/local/bin/*.sh
deploy/local/bin/setup-all.sh
```

When the script completes:

- start `agents_service` in a separate terminal:
  - `uv run --package agents_service uvicorn agents_service.server:app --host 0.0.0.0 --port 8009`
- open Element Web at `http://localhost:8080`
- log in as `MATRIX_ADMIN_USER` (from `.env`) and chat with a Ghost DM.

See `specs/001-agent-service/quickstart.md` for details.

## EverMemOS Ingestion CLI

Docs/spec/tasks live under `specs/002-evermemos-content-ingest/`.

Environment variables:

- `EMOS_BASE_URL` (required)
- `EMOS_API_KEY` (optional)
- `INGEST_INDEX_PATH` (optional)

Examples:

- Ingest inline text:
  - `uv run --package ingestion_service -m ingestion_service --emos-base-url "$EMOS_BASE_URL" ingest text --user-id <USER_ID> --platform local --external-id <ID> --title "<TITLE>" --text "<TEXT>"`
- Ingest a local file:
  - `uv run --package ingestion_service -m ingestion_service --emos-base-url "$EMOS_BASE_URL" ingest file --user-id <USER_ID> --platform local --external-id <ID> --title "<TITLE>" --path /absolute/path/to/file.txt`
- Batch ingest from a manifest:
  - `uv run --package ingestion_service -m ingestion_service --emos-base-url "$EMOS_BASE_URL" ingest manifest --path /absolute/path/to/manifest.yaml`

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
See `specs/001-agent-service/quickstart.md` for a runnable step-by-step.
