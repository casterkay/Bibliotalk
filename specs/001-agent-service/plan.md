# Implementation Plan: Agent Service

**Feature**: `001-agent-service` | **Date**: 2026-03-06 | **Spec**: [spec.md](./spec.md)  
**Input**: `BLUEPRINT.md` + the design docs in `specs/001-agent-service/`

## Summary

Implement `agents_service`, the Matrix appservice + runtime that powers Ghosts (AI digital twins) with EverMemOS-grounded responses and verifiable citations (**言必有據**). The service also owns multi-agent discussion orchestration (floor control) and coordinates with `voice_call_service` for MatrixRTC voice sessions.

This repository contains an end-to-end text chat loop (Matrix appservice → retrieval → LLM composition → citations → Matrix response). The agent runtime is now wired to **Google ADK** for Gemini-backed text generation (see `services/agents_service/src/agent/providers/gemini.py`). Future work should extend ADK usage to richer tool-calling orchestration, additional providers (Bedrock Nova), and the planned multi-agent floor-control flows, while preserving the tool contracts (`memory_search`, `emit_citations`) and citation validation rules.

## Conflicts / Decisions (Read First)

This plan is sourced from `BLUEPRINT.md`, but it includes **local-dev** decisions that intentionally diverge from the blueprint’s proposed Supabase setup.

### C0: Postgres (blueprint/prod) vs SQLite (local dev)

- `BLUEPRINT.md` specifies a relational schema (shown in Postgres dialect) for `agents`, `segments`, `profile_rooms`, `chat_history`, etc.
- This repo’s local end-to-end flow uses **SQLite** as the canonical store for dev.

**Resolution**:
- Treat the blueprint schema as the **logical data model**.
- Implement a DB abstraction in `agents_service` backed by **SQLAlchemy ORM**.
- Keep a path open for a future Postgres deployment by changing `DATABASE_URL` (no code changes).

### C1: EverMemOS is not a canonical segment store

EverMemOS search returns `group_id` and summaries, but it is **not** a reliable store to fetch canonical verbatim segment text for citation verification. Therefore, a separate canonical store is required for:
- Quote verification (citations must be substrings of canonical segments)
- Profile-room timeline posting (verbatim segments)

**Resolution**:
- Canonical segments live in SQLite (`sources` / `segments` tables).
- Populate SQLite by replaying ingestion outputs (see “Ingestion Replay → SQLite Import”).

### C2: Local Matrix server_name

The local E2E flow uses `server_name=localhost` (so Matrix IDs are `@alice:localhost`). This is not a production posture; it is a dev convenience.

## Technical Context

**Languages**: Python 3.11+ (`services/agents_service`, `packages/bt_common`); Node.js 20+ (`services/voice_call_service`)  
**Key deps (current)**:
- Python: `litestar`, `uvicorn`, `sqlalchemy` (+ `aiosqlite`), `pydantic`, `pydantic-settings`, `httpx`, `evermemos`
- Node: `matrix-js-sdk`, `ws`
**Key deps (target, per blueprint)**: Google ADK, Gemini APIs, AWS Bedrock (Nova Lite v2 / Nova Sonic)

**Storage (local dev)**: SQLite (agents, sources/segments, profile_rooms, chat_history), EverMemOS (retrieval + memory metadata)  
**Storage (blueprint/prod target)**: Postgres (same ORM models), EverMemOS (memory)  
**Performance goals**: <5s text response latency; <3s voice response latency  
**Constraints**: unencrypted voice for MVP; single homeserver; appservice reserves `@bt_*` namespace; Ghosts never respond in profile rooms

## Constitution Check

*GATE: Must pass before major implementation changes. Re-check after each milestone.*

| Principle                        | Gate                                                                | Status |
| -------------------------------- | ------------------------------------------------------------------- | ------ |
| I. Design-First Architecture     | `spec.md` + `plan.md` exist before deeper build-out                 | PASS   |
| II. Test-Driven Quality          | Unit tests cover core business logic; contract tests cover EMOS edge | PASS   |
| III. Contract-Driven Integration | Explicit contracts for EMOS, citations, floor control, voice backend | PASS   |
| IV. Incremental Delivery         | US1 before US2 before US3 before US4                                | PASS   |
| V. Observable Systems            | Structured logs + correlation IDs at service entry points           | PASS   |
| VI. Principled Simplicity        | CLI-first harness for rapid iteration                               | PASS   |

## Repository Ownership (authoritative)

From `BLUEPRINT.md` and the current tree:
- `format_ghost_response` owner: `services/agents_service/src/matrix/appservice.py`
- Citation + segment domain models: `services/agents_service/src/models/`
- Agent runtime + tools: `services/agents_service/src/agent/`
- Infra-only shared lib (EMOS client, config, logging, exceptions): `packages/bt_common/src/`

