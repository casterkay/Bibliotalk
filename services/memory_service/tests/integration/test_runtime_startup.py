from __future__ import annotations

import uuid

import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_ingestion import Subscription
from memory_service.runtime.config import load_runtime_config
from memory_service.runtime.poller import CollectorPoller
from memory_service.runtime.reporting import configure_logging


@pytest.mark.anyio
async def test_collector_runtime_startup(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)

    async with session_factory() as session:
        agent_id = uuid.uuid4()
        session.add(
            Agent(
                agent_id=agent_id,
                kind="figure",
                slug="alan-watts",
                display_name="Alan Watts",
                persona_summary=None,
                is_active=True,
            )
        )
        session.add(
            Subscription(
                subscription_id=uuid.uuid4(),
                agent_id=agent_id,
                content_platform="youtube",
                subscription_type="youtube.channel",
                subscription_url="https://www.youtube.com/@AlanWattsOrg",
                poll_interval_minutes=30,
                is_active=True,
            )
        )
        await session.commit()

    config = load_runtime_config(
        db_path=str(db), figure_slug="alan-watts", emos_base_url="https://emos.local"
    )
    poller = CollectorPoller(
        config=config, session_factory=session_factory, logger=configure_logging()
    )
    snapshot = await poller.run_once()

    assert snapshot.figure_slug == "alan-watts"
    assert snapshot.active_subscriptions == 1
    assert snapshot.failed_subscriptions == 0
