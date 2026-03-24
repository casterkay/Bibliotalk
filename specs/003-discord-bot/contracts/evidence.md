# Contract: Evidence and Citation

**Used by:** `agents_service` (production) · `discord_service` (validation + sending) · tests
**Source:** `services/agents_service/src/models/citation.py`
**Date:** 2026-03-07

---

## Evidence

The `Evidence` object is the unit of grounding passed from the memory search tool to the agent runtime. It carries all fields needed to construct a `memory_url` inline link and to validate quoted spans.

```python
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, HttpUrl


class Evidence(BaseModel):
    # Segment identity
    segment_id: uuid.UUID
    source_id: uuid.UUID

    # Agent identity (for cross-agent isolation check)
    agent_id: uuid.UUID
    memory_user_id: str          # == agent slug (EverMemOS user_id) e.g. "alan-watts"

    # EMOS retrieval fields — used to construct memory_url
    memory_timestamp: datetime   # EMOS memory item `timestamp` (UTC)
    memory_id: str               # "{memory_user_id}_{timestamp_compact}" — URL key
    memory_url: str              # "{BIBLIOTALK_WEB_URL}/memories/{memory_id}"

    # Verbatim evidence for BM25 reranking and quote validation
    text: str                    # full cached segment text from SQLite
    group_id: str                # "{emos_user_id}:youtube:{video_id}"

    # Source metadata for display
    source_title: str
    source_url: str              # YouTube video URL
    platform: str = "youtube"
    published_at: datetime | None = None

    # Optional timestamped video URL (reconstructed from create_time - published_at)
    video_url_with_timestamp: str | None = None
```

### Construction rules

- `memory_id` = `f"{memory_user_id}_{memory_timestamp.strftime('%Y%m%dT%H%M%SZ')}"` (UTC compact timestamp, no colons for URL safety)
- `memory_url` = `f"{BIBLIOTALK_WEB_URL.rstrip('/')}/memories/{memory_id}"` (default base URL: `https://www.bibliotalk.space`)
- `video_url_with_timestamp`: when `published_at` is known, offset = `int((memory_timestamp - published_at).total_seconds())`; URL = `f"{source_url}{'&' if '?' in source_url else '?'}t={offset}s"`
- `memory_timestamp` is the EMOS `timestamp` field returned by `search()` for the matching memory item — it is not re-derived locally

---

## Citation validation

Replace the existing `validate_citations` helper with `validate_evidence_links`. Called on the agent's raw response text before sending to Discord.

```python
def validate_evidence_links(
    response_text: str,
    evidence_set: list[Evidence],
    *,
    agent_emos_user_id: str,
) -> str:
    """
    Strip any inline markdown links in response_text that fail validation.

    Validation rules (all three must pass):
    1. memory_user_id == agent_emos_user_id  (cross-agent isolation)
    2. The memory_url appears in the provided evidence_set   (retrieval-set membership)
    3. Any quoted span adjacent to the link is a substring of the corresponding
       Evidence.text  (verbatim cache check)

    Returns the response with invalid links stripped (link text retained, URL removed).
    """
```

### Validation rules

| Rule                     | Check                                                                                                   | Failure action                    |
| ------------------------ | ------------------------------------------------------------------------------------------------------- | --------------------------------- |
| Cross-agent isolation    | `evidence.memory_user_id == agent_emos_user_id`                                                         | Strip link URL; keep visible text |
| Retrieval-set membership | URL appears in `{e.memory_url for e in evidence_set}`                                                   | Strip link URL; keep visible text |
| Quote substring          | If response contains a quoted phrase attributed to this link, it must be a substring of `evidence.text` | Strip link URL; keep visible text |

If the response after stripping has no usable inline links, the agent MUST return the explicit no-evidence message rather than a link-free answer that implies grounding.

---

## Breaking changes from previous Citation model

| Old field                                      | New field                                                     | Notes                                       |
| ---------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------- |
| `Citation.index: int`                          | Removed                                                       | No citation indices in MVP (FR-025)         |
| `Evidence.emos_message_id: str`                | `Evidence.memory_timestamp: datetime` + `memory_id: str`      | Timestamp-based URL construction            |
| `validate_citations(citations, segments, ...)` | `validate_evidence_links(text, evidence_set, ...)`            | Text-level validation instead of list-level |
