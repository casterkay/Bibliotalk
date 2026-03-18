"""Evidence contract and link-validation helpers for grounded responses."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

NO_EVIDENCE_RESPONSE = "I couldn't find relevant supporting evidence for that question."


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def build_verifiable_quote(text: str | None, *, max_chars: int = 200) -> str:
    """Build a quote that can be verified via substring checks against the source text.

    Do not normalize whitespace, as verification uses `quote in segment.text`.
    Prefer a single-line prefix (up to max_chars) to keep payloads/UI readable.
    """

    raw = (text or "").strip()
    if not raw:
        return ""

    candidate = raw[:max_chars]
    newline_indexes = [i for i in (candidate.find("\n"), candidate.find("\r")) if i != -1]
    if newline_indexes:
        candidate = candidate[: min(newline_indexes)].rstrip()
    return candidate


class Evidence(BaseModel):
    segment_id: UUID
    source_id: UUID | None = None
    agent_id: UUID | None = None
    memory_user_id: str = ""
    memory_timestamp: datetime | None = None
    memory_id: str | None = None
    memory_url: str | None = None
    source_title: str
    source_url: str
    text: str
    group_id: str = ""
    platform: str
    published_at: datetime | None = None
    video_url_with_timestamp: str | None = None
    emos_message_id: str | None = None

    def model_post_init(self, __context: object) -> None:
        if self.memory_id is None and self.memory_user_id and self.memory_timestamp is not None:
            self.memory_id = (
                f"{self.memory_user_id}_{self.memory_timestamp.strftime('%Y%m%dT%H%M%SZ')}"
            )
        if self.memory_url is None and self.memory_id:
            self.memory_url = f"https://www.bibliotalk.space/memories/{self.memory_id}"
        if (
            self.video_url_with_timestamp is None
            and self.published_at is not None
            and self.memory_timestamp is not None
            and self.source_url
        ):
            offset = max(0, int((self.memory_timestamp - self.published_at).total_seconds()))
            separator = "&" if "?" in self.source_url else "?"
            self.video_url_with_timestamp = f"{self.source_url}{separator}t={offset}s"


def build_inline_link(evidence: Evidence, *, max_chars: int = 120) -> str | None:
    if not evidence.memory_url:
        return None
    visible_text = _normalize_whitespace(evidence.text)[:max_chars].strip()
    if not visible_text:
        return None
    return f"[{visible_text}]({evidence.memory_url})"


class Citation(BaseModel):
    index: int = Field(ge=1)
    segment_id: UUID
    emos_message_id: str
    source_title: str
    source_url: str
    quote: str = Field(min_length=1)
    platform: str
    timestamp: datetime | None = None

    @classmethod
    def from_evidence(cls, evidence: Evidence, *, index: int, quote: str) -> Citation:
        return cls(
            index=index,
            segment_id=evidence.segment_id,
            emos_message_id=evidence.emos_message_id,
            source_title=evidence.source_title,
            source_url=evidence.source_url,
            quote=quote,
            platform=evidence.platform,
        )


class SegmentLike(BaseModel):
    id: UUID
    agent_id: UUID
    text: str


def validate_citations(
    citations: Iterable[Citation],
    segments: Sequence[SegmentLike],
    *,
    responding_agent_id: UUID,
) -> list[Citation]:
    """Keep only citations whose segment exists, belongs to agent, and contains quote."""

    segments_by_id = {segment.id: segment for segment in segments}
    valid: list[Citation] = []

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


_INLINE_LINK_RE = re.compile(r"\[([^\]]+)\]\((https://www\.bibliotalk\.space/memories/[^)]+)\)")
_QUOTED_TEXT_RE = re.compile(r'"([^"]+)"')


def validate_evidence_links(
    response_text: str,
    evidence_set: list[Evidence],
    *,
    agent_emos_user_id: str,
) -> str:
    evidence_by_url = {e.memory_url: e for e in evidence_set if e.memory_url}
    normalized_text_by_url = {
        url: _normalize_whitespace(evidence.text) for url, evidence in evidence_by_url.items()
    }

    def _replace(match: re.Match[str]) -> str:
        visible_text, url = match.group(1), match.group(2)
        evidence = evidence_by_url.get(url)
        if evidence is None:
            return visible_text
        if evidence.memory_user_id != agent_emos_user_id:
            return visible_text
        if visible_text in evidence.text:
            return match.group(0)
        if _normalize_whitespace(visible_text) not in normalized_text_by_url.get(url, ""):
            return visible_text
        return match.group(0)

    return _INLINE_LINK_RE.sub(_replace, response_text)


def extract_memory_links(response_text: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2)) for match in _INLINE_LINK_RE.finditer(response_text)]
