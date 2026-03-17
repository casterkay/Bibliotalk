# Quickstart: Local Development (Matrix MVP)

**Feature:** `001-matrix-mvp`
**Date:** 2026-03-16

This quickstart describes the intended local end-to-end dev loop for:

- **Dialogue Rooms**: Spirit text chat + 1:1 voice calls (with transcript + citations)
- **Archive Rooms**: ingestion-backed public, read-only archives

---

## Prerequisites

- Python 3.11+
- `uv` (workspace package manager)
- Node.js 20+ (for `matrix_service` + `voip_service`)
- Docker (for Synapse + Element)
- EverMemOS instance + API key
- Google API key with Gemini access (text + voice)

---

## 1) Install workspace dependencies

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --all-packages --all-extras
```

---

## 2) Configure environment

Create a `.env` file at the repo root (gitignored) from `.env.example`.

Minimum required configuration (illustrative; exact variable set may expand during implementation):

```env
# EverMemOS
EMOS_BASE_URL=
EMOS_API_KEY=

# Gemini
GOOGLE_API_KEY=

# Storage
BIBLIOTALK_DB_PATH=

# Matrix (homeserver + appservice)
MATRIX_HOMESERVER_URL=
MATRIX_AS_TOKEN=
MATRIX_HS_TOKEN=
MATRIX_SENDER_LOCALPART=bt_system
MATRIX_SPIRIT_USER_PREFIX=bt_
```

---

## 3) Start Synapse + Element (local)

Start the local Matrix stack (Synapse + Element Web):

```bash
./scripts/matrix-dev.sh provision
```

Expected outcome:
- Element Web is reachable (local URL defined by the compose config).
- Synapse is running and configured with the Bibliotalk appservice.

---

## 4) Initialize database + seed Spirits

Initialize the DB schema and seed at least one Spirit.

```bash
uv run --package bt_cli bibliotalk db-init
uv run --package bt_cli bibliotalk agent seed --agent confucius
```

---

## 5) Ingest one source and publish to an Archive Room

Run a one-shot ingest for a configured Spirit and publish to its Archive Room.

```bash
uv run --package bt_cli bibliotalk ingest request --agent confucius --source <SOURCE_ID>
uv run --package bt_cli bibliotalk ingest run --once
uv run --package bt_cli bibliotalk matrix publish-archive --agent confucius
```

Expected outcome:
- A Confucius Archive Room exists in the Bibliotalk Space.
- The new source appears as a thread: root source message + reply segments.

---

## 6) Run services (Matrix text chat)

Start the agent core and Matrix adapter in separate terminals:

```bash
uv run --package agents_service uvicorn agents_service.server:app --host 0.0.0.0 --port 8009
cd services/matrix_service
npm install
npm run dev
```

Then open Element Web, create or open a Dialogue Room with the Spirit, and send a message.

Expected outcome:
- The Spirit replies in the Dialogue Room.
- The reply includes verifiable citations.

---

## 7) Run voice (1:1 Element Call)

Start the Node sidecar:

```bash
cd services/voip_service
npm install
npm start
```

In Element:
- Start a call in a Dialogue Room.
- Trigger the Spirit to join and speak (command UX is implementation-defined for MVP).

Expected outcome:
- Spirit audio is heard in the call.
- A text transcript + citations are posted into the Dialogue Room for each Spirit turn.

---

## Running tests

```bash
uv --directory services/agents_service run --package agents_service -m pytest
uv --directory services/memory_service run --package memory_service -m pytest
cd services/matrix_service && npm test
uv --directory packages/bt_store run --package bt_store -m pytest
```
