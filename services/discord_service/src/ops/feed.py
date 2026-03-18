from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

import discord
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_evidence import Source
from bt_store.models_ingestion import SourceTextBatch
from bt_store.models_runtime import PlatformPost, PlatformRoute
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import DiscordRuntimeConfig
from ..config import resolve_discord_token
from ..feed.discord_transport import DiscordPyFeedTransport
from ..feed.publisher import FeedPublisher, PublishResult
from ..runtime import FeedPublicationSummary, publish_pending_feeds

logger = logging.getLogger("discord_service.ops.feed")


@dataclass(frozen=True, slots=True)
class SourceFeedStatus:
    source_id: str
    parent_posted: bool
    batches_total: int
    batches_posted: int
    failed_posts: int


async def _with_discord_client(
    token: str,
    *,
    logger_: logging.Logger,
    fn,
):
    intents = discord.Intents.none()
    client = discord.Client(intents=intents)
    done = asyncio.Event()
    result_holder: dict[str, object] = {}
    exc_holder: dict[str, BaseException] = {}

    async def _run() -> None:
        try:
            result_holder["value"] = await fn(client)
        except BaseException as exc:  # noqa: BLE001
            exc_holder["exc"] = exc
        finally:
            done.set()
            try:
                await client.close()
            except Exception:
                pass

    @client.event
    async def on_ready() -> None:  # type: ignore[override]
        logger_.info("discord ops client ready user=%s", client.user)
        asyncio.create_task(_run())

    await client.start(token)
    await done.wait()
    if "exc" in exc_holder:
        raise exc_holder["exc"]
    return result_holder.get("value")


async def publish_pending_feeds_once(
    config: DiscordRuntimeConfig,
    *,
    agent_slug: str | None = None,
    logger_: logging.Logger | None = None,
) -> FeedPublicationSummary:
    logger_ = logger_ or logging.getLogger("discord_service")
    token = resolve_discord_token()
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN")

    async def _publish(client: discord.Client) -> FeedPublicationSummary:
        transport = DiscordPyFeedTransport(client)
        return await publish_pending_feeds(
            config,
            transport=transport,
            session_factory=get_session_factory(config.db_path),
            logger_=logger_,
            agent_slug=agent_slug,
        )

    value = await _with_discord_client(token, logger_=logger_, fn=_publish)
    assert isinstance(value, FeedPublicationSummary)
    return value


async def _lookup_source_by_video(
    session: AsyncSession,
    *,
    agent_slug: str,
    video_id: str,
) -> tuple[Agent, Source]:
    agent = (
        (await session.execute(select(Agent).where(Agent.slug == agent_slug)))
        .scalars()
        .first()
    )
    if agent is None:
        raise LookupError(f"Unknown agent: {agent_slug}")
    source = (
        (
            await session.execute(
                select(Source).where(
                    Source.agent_id == agent.agent_id,
                    Source.content_platform == "youtube",
                    Source.external_id == video_id,
                )
            )
        )
        .scalars()
        .first()
    )
    if source is None:
        raise LookupError(f"Unknown video_id for {agent_slug}: {video_id}")
    return agent, source


async def source_feed_status_by_video(
    *,
    db_path: str | None,
    agent_slug: str,
    video_id: str,
) -> SourceFeedStatus:
    await init_database(db_path)
    session_factory = get_session_factory(db_path)
    async with session_factory() as session:
        _agent, source = await _lookup_source_by_video(
            session, agent_slug=agent_slug, video_id=video_id
        )

        parent_posted = (
            await session.execute(
                select(PlatformPost.platform_event_id, PlatformPost.thread_id).where(
                    PlatformPost.platform == "discord",
                    PlatformPost.kind == "feed.parent",
                    PlatformPost.source_id == source.source_id,
                    PlatformPost.status == "posted",
                )
            )
        ).first() is not None
        batches_total = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(SourceTextBatch)
                    .where(SourceTextBatch.source_id == source.source_id)
                )
            ).scalar_one()
            or 0
        )
        batches_posted = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(PlatformPost)
                    .where(
                        PlatformPost.platform == "discord",
                        PlatformPost.kind == "feed.batch",
                        PlatformPost.source_id == source.source_id,
                        PlatformPost.status == "posted",
                    )
                )
            ).scalar_one()
            or 0
        )
        failed_posts = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(PlatformPost)
                    .where(
                        PlatformPost.platform == "discord",
                        PlatformPost.source_id == source.source_id,
                        PlatformPost.kind.in_(["feed.parent", "feed.batch"]),
                        PlatformPost.status == "failed",
                    )
                )
            ).scalar_one()
            or 0
        )
        return SourceFeedStatus(
            source_id=str(source.source_id),
            parent_posted=parent_posted,
            batches_total=batches_total,
            batches_posted=batches_posted,
            failed_posts=failed_posts,
        )


