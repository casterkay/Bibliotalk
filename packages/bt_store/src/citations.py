from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CitationV1:
    segment_id: UUID
    emos_message_id: str
    source_title: str
    source_url: str
    quote: str
    content_platform: str
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class SegmentLike:
    segment_id: UUID
    agent_id: UUID
    text: str


def validate_citations(
    citations: Iterable[CitationV1],
    segments: Sequence[SegmentLike],
    *,
    responding_agent_id: UUID,
) -> list[CitationV1]:
    segments_by_id = {segment.segment_id: segment for segment in segments}
    valid: list[CitationV1] = []

    for citation in citations:
        segment = segments_by_id.get(citation.segment_id)
        if segment is None:
            continue
        if segment.agent_id != responding_agent_id:
            continue
        if citation.quote not in segment.text:
            continue
        valid.append(citation)

    return valid
