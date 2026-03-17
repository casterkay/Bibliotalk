from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bt_store.models_core import Agent
from bt_store.models_evidence import Segment, Source
from bt_store.models_ingestion import SubscriptionState
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.errors import IndexError


@dataclass(frozen=True, slots=True)
class SegmentIndexRecord:
    message_id: str
    sha256: str


class IngestionIndex:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], path: Path | None = None):
        self.session_factory = session_factory
        self.path = path

    async def get_source_meta_saved(self, *, user_id: str, group_id: str) -> bool:
        async with self.session_factory() as session:
            figure_id = await _get_figure_id(session, user_id)
            if figure_id is None:
                return False
            stmt = select(Source).where(
                Source.agent_id == figure_id, Source.emos_group_id == group_id
            )
            result = await session.execute(stmt)
            source = result.scalar_one_or_none()
            return source is not None and source.meta_synced_at is not None

    async def set_source_meta_saved(
        self, *, user_id: str, group_id: str, source_fingerprint: str | None = None
    ) -> None:
        del source_fingerprint
        async with self.session_factory() as session:
            figure_id = await _get_figure_id(session, user_id)
            if figure_id is None:
                return
            stmt = select(Source).where(
                Source.agent_id == figure_id, Source.emos_group_id == group_id
            )
            source = (await session.execute(stmt)).scalar_one_or_none()
            if source is not None:
                source.meta_synced_at = datetime.now(tz=UTC)
            await session.commit()

    async def get_segment(self, *, user_id: str, message_id: str) -> SegmentIndexRecord | None:
        async with self.session_factory() as session:
            figure_id = await _get_figure_id(session, user_id)
            if figure_id is None:
                return None
            stmt = (
                select(Segment.seq, Segment.sha256, Source.emos_group_id)
                .join(Source, Source.source_id == Segment.source_id)
                .where(Source.agent_id == figure_id, Segment.is_superseded.is_(False))
            )
            rows = (await session.execute(stmt)).all()
            for seq, sha256, emos_group_id in rows:
                if f"{emos_group_id}:seg:{seq}" == message_id:
                    return SegmentIndexRecord(message_id=message_id, sha256=sha256)
            return None

    async def upsert_segment_status(
        self,
        *,
        user_id: str,
        group_id: str,
        message_id: str,
        seq: int,
        sha256: str,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        del status, error_code, error_message
        async with self.session_factory() as session:
            figure_id = await _get_figure_id(session, user_id)
            if figure_id is None:
                return
            stmt = select(Source).where(
                Source.agent_id == figure_id, Source.emos_group_id == group_id
            )
            source = (await session.execute(stmt)).scalar_one_or_none()
            if source is None:
                return
            segment_stmt = select(Segment).where(
                Segment.source_id == source.source_id,
                Segment.seq == seq,
                Segment.is_superseded.is_(False),
            )
            segment = (await session.execute(segment_stmt)).scalar_one_or_none()
            if segment is None:
                segment = Segment(
                    source_id=source.source_id,
                    agent_id=figure_id,
                    seq=seq,
                    text="",
                    sha256=sha256,
                    emos_message_id=f"{group_id}:seg:{seq}",
                )
                session.add(segment)
            segment.sha256 = sha256
            await session.commit()


async def _get_figure_id(session: AsyncSession, emos_user_id: str):
    stmt = select(Agent.agent_id).where(Agent.slug == emos_user_id).limit(1)
    result = await session.execute(stmt)
    figure_id = result.scalar_one_or_none()
    if figure_id is not None:
        return figure_id

    stmt = select(SubscriptionState.subscription_id).limit(1)
    try:
        await session.execute(stmt)
    except Exception as exc:
        raise IndexError(f"Evidence store lookup failed for {emos_user_id}: {exc}") from exc
    return None
