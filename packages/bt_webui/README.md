# bt_webui (Bibliotalk Operator Console)

`bt_webui` is the all-in-one admin panel for managing Bibliotalk’s backend:

- Agents (registry): rename, activate/deactivate
- Subscriptions: add/edit/deactivate
- Discord routes: feed + voice bindings
- Sources: browse ingest status, delete (EverMemOS + local evidence)
- Collector: run one poll/ingest cycle and inspect results
- EverMemOS: raw `/memories/get` browser per agent

## Run (API + UI)

Environment:
- `BIBLIOTALK_ADMIN_TOKEN` (required)
- `BIBLIOTALK_DB_PATH` (optional)
- `EMOS_BASE_URL`, `EMOS_API_KEY` (required for EverMemOS browser + ingest)
- `MEMORIES_SERVICE_URL` (optional; default `http://localhost:8080`)

Run server:

```
uv run --package bt_cli bibliotalk webui run --host 0.0.0.0 --port 8090
```

## Build the frontend

The FastAPI server serves the static export at `packages/bt_webui/web/out/`.

From `packages/bt_webui/web/`:

```
npm install
npm run build
```
