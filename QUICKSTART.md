# Quickstart: Agent Service

**Feature**: `001-agent-service`  
**Created**: 2026-02-28  
**Last Updated**: 2026-03-06  
**Prereqs**: Python 3.11+, Node.js 20+ (for `voice_call_service`)

This quickstart offers two paths:

- **A) Fast dev loop**: CLI harness for grounding + citations (no Synapse).
- **B) Local E2E (“chat with ghosts”)**: Synapse + Element Web + SQLite + `agents_service` + EverMemOS.

## 1) Configure Environment

From the repo root:

```bash
cp .env.example .env
# edit .env (SQLite DB, EMOS, Matrix, etc.)
```

If you want to use Gemini via Google ADK for text generation, set:

```bash
export GOOGLE_API_KEY="..."
```

## 2) Install Python deps (agents_service)

```bash
cd services/agents_service
UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev
source .venv/bin/activate
```

## 3A) Fast dev loop: Quick Test (CLI harness)

Run from the repo root so `.env` is discovered:

```bash
cd ../..
python -m agents_service --agent confucius --mock-emos
```

To exercise Gemini (requires `GOOGLE_API_KEY`):

```bash
python -m agents_service --agent confucius --mock-emos --model gemini-2.5-flash
```

## 3B) Local E2E: Synapse + Element Web + SQLite

1. Generate Synapse config + appservice registration (idempotent):

```bash
chmod +x deploy/local/bin/*.sh
deploy/local/bin/setup-appservice.sh
```

2. Start infrastructure (Synapse + Element Web):

```bash
docker compose -f deploy/local/docker-compose.yml up -d
```

3. Create a Synapse admin user (first run only):

```bash
docker compose -f deploy/local/docker-compose.yml exec synapse \
  register_new_matrix_user -c /data/homeserver.yaml http://localhost:8008 \
  -u "$MATRIX_ADMIN_USER" -p "$MATRIX_ADMIN_PASSWORD" -a
```

4. Start `agents_service`:

```bash
uvicorn agents_service.server:app --host 0.0.0.0 --port 8009
```

5. Seed Ghosts in SQLite:

```bash
python -m agents_service.bootstrap seed-ghosts
```

6. Replay ingestion (build canonical segments + memorize into EverMemOS):

```bash
python -m ingestion_service ingest manifest --path "$(pwd)/deploy/local/ingest/manifest.yaml"
```

7. Import `.ingestion_service/segment_cache/*.jsonl` into SQLite:

```bash
python -m agents_service.bootstrap import-segment-cache --cache-dir .ingestion_service/segment_cache
```

8. Provision Matrix Space + rooms + profile-room permissions:

```bash
python -m agents_service.bootstrap provision-matrix
python -m agents_service.bootstrap post-profile-timeline
python -m agents_service.bootstrap smoke-test
```

9. Chat:
- open Element Web (`http://localhost:8080`)
- login as `MATRIX_ADMIN_USER`
- open “DM — Confucius”, send a message, and verify a cited reply.

## 4) Run Tests

`agents_service` tests:

```bash
cd services/agents_service
python -m pytest
```

`bt_common` tests (EverMemOS wrapper + infra):

```bash
cd packages/bt_common
UV_CACHE_DIR=/tmp/uv-cache uv sync --extra dev
python -m pytest
```

## 5) Start agents_service (Litestar)

```bash
cd ../..
uvicorn agents_service.server:app --host 0.0.0.0 --port 8009
```

## 6) Start voice_call_service (Node sidecar)

```bash
cd services/voice_call_service
npm install
npm start
```

## Repository Map (authoritative)

- `format_ghost_response`: `services/agents_service/src/matrix/appservice.py`
- Agent runtime/tools: `services/agents_service/src/agent/`
- Citation/segment models: `services/agents_service/src/models/`
- EverMemOS wrapper + config/logging/exceptions: `packages/bt_common/src/`
