from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_evidence import Segment as StoredSegment
from bt_store.models_evidence import Source as StoredSource
from bt_store.models_ingestion import (
    SourceIngestionState,
    SourceTextBatch,
    Subscription,
    SubscriptionState,
)
from ingestion_service.domain.errors import AccessRestrictedError, RetryLaterError
from ingestion_service.domain.models import Source, SourceContent, TranscriptContent, TranscriptLine
from ingestion_service.pipeline.discovery import DiscoveredVideo
from ingestion_service.pipeline.index import IngestionIndex
from ingestion_service.pipeline.ingest import ingest_source, manual_reingest_source
from ingestion_service.runtime.config import load_runtime_config
from ingestion_service.runtime.poller import CollectorPoller
from ingestion_service.runtime.reporting import configure_logging
from sqlalchemy import func, select


class StubEverMemOS:
    def __init__(self) -> None:
        self.memorize_calls: list[dict] = []
        self.meta_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self.memorize_results: list[object] = []

    async def memorize(self, payload: dict) -> dict:
        self.memorize_calls.append(payload)
        if self.memorize_results:
            value = self.memorize_results.pop(0)
            if isinstance(value, Exception):
                raise value
        return {"ok": True}

    async def save_conversation_meta(self, *, group_id: str, source_meta: dict) -> dict:
        self.meta_calls.append({"group_id": group_id, "source_meta": source_meta})
        return {"ok": True}

    async def delete_by_group_id(self, group_id: str, *, user_id: str | None = None) -> dict:
        self.delete_calls.append({"group_id": group_id, "user_id": user_id})
        return {"ok": True}


def _build_source_content(*, text_a: str = "One.", text_b: str = "Two.") -> SourceContent:
    source = Source(
        user_id="alan-watts",
        external_id="abc123",
        title="Alan Watts Lecture",
        source_url="https://www.youtube.com/watch?v=abc123",
        channel_name="Alan Watts Org",
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
        raw_meta={"timestamp": 1704067200},
    )
    return SourceContent(
        source=source,
        content=TranscriptContent(
            lines=[
                TranscriptLine(text=text_a, start_ms=0, end_ms=900),
                TranscriptLine(text=text_b, start_ms=1200, end_ms=2200),
            ]
        ),
    )


async def _noop_sleep(_: float) -> None:
    return