## Project Structure

### Documentation (this feature)

```text
specs/001-agent-service/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── emos-client.md
│   ├── citation-schema.md
│   ├── voice-backend.md
│   └── discussion-floor-control.md
└── tasks.md
```

### Source Code (repository root)

```text
packages/bt_common/src/
├── __init__.py
├── config.py                     # pydantic-settings + .env loading
├── logging.py                    # JSON logging + correlation IDs
├── exceptions.py                 # shared exception types
└── evermemos_client.py           # EverMemOS SDK wrapper + retry/error mapping

services/agents_service/src/
├── __init__.py
├── __main__.py                   # CLI harness (`python -m agents_service ...`)
├── server.py                     # Litestar appservice transaction endpoint
├── agent/
│   ├── agent_factory.py          # Ghost agent creation + caching
│   ├── orchestrator.py           # (current) simple multi-ghost orchestration
│   ├── providers/                # LLM backends (Gemini/Nova)
│   └── tools/
│       ├── memory_search.py      # EMOS search + local rerank → Evidence
│       └── emit_citations.py     # Evidence → validated citations
├── database/
│   ├── store.py                  # DB interface (logical model from BLUEPRINT.md)
│   ├── sqlalchemy_models.py      # SQLAlchemy ORM tables
│   └── sqlalchemy_store.py       # SQLAlchemy-backed Store (SQLite local / Postgres prod)
├── matrix/
│   ├── appservice.py             # event handling + `format_ghost_response`
│   └── guards.py                 # per-room rate limiter
├── models/
│   ├── citation.py
│   └── segment.py
└── voice/
    ├── session_manager.py
    ├── transcript.py
    └── backends/
        ├── base.py
        ├── nova_sonic.py
        └── gemini_live.py

services/voice_call_service/src/
├── index.js
├── matrixrtc.js
├── audio_bridge.js
└── mixer.js
```

### Tests

```text
packages/bt_common/tests/
services/agents_service/tests/
```

## Phased Delivery (maps to spec priorities)

- **P1 (US1)**: Private text chat with a Ghost, grounded in EverMemOS with verifiable citations.
- **P2 (US2)**: Multi-agent text discussion with floor control (one speaker at a time; user preemption).
- **P3 (US3)**: Voice calls (MatrixRTC sidecar + voice backend tool-use + transcript + citations).
- **P4 (US4)**: Multi-agent voice discussions (floor-gated audio, barge-in, transcript + citations).

---

## Local End-to-End Flow (Synapse + Element Web + agents_service + SQLite + EverMemOS)

### Single Goal

“Let me chat with ghosts” end-to-end:
- Create a Bibliotalk Space
- Create Ghost profile rooms (read-only to humans)
- Create DMs to Ghosts and get replies
- Create a group room; Ghosts respond only when mentioned
- Populate profile rooms with an “EMOS memory timeline” thread from canonical segments

### Local Topology

| Component | Runtime | URL / Port | Notes |
| --- | --- | --- | --- |
| Synapse homeserver | Docker | `http://localhost:8008` | Matrix Client-Server API |
| Element Web | Docker | `http://localhost:8080` | Local dev UI |
| SQLite DB | Local file | `.agents_service/bibliotalk.sqlite` | Canonical local data store (SQLAlchemy ORM) |
| agents_service | Host python | `http://localhost:8009` | Matrix appservice + agent runtime |
| EverMemOS | external/local | `EMOS_BASE_URL` | Retrieval; must already be reachable |

### Environment Variables (local dev)

At minimum, `.env` must include:

```bash
# Matrix / Synapse
MATRIX_HOMESERVER_URL="http://localhost:8008"
MATRIX_AS_TOKEN="..."    # appservice token (used by agents_service to send as Ghosts)
MATRIX_HS_TOKEN="..."    # synapse → agents_service auth token (hs_token)

# Synapse admin (for scripted provisioning)
MATRIX_SERVER_NAME="localhost"
MATRIX_ADMIN_USER="bt_admin"
MATRIX_ADMIN_PASSWORD="..."

# SQLite (local canonical store)
DATABASE_URL="sqlite+aiosqlite:///./.agents_service/bibliotalk.sqlite"

# EverMemOS (retrieval + memorize during ingestion replay)
EMOS_BASE_URL="http://localhost:1995"
EMOS_API_KEY=""

# LLM
GOOGLE_API_KEY="..."
```

### Required agent_service Appservice Endpoints

To support Synapse appservice user resolution and reliable virtual user handling:
- `PUT`/`POST` `/_matrix/app/v1/transactions/{txn_id}` (already implemented)
- `GET` `/_matrix/app/v1/users/{userId}` (**implemented**)
  - Auth via `hs_token`
  - Return 200 only for `@bt_...:localhost` users that exist in the SQLite `agents` table

