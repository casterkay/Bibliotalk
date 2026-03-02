"""Thin async wrappers for common Supabase data access patterns."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel


class ChatHistory(BaseModel):
    id: UUID | None = None
    matrix_room_id: str
    sender_agent_id: UUID | None = None
    sender_matrix_user_id: str
    matrix_event_id: str | None = None
    modality: str
    content: str
    citations: list[dict]
    created_at: str | None = None


class SupabaseHelpers:
    def __init__(self, client: Any):
        self.client = client

    async def get_agent(self, agent_id: UUID) -> dict[str, Any] | None:
        result = await self.client.table("agents").select("*").eq("id", str(agent_id)).limit(1).execute()
        return result.data[0] if result.data else None

    async def get_agent_by_matrix_id(self, matrix_user_id: str) -> dict[str, Any] | None:
        result = (
            await self.client.table("agents").select("*").eq("matrix_user_id", matrix_user_id).limit(1).execute()
        )
        return result.data[0] if result.data else None

    async def is_profile_room(self, matrix_room_id: str) -> bool:
        result = (
            await self.client.table("profile_rooms")
            .select("matrix_room_id")
            .eq("matrix_room_id", matrix_room_id)
            .limit(1)
            .execute()
        )
        return bool(result.data)

    async def get_agent_emos_config(self, agent_id: UUID) -> dict[str, Any] | None:
        result = (
            await self.client.table("agent_emos_config").select("*").eq("agent_id", str(agent_id)).limit(1).execute()
        )
        return result.data[0] if result.data else None

    async def get_segments_by_ids(self, segment_ids: list[UUID]) -> list[dict[str, Any]]:
        ids = [str(segment_id) for segment_id in segment_ids]
        result = await self.client.table("segments").select("*").in_("id", ids).execute()
        return result.data or []

    async def get_sources_by_emos_group_ids(self, emos_group_ids: list[str]) -> list[dict[str, Any]]:
        if not emos_group_ids:
            return []
        result = (
            await self.client.table("sources")
            .select("*")
            .in_("emos_group_id", emos_group_ids)
            .execute()
        )
        return result.data or []

    async def get_segments_by_source_ids(self, source_ids: list[str]) -> list[dict[str, Any]]:
        if not source_ids:
            return []
        result = (
            await self.client.table("segments")
            .select("*")
            .in_("source_id", source_ids)
            .execute()
        )
        return result.data or []

    async def get_segments_for_agent(self, agent_id: UUID) -> list[dict[str, Any]]:
        result = await self.client.table("segments").select("*").eq("agent_id", str(agent_id)).execute()
        return result.data or []

    async def save_chat_history(self, record: dict[str, Any]) -> dict[str, Any]:
        result = await self.client.table("chat_history").insert(record).execute()
        return result.data[0]
