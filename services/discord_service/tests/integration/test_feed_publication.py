from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_evidence import Source
from bt_store.models_ingestion import SourceIngestionState, SourceTextBatch
from bt_store.models_runtime import PlatformPost, PlatformRoute
from discord_service.config import load_runtime_config
from discord_service.feed.publisher import DiscordPermissionError
from discord_service.runtime import publish_pending_feeds
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
        agent = Agent(
            agent_id=uuid.uuid4(),
            kind="figure",
            slug="alan-watts",
            display_name="Alan Watts",
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
        source = Source(
            agent_id=agent.agent_id,
            content_platform="youtube",
            external_id="abc123",
            emos_group_id="alan-watts:youtube:abc123",
            title="Alan Watts Lecture",
            external_url="https://www.youtube.com/watch?v=abc123",
            published_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        session.add(source)
        await session.flush()
        session.add(
            SourceIngestionState(source_id=source.source_id, ingest_status="ingested")
        )
        session.add_all(
            [
                SourceTextBatch(
                    source_id=source.source_id,
                    speaker_label=None,
                    start_seq=0,
                    end_seq=1,
                    start_ms=0,
                    end_ms=2300,
                    text="First transcript segment.\n\nSecond transcript segment.",
                    batch_rule="silence_gap",
                ),
                SourceTextBatch(
                    source_id=source.source_id,
                    speaker_label=None,
                    start_seq=2,
                    end_seq=2,
                    start_ms=7000,
                    end_ms=8200,
                    text="Third transcript segment.",
                    batch_rule="char_limit",
                ),
            ]
        )
        await session.commit()

    config = load_runtime_config(db_path=str(db))
    first_transport = FakeTransport()
    first_transport.fail_on_batch_call = 2

    first = await publish_pending_feeds(
        config,
        transport=first_transport,
        session_factory=session_factory,
    )

    assert first.attempted_agents == 1
    assert first.attempted_sources == 1
    assert first.published_sources == 0
    assert first.failed_sources == 1
    assert len(first_transport.parent_posts) == 1
    assert len(first_transport.threads) == 1
    assert len(first_transport.thread_messages) == 1

    async with session_factory() as session:
        posts = (
            (
                await session.execute(
                    select(PlatformPost)
                    .where(
                        PlatformPost.platform == "discord",
                        PlatformPost.kind.in_(["feed.parent", "feed.batch"]),
                    )
                    .order_by(PlatformPost.batch_id)
                )
            )
            .scalars()
            .all()
        )
        batches = (
            (
                await session.execute(
                    select(SourceTextBatch).order_by(SourceTextBatch.start_seq)
                )
            )
            .scalars()
            .all()
        )

    assert len(batches) == 2
    assert len(posts) == 3
    assert any(post.status == "failed" for post in posts if post.batch_id is not None)

    second_transport = FakeTransport()
    second = await publish_pending_feeds(
        config,
        transport=second_transport,
        session_factory=session_factory,
    )

    assert second.attempted_agents == 1
    assert second.attempted_sources == 1
    assert second.published_sources == 1
    assert second.failed_sources == 0
    assert len(second_transport.parent_posts) == 0
    assert len(second_transport.threads) == 0
    assert len(second_transport.thread_messages) == 1

    third_transport = FakeTransport()
    third = await publish_pending_feeds(
        config,
        transport=third_transport,
        session_factory=session_factory,
    )

    assert third.attempted_agents == 1
    assert third.attempted_sources == 0
    assert third.published_sources == 0
    assert third.failed_sources == 0
    assert len(third_transport.parent_posts) == 0
    assert len(third_transport.threads) == 0
    assert len(third_transport.thread_messages) == 0
