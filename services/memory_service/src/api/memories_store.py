from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bt_store.models_evidence import Segment, Source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class StoredSource:
    source_id: str  # EverMemOS group_id
    agent_slug: str
    platform: str
    external_id: str
    title: str
    url: str
    published_at: datetime | None
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StoredChunk:
    segment_id: Any
    seq: int
    timestamp: datetime
    text: str
    start_ms: int | None
    end_ms: int | None


class MemoriesStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def get_source_by_source_id(self, source_id: str) -> StoredSource | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(select(Source).where(Source.emos_group_id == source_id))
            ).scalar_one_or_none()
        if row is None:
            return None
        agent_slug = source_id.split(":", 1)[0] if ":" in source_id else ""
        return StoredSource(
            source_id=row.emos_group_id,
            agent_slug=agent_slug,
            platform=row.content_platform,
            external_id=row.external_id,
            title=row.title,
            url=row.external_url or "",
            published_at=row.published_at,
            raw=(row.raw_meta_json or {}),
        )

    async def list_chunks_for_source(self, source_id: str) -> list[StoredChunk]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(Segment)
                        .join(Source, Source.source_id == Segment.source_id)
                        .where(Source.emos_group_id == source_id, Segment.is_superseded.is_(False))
                        .order_by(Segment.seq)
                    )
                )
                .scalars()
                .all()
            )

        chunks: list[StoredChunk] = []
        for seg in rows:
            if seg.create_time is None:
                continue
            chunks.append(
                StoredChunk(
                    segment_id=seg.segment_id,
                    seq=seg.seq,
                    timestamp=_ensure_utc(seg.create_time),
                    text=seg.text,
                    start_ms=seg.start_ms,
                    end_ms=seg.end_ms,
                )
            )
        return chunks
