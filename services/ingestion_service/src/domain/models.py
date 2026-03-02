from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .ids import build_group_id, build_message_id


class Source(BaseModel):
    user_id: str
    platform: str
    external_id: str
    title: str
    canonical_url: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    raw_meta: dict[str, Any] | None = None

    group_id: str | None = None
    group_name: str | None = None

    @model_validator(mode="after")
    def _derive_ids(self) -> "Source":
        if not self.group_id:
            self.group_id = build_group_id(user_id=self.user_id, platform=self.platform, external_id=self.external_id)
        if not self.group_name:
            self.group_name = self.title
        return self


class TranscriptLine(BaseModel):
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    speaker: str | None = None


class Segment(BaseModel):
    seq: int
    text: str
    sha256: str
    message_id: str
    speaker: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    virtual_start_at: str | None = None
    virtual_end_at: str | None = None
    group_id: str | None = None
    group_name: str | None = None


class PlainTextContent(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class TranscriptContent(BaseModel):
    kind: Literal["transcript"] = "transcript"
    lines: list[TranscriptLine]


Content = PlainTextContent | TranscriptContent


class SourceContent(BaseModel):
    source: Source
    content: Content


class ReportError(BaseModel):
    code: str
    message: str


class SegmentResult(BaseModel):
    seq: int
    message_id: str
    sha256: str
    status: Literal["ingested", "skipped_unchanged", "failed"]
    start_ms: int | None = None
    end_ms: int | None = None
    virtual_start_at: str | None = None
    virtual_end_at: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    error: ReportError | None = None


class SourceResult(BaseModel):
    user_id: str
    platform: str
    external_id: str
    title: str
    canonical_url: str | None = None
    group_id: str
    status: Literal["done", "failed"]
    meta_saved: bool
    segments_total: int
    segments_ingested: int
    segments_skipped_unchanged: int
    segments_failed: int
    error: ReportError | None = None
    segments: list[SegmentResult] | None = None


class ReportSummary(BaseModel):
    sources_total: int
    sources_succeeded: int
    sources_failed: int
    segments_ingested: int
    segments_skipped_unchanged: int
    segments_failed: int


class IngestReport(BaseModel):
    version: Literal["1"] = "1"
    run_id: str
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["done", "failed"]
    summary: ReportSummary
    sources: list[SourceResult]


def build_segment(
    *,
    source: Source,
    seq: int,
    text: str,
    sha256: str,
    start_ms: int | None,
    end_ms: int | None,
    speaker: str | None,
    virtual_start_at: str | None = None,
    virtual_end_at: str | None = None,
    group_id: str | None = None,
    group_name: str | None = None,
) -> Segment:
    return Segment(
        seq=seq,
        text=text,
        sha256=sha256,
        message_id=build_message_id(user_id=source.user_id, platform=source.platform, external_id=source.external_id, seq=seq),
        start_ms=start_ms,
        end_ms=end_ms,
        speaker=speaker,
        virtual_start_at=virtual_start_at,
        virtual_end_at=virtual_end_at,
        group_id=group_id,
        group_name=group_name,
    )