### DB Design: SQLite tables (SQLAlchemy ORM)

SQLite is the canonical local store for:
- `agents`, `agent_emos_config`
- `profile_rooms`
- `sources`, `segments` (canonical text for citation verification + profile timeline)
- `chat_history` (audit trail)

The ORM schema lives in `services/agents_service/src/database/sqlalchemy_models.py`.

### Ingestion Replay → SQLite Import (required for citations + profile timeline)

EverMemOS cannot reliably provide canonical segment text on demand, so the canonical segments must be imported into SQLite.

**Workflow**:
1. Run `ingestion_service` with `user_id = tenant_prefix` (e.g. `confucius`) so that EMOS `group_id` / `message_id` match the ID convention used by retrieval.
2. `ingestion_service` writes JSONL cache lines to `.ingestion_service/segment_cache/{user_id}.jsonl`.
3. `agents_service` imports this cache into SQLite (`sources` + `segments`).

#### Initial demo dataset (deterministic, rerunnable)

- Confucius: Gutenberg `3330` and `24055`
- Alan Watts: exactly one YouTube video (operator-provided `video_id`)

The ingestion manifest must use:
- `defaults.user_id: confucius` for Confucius sources
- `defaults.user_id: alan_watts` for Alan Watts sources

### Matrix Provisioning (scripted, idempotent)

Add a single bootstrap CLI that:
- Creates/updates Ghost records in SQLite
- Ensures Ghost Matrix accounts exist (Synapse admin API)
- Creates Bibliotalk Space + rooms (profile rooms, DMs, group room)
- Invites Ghosts to DMs + group room (Ghost joins via appservice)
- Sets profile-room power levels so humans cannot send messages
- Posts profile-room “timeline” threads from canonical segments in SQLite
- Smoke-tests DM response + citations

### Repo Additions (deployment assets)

Add:
- `deploy/local/docker-compose.yml`
  - Synapse, Element Web services
- `deploy/local/synapse/`
  - generate/config scripts
  - appservice registration YAML generation
- `services/agents_service/src/bootstrap.py`
  - the provisioning CLI described above

### Runbook (local dev)

The intended “happy path” commands (exact scripts/CLIs to be implemented under this plan):

1. Start infrastructure:
   - `docker compose -f deploy/local/docker-compose.yml up -d`
   - generate + enable the Synapse appservice:
     - `deploy/local/bin/generate-appservice.sh`
     - `(cd deploy/local && ./bin/enable-appservice.sh)`
     - `docker compose -f deploy/local/docker-compose.yml restart synapse`
2. Start `agents_service`:
   - `uvicorn agents_service.server:app --host 0.0.0.0 --port 8009`
3. Seed Ghosts in SQLite:
   - `python -m agents_service.bootstrap seed-ghosts`
4. Replay ingestion:
   - `python -m ingestion_service ingest manifest --path "$(pwd)/deploy/local/ingest/manifest.yaml"`
5. Import canonical segments to SQLite:
   - `python -m agents_service.bootstrap import-segment-cache --cache-dir .ingestion_service/segment_cache`
6. Provision Matrix Space + rooms:
   - `python -m agents_service.bootstrap provision-matrix`
7. Post profile timelines:
   - `python -m agents_service.bootstrap post-profile-timeline`
8. Validate:
   - `python -m agents_service.bootstrap smoke-test`
9. Chat:
   - open `http://localhost:8080` (Element Web), login, DM a Ghost

## Complexity Tracking

| Decision | Why it exists | Alternative rejected |
| --- | --- | --- |
| Node.js voice sidecar | MatrixRTC/WebRTC media handling is a separate runtime concern | A pure-Python stack still needs WebRTC media plumbing |
| VoiceBackend abstraction | Swap Nova Sonic ↔ Gemini Live without changing orchestration | Backend-specific logic would sprawl across the session manager |
| Domain models in `agents_service` | Keeps agent-domain ownership out of infra package (`bt_common`) | Putting agent models in `bt_common` breaks repository boundaries |

## Proposed Improvements (Non-Blocking)

- Wire `services/voice_call_service/package.json` to run `src/index.js` via `npm start`.
- Make `.env` discovery robust (support repo-root `.env` even when running from service directories).
- Add a dedicated Matrix event contract doc (appservice transactions + message send payloads).
- Implement the `BLUEPRINT.md` retrieval narrowing: EverMemOS `group_id` → `sources/segments` before reranking.
- Add a first-class “local E2E” developer flow (`deploy/local/*` + `agents_service.bootstrap`) that provisions Synapse + Element Web and seeds a working set of Ghosts + sources into SQLite.