@pytest.mark.anyio
async def test_ingest_persists_sources_segments_and_batches_without_duplicates(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    index = IngestionIndex(session_factory, path=db)
    client = StubEverMemOS()

    async with session_factory() as session:
        session.add(
            Agent(
                agent_id=uuid.uuid4(),
                kind="figure",
                slug="alan-watts",
                display_name="Alan Watts",
                persona_summary=None,
                is_active=True,
            )
        )
        await session.commit()

    first = await ingest_source(
        source_content=_build_source_content(),
        index=index,
        client=client,
    )
    second = await ingest_source(
        source_content=_build_source_content(),
        index=index,
        client=client,
    )

    assert first.status == "done"
    assert second.segments_skipped_unchanged == 2
    assert len(client.meta_calls) == 1
    assert len(client.memorize_calls) == 2

    async with session_factory() as session:
        stored_source = (await session.execute(select(StoredSource))).scalar_one()
        state = await session.get(SourceIngestionState, stored_source.source_id)
        segment_count = await session.scalar(select(func.count()).select_from(StoredSegment))
        batch_count = await session.scalar(select(func.count()).select_from(SourceTextBatch))
        max_batch_len = await session.scalar(
            select(func.max(func.length(SourceTextBatch.text))).select_from(SourceTextBatch)
        )

    assert stored_source.emos_group_id == "alan-watts:youtube:abc123"
    assert state is not None
    assert state.ingest_status == "ingested"
    assert stored_source.meta_synced_at is not None
    assert segment_count == 2
    assert batch_count >= 1
    assert (max_batch_len or 0) <= 1_800


@pytest.mark.anyio
async def test_manual_reingest_deletes_remote_memories_and_supersedes_old_segments(
    tmp_path,
) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    index = IngestionIndex(session_factory, path=db)
    client = StubEverMemOS()

    async with session_factory() as session:
        session.add(
            Agent(
                agent_id=uuid.uuid4(),
                kind="figure",
                slug="alan-watts",
                display_name="Alan Watts",
                persona_summary=None,
                is_active=True,
            )
        )
        await session.commit()

    await ingest_source(source_content=_build_source_content(), index=index, client=client)
    client.memorize_calls.clear()

    result = await manual_reingest_source(
        source_content=_build_source_content(text_a="One revised.", text_b="Two revised."),
        index=index,
        client=client,
    )

    assert result.status == "done"
    assert client.delete_calls == [
        {"group_id": "alan-watts:youtube:abc123", "user_id": "alan-watts"}
    ]
    assert len(client.memorize_calls) == 2

    async with session_factory() as session:
        stored_source = (await session.execute(select(StoredSource))).scalar_one()
        state = await session.get(SourceIngestionState, stored_source.source_id)
        segments = (
            (await session.execute(select(StoredSegment).order_by(StoredSegment.seq)))
            .scalars()
            .all()
        )
        batch_count = await session.scalar(select(func.count()).select_from(SourceTextBatch))

    assert state is not None
    assert state.ingest_status == "ingested"
    assert len(segments) == 2
    assert all("revised" in segment.text for segment in segments)
    assert batch_count >= 1


@pytest.mark.anyio
async def test_manual_reingest_same_content_succeeds_without_unique_constraint_conflict(
    tmp_path,
) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    index = IngestionIndex(session_factory, path=db)
    client = StubEverMemOS()

    async with session_factory() as session:
        session.add(
            Agent(
                agent_id=uuid.uuid4(),
                kind="figure",
                slug="alan-watts",
                display_name="Alan Watts",
                persona_summary=None,
                is_active=True,
            )
        )
        await session.commit()

    await ingest_source(source_content=_build_source_content(), index=index, client=client)
    client.memorize_calls.clear()

    result = await manual_reingest_source(
        source_content=_build_source_content(),
        index=index,
        client=client,
    )

    assert result.status == "done"
    assert len(client.memorize_calls) == 2

    async with session_factory() as session:
        segment_count = await session.scalar(select(func.count()).select_from(StoredSegment))

    assert segment_count == 2


@pytest.mark.anyio
async def test_segment_failure_marks_whole_transcript_failed_and_cleans_up(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    index = IngestionIndex(session_factory, path=db)
    client = StubEverMemOS()
    client.memorize_results = [{"ok": True}, RuntimeError("emos down")]

    async with session_factory() as session:
        session.add(
            Agent(
                agent_id=uuid.uuid4(),
                kind="figure",
                slug="alan-watts",
                display_name="Alan Watts",
                persona_summary=None,
                is_active=True,
            )
        )
        await session.commit()

    result = await ingest_source(
        source_content=_build_source_content(),
        index=index,
        client=client,
    )

    assert result.status == "failed"
    assert result.segments_ingested == 1
    assert result.segments_failed == 1
    assert client.delete_calls == [
        {"group_id": "alan-watts:youtube:abc123", "user_id": "alan-watts"}
    ]

    async with session_factory() as session:
        stored_source = (await session.execute(select(StoredSource))).scalar_one()
        state = await session.get(SourceIngestionState, stored_source.source_id)
        segment_count = await session.scalar(select(func.count()).select_from(StoredSegment))
        batch_count = await session.scalar(select(func.count()).select_from(SourceTextBatch))

    assert state is not None
    assert state.ingest_status == "failed"
    assert segment_count == 0
    assert batch_count == 0


@pytest.mark.anyio
async def test_collector_poll_once_ingests_new_video_and_skips_it_on_next_cycle(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    client = StubEverMemOS()

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

    async def fake_discovery(
        _: str,
        *,
        last_seen_video_id: str | None = None,
        last_published_at: datetime | None = None,
        bootstrap: bool = False,
    ) -> list[DiscoveredVideo]:
        del last_published_at, bootstrap
        if last_seen_video_id:
            return []
        return [
            DiscoveredVideo(
                video_id="abc123",
                title="Alan Watts Lecture",
                source_url="https://www.youtube.com/watch?v=abc123",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
                channel_name="Alan Watts Org",
                raw_meta={"timestamp": 1704067200},
            )
        ]

    async def fake_loader(**kwargs) -> SourceContent:
        del kwargs
        return _build_source_content()

    config = load_runtime_config(
        db_path=str(db),
        figure_slug="alan-watts",
        emos_base_url="https://emos.local",
        index_path=str(tmp_path / "index.sqlite3"),
    )
    poller = CollectorPoller(
        config=config,
        session_factory=session_factory,
        logger=configure_logging(),
        client=client,
        discovery_fn=fake_discovery,
        transcript_loader=fake_loader,
        sleep=_noop_sleep,
    )

    first = await poller.run_once()
    second = await poller.run_once()

    assert first.discovered_videos == 1
    assert first.ingested_videos == 1
    assert second.discovered_videos == 0
    assert second.ingested_videos == 0
    assert len(client.memorize_calls) == 2

    async with session_factory() as session:
        source_count = await session.scalar(select(func.count()).select_from(StoredSource))
        segment_count = await session.scalar(select(func.count()).select_from(StoredSegment))
        batch_count = await session.scalar(select(func.count()).select_from(SourceTextBatch))

    assert source_count == 1
    assert segment_count == 2
    assert batch_count >= 1


@pytest.mark.anyio
async def test_collector_does_not_advance_cursor_when_ingest_fails(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    client = StubEverMemOS()
    client.memorize_results = [RuntimeError("emos down")]

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
        await session.commit()

    async def fake_discovery(
        _: str,
        *,
        last_seen_video_id: str | None = None,
        last_published_at: datetime | None = None,
        bootstrap: bool = False,
    ) -> list[DiscoveredVideo]:
        del last_seen_video_id, last_published_at, bootstrap
        return [
            DiscoveredVideo(
                video_id="vid1",
                title="Broken Lecture",
                source_url="https://www.youtube.com/watch?v=vid1",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
                channel_name="Alan Watts Org",
                raw_meta={"timestamp": 1704067200},
            )
        ]

    async def fake_loader(**kwargs) -> SourceContent:
        del kwargs
        return SourceContent(
            source=Source(
                user_id="alan-watts",
                external_id="vid1",
                title="Broken Lecture",
                source_url="https://www.youtube.com/watch?v=vid1",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
            ),
            content=TranscriptContent(lines=[TranscriptLine(text="One.", start_ms=0, end_ms=900)]),
        )

    config = load_runtime_config(
        db_path=str(db),
        figure_slug="alan-watts",
        emos_base_url="https://emos.local",
        index_path=str(tmp_path / "index.sqlite3"),
    )
    poller = CollectorPoller(
        config=config,
        session_factory=session_factory,
        logger=configure_logging(),
        client=client,
        discovery_fn=fake_discovery,
        transcript_loader=fake_loader,
        sleep=_noop_sleep,
    )

    snapshot = await poller.run_once()

    assert snapshot.failed_subscriptions == 0
    assert snapshot.ingested_videos == 0

    async with session_factory() as session:
        sub_state = await session.get(SubscriptionState, subscription_id)
        stored = (
            (await session.execute(select(StoredSource).where(StoredSource.external_id == "vid1")))
            .scalars()
            .one()
        )
        src_state = await session.get(SourceIngestionState, stored.source_id)

    assert sub_state is not None
    assert sub_state.last_seen_external_id == "vid1"
    assert sub_state.failure_count == 0
    assert sub_state.next_retry_at is None

    assert src_state is not None
    assert src_state.ingest_status == "pending"
    assert src_state.failure_count == 1
    assert src_state.next_retry_at is not None


@pytest.mark.anyio
async def test_collector_skips_members_only_videos(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    client = StubEverMemOS()

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
        await session.commit()

    async def fake_discovery(*_args, **_kwargs) -> list[DiscoveredVideo]:
        return [
            DiscoveredVideo(
                video_id="members1",
                title="Members Only",
                source_url="https://www.youtube.com/watch?v=members1",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
                channel_name="Alan Watts Org",
                raw_meta={"timestamp": 1704067200},
            )
        ]

    async def fake_loader(**_kwargs) -> SourceContent:
        raise AccessRestrictedError("members-only")

    config = load_runtime_config(
        db_path=str(db),
        figure_slug="alan-watts",
        emos_base_url="https://emos.local",
        index_path=str(tmp_path / "index.sqlite3"),
    )
    poller = CollectorPoller(
        config=config,
        session_factory=session_factory,
        logger=configure_logging(),
        client=client,
        discovery_fn=fake_discovery,
        transcript_loader=fake_loader,
        sleep=_noop_sleep,
    )

    snapshot = await poller.run_once()

    assert snapshot.failed_subscriptions == 0
    assert snapshot.discovered_videos == 1
    assert snapshot.ingested_videos == 0

    async with session_factory() as session:
        sub_state = await session.get(SubscriptionState, subscription_id)
        stored = (
            (
                await session.execute(
                    select(StoredSource).where(StoredSource.external_id == "members1")
                )
            )
            .scalars()
            .one()
        )
        src_state = await session.get(SourceIngestionState, stored.source_id)

    assert sub_state is not None
    assert sub_state.last_seen_external_id == "members1"
    assert src_state is not None
    assert src_state.ingest_status == "skipped"
    assert src_state.skip_reason == "members_only"


@pytest.mark.anyio
async def test_collector_schedules_retry_on_rate_limit(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    client = StubEverMemOS()

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
        await session.commit()

    async def fake_discovery(*_args, **_kwargs) -> list[DiscoveredVideo]:
        return [
            DiscoveredVideo(
                video_id="rate1",
                title="Rate Limited",
                source_url="https://www.youtube.com/watch?v=rate1",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
                channel_name="Alan Watts Org",
                raw_meta={"timestamp": 1704067200},
            )
        ]

    async def fake_loader(**_kwargs) -> SourceContent:
        raise RetryLaterError("429 Too Many Requests")

    config = load_runtime_config(
        db_path=str(db),
        figure_slug="alan-watts",
        emos_base_url="https://emos.local",
        index_path=str(tmp_path / "index.sqlite3"),
    )
    poller = CollectorPoller(
        config=config,
        session_factory=session_factory,
        logger=configure_logging(),
        client=client,
        discovery_fn=fake_discovery,
        transcript_loader=fake_loader,
        sleep=_noop_sleep,
    )

    snapshot = await poller.run_once()

    assert snapshot.failed_subscriptions == 0
    assert snapshot.discovered_videos == 1
    assert snapshot.ingested_videos == 0

    async with session_factory() as session:
        stored = (
            (await session.execute(select(StoredSource).where(StoredSource.external_id == "rate1")))
            .scalars()
            .one()
        )
        state = await session.get(SourceIngestionState, stored.source_id)

    assert state is not None
    assert state.ingest_status == "pending"
    assert state.failure_count == 1
    assert state.next_retry_at is not None


@pytest.mark.anyio
async def test_collector_continues_processing_manual_sources_when_one_fails(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    client = StubEverMemOS()

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
        session.add(
            Subscription(
                subscription_id=subscription_id,
                agent_id=agent_id,
                content_platform="youtube",
                subscription_type="youtube.channel",
                subscription_url="https://www.youtube.com/@AlanWattsOrg",
                poll_interval_minutes=30,
                is_active=True,
            )
        )
        now = datetime.now(tz=UTC)
        bad_source_id = uuid.uuid4()
        good_source_id = uuid.uuid4()
        session.add(
            StoredSource(
                source_id=bad_source_id,
                agent_id=agent_id,
                content_platform="youtube",
                external_id="bad",
                emos_group_id="alan-watts:youtube:bad",
                title="Bad video",
                external_url="https://www.youtube.com/watch?v=bad",
            )
        )
        session.add(
            SourceIngestionState(
                source_id=bad_source_id,
                ingest_status="pending",
                manual_requested_at=now,
            )
        )
        session.add(
            StoredSource(
                source_id=good_source_id,
                agent_id=agent_id,
                content_platform="youtube",
                external_id="good",
                emos_group_id="alan-watts:youtube:good",
                title="Good video",
                external_url="https://www.youtube.com/watch?v=good",
            )
        )
        session.add(
            SourceIngestionState(
                source_id=good_source_id,
                ingest_status="pending",
                manual_requested_at=now,
            )
        )
        await session.commit()

    async def fake_discovery(*args, **kwargs) -> list[DiscoveredVideo]:
        del args, kwargs
        return []

    async def fake_loader(**kwargs) -> SourceContent:
        video_id = str(kwargs["video_id"])
        if video_id == "bad":
            return SourceContent(
                source=Source(
                    user_id="alan-watts",
                    external_id="bad",
                    title="Bad video",
                    source_url="https://www.youtube.com/watch?v=bad",
                ),
                content=TranscriptContent(lines=[]),
            )
        return SourceContent(
            source=Source(
                user_id="alan-watts",
                external_id="good",
                title="Good video",
                source_url="https://www.youtube.com/watch?v=good",
                published_at=datetime(2024, 1, 1, tzinfo=UTC),
            ),
            content=TranscriptContent(lines=[TranscriptLine(text="One.", start_ms=0, end_ms=900)]),
        )

    config = load_runtime_config(
        db_path=str(db),
        figure_slug="alan-watts",
        emos_base_url="https://emos.local",
        index_path=str(tmp_path / "index.sqlite3"),
    )
    poller = CollectorPoller(
        config=config,
        session_factory=session_factory,
        logger=configure_logging(),
        client=client,
        discovery_fn=fake_discovery,
        transcript_loader=fake_loader,
        sleep=_noop_sleep,
    )

    snapshot = await poller.run_once()

    assert snapshot.failed_subscriptions == 0
    assert snapshot.ingested_videos == 1
    assert len(client.memorize_calls) == 1
    assert len(client.meta_calls) == 1

    async with session_factory() as session:
        sources = (
            (await session.execute(select(StoredSource).order_by(StoredSource.external_id)))
            .scalars()
            .all()
        )
        states = {
            row.source_id: row
            for row in (
                (
                    await session.execute(
                        select(SourceIngestionState).where(
                            SourceIngestionState.source_id.in_([s.source_id for s in sources])
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
    assert [s.external_id for s in sources] == ["bad", "good"]
    assert all(states[s.source_id].manual_requested_at is None for s in sources)
    assert [states[s.source_id].ingest_status for s in sources] == ["no_transcript", "ingested"]
