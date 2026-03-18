# Contract: EverMemOS API Usage (Agent Bots)

**Feature**: `/Users/tcai/Projects/Bibliotalk/specs/003-discord-bot/spec.md`
**Created**: 2026-03-07
**Scope**: Memorize, conversation metadata, retrieval/search, and delete-by-group for manual re-ingest

This contract defines how the successor agent-bot system interacts with EverMemOS.

## Base URL and Auth

- Base URL: `${EMOS_BASE_URL}`
- Auth header when required by the instance:
  - `Authorization: Bearer ${EMOS_API_KEY}`

## Endpoints

All endpoints are under `/api/v1/memories`.

### 1) Memorize Segment

**Purpose**: Store one transcript segment as a memory item.

- Method: `POST`
- Path: `/api/v1/memories`

**Required fields**:
- `message_id` (string): stable per segment
- `sender` (string): agent slug (EverMemOS `user_id`)
- `content` (string): verbatim segment text
- `create_time` (string/date-time): `video_published_at + chunk_start_offset`

**Optional fields**:
- `group_id` (string)
- `group_name` (string)
- `role` (string), default `"assistant"`
- extra metadata such as `platform`, `external_id`, `seq`, `sha256`, `source_url`, `start_ms`, `end_ms`, `speaker`

**Idempotency expectation**:
- The client MUST NOT assume server-side deduplication.
- The client enforces idempotency via the local evidence store keyed by `(source_id, seq, sha256)` and stable `message_id`.

### 2) Save Group / Conversation Metadata

**Purpose**: Attach source-level metadata once per `group_id`.

- Method: `POST`
- Path: `/api/v1/memories/conversation-meta`

**Client expectations**:
- Called once per source before or during first segment memorize.
- Payload MUST include `group_id`.
- Payload SHOULD include title, canonical URL, channel/author, publish date, and tags.

### 3) Search / Retrieval

**Purpose**: Retrieve candidate memories for grounded DM chat.

- Method: SDK wrapper or `POST` to the instance search endpoint exposed by the deployed EverMemOS version
- Inputs MUST include:
  - `query`
  - `user_id` = agent slug (EverMemOS `user_id`)
  - `retrieve_method` = `rrf` or `agentic`
  - `top_k`

**Expected response fields used by this feature**:
- `group_id`
- `user_id`
- `timestamp`
- `summary`

The caller MUST treat `(user_id, timestamp)` as the source of truth for constructing the public `memory_id` (`{user_id}_{timestamp_compact}`) and `memory_url` (`{BIBLIOTALK_WEB_URL}/memories/{memory_id}`).

### 4) Delete by Group

**Purpose**: Support manual single-video re-ingest.

- Method: SDK wrapper or instance-specific delete operation
- Input: `group_id = {user_id}:youtube:{video_id}`

**Client expectations**:
- Deletes all memories belonging to that video before re-ingest.
- Failures MUST surface clearly and MUST NOT silently continue with a mixed old/new memory set.

## Stable ID Rules

- `sender` = `{user_id}`
- `group_id` = `{user_id}:youtube:{video_id}`
- `message_id` = `{user_id}:youtube:{video_id}:seg:{seq}`

## Error Handling

The client MUST:

- Retry transient failures (timeouts, connection errors, HTTP 5xx) with exponential backoff.
- Fail fast on validation/auth failures (HTTP 400/401/403/422) and surface actionable messages.
- Never log secrets (API keys, auth headers) or raw request bodies that may contain secrets.
- Preserve local SQLite state if memorize or search fails.
