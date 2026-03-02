# Data Model: EverMemOS Content Ingestion Package

**Feature**: `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`  
**Created**: 2026-03-01

This data model describes the core entities used by the ingestion package. It is intentionally independent of Bibliotalk’s Supabase schema so the package can run standalone.

## Entities

### Person/Figure

Represents the EverMemOS tenant/user whose memory is being populated.

- **user_id** (string, required): Stable identifier used as EverMemOS `sender` and search `user_id` (when retrieval is added later).

### Source

One upstream content item to ingest (book, essay, transcript, etc.). All segments for a source share a single EverMemOS `group_id`.

- **platform** (enum string, required): e.g. `local`, `gutenberg`, `youtube`
- **external_id** (string, required): platform-specific stable ID (file hash, Gutenberg ebook ID, YouTube video ID, etc.)
- **title** (string, required)
- **source_url** (string, optional but recommended)
- **author** (string, optional)
- **published_at** (string/date-time, optional)
- **raw_meta** (object, optional): platform-specific metadata
- **group_id** (string, derived, required): `{user_id}:{platform}:{external_id}`
- **group_name** (string, derived, required): recommended default = `title`

### Segment

One citation-friendly chunk of a Source.

- **seq** (int, required): 0-based or 1-based, but must be consistent and stable for the source
- **text** (string, required): verbatim content for this chunk
- **sha256** (string, required): hash of `text` (exact bytes after normalization rules)
- **message_id** (string, derived, required): `{user_id}:{platform}:{external_id}:seg:{seq}`
- **speaker** (string, optional): transcript speaker label, when available
- **start_ms** (int, optional): transcript location marker
- **end_ms** (int, optional): transcript location marker

### Ingestion Run

Represents one execution attempt that may ingest multiple sources.

- **run_id** (string, required): unique identifier for this run (UUID recommended)
- **started_at** (string/date-time, required)
- **finished_at** (string/date-time, optional)
- **status** (enum string, required): `running` | `done` | `failed`
- **items** (list, required): list of Source ingestion results (see “Report” below)

### Ingestion Index (Local State)

Local persistence used for idempotency and re-run safety. Default implementation is a SQLite database on disk.

**Record** (per segment):
- **user_id** (string, required)
- **group_id** (string, required)
- **message_id** (string, required, unique)
- **sha256** (string, required)
- **ingested_at** (string/date-time, required)
- **status** (enum string, required): `ingested` | `skipped_unchanged` | `failed`
- **error_code** (string, optional)
- **error_message** (string, optional, redacted)

**Record** (per source):
- **user_id** (string, required)
- **group_id** (string, required, unique)
- **source_fingerprint** (string, optional): stable hash for the full source (when available)
- **meta_saved** (boolean, required)
- **last_ingested_at** (string/date-time, optional)

## Validation Rules (Derived From Requirements)

- A **Source** must have enough metadata to support citations: `title` and (when available) `source_url`.
- A **Segment** must retain verbatim text; citations must be exact substrings of `Segment.text`.
- Chunking must be deterministic for unchanged inputs so `seq`, `message_id`, and `sha256` remain stable across re-runs.
- Re-runs must not create duplicates: the ingestion index must prevent re-submitting unchanged segments.
- Secrets must never be stored in report files or error messages.

## State Transitions

### Per Source (within a run)

`pending` → `running` → (`done` | `failed`)

### Per Segment (within a source)

`pending` → (`ingested` | `skipped_unchanged` | `failed`)

