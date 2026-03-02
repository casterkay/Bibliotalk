# Contract: Ingestion Report Format (JSON)

**Feature**: `/Users/tcai/Projects/Bibliotalk/specs/002-evermemos-content-ingest/spec.md`  
**Created**: 2026-03-01

This contract defines the machine-readable report written per ingestion run.

## Top-Level Schema (v1)

- `version` (string, required): `"1"`
- `run_id` (string, required)
- `started_at` (string/date-time, required)
- `finished_at` (string/date-time, optional)
- `status` (string, required): `done|failed`
- `summary` (object, required):
  - `sources_total` (int)
  - `sources_succeeded` (int)
  - `sources_failed` (int)
  - `segments_ingested` (int)
  - `segments_skipped_unchanged` (int)
  - `segments_failed` (int)
- `sources` (list, required): one entry per attempted source

## Source Result Schema (v1)

- `user_id` (string, required)
- `platform` (string, required)
- `external_id` (string, required)
- `title` (string, required)
- `source_url` (string, optional)
- `group_id` (string, required)
- `status` (string, required): `done|failed`
- `meta_saved` (boolean, required)
- `segments_total` (int, required)
- `segments_ingested` (int, required)
- `segments_skipped_unchanged` (int, required)
- `segments_failed` (int, required)
- `error` (object, optional):
  - `code` (string)
  - `message` (string, redacted; must not include secrets)
- `segments` (list, optional): segment-level details (may be omitted for very large sources)

## Segment Result Schema (v1, optional)

- `seq` (int, required)
- `message_id` (string, required)
- `sha256` (string, required)
- `status` (string, required): `ingested|skipped_unchanged|failed`
- `start_ms` (int, optional)
- `end_ms` (int, optional)
- `error` (object, optional): same shape as source error

## Redaction Rules

- API keys, bearer tokens, auth headers MUST NOT appear anywhere in the report.
- If EverMemOS returns an error message containing sensitive text, the report MUST redact it.

