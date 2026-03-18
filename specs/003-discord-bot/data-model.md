# Data Model: YouTube → EverMemOS → Discord Agent Bots

**Phase 1 output for:** `003-discord-bot`
**Date:** 2026-03-07
**Status:** Deprecated (schema moved to `packages/bt_store/`)

All services share a single relational schema owned by `bt_store` (SQLite for local dev; Postgres for prod).
If you need to migrate an existing legacy SQLite DB, use `scripts/backfill_bt_store_v2.py`.

## Source of truth

- Core identity + platform mapping: `packages/bt_store/src/models_core.py`
- Ingestion state + subscriptions: `packages/bt_store/src/models_ingestion.py`
- Evidence store (sources/segments) + publish intents: `packages/bt_store/src/models_evidence.py`
- Runtime state: `packages/bt_store/src/models_runtime.py`
- Initial migration: `packages/bt_store/alembic/versions/0001_initial_schema.py`

Notes:

- The canonical identity term is **agent** (not figure). If you need a public-figure vs app-user distinction, use `agents.kind` (e.g. `figure|user`) rather than separate tables.
- Public memory pages are served by the unified Memories API (`memory_service`), at `GET /memories/{id}` and `/v1/*`.

## Required query patterns

| Query                                                  | How satisfied                                                                                                                                                |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Given EMOS `group_id` values, fetch all local segments | Join `sources → segments` filtered by `sources.emos_group_id IN (...)`                                                                                       |
| Given `segment_id`, fetch verbatim text                | Primary key lookup on `segments.segment_id`                                                                                                                  |
| Given EMOS `(user_id, timestamp)`, reconstruct time    | Join `agents` on `agents.slug = user_id` → `sources.published_at` + compute `(memcell.timestamp - sources.published_at)` (or use stored segment timestamps) |
| Given `source_id`, fetch unposted transcript batches   | `WHERE source_id = ? AND posted_to_discord = FALSE ORDER BY start_seq`                                                                                        |
| Given `agent_id`, fetch all segments for reranking     | Join `sources → segments` filtered by `sources.agent_id`                                                                                                      |
| Given `source_id`, check Discord post state            | `SELECT * FROM discord_posts WHERE source_id = ?`                                                                                                            |

## Entity identifier summary

| Entity                | ID         | Format                                                   |
| --------------------- | ---------- | -------------------------------------------------------- |
| Agent                 | `agent_id` | UUID v4, internal PK                                     |
| Agent (EverMemOS)     | `user_id`  | Readable slug `"alan-watts"` — immutable                 |
| YouTube video         | `external_id` | YouTube `video_id` string                             |
| EverMemOS group       | `group_id` | `"{user_id}:youtube:{video_id}"`                         |
| EverMemOS message     | `message_id` | `"{user_id}:youtube:{video_id}:seg:{seq}"`            |
| MemCell timestamp     | —          | EverMemOS `timestamp` (UTC datetime)                     |
| Public memory URL     | —          | `https://www.bibliotalk.space/memories/{user_id}_{YYYYMMDDTHHMMSSZ}` |
