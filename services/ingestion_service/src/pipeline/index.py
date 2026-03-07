from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bt_common.evidence_store.models import IngestState, Segment, Source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..domain.errors import IndexError


@dataclass(frozen=True, slots=True)
class SegmentIndexRecord:
    message_id: str
    sha256: str
    status: str


class IngestionIndex:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], path: Path | None = None):
        self.session_factory = session_factory
        self.path = path

    async def get_source_meta_saved(self, *, user_id: str, group_id: str) -> bool:
        async with self.session_factory() as session:
            figure_id = await _get_figure_id(session, user_id)
            if figure_id is None:
                return False
            stmt = select(Source.source_id).where(
                Source.figure_id == figure_id, Source.group_id == group_id
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    async def set_source_meta_saved(
        self, *, user_id: str, group_id: str, source_fingerprint: str | None = None
    ) -> None:
        del source_fingerprint
        async with self.session_factory() as session:
            figure_id = await _get_figure_id(session, user_id)
            if figure_id is None:
                return
            stmt = select(Source).where(Source.figure_id == figure_id, Source.group_id == group_id)
            source = (await session.execute(stmt)).scalar_one_or_none()
            if source is not None and source.transcript_status == "pending":
                source.transcript_status = "ingested"
            await session.commit()

    async def get_segment(self, *, user_id: str, message_id: str) -> SegmentIndexRecord | None:
        async with self.session_factory() as session:
            figure_id = await _get_figure_id(session, user_id)
            if figure_id is None:
                return None
            stmt = (
                select(Segment.seq, Segment.sha256, Source.group_id)
                .join(Source, Source.source_id == Segment.source_id)
                .where(Source.figure_id == figure_id)
            )
            rows = (await session.execute(stmt)).all()
            for seq, sha256, group_id in rows:
                if f"{group_id}:seg:{seq}" == message_id:
                    return SegmentIndexRecord(
                        message_id=message_id, sha256=sha256, status="ingested"
                    )
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
        del error_code, error_message
        async with self.session_factory() as session:
            figure_id = await _get_figure_id(session, user_id)
            if figure_id is None:
                return
            stmt = select(Source).where(Source.figure_id == figure_id, Source.group_id == group_id)
            source = (await session.execute(stmt)).scalar_one_or_none()
            if source is None:
                return
            segment_stmt = select(Segment).where(
                Segment.source_id == source.source_id, Segment.seq == seq
            )
            segment = (await session.execute(segment_stmt)).scalar_one_or_none()
            if segment is None:
                segment = Segment(source_id=source.source_id, seq=seq, text="", sha256=sha256)
                session.add(segment)
            segment.sha256 = sha256
            source.transcript_status = "failed" if status == "failed" else "ingested"
            await session.commit()


async def _get_figure_id(session: AsyncSession, emos_user_id: str):
    stmt = select(Source.figure_id).where(Source.group_id.like(f"{emos_user_id}:%")).limit(1)
    result = await session.execute(stmt)
    figure_id = result.scalar_one_or_none()
    if figure_id is not None:
        return figure_id

    stmt = select(IngestState.subscription_id).limit(1)
    try:
        await session.execute(stmt)
    except Exception as exc:
        raise IndexError(f"Evidence store lookup failed for {emos_user_id}: {exc}") from exc
    return None
