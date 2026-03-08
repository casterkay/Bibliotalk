from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

import discord
from agents_service.agent.agent_factory import create_ghost_agent
from agents_service.agent.orchestrator import DMOrchestrator
from agents_service.store import SQLiteFigureStore
from bt_common.evidence_store.engine import get_session_factory, init_database
from bt_common.evidence_store.models import DiscordMap, Figure
from bt_common.logging import JsonFormatter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .bot.client import FigureDiscordClient
from .bot.dm_handler import DMHandler
from .config import DiscordRuntimeConfig
from .feed.discord_transport import DiscordPyFeedTransport
from .feed.publisher import DiscordFeedTransport, FeedPublisher, PublishSummary


def configure_logging(*, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("discord_service")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    logger.setLevel(level.upper())
    return logger


@dataclass(frozen=True, slots=True)
class FigureRuntimeContext:
    figure_id: uuid.UUID | None
    figure_slug: str | None
    display_name: str | None
    figure_found: bool
    channel_id: str | None


@dataclass(frozen=True, slots=True)
class RuntimeExecutionSummary:
    figure_slug: str | None
    figure_found: bool
    channel_id: str | None
    publication: PublishSummary


@dataclass(frozen=True, slots=True)
class LiveDiscordRuntime:
    client: FigureDiscordClient
    context: FigureRuntimeContext


async def build_runtime_context(
    config: DiscordRuntimeConfig,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FigureRuntimeContext:
    await init_database(config.db_path)
    session_factory = session_factory or get_session_factory(config.db_path)

    async with session_factory() as session:
        stmt = select(Figure, DiscordMap).join(
            DiscordMap, DiscordMap.figure_id == Figure.figure_id, isouter=True
        )
        if config.figure_slug:
            stmt = stmt.where(Figure.emos_user_id == config.figure_slug)
        row = (await session.execute(stmt)).first()

    if row is None:
        return FigureRuntimeContext(
            figure_id=None,
            figure_slug=config.figure_slug,
            figure_found=False,
            channel_id=None,
        )

    figure, discord_map = row
    return FigureRuntimeContext(
        figure_id=figure.figure_id,
        figure_slug=figure.emos_user_id,
        display_name=figure.display_name,
        figure_found=True,
        channel_id=(discord_map.channel_id if discord_map is not None else None),
    )


async def publish_pending_feed(
    config: DiscordRuntimeConfig,
    *,
    transport: DiscordFeedTransport,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> RuntimeExecutionSummary:
    await init_database(config.db_path)
    session_factory = session_factory or get_session_factory(config.db_path)
    context = await build_runtime_context(config, session_factory=session_factory)

    if (
        not context.figure_found
        or context.figure_id is None
        or context.channel_id is None
    ):
        return RuntimeExecutionSummary(
            figure_slug=context.figure_slug,
            figure_found=context.figure_found,
            channel_id=context.channel_id,
            publication=PublishSummary(),
        )

    publisher = FeedPublisher(session_factory, transport=transport)
    publication = await publisher.publish_pending_sources(
        figure_id=context.figure_id,
        channel_id=context.channel_id,
    )
    return RuntimeExecutionSummary(
        figure_slug=context.figure_slug,
        figure_found=context.figure_found,
        channel_id=context.channel_id,
        publication=publication,
    )


async def build_live_discord_runtime(
    config: DiscordRuntimeConfig,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    logger_: logging.Logger | None = None,
) -> LiveDiscordRuntime:
    logger_ = logger_ or logging.getLogger("discord_service")
    await init_database(config.db_path)
    session_factory = session_factory or get_session_factory(config.db_path)
    context = await build_runtime_context(config, session_factory=session_factory)
    if (
        not context.figure_found
        or context.figure_id is None
        or context.figure_slug is None
    ):
        raise LookupError(f"Figure not found for slug: {config.figure_slug}")

    store = SQLiteFigureStore(session_factory)
    orchestrator = DMOrchestrator(
        agent_factory=lambda figure_id: create_ghost_agent(figure_id, store=store)
    )
    dm_handler = DMHandler(
        orchestrator=orchestrator,
        figure_slug_resolver=lambda _figure_id: _resolve_figure_slug(
            context.figure_slug
        ),
    )
    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True
    intents.guilds = True

    client = FigureDiscordClient(
        figure_id=context.figure_id,
        display_name=context.display_name,
        dm_handler=dm_handler,
        on_ready_callback=lambda: _publish_feed_on_ready(
            client=None,
            config=config,
            context=context,
            session_factory=session_factory,
            logger_=logger_,
        ),
        logger=logger_,
        intents=intents,
    )
    client.on_ready_callback = lambda: _publish_feed_on_ready(
        client=client,
        config=config,
        context=context,
        session_factory=session_factory,
        logger_=logger_,
    )
    return LiveDiscordRuntime(client=client, context=context)


async def _resolve_figure_slug(figure_slug: str) -> str:
    return figure_slug


async def _publish_feed_on_ready(
    *,
    client: FigureDiscordClient | None,
    config: DiscordRuntimeConfig,
    context: FigureRuntimeContext,
    session_factory: async_sessionmaker[AsyncSession],
    logger_: logging.Logger,
) -> None:
    if client is None:
        return
    if context.channel_id is None or context.figure_id is None:
        logger_.info(
            "skipping feed publication figure_slug=%s reason=no_channel",
            context.figure_slug,
        )
        return
    transport = DiscordPyFeedTransport(client)
    summary = await publish_pending_feed(
        config,
        transport=transport,
        session_factory=session_factory,
    )
    logger_.info(
        "feed publication complete figure_slug=%s attempted=%s published=%s failed=%s",
        context.figure_slug,
        summary.publication.attempted_sources,
        summary.publication.published_sources,
        summary.publication.failed_sources,
    )
