# Data Model: Matrix MVP (Archive + Dialogue + Voice)

**Phase 1 output for:** `001-matrix-mvp`
**Date:** 2026-03-16
**Planned schema owner:** `packages/bt_store/` (shared across services)

This document defines the logical data model required to implement:

- **Dialogue Rooms**: grounded Spirit conversations (text + voice transcripts) with verifiable citations.
- **Archive Rooms**: public, read-only, ingestion-backed room timelines posted idempotently.
- **Platform-agnostic core**: the same Spirit grounding/citation logic works across platforms.

Implementation note: In the Matrix MVP, the Matrix adapter (`matrix_service`) is implemented in Node.js/TypeScript; this does not affect the shared relational schema.

---

## Core Entities

### 1) Agent (Spirit)

Represents a single Spirit persona that can participate in Dialogue Rooms and owns an Archive Room.

**Key fields**
- `agent_id`: stable UUID
- `kind`: `figure` (MVP) *(future: `user`)*
- `slug`: stable unique handle (used as EverMemOS tenant prefix and CLI key)
- `display_name`: human-friendly name (e.g., "Confucius (Spirit)")
- `persona_summary`: optional short persona descriptor (for UX)
- `is_active`: active/inactive flag
- `created_at`

**Validation rules**
- `display_name` non-empty; stable enough for UI display.
- `slug` unique, URL-safe-ish, and stable (used in IDs and CLI).
- Inactive agents never respond in Dialogue Rooms.

---

### 2) AgentPlatformIdentity

Maps an `agent_id` to a platform-scoped identifier (e.g., Matrix user ID for virtual Spirit users).

**Key fields**
- `agent_id`
- `platform`: `matrix` *(future: `discord`, others)*
- `platform_user_id`: e.g., `@bt_spirit_confucius:bibliotalk.space`
- `created_at`

**Constraints**
- Unique `(platform, platform_user_id)`.
- One agent may have multiple platform identities across platforms.

---

### 3) Room

Represents a platform room that Bibliotalk must reason about for routing, enforcement, and posting.

**Key fields**
- `platform`: `matrix`
- `room_id`: platform-native room identifier (e.g., `!abc:server`)
- `kind`: `archive` | `dialogue`
- `created_at`

**Validation rules**
- A room’s `kind` is immutable after creation.

---

### 3.1) RoomMember

Represents a room participant. A room is explicitly multi-participant (humans and/or agents).

**Key fields**
- `room_pk`: FK to `Room`
- `platform_user_id`: platform user ID within the room
- `agent_id`: optional FK to `Agent` (present when this member is a Spirit virtual user)
- `member_kind`: `human` | `agent` *(extensible)*
- `role`: optional platform-agnostic role hint (e.g., `admin`, `moderator`)
- `created_at`

**Constraints**
- Unique `(room_pk, platform_user_id)`.

---

## Ingestion Evidence Entities

These entities back grounding and citations and populate Archive Rooms.

### 4) Source

One upstream content item ingested for an agent (video, book, podcast, document).

**Key fields**
- `source_id`: UUID
- `agent_id`
- `content_platform`: e.g., `youtube`, `gutenberg`, `podcast` *(MVP may start with a subset)*
- `external_id`: upstream identity (e.g., YouTube video ID)
- `external_url`: canonical URL
- `title`
- `author` *(optional)*
- `published_at` *(optional)*
- `raw_meta_json` *(optional)*
- `emos_group_id`: stable memory grouping identifier
- `created_at`

**Constraints**
- Unique `(agent_id, content_platform, external_id)`.
- `emos_group_id` stable and derivable from `(agent_id/content_platform/external_id)` by convention.

---

### 4.1) Subscription + SubscriptionState

Tracks source feed subscriptions (e.g., YouTube channel/playlist feeds) and their ingestion cursors.

**Subscription key fields**
- `subscription_id`: UUID
- `agent_id`
- `content_platform`: e.g., `youtube`
- `subscription_type`: e.g., `youtube.channel`, `youtube.playlist`
- `subscription_url`
- `poll_interval_minutes`
- `is_active`
- `created_at`

