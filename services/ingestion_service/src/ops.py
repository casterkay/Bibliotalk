from __future__ import annotations

from datetime import UTC, datetime

from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_evidence import Source
from bt_store.models_ingestion import SourceIngestionState
from sqlalchemy import select


async def request_manual_ingest(
    *,
    db_path: str | None,
    figure_slug: str,
    video_id: str,
    title: str,
    source_url: str | None,
) -> None:
    await init_database(db_path)
    session_factory = get_session_factory(db_path)
    now = datetime.now(tz=UTC)

    async with session_factory() as session:
        figure = (
            (await session.execute(select(Agent).where(Agent.slug == figure_slug)))
            .scalars()
            .first()
        )
        if figure is None:
            raise LookupError(
                f"Figure '{figure_slug}' not found. Seed it first with `bibliotalk figure seed ...`."
            )

        source = (
            (
                await session.execute(
                    select(Source).where(
                        Source.agent_id == figure.agent_id,
                        Source.content_platform == "youtube",
                        Source.external_id == video_id,
                    )
                )
            )
            .scalars()
            .first()
        )

        if source is None:
            effective_source_url = source_url or f"https://www.youtube.com/watch?v={video_id}"
            source = Source(
                agent_id=figure.agent_id,
                content_platform="youtube",
                external_id=video_id,
                emos_group_id=f"{figure.slug}:youtube:{video_id}",
                title=title,
                external_url=effective_source_url,
            )
            session.add(source)
        else:
            if source_url:
                source.external_url = source_url
            if title and source.title.startswith("("):
                source.title = title

        await session.flush()
        state = await session.get(SourceIngestionState, source.source_id)
        if state is None:
            state = SourceIngestionState(source_id=source.source_id)
            session.add(state)
        state.manual_requested_at = now
        state.ingest_status = "pending"

        await session.commit()
