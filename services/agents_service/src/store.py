"""Store protocol for figure-agent retrieval dependencies."""

from __future__ import annotations

from typing import Protocol, TypedDict
from uuid import UUID

from bt_common.config import get_emos_fallback_settings
from bt_common.evidence_store.models import Figure, Segment, Source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker


class AgentRow(TypedDict, total=False):
    id: str
    kind: str
    display_name: str
    persona_prompt: str
    emos_user_id: str
    llm_model: str
    is_active: bool
    created_at: str | None


class AgentEmosConfigRow(TypedDict, total=False):
    agent_id: str
    emos_base_url: str
    emos_api_key_encrypted: str | None
    emos_api_key: str | None
    tenant_prefix: str


class SourceRow(TypedDict, total=False):
    id: str
    agent_id: str
    platform: str
    external_id: str
    external_url: str | None
    title: str
    author: str | None
    published_at: str | None
    emos_group_id: str


class SegmentRow(TypedDict, total=False):
    id: str
    agent_id: str
    source_id: str
    platform: str
    seq: int
    text: str
    sha256: str
    emos_message_id: str
    source_title: str | None
    source_url: str | None
    speaker: str | None
    start_ms: int | None
    end_ms: int | None


class Store(Protocol):
    async def aclose(self) -> None: ...

    async def get_agent(self, agent_id: UUID) -> AgentRow | None: ...
    async def get_agent_emos_config(self, agent_id: UUID) -> AgentEmosConfigRow | None: ...

    async def get_sources_by_emos_group_ids(self, emos_group_ids: list[str]) -> list[SourceRow]: ...
    async def get_segments_by_source_ids(self, source_ids: list[str]) -> list[SegmentRow]: ...
    async def get_segments_by_ids(self, segment_ids: list[UUID]) -> list[SegmentRow]: ...
    async def get_segments_for_agent(self, agent_id: UUID) -> list[SegmentRow]: ...


class SQLiteFigureStore:
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def aclose(self) -> None:
        return None

    async def get_agent(self, agent_id: UUID) -> AgentRow | None:
        async with self._session_factory() as session:
            figure = await session.get(Figure, agent_id)
        if figure is None:
            return None
        persona_summary = (figure.persona_summary or "").strip()
        persona_prompt = f"You are {figure.display_name}."
        if persona_summary:
            persona_prompt = f"{persona_prompt} {persona_summary}"
        return {
            "id": str(figure.figure_id),
            "kind": "figure",
            "display_name": figure.display_name,
            "persona_prompt": persona_prompt,
            "emos_user_id": figure.emos_user_id,
            "llm_model": "gemini-2.5-flash",
            "is_active": figure.status == "active",
        }

    async def get_agent_emos_config(self, agent_id: UUID) -> AgentEmosConfigRow | None:
        agent = await self.get_agent(agent_id)
        if agent is None:
            return None
        fallback = get_emos_fallback_settings()
        return {
            "agent_id": str(agent_id),
            "tenant_prefix": agent["emos_user_id"],
            "emos_base_url": fallback.EMOS_BASE_URL or "",
            "emos_api_key": fallback.EMOS_API_KEY,
        }

    async def get_sources_by_emos_group_ids(self, emos_group_ids: list[str]) -> list[SourceRow]:
        if not emos_group_ids:
            return []
        async with self._session_factory() as session:
            rows = (
                (await session.execute(select(Source).where(Source.group_id.in_(emos_group_ids))))
                .scalars()
                .all()
            )
        return [
            {
                "id": str(row.source_id),
                "agent_id": str(row.figure_id),
                "platform": row.platform,
                "external_id": row.external_id,
                "external_url": row.source_url,
                "title": row.title,
                "author": row.channel_name,
                "published_at": row.published_at.isoformat() if row.published_at else None,
                "emos_group_id": row.group_id,
                "memory_user_id": self._extract_memory_user_id(row.group_id),
            }
            for row in rows
        ]

    async def get_segments_by_source_ids(self, source_ids: list[str]) -> list[SegmentRow]:
        if not source_ids:
            return []
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Segment, Source)
                    .join(Source, Source.source_id == Segment.source_id)
                    .where(Segment.source_id.in_(source_ids))
                    .order_by(Segment.seq)
                )
            ).all()
        return [self._serialize_segment(segment, source) for segment, source in rows]

    async def get_segments_by_ids(self, segment_ids: list[UUID]) -> list[SegmentRow]:
        if not segment_ids:
            return []
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Segment, Source)
                    .join(Source, Source.source_id == Segment.source_id)
                    .where(Segment.segment_id.in_(segment_ids))
                )
            ).all()
        return [self._serialize_segment(segment, source) for segment, source in rows]

    async def get_segments_for_agent(self, agent_id: UUID) -> list[SegmentRow]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Segment, Source)
                    .join(Source, Source.source_id == Segment.source_id)
                    .where(Source.figure_id == agent_id)
                    .order_by(Source.published_at, Segment.seq)
                )
            ).all()
        return [self._serialize_segment(segment, source) for segment, source in rows]

    def _serialize_segment(self, segment: Segment, source: Source) -> SegmentRow:
        return {
            "id": str(segment.segment_id),
            "agent_id": str(source.figure_id),
            "figure_id": str(source.figure_id),
            "source_id": str(segment.source_id),
            "platform": source.platform,
            "seq": segment.seq,
            "text": segment.text,
            "sha256": segment.sha256,
            "emos_message_id": f"{self._extract_memory_user_id(source.group_id)}:youtube:{source.external_id}:seg:{segment.seq}",
            "source_title": source.title,
            "source_url": source.source_url,
            "speaker": None,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
            "create_time": segment.create_time.isoformat() if segment.create_time else None,
            "group_id": source.group_id,
            "published_at": source.published_at.isoformat() if source.published_at else None,
            "memory_user_id": self._extract_memory_user_id(source.group_id),
        }

    def _extract_memory_user_id(self, group_id: str) -> str:
        return group_id.split(":", 1)[0] if ":" in group_id else group_id
