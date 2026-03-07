from __future__ import annotations

import uuid

import pytest
from bt_common.evidence_store.engine import get_session, init_database
from bt_common.evidence_store.models import DiscordMap, Figure, Segment, Source, Subscription
from sqlalchemy import select


@pytest.mark.anyio
async def test_evidence_store_round_trip(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)

    async with get_session(db) as session:
        figure = Figure(
            figure_id=uuid.uuid4(), display_name="Alan Watts", emos_user_id="alan-watts"
        )
        session.add(figure)
        await session.flush()

        subscription = Subscription(
            figure_id=figure.figure_id,
            subscription_type="channel",
            subscription_url="https://www.youtube.com/@AlanWattsOrg",
        )
        source = Source(
            figure_id=figure.figure_id,
            external_id="video-123",
            group_id="alan-watts:youtube:video-123",
            title="Lecture",
            source_url="https://www.youtube.com/watch?v=video-123",
        )
        session.add_all(
            [
                subscription,
                source,
                DiscordMap(figure_id=figure.figure_id, guild_id="1", channel_id="2"),
            ]
        )
        await session.flush()

        session.add(Segment(source_id=source.source_id, seq=0, text="Hello world", sha256="abc"))
        await session.commit()

    async with get_session(db) as session:
        figures = (await session.execute(select(Figure))).scalars().all()
        segments = (await session.execute(select(Segment))).scalars().all()

    assert len(figures) == 1
    assert figures[0].emos_user_id == "alan-watts"
    assert len(segments) == 1
    assert segments[0].text == "Hello world"