async def _reset_failed_posts_for_source(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
) -> int:
    failed = (
        (
            await session.execute(
                select(PlatformPost).where(
                    PlatformPost.platform == "discord",
                    PlatformPost.source_id == source_id,
                    PlatformPost.kind.in_(["feed.parent", "feed.batch"]),
                    PlatformPost.status == "failed",
                )
            )
        )
        .scalars()
        .all()
    )
    if not failed:
        return 0
    await session.execute(
        update(PlatformPost)
        .where(
            PlatformPost.platform == "discord",
            PlatformPost.source_id == source_id,
            PlatformPost.kind.in_(["feed.parent", "feed.batch"]),
            PlatformPost.status == "failed",
        )
        .values(status="pending", platform_event_id=None, error=None)
    )
    await session.commit()
    return len(failed)


async def _publish_source_once(
    *,
    discord_config: DiscordRuntimeConfig,
    session_factory: async_sessionmaker[AsyncSession],
    source_id: uuid.UUID,
    channel_id: str,
    logger_: logging.Logger,
) -> PublishResult:
    token = resolve_discord_token()
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN")

    async def _publish(client: discord.Client) -> PublishResult:
        transport = DiscordPyFeedTransport(client)
        publisher = FeedPublisher(session_factory, transport=transport)
        return await publisher.publish_source(
            source_id=source_id, channel_id=channel_id
        )

    value = await _with_discord_client(token, logger_=logger_, fn=_publish)
    assert isinstance(value, PublishResult)
    return value


async def retry_failed_posts_by_video(
    *,
    db_path: str | None,
    agent_slug: str,
    video_id: str,
    discord_config: DiscordRuntimeConfig,
    logger_: logging.Logger | None = None,
) -> FeedPublicationSummary:
    logger_ = logger_ or logging.getLogger("discord_service")
    await init_database(db_path)
    session_factory = get_session_factory(db_path)

    source_id: uuid.UUID
    channel_id: str
    async with session_factory() as session:
        agent, source = await _lookup_source_by_video(
            session, agent_slug=agent_slug, video_id=video_id
        )
        route = (
            (
                await session.execute(
                    select(PlatformRoute).where(
                        PlatformRoute.platform == "discord",
                        PlatformRoute.purpose == "feed",
                        PlatformRoute.agent_id == agent.agent_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if route is None:
            raise LookupError(f"Missing discord feed route for agent: {agent_slug}")
        await _reset_failed_posts_for_source(session, source_id=source.source_id)
        source_id = source.source_id
        channel_id = str(route.container_id)

    result = await _publish_source_once(
        discord_config=discord_config,
        session_factory=session_factory,
        source_id=source_id,
        channel_id=channel_id,
        logger_=logger_,
    )

    # Report summary for just this source.
    return FeedPublicationSummary(
        attempted_agents=1,
        attempted_sources=1,
        published_sources=1 if result.status == "done" else 0,
        failed_sources=1 if result.status != "done" else 0,
    )


async def republish_source_by_video(
    *,
    db_path: str | None,
    agent_slug: str,
    video_id: str,
    discord_config: DiscordRuntimeConfig,
    logger_: logging.Logger | None = None,
) -> PublishResult:
    """Publish/resume feed posting for one video (idempotent; does not reset state)."""
    logger_ = logger_ or logging.getLogger("discord_service")
    await init_database(db_path)
    session_factory = get_session_factory(db_path)

    async with session_factory() as session:
        agent, source = await _lookup_source_by_video(
            session, agent_slug=agent_slug, video_id=video_id
        )
        route = (
            (
                await session.execute(
                    select(PlatformRoute).where(
                        PlatformRoute.platform == "discord",
                        PlatformRoute.purpose == "feed",
                        PlatformRoute.agent_id == agent.agent_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if route is None:
            raise LookupError(f"Missing discord feed route for agent: {agent_slug}")
        source_id = source.source_id
        channel_id = str(route.container_id)

    return await _publish_source_once(
        discord_config=discord_config,
        session_factory=session_factory,
        source_id=source_id,
        channel_id=channel_id,
        logger_=logger_,
    )
