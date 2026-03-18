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
    agent_slug: str,
    external_id: str,
    title: str,
    source_url: str | None,
    platform: str = "youtube",
) -> None:
    await init_database(db_path)
    session_factory = get_session_factory(db_path)
    now = datetime.now(tz=UTC)

    async with session_factory() as session:
        agent = (
            (await session.execute(select(Agent).where(Agent.slug == agent_slug))).scalars().first()
        )
        if agent is None:
            raise LookupError(
                f"Agent '{agent_slug}' not found. Seed it first with `bibliotalk agent seed ...`."
            )

        source = (
            (
                await session.execute(
                    select(Source).where(
                        Source.agent_id == agent.agent_id,
                        Source.content_platform == platform,
                        Source.external_id == external_id,
                    )
                )
            )
            .scalars()
            .first()
        )

        if source is None:
            effective_source_url = source_url or (
                f"https://www.youtube.com/watch?v={external_id}" if platform == "youtube" else ""
            )
            source = Source(
                agent_id=agent.agent_id,
                content_platform=platform,
                external_id=external_id,
                emos_group_id=f"{agent.slug}:{platform}:{external_id}",
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
