from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from bt_common.evidence_store.engine import get_session_factory, init_database
from bt_common.evidence_store.models import (
    DiscordMap,
    DiscordPost,
    Figure,
    Source,
    TranscriptBatch,
)
from discord_service.feed.publisher import DiscordRateLimitError, FeedPublisher
from sqlalchemy import select


class FakeTransport:
    def __init__(self) -> None:
        self.parent_posts: list[tuple[str, str]] = []
        self.threads: list[tuple[str, str, str]] = []
        self.thread_messages: list[tuple[str, str]] = []
        self.batch_failures: dict[int, Exception] = {}
        self.batch_attempts = 0

    async def post_parent_message(self, *, channel_id: str, text: str) -> str:
        self.parent_posts.append((channel_id, text))
        return f"parent-{len(self.parent_posts)}"

    async def create_thread(
        self,
        *,
        channel_id: str,
        parent_message_id: str,
        name: str,
    ) -> str:
        self.threads.append((channel_id, parent_message_id, name))
        return f"thread-{len(self.threads)}"

    async def post_thread_message(self, *, thread_id: str, text: str) -> str:
        self.batch_attempts += 1
        failure = self.batch_failures.pop(self.batch_attempts, None)
        if failure is not None:
            raise failure
        self.thread_messages.append((thread_id, text))
        return f"msg-{len(self.thread_messages)}"


async def _seed_source_with_batches(session_factory):
    async with session_factory() as session:
        figure = Figure(
            figure_id=uuid.uuid4(),
            display_name="Alan Watts",
            emos_user_id="alan-watts",
        )
        session.add(figure)
        await session.flush()
        session.add(
            DiscordMap(
                figure_id=figure.figure_id,
                guild_id="guild",
                channel_id="channel",
            )
        )
        source = Source(
            figure_id=figure.figure_id,
            external_id="abc123",
            group_id="alan-watts:youtube:abc123",
            title="Alan Watts Lecture",
            source_url="https://www.youtube.com/watch?v=abc123",
            transcript_status="ingested",
            published_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        session.add(source)
        await session.flush()
        session.add_all(
            [
                TranscriptBatch(
                    source_id=source.source_id,
                    start_seq=0,
                    end_seq=0,
                    start_ms=0,
                    end_ms=1000,
                    text="First transcript batch.",
                    batch_rule="char_limit",
                ),
                TranscriptBatch(
                    source_id=source.source_id,
                    start_seq=1,
                    end_seq=1,
                    start_ms=2000,
                    end_ms=3000,
                    text="Second transcript batch.",
                    batch_rule="char_limit",
                ),
            ]
        )
        await session.commit()
        return figure.figure_id, source.source_id


@pytest.mark.anyio
async def test_publish_source_is_idempotent_on_rerun(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    figure_id, source_id = await _seed_source_with_batches(session_factory)
    transport = FakeTransport()

    async def fake_sleep(_: float) -> None:
        return None

    publisher = FeedPublisher(session_factory, transport=transport, sleep=fake_sleep)
    first = await publisher.publish_source(source_id=source_id, channel_id="channel")
    second = await publisher.publish_source(source_id=source_id, channel_id="channel")

    assert figure_id is not None
    assert first.status == "done"
    assert first.parent_posted is True
    assert first.thread_created is True
    assert first.batches_posted == 2
    assert second.status == "done"
    assert second.parent_posted is False
    assert second.thread_created is False
    assert second.batches_posted == 0
    assert len(transport.parent_posts) == 1
    assert len(transport.threads) == 1
    assert len(transport.thread_messages) == 2

    async with session_factory() as session:
        posts = (
            (
                await session.execute(
                    select(DiscordPost).where(DiscordPost.source_id == source_id)
                )
            )
            .scalars()
            .all()
        )
        batches = (
            (
                await session.execute(
                    select(TranscriptBatch).where(
                        TranscriptBatch.source_id == source_id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(posts) == 3
    assert all(post.post_status == "posted" for post in posts)
    assert all(batch.posted_to_discord for batch in batches)


@pytest.mark.anyio
async def test_publish_source_retries_after_rate_limit_and_preserves_post_state(
    tmp_path,
) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    _, source_id = await _seed_source_with_batches(session_factory)
    transport = FakeTransport()
    transport.batch_failures[1] = DiscordRateLimitError(2.5)
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    publisher = FeedPublisher(session_factory, transport=transport, sleep=fake_sleep)
    result = await publisher.publish_source(source_id=source_id, channel_id="channel")

    assert result.status == "done"
    assert len(transport.thread_messages) == 2
    assert 2.5 in sleep_calls
