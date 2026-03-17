from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from .ids import build_youtube_group_id, build_youtube_message_id


class Source(BaseModel):
    user_id: str
    platform: Literal["youtube"] = "youtube"
    external_id: str
    title: str
    source_url: str
    channel_name: str | None = None
    published_at: datetime | None = None
    raw_meta: dict[str, Any] | None = None

    group_id: str | None = None

    @model_validator(mode="after")
    def _derive_ids(self) -> Source:
        if not self.group_id:
            self.group_id = build_youtube_group_id(user_id=self.user_id, video_id=self.external_id)
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
    create_time: datetime | None = None
    group_id: str | None = None


class TranscriptContent(BaseModel):
    kind: Literal["transcript"] = "transcript"
    lines: list[TranscriptLine]


class SourceContent(BaseModel):
    source: Source
    content: TranscriptContent


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
    create_time: datetime | None = None
    group_id: str | None = None
    error: ReportError | None = None


class SourceResult(BaseModel):
    user_id: str
    platform: Literal["youtube"] = "youtube"
    external_id: str
    title: str
    source_url: str
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
    group_id: str | None = None,
) -> Segment:
    create_time = None
    if source.published_at is not None and start_ms is not None:
        published_at = source.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        else:
            published_at = published_at.astimezone(UTC)
        create_time = published_at + timedelta(milliseconds=max(0, start_ms))

    return Segment(
        seq=seq,
        text=text,
        sha256=sha256,
        message_id=build_youtube_message_id(
            user_id=source.user_id, video_id=source.external_id, seq=seq
        ),
        start_ms=start_ms,
        end_ms=end_ms,
        speaker=speaker,
        create_time=create_time,
        group_id=group_id,
    )
