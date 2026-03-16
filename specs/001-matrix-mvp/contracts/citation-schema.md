# Contract: Citation Schema (v1)

**Scope**: Bibliotalk Spirit responses (text + voice transcripts)
**Used by**: agent core, Matrix adapter, audit storage (`TalkThread`)

This contract defines the structured citation payload used to keep Spirit responses verifiable (**言必有據**).

## Citation Object

```json
{
  "segment_id": "uuid",
  "emos_message_id": "{tenant}:{content_platform}:{external_id}:seg:{seq}",
  "source_title": "The Analects, Book II",
  "source_url": "https://www.gutenberg.org/ebooks/3330",
  "quote": "Learning without reflection is a waste...",
  "content_platform": "gutenberg",
  "timestamp": "2025-01-15T10:00:00Z"
}
```

Notes:
- `timestamp` is optional and may be either an ISO date or ISO date-time.
- `quote` MUST be a substring of the canonical `segments.text` for the referenced `segment_id`.
- Citations MUST be scoped to the responding Spirit; cross-Spirit citations are always invalid.

## Matrix Event Extension

Spirit responses in **Dialogue Rooms** include structured citations under `com.bibliotalk.citations`:

```json
{
  "msgtype": "m.text",
  "body": "Response with citation markers...",
  "format": "org.matrix.custom.html",
  "formatted_body": "Response with <sup>[1]</sup>...",
  "com.bibliotalk.citations": {
    "version": "1",
    "items": [<Citation>, ...]
  }
}
```

Notes:
- Citation marker style (e.g., footnotes, inline links) is adapter-owned and implementation-defined. The agent core emits plain text plus structured citations; the Matrix adapter renders visible markers in `body` / `formatted_body`.

## Validation Rules (MUST)

Before delivering any cited Spirit response:

1. Verify every cited `segment_id` exists in `segments`.
2. Verify the cited segment belongs to the responding Spirit (`segments.agent_id` matches).
3. Verify `quote` is a substring of the canonical `segments.text`.
4. Strip citations that fail validation; log a warning with safe metadata only.

If no usable citations remain and the response makes non-trivial factual claims, the system MUST fall back to the “no evidence” response behavior for the relevant claims (exact fallback wording is implementation-defined, but MUST be explicit).
