"""SQLAlchemy-backed Store implementation.

Local development uses SQLite via aiosqlite (async engine). The same ORM models
can target Postgres in production by changing the connection string.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .sqlalchemy_models import Agent, AgentEmosConfig, Base, ChatHistory, ProfileRoom, Segment, Source


def _repo_root() -> Path:
    start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        if (candidate / "AGENTS.md").is_file():
            return candidate
    return start


def default_sqlite_url() -> str:
    db_dir = _repo_root() / ".agents_service"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "bibliotalk.sqlite"
    return f"sqlite+aiosqlite:///{db_path}"


@dataclass(frozen=True)
class SQLAlchemyStoreConfig:
    database_url: str
    create_all: bool = True


class SQLAlchemyStore:
    """Async SQLAlchemy Store implementation for agents_service."""

    def __init__(
        self,
        *,
        config: SQLAlchemyStoreConfig,
        engine: AsyncEngine | None = None,
        session_maker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._config = config
        self._engine = engine or create_async_engine(
            config.database_url,
            pool_pre_ping=True,
        )
        self._session_maker = session_maker or async_sessionmaker(
            bind=self._engine, expire_on_commit=False
        )
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def init(self) -> None:
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            if self._config.create_all:
                async with self._engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            self._initialized = True

    async def aclose(self) -> None:
        await self._engine.dispose()

    async def _one_or_none(self, stmt: Select[Any]) -> Any | None:
        async with self._session_maker() as session:
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def _all(self, stmt: Select[Any]) -> list[Any]:
        async with self._session_maker() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ---- Store interface (runtime paths) ----

    async def get_agent(self, agent_id: UUID) -> dict[str, Any] | None:
        row = await self._one_or_none(select(Agent).where(Agent.id == str(agent_id)))
        return _map_agent(row) if row else None

    async def get_agent_by_matrix_id(self, matrix_user_id: str) -> dict[str, Any] | None:
        row = await self._one_or_none(select(Agent).where(Agent.matrix_user_id == matrix_user_id))
        return _map_agent(row) if row else None

    async def get_agent_emos_config(self, agent_id: UUID) -> dict[str, Any] | None:
        row = await self._one_or_none(
            select(AgentEmosConfig).where(AgentEmosConfig.agent_id == str(agent_id))
        )
        if not row:
            return None
        return {
            "agent_id": str(agent_id),
            "emos_base_url": row.emos_base_url,
            "emos_api_key_encrypted": row.emos_api_key_encrypted,
            "emos_api_key": row.emos_api_key,
            "tenant_prefix": row.tenant_prefix,
        }

    async def is_profile_room(self, matrix_room_id: str) -> bool:
        row = await self._one_or_none(
            select(ProfileRoom).where(ProfileRoom.matrix_room_id == matrix_room_id)
        )
        return row is not None

    async def get_sources_by_emos_group_ids(self, emos_group_ids: list[str]) -> list[dict[str, Any]]:
        if not emos_group_ids:
            return []
        rows = await self._all(select(Source).where(Source.emos_group_id.in_(emos_group_ids)))
        return [_map_source(row) for row in rows]

    async def get_segments_by_source_ids(self, source_ids: list[str]) -> list[dict[str, Any]]:
        if not source_ids:
            return []
        rows = await self._all(
            select(Segment).where(Segment.source_id.in_(source_ids)).order_by(Segment.seq.asc())
        )
        return [_map_segment(row) for row in rows]

    async def get_segments_by_ids(self, segment_ids: list[UUID]) -> list[dict[str, Any]]:
        ids = [str(i) for i in segment_ids]
        if not ids:
            return []
        rows = await self._all(select(Segment).where(Segment.id.in_(ids)))
        return [_map_segment(row) for row in rows]

    async def get_segments_for_agent(self, agent_id: UUID) -> list[dict[str, Any]]:
        rows = await self._all(
            select(Segment).where(Segment.agent_id == str(agent_id)).order_by(Segment.seq.asc())
        )
        return [_map_segment(row) for row in rows]

    async def save_chat_history(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        payload.setdefault("id", str(uuid4()))
        citations = payload.get("citations")
        if citations is None:
            citations = []
        sender_agent_id = payload.get("sender_agent_id")
        if sender_agent_id is not None:
            sender_agent_id = str(sender_agent_id)

        row = ChatHistory(
            id=str(payload["id"]),
            matrix_room_id=str(payload["matrix_room_id"]),
            sender_agent_id=sender_agent_id,
            sender_matrix_user_id=str(payload["sender_matrix_user_id"]),
            matrix_event_id=(str(payload["matrix_event_id"]) if payload.get("matrix_event_id") else None),
            modality=str(payload["modality"]),
            content=str(payload["content"]),
            citations=list(citations),
        )
        async with self._session_maker() as session:
            session.add(row)
            await session.commit()
        return {
            "id": row.id,
            "matrix_room_id": row.matrix_room_id,
            "sender_agent_id": row.sender_agent_id,
            "sender_matrix_user_id": row.sender_matrix_user_id,
            "matrix_event_id": row.matrix_event_id,
            "modality": row.modality,
            "content": row.content,
            "citations": row.citations,
            "created_at": row.created_at.isoformat(),
        }

    # ---- Bootstrap helpers (write paths) ----

    async def upsert_agent(
        self,
        *,
        agent_uuid: UUID,
        kind: str,
        display_name: str,
        matrix_user_id: str,
        persona_prompt: str,
        llm_model: str,
        is_active: bool = True,
    ) -> dict[str, Any]:
        agent_id = str(agent_uuid)
        async with self._session_maker() as session:
            existing = await session.get(Agent, agent_id)
            if existing is None:
                existing = Agent(
                    id=agent_id,
                    kind=kind,
                    display_name=display_name,
                    matrix_user_id=matrix_user_id,
                    persona_prompt=persona_prompt,
                    llm_model=llm_model,
                    is_active=bool(is_active),
                )
                session.add(existing)
            else:
                existing.kind = kind
                existing.display_name = display_name
                existing.matrix_user_id = matrix_user_id
                existing.persona_prompt = persona_prompt
                existing.llm_model = llm_model
                existing.is_active = bool(is_active)
            await session.commit()
            return _map_agent(existing)

    async def upsert_agent_emos_config(
        self,
        *,
        agent_uuid: UUID,
        emos_base_url: str,
        tenant_prefix: str,
        emos_api_key: str | None = None,
    ) -> dict[str, Any]:
        agent_id = str(agent_uuid)
        async with self._session_maker() as session:
            existing = await session.get(AgentEmosConfig, agent_id)
            if existing is None:
                existing = AgentEmosConfig(
                    agent_id=agent_id,
                    emos_base_url=emos_base_url,
                    tenant_prefix=tenant_prefix,
                    emos_api_key=emos_api_key,
                )
                session.add(existing)
            else:
                existing.emos_base_url = emos_base_url
                existing.tenant_prefix = tenant_prefix
                existing.emos_api_key = emos_api_key
            await session.commit()
            return {
                "agent_id": existing.agent_id,
                "emos_base_url": existing.emos_base_url,
                "tenant_prefix": existing.tenant_prefix,
                "emos_api_key": existing.emos_api_key,
            }

    async def upsert_profile_room(self, *, agent_uuid: UUID, matrix_room_id: str) -> dict[str, Any]:
        agent_id = str(agent_uuid)
        async with self._session_maker() as session:
            existing = await session.get(ProfileRoom, agent_id)
            if existing is None:
                existing = ProfileRoom(agent_id=agent_id, matrix_room_id=matrix_room_id)
                session.add(existing)
            else:
                existing.matrix_room_id = matrix_room_id
            await session.commit()
            return {"agent_id": existing.agent_id, "matrix_room_id": existing.matrix_room_id}

    async def upsert_source(
        self,
        *,
        agent_uuid: UUID,
        emos_group_id: str,
        platform: str,
        external_id: str,
        external_url: str | None,
        title: str,
        author: str | None = None,
        published_at: str | None = None,
        raw_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with self._session_maker() as session:
            stmt = select(Source).where(Source.emos_group_id == emos_group_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is None:
                existing = Source(
                    id=str(uuid4()),
                    agent_id=str(agent_uuid),
                    emos_group_id=emos_group_id,
                    platform=platform,
                    external_id=external_id,
                    external_url=external_url,
                    title=title,
                    author=author,
                    published_at=published_at,
                    raw_meta=raw_meta or {},
                )
                session.add(existing)
            else:
                existing.agent_id = str(agent_uuid)
                existing.platform = platform
                existing.external_id = external_id
                existing.external_url = external_url
                existing.title = title
                existing.author = author
                existing.published_at = published_at
                existing.raw_meta = raw_meta or {}
            await session.commit()
            return _map_source(existing)

    async def upsert_segment(
        self,
        *,
        agent_uuid: UUID,
        source_uuid: UUID,
        emos_message_id: str,
        platform: str,
        seq: int,
        text: str,
        sha256: str,
        speaker: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        source_title: str | None = None,
        source_url: str | None = None,
        matrix_event_id: str | None = None,
    ) -> dict[str, Any]:
        async with self._session_maker() as session:
            stmt = select(Segment).where(Segment.emos_message_id == emos_message_id)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is None:
                existing = Segment(
                    id=str(uuid4()),
                    agent_id=str(agent_uuid),
                    source_id=str(source_uuid),
                    emos_message_id=emos_message_id,
                    platform=platform,
                    seq=int(seq),
                    text=text,
                    sha256=sha256,
                    speaker=speaker,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    source_title=source_title,
                    source_url=source_url,
                    matrix_event_id=matrix_event_id,
                )
                session.add(existing)
            else:
                existing.agent_id = str(agent_uuid)
                existing.source_id = str(source_uuid)
                existing.platform = platform
                existing.seq = int(seq)
                existing.text = text
                existing.sha256 = sha256
                existing.speaker = speaker
                existing.start_ms = start_ms
                existing.end_ms = end_ms
                existing.source_title = source_title
                existing.source_url = source_url
                existing.matrix_event_id = matrix_event_id
            await session.commit()
            return _map_segment(existing)

    async def list_agents(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        stmt = select(Agent)
        if active_only:
            stmt = stmt.where(Agent.is_active.is_(True))
        rows = await self._all(stmt)
        return [_map_agent(row) for row in rows]

    async def get_profile_room_for_agent(self, agent_uuid: UUID) -> dict[str, Any] | None:
        row = await self._one_or_none(
            select(ProfileRoom).where(ProfileRoom.agent_id == str(agent_uuid))
        )
        if not row:
            return None
        return {"agent_id": str(agent_uuid), "matrix_room_id": row.matrix_room_id}

    async def get_agent_by_tenant_prefix(self, tenant_prefix: str) -> dict[str, Any] | None:
        stmt = (
            select(Agent)
            .join(AgentEmosConfig, AgentEmosConfig.agent_id == Agent.id)
            .where(AgentEmosConfig.tenant_prefix == tenant_prefix)
            .limit(1)
        )
        row = await self._one_or_none(stmt)
        return _map_agent(row) if row else None


def _map_agent(row: Agent) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "display_name": row.display_name,
        "matrix_user_id": row.matrix_user_id,
        "persona_prompt": row.persona_prompt,
        "llm_model": row.llm_model,
        "is_active": row.is_active,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _map_source(row: Source) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "platform": row.platform,
        "external_id": row.external_id,
        "external_url": row.external_url,
        "title": row.title,
        "author": row.author,
        "published_at": row.published_at,
        "raw_meta": row.raw_meta,
        "emos_group_id": row.emos_group_id,
    }


def _map_segment(row: Segment) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "agent_id": row.agent_id,
        "platform": row.platform,
        "seq": row.seq,
        "text": row.text,
        "speaker": row.speaker,
        "start_ms": row.start_ms,
        "end_ms": row.end_ms,
        "sha256": row.sha256,
        "emos_message_id": row.emos_message_id,
        "source_title": row.source_title,
        "source_url": row.source_url,
        "matrix_event_id": row.matrix_event_id,
    }
