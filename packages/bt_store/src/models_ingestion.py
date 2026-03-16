from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models_base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "content_platform",
            "subscription_type",
            "subscription_url",
            name="uq_subscriptions_identity",
        ),
    )

    subscription_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[UUID] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    content_platform: Mapped[str] = mapped_column(String(64), index=True)
    subscription_type: Mapped[str] = mapped_column(String(32))
    subscription_url: Mapped[str] = mapped_column(Text)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class SubscriptionState(Base):
    __tablename__ = "subscription_state"

    subscription_id: Mapped[UUID] = mapped_column(
        ForeignKey("subscriptions.subscription_id"), primary_key=True
    )
    last_seen_external_id: Mapped[str | None] = mapped_column(String(255), default=None)
    last_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class SourceIngestionState(Base):
    __tablename__ = "source_ingestion_state"

    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.source_id"), primary_key=True)
    ingest_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    skip_reason: Mapped[str | None] = mapped_column(String(120), default=None)
    manual_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class SourceTextBatch(Base):
    __tablename__ = "source_text_batches"

    batch_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.source_id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="transcript", index=True)
    speaker_label: Mapped[str | None] = mapped_column(String(200), default=None)
    start_seq: Mapped[int] = mapped_column(Integer)
    end_seq: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    end_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    text: Mapped[str] = mapped_column(Text)
    batch_rule: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
