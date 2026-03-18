from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_ingestion import Subscription
from bt_store.models_runtime import PlatformRoute
from discord_service.config import load_runtime_config
from discord_service.talks.agent_directory import AgentDirectory
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[4]
SEED_SCRIPT = ROOT / "services" / "discord_service" / "scripts" / "seed_agent.py"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("seed_agent_script", SEED_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load seed_agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_quickstart_seed_script_creates_runtime_rows(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    seed_module = _load_seed_module()

    await seed_module.seed_agent(
        db_path=str(db),
        agent_slug="alan-watts",
        kind="figure",
        display_name="Alan Watts",
        persona_summary="Agent bot used for quickstart validation.",
        subscription_url="https://www.youtube.com/@AlanWattsOrg",
        subscription_type="channel",
        guild_id="guild-1",
        channel_id="channel-1",
        poll_interval_minutes=30,
    )
    await seed_module.seed_agent(
        db_path=str(db),
        agent_slug="alan-watts",
        kind="figure",
        display_name="Alan Watts",
        persona_summary="Agent bot used for quickstart validation.",
        subscription_url="https://www.youtube.com/@AlanWattsOrg",
        subscription_type="channel",
        guild_id="guild-1",
        channel_id="channel-2",
        poll_interval_minutes=60,
    )

    session_factory = get_session_factory(db)
    async with session_factory() as session:
        agents = (await session.execute(select(Agent))).scalars().all()
        subscriptions = (await session.execute(select(Subscription))).scalars().all()
        routes = (
            (
                await session.execute(
                    select(PlatformRoute).where(
                        PlatformRoute.platform == "discord",
                        PlatformRoute.purpose == "feed",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(agents) == 1
    assert len(subscriptions) == 1
    assert len(routes) == 1
    assert subscriptions[0].poll_interval_minutes == 60
    assert routes[0].container_id == "channel-2"

    config = load_runtime_config(db_path=str(db))
    assert str(config.db_path) == str(db)

    directory = AgentDirectory(session_factory=session_factory)
    await directory.refresh()
    resolved = directory.resolve_token("alan-watts")
    assert resolved is not None
    assert resolved.display_name == "Alan Watts"
