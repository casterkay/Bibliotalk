from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_ingestion import Subscription, SubscriptionState
from ingestion_service.runtime.config import load_runtime_config
from ingestion_service.runtime.poller import CollectorPoller
from ingestion_service.runtime.reporting import configure_logging


@pytest.mark.anyio
async def test_poller_handles_naive_retry_timestamps_without_crashing(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)

    async with session_factory() as session:
        agent_id = uuid.uuid4()
        subscription_id = uuid.uuid4()
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
        subscription = Subscription(
            subscription_id=subscription_id,
            agent_id=agent_id,
            content_platform="youtube",
            subscription_type="youtube.channel",
            subscription_url="https://www.youtube.com/@AlanWattsOrg",
            poll_interval_minutes=30,
            is_active=True,
        )
        session.add(subscription)
        # Simulate a SQLite-loaded naive timestamp (common when timezone=True columns roundtrip).
        session.add(
            SubscriptionState(
                subscription_id=subscription.subscription_id,
                next_retry_at=(datetime.now(tz=UTC) + timedelta(minutes=30)).replace(tzinfo=None),
            )
        )
        await session.commit()

    async def fake_discovery(*args, **kwargs):
        return []

    config = load_runtime_config(
        db_path=str(db),
        figure_slug="alan-watts",
        emos_base_url="https://emos.local",
    )

    async def _noop_sleep(_: float) -> None:
        return

    poller = CollectorPoller(
        config=config,
        session_factory=session_factory,
        logger=configure_logging(),
        client=object(),  # non-None to exercise subscription processing
        discovery_fn=fake_discovery,
        sleep=_noop_sleep,
    )

    snapshot = await poller.run_once()

    assert snapshot.failed_subscriptions == 0
