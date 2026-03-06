"""SQLAlchemy ORM models for agents_service.

The logical schema is defined in BLUEPRINT.md. This module implements the
SQLite/Postgres-compatible subset of that schema using SQLAlchemy ORM.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_str() -> str:
    return str(uuid4())


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    matrix_user_id: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    persona_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    llm_model: Mapped[str] = mapped_column(String(128), nullable=False, default="gemini-2.5-flash")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    emos_config: Mapped["AgentEmosConfig | None"] = relationship(
        back_populates="agent", uselist=False, cascade="all, delete-orphan"
    )


class AgentEmosConfig(Base):
    __tablename__ = "agent_emos_config"
    __table_args__ = (UniqueConstraint("tenant_prefix", name="uq_agent_emos_config_tenant_prefix"),)

    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    emos_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    emos_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    emos_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_prefix: Mapped[str] = mapped_column(String(256), nullable=False)

    agent: Mapped[Agent] = relationship(back_populates="emos_config")


class ProfileRoom(Base):
    __tablename__ = "profile_rooms"

    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    matrix_room_id: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("emos_group_id", name="uq_sources_emos_group_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    external_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    emos_group_id: Mapped[str] = mapped_column(String(256), nullable=False)


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (UniqueConstraint("emos_message_id", name="uq_segments_emos_message_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    emos_message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    matrix_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    matrix_room_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    sender_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    sender_matrix_user_id: Mapped[str] = mapped_column(String(256), nullable=False)
    matrix_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    modality: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

