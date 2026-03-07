from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid


class Base(DeclarativeBase):
    pass


class Figure(Base):
    __tablename__ = "figures"

    figure_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    emos_user_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    persona_summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="figure", cascade="all, delete-orphan"
    )
    sources: Mapped[list[Source]] = relationship(
        back_populates="figure", cascade="all, delete-orphan"
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    figure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("figures.figure_id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False, default="youtube")
    subscription_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subscription_url: Mapped[str] = mapped_column(Text, nullable=False)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    figure: Mapped[Figure] = relationship(back_populates="subscriptions")
    ingest_state: Mapped[IngestState | None] = relationship(
        back_populates="subscription", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (Index("ix_subscriptions_figure_id", "figure_id"),)


class Source(Base):
    __tablename__ = "sources"

    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    figure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("figures.figure_id", ondelete="CASCADE"), nullable=False
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False, default="youtube")
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    group_id: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    channel_name: Mapped[str | None] = mapped_column(String(300))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_meta_json: Mapped[str | None] = mapped_column(Text)
    transcript_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    manual_ingestion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    figure: Mapped[Figure] = relationship(back_populates="sources")
    segments: Mapped[list[Segment]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    transcript_batches: Mapped[list[TranscriptBatch]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("figure_id", "platform", "external_id", name="uq_source_identity"),
        Index("ix_sources_figure_id", "figure_id"),
        Index("ix_sources_group_id", "group_id"),
    )


class Segment(Base):
    __tablename__ = "segments"

    segment_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.source_id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    create_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_superseded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source: Mapped[Source] = relationship(back_populates="segments")

    __table_args__ = (
        UniqueConstraint("source_id", "seq", "sha256", name="uq_segment_dedup"),
        Index("ix_segments_source_id", "source_id"),
    )


class TranscriptBatch(Base):
    __tablename__ = "transcript_batches"

    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.source_id", ondelete="CASCADE"), nullable=False
    )
    speaker_label: Mapped[str | None] = mapped_column(String(200))
    start_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    end_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    batch_rule: Mapped[str] = mapped_column(String(30), nullable=False)
    posted_to_discord: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source: Mapped[Source] = relationship(back_populates="transcript_batches")

    __table_args__ = (
        Index("ix_transcript_batches_source_id", "source_id"),
        Index("ix_transcript_batches_unposted", "source_id", "posted_to_discord"),
    )


class IngestState(Base):
    __tablename__ = "ingest_state"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subscriptions.subscription_id", ondelete="CASCADE"), primary_key=True
    )
    last_seen_video_id: Mapped[str | None] = mapped_column(String(200))
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    subscription: Mapped[Subscription] = relationship(back_populates="ingest_state")


class DiscordMap(Base):
    __tablename__ = "discord_map"

    figure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("figures.figure_id", ondelete="CASCADE"), primary_key=True
    )
    guild_id: Mapped[str] = mapped_column(String(30), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(30), nullable=False)
    bot_application_id: Mapped[str | None] = mapped_column(String(30))
    bot_user_id: Mapped[str | None] = mapped_column(String(30))


class DiscordPost(Base):
    __tablename__ = "discord_posts"

    post_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    figure_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("figures.figure_id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.source_id", ondelete="CASCADE"), nullable=False
    )
    parent_message_id: Mapped[str | None] = mapped_column(String(30))
    thread_id: Mapped[str | None] = mapped_column(String(30))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transcript_batches.batch_id", ondelete="SET NULL")
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    post_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    __table_args__ = (
        UniqueConstraint("source_id", "batch_id", name="uq_discord_post_dedup"),
        Index("ix_discord_posts_source_id", "source_id"),
        Index("ix_discord_posts_pending", "figure_id", "post_status"),
    )
