from __future__ import annotations

import uuid

import pytest
from bt_common.evidence_store.engine import get_session_factory, init_database
from bt_common.evidence_store.models import Figure, Subscription
from ingestion_service.runtime.config import load_runtime_config
from ingestion_service.runtime.poller import CollectorPoller
from ingestion_service.runtime.reporting import configure_logging


@pytest.mark.anyio
async def test_collector_runtime_startup(tmp_path) -> None:
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
            Subscription(
                figure_id=figure.figure_id,
                subscription_type="channel",
                subscription_url="https://www.youtube.com/@AlanWattsOrg",
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
