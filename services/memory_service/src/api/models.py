from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ApiSource(BaseModel):
    source_id: str = Field(description="EverMemOS group_id `{agent_slug}:{platform}:{external_id}`")
    agent_slug: str
    platform: str
    external_id: str
    title: str
    url: str = ""
    published_at: datetime | None = None


class ApiChunk(BaseModel):
    segment_id: UUID
    seq: int
    timestamp: datetime
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


class ApiLinks(BaseModel):
    html: str
    video_at_timepoint: str | None = None


class ApiMemCellRecord(BaseModel):
    id: str
    agent_slug: str
    source_id: str
    timestamp: datetime
    memcell: dict[str, Any]
    source: ApiSource
    chunks: list[ApiChunk]
    links: ApiLinks


class IngestRequest(BaseModel):
    agent_slug: str
    url: str
    title: str | None = None


class IngestBatchRequest(BaseModel):
    agent_slug: str
    url: str | None = None
    urls: list[str] | None = None
    max_items: int | None = Field(default=None, ge=1, le=500)


class SubscribeRequest(BaseModel):
    agent_slug: str
    subscription_url: str
    content_platform: str = "youtube"
    subscription_type: str = "rss"
    poll_interval_minutes: int = Field(default=60, ge=1, le=7 * 24 * 60)


class EnqueueSummary(BaseModel):
    enqueued_sources: int
    enqueued_source_ids: list[str]
    skipped_sources: int
    errors: list[str] = []


class SearchResponse(BaseModel):
    results: list[ApiMemCellRecord]
    retrieve_method: Literal["keyword", "vector", "hybrid", "rrf", "agentic"] = "rrf"
