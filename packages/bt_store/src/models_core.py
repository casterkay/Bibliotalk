from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models_base import Base


class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), default="figure", index=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    persona_summary: Mapped[str | None] = mapped_column(String, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class AgentPlatformIdentity(Base):
    __tablename__ = "agent_platform_identities"
    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id"),
        UniqueConstraint("agent_id", "platform"),
    )

    identity_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[UUID] = mapped_column(index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    platform_user_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


RoomKind = Literal["archive", "dialogue"]


class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (UniqueConstraint("platform", "room_id"),)

    room_pk: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    room_id: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class RoomMember(Base):
    __tablename__ = "room_members"
    __table_args__ = (UniqueConstraint("room_pk", "platform_user_id"),)

    member_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    room_pk: Mapped[UUID] = mapped_column(ForeignKey("rooms.room_pk"), index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    platform_user_id: Mapped[str] = mapped_column(String(255))
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.agent_id"), index=True)
    member_kind: Mapped[str] = mapped_column(String(16), default="human", index=True)
    role: Mapped[str | None] = mapped_column(String(32), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