**SubscriptionState key fields**
- `subscription_id`: PK/FK to `Subscription`
- `last_seen_external_id`: cursor (e.g., last seen video ID)
- `last_published_at`: cursor timestamp (optional)
- `last_polled_at`
- `failure_count`, `next_retry_at`
- `updated_at`

---

### 4.2) SourceIngestionState + SourceTextBatch

Tracks per-source ingestion state and the derived “postable text batches”.

**SourceIngestionState key fields**
- `source_id`: PK/FK to `Source`
- `ingest_status`: `pending` | `ingested` | `failed` | `no_transcript` *(extensible)*
- `failure_count`, `last_attempt_at`, `next_retry_at`, `skip_reason`
- `manual_requested_at`
- `updated_at`

**SourceTextBatch key fields**
- `batch_id`: UUID
- `source_id`
- `kind`: e.g., `transcript`
- `start_seq`, `end_seq` (+ optional `start_ms`, `end_ms`)
- `text`
- `batch_rule`: batching reason (speaker change, silence gap, char limit, etc.)
- `created_at`

---

### 5) Segment

Atomic verbatim evidence chunk used for:
1) EverMemOS memorize/search alignment
2) citation verification (quote substring checks)
3) Archive Room posting (thread replies)

**Key fields**
- `segment_id`: UUID
- `source_id`
- `agent_id`
- `seq`: integer ordering within the source
- `text`: canonical verbatim chunk text
- `sha256`: content hash for dedup/changes
- `speaker` *(optional)*
- `start_ms`, `end_ms` *(optional; for time-coded sources)*
- `emos_message_id`: stable per-segment memory id
- `create_time` *(optional; used to map to timepoint for some sources)*
- `created_at`

**Constraints**
- Unique `(source_id, seq)` and/or `(source_id, seq, sha256)` depending on update strategy.
- `agent_id` must match `Source.agent_id`.

---

## Conversation & Publication Entities

### 6) TalkThreads

Audit record of Dialogue Room turns (text and voice transcripts), including structured citations.

**Key fields**
- `thread_id`: UUID
- `platform`: `matrix`
- `room_id`
- `sender_agent_id`: nullable (null for real human users)
- `sender_platform_user_id`: platform user id
- `platform_event_id`: nullable (null for voice turns)
- `modality`: `text` | `voice`
- `content`: message text or transcript
- `citations_json`: list of structured citations (possibly empty)
- `created_at`

**Validation rules**
- If `sender_agent_id` is non-null, sender must be a valid agent and must match the responding agent for any citations.

---

### 7) PlatformPost (Archive Publication)

Tracks idempotent publication of Source/Segment content into Archive Rooms.

**Key fields**
- `post_id`: UUID
- `platform`: `matrix`
- `kind`: `archive.thread_root` | `archive.thread_reply`
- `agent_id`
- `room_id`: target Archive Room
- `source_id`
- `segment_id`: null for root; set for reply
- `idempotency_key`: stable deterministic key (e.g., `matrix:archive:{agent_id}:{source_id}:root` or `...:{segment_seq}`)
- `platform_event_id`: set after successful post
- `status`: `pending` | `posted` | `failed`
- `error`: last error string (redacted)
- `created_at`, `updated_at`

**Constraints**
- Unique `idempotency_key`.
- Re-try logic: pending/failed posts can be retried without duplicates.

**State transitions**
- `pending → posted` on success
- `pending → failed` on error
- `failed → pending` on retry request

---

## Derived / Non-Persisted Entities

### Citation (structured payload)

Structured citation object produced during response generation and attached to:
- Dialogue Room messages (as payload + visible markers)
- TalkThreads records

**Key fields**
- `segment_id`
- `emos_message_id`
- `source_title`
- `source_url`
- `quote` (must be substring of `Segment.text`)
- `content_platform`
- `timestamp` *(optional; if derived from source time mapping)*

---

## Data Access Patterns (must be efficient)

- Given a set of EverMemOS retrieval results (group IDs), fetch candidate `Source` rows and then the associated `Segment` rows.
- Given `segment_id`, fetch `Segment.text` for citation verification.
- Given `source_id`, list ordered `Segment` rows for Archive thread posting.
- Given a Dialogue Room `room_id`, append `TalkThreads` and query recent history for conversational context.
- Given `agent_id`, query pending `PlatformPost` rows and publish them idempotently.
