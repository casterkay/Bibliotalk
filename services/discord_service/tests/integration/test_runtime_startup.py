from __future__ import annotations

import uuid

import pytest
from bt_common.evidence_store.engine import get_session_factory, init_database
from bt_common.evidence_store.models import DiscordMap, Figure
from discord_service.config import load_runtime_config
from discord_service.runtime import build_runtime_context


@pytest.mark.anyio
async def test_discord_runtime_context_loads_figure(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)

    async with session_factory() as session:
        figure = Figure(
            figure_id=uuid.uuid4(), display_name="Alan Watts", emos_user_id="alan-watts"
        )
        session.add(figure)
        await session.flush()
        session.add(
            DiscordMap(
                figure_id=figure.figure_id, guild_id="guild", channel_id="channel"
            )
        )
        await session.commit()

    config = load_runtime_config(db_path=str(db), figure_slug="alan-watts")
    context = await build_runtime_context(config, session_factory=session_factory)

    assert context.figure_found is True
    assert context.figure_slug == "alan-watts"
    assert context.channel_id == "channel"
