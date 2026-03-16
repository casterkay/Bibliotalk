from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models_base import Base


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("agent_id", "content_platform", "external_id"),)

    source_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[UUID] = mapped_column(index=True)
    subscription_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("subscriptions.subscription_id"), index=True, default=None
    )
    content_platform: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    external_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    title: Mapped[str] = mapped_column(String(1024))
    author: Mapped[str | None] = mapped_column(String(512), default=None)
    channel_name: Mapped[str | None] = mapped_column(String(512), default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    raw_meta_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    emos_group_id: Mapped[str] = mapped_column(String(255), index=True)
    meta_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (
        UniqueConstraint("source_id", "seq", "sha256"),
        Index("ix_segments_agent_source_seq", "agent_id", "source_id", "seq"),
    )

    segment_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.source_id"), index=True)
    agent_id: Mapped[UUID] = mapped_column(index=True)
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    speaker: Mapped[str | None] = mapped_column(String(255), default=None)
    start_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    end_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    emos_message_id: Mapped[str] = mapped_column(String(255), index=True)
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    is_superseded: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
