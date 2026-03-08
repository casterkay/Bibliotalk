from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from bt_common.evidence_store.engine import get_session_factory, init_database
from bt_common.evidence_store.models import (
    DiscordMap,
    DiscordPost,
    Figure,
    Segment,
    Source,
    TranscriptBatch,
)
from discord_service.config import load_runtime_config
from discord_service.feed.publisher import DiscordPermissionError
from discord_service.runtime import publish_pending_feed
from sqlalchemy import select


class FakeTransport:
    def __init__(self) -> None:
        self.parent_posts: list[tuple[str, str]] = []
        self.threads: list[tuple[str, str, str]] = []
        self.thread_messages: list[tuple[str, str]] = []
        self.fail_on_batch_call: int | None = None
        self.batch_calls = 0

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
        self.batch_calls += 1
        if self.fail_on_batch_call == self.batch_calls:
            raise DiscordPermissionError("missing permission")
        self.thread_messages.append((thread_id, text))
        return f"msg-{len(self.thread_messages)}"


@pytest.mark.anyio
async def test_feed_publication_retries_and_resumes_without_duplicates(
    tmp_path,
) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)

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
                Segment(
                    source_id=source.source_id,
                    seq=0,
                    text="First transcript segment.",
                    sha256="a" * 64,
                    start_ms=0,
                    end_ms=1000,
                ),
                Segment(
                    source_id=source.source_id,
                    seq=1,
                    text="Second transcript segment.",
                    sha256="b" * 64,
                    start_ms=1500,
                    end_ms=2300,
                ),
                Segment(
                    source_id=source.source_id,
                    seq=2,
                    text="Third transcript segment.",
                    sha256="c" * 64,
                    start_ms=7000,
                    end_ms=8200,
                ),
            ]
        )
        await session.commit()

    config = load_runtime_config(db_path=str(db), figure_slug="alan-watts")
    first_transport = FakeTransport()
    first_transport.fail_on_batch_call = 2

    first = await publish_pending_feed(
        config,
        transport=first_transport,
        session_factory=session_factory,
    )

    assert first.publication.attempted_sources == 1
    assert first.publication.published_sources == 0
    assert first.publication.failed_sources == 1
    assert len(first_transport.parent_posts) == 1
    assert len(first_transport.threads) == 1
    assert len(first_transport.thread_messages) == 1

    async with session_factory() as session:
        posts = (
            (await session.execute(select(DiscordPost).order_by(DiscordPost.batch_id)))
            .scalars()
            .all()
        )
        batches = (
            (
                await session.execute(
                    select(TranscriptBatch).order_by(TranscriptBatch.start_seq)
                )
            )
            .scalars()
            .all()
        )

    assert len(batches) == 2
    assert [batch.posted_to_discord for batch in batches] == [True, False]
    assert len(posts) == 3
    assert any(
        post.post_status == "failed" for post in posts if post.batch_id is not None
    )

    second_transport = FakeTransport()
    second = await publish_pending_feed(
        config,
        transport=second_transport,
        session_factory=session_factory,
    )

    assert second.publication.attempted_sources == 1
    assert second.publication.published_sources == 1
    assert second.publication.failed_sources == 0
    assert len(second_transport.parent_posts) == 0
    assert len(second_transport.threads) == 0
    assert len(second_transport.thread_messages) == 1

    third_transport = FakeTransport()
    third = await publish_pending_feed(
        config,
        transport=third_transport,
        session_factory=session_factory,
    )

    assert third.publication.attempted_sources == 0
    assert third.publication.published_sources == 0
    assert third.publication.failed_sources == 0
    assert len(third_transport.parent_posts) == 0
    assert len(third_transport.threads) == 0
    assert len(third_transport.thread_messages) == 0
