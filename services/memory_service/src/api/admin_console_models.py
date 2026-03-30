from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AgentSummary(BaseModel):
    agent_id: UUID
    slug: str
    display_name: str
    persona_summary: str | None = None
    kind: str
    is_active: bool
    created_at: datetime | None = None

    subscriptions: list[dict[str, Any]] = Field(default_factory=list)
    discord_feed_routes: list[dict[str, Any]] = Field(default_factory=list)
    discord_voice_routes: list[dict[str, Any]] = Field(default_factory=list)


class AgentCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=256)
    kind: str = Field(default="figure", min_length=1, max_length=32)
    persona_summary: str | None = None
    is_active: bool = True


class AgentPatchRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    persona_summary: str | None = None
    kind: str | None = Field(default=None, min_length=1, max_length=32)
    is_active: bool | None = None


class SubscriptionCreateRequest(BaseModel):
    content_platform: str = Field(default="youtube", min_length=1, max_length=64)
    subscription_type: str = Field(default="youtube.channel", min_length=1, max_length=32)
    subscription_url: str = Field(min_length=1)
    poll_interval_minutes: int = Field(default=60, ge=1, le=7 * 24 * 60)
    is_active: bool = True


class SubscriptionPatchRequest(BaseModel):
    subscription_url: str | None = Field(default=None, min_length=1)
    subscription_type: str | None = Field(default=None, min_length=1, max_length=32)
    poll_interval_minutes: int | None = Field(default=None, ge=1, le=7 * 24 * 60)
    is_active: bool | None = None


class DiscordFeedRouteUpsertRequest(BaseModel):
    guild_id: str = Field(min_length=1)
    channel_id: str = Field(min_length=1)


class DiscordVoiceRouteUpsertRequest(BaseModel):
    guild_id: str = Field(min_length=1)
    voice_channel_id: str = Field(min_length=1)
    text_channel_id: str | None = None
    text_thread_id: str | None = None
    updated_by_user_id: str = Field(default="console", min_length=1)


class EMOSGetMemoriesRequest(BaseModel):
    agent_id: UUID
    group_id: str | None = None
    memory_type: str = "episodic_memory"
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0, le=50_000)
