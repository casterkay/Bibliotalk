# Contract: EverMemOS API Usage (Ingestion)

**Feature**: `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`  
**Created**: 2026-03-01  
**Scope**: Memorize + group metadata only (no retrieval contract in this feature)

This contract defines how the ingestion package interacts with EverMemOS.

## Base URL and Auth

- Base URL: `${EMOS_BASE_URL}` (no trailing slash recommended)
- Auth header (optional, when required by the instance):
  - `Authorization: Bearer ${EMOS_API_KEY}`

## Endpoints

All endpoints are under `/api/v1/memories` (per `/Users/tcai/Projects/Bibliotalk/BLUEPRINT.md`).

### 1) Memorize Segment

**Purpose**: Store one segment as a message.

- Method: `POST`
- Path: `/api/v1/memories`

**Required fields**:
- `message_id` (string): stable per segment (see ID rules below)
- `sender` (string): EverMemOS user/tenant ID (the Ghost/person being populated)
- `content` (string): verbatim segment text
- `create_time` (string/date-time): set by client if not provided by SDK defaults

**Optional fields** (when supported by the target EverMemOS instance):
- `group_id` (string): stable per source
- `group_name` (string): human-readable source title
- `role` (string): default `"assistant"` per blueprint convention
- Additional metadata fields MAY be included as extra payload fields, for example:
  - `platform`, `external_id`, `seq`, `sha256`, `source_url`
  - `start_ms`, `end_ms`, `speaker` (for transcripts)

**Idempotency expectation**:
- The client MUST NOT assume server-side deduplication.
- The client enforces idempotency via a local ingestion index keyed by `message_id` + `sha256`.

### 2) Save Group / Conversation Metadata

**Purpose**: Attach source-level metadata once per `group_id`.

- Method: `POST`
- Path: `/api/v1/memories/conversation-meta`

**Client expectations**:
- Called once per source prior to memorizing segments (or on first segment when easier).
- Payload MUST include `group_id` (directly or nested within the EverMemOS “scene” structure, depending on API shape).
- Payload SHOULD include:
  - Title, canonical URL, author, publish date (when available)
  - Tags (platform, language, content type)

Because EverMemOS payload shapes may vary across versions, the ingestion package MUST implement this call through a typed wrapper with contract tests against captured example responses.

## Stable ID Rules

Following `/Users/tcai/Projects/Bibliotalk/BLUEPRINT.md` conventions:

- `sender` = `{user_id}`
- `group_id` = `{user_id}:{platform}:{external_id}`
- `message_id` = `{user_id}:{platform}:{external_id}:seg:{seq}`

## Error Handling

The client MUST:

- Retry transient failures (timeouts, connection errors, HTTP 5xx) with exponential backoff.
- Fail fast on validation/auth failures (HTTP 400/401/403/422) and surface actionable messages.
- Never log secrets (API keys, auth headers) or raw request bodies that may contain secrets.

