from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from bt_common.evidence_store.engine import get_session_factory, init_database
from bt_common.evidence_store.models import Figure, IngestState, Subscription
from ingestion_service.runtime.config import load_runtime_config
from ingestion_service.runtime.poller import CollectorPoller
from ingestion_service.runtime.reporting import configure_logging


@pytest.mark.anyio
async def test_poller_handles_naive_retry_timestamps_without_crashing(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)

    async with session_factory() as session:
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
        session.add(subscription)
        await session.flush()
        # Simulate a SQLite-loaded naive timestamp (common when timezone=True columns roundtrip).
        session.add(
            IngestState(
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
