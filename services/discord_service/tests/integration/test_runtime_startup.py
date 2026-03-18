from __future__ import annotations

import uuid

import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_runtime import PlatformRoute
from discord_service.config import load_runtime_config
from discord_service.runtime import build_live_discord_runtime


@pytest.mark.anyio
async def test_discord_runtime_builds_single_bot_client(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)

    async with session_factory() as session:
        agent = Agent(
            agent_id=uuid.uuid4(),
            display_name="Alan Watts",
            slug="alan-watts",
            kind="figure",
            persona_summary=None,
            is_active=True,
        )
        session.add(agent)
        await session.flush()
        session.add(
            PlatformRoute(
                platform="discord",
                purpose="feed",
                agent_id=agent.agent_id,
                container_id="channel",
                config_json={"guild_id": "guild"},
            )
        )
        await session.commit()

    config = load_runtime_config(db_path=str(db))
    runtime = await build_live_discord_runtime(config, session_factory=session_factory)

    assert runtime.client is not None
    assert runtime.client.agent_directory.resolve_token("alan-watts") is not None
