from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from bt_common.evidence_store.engine import get_session_factory, init_database
from bt_common.evidence_store.models import DiscordMap, Figure
from bt_common.logging import JsonFormatter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import DiscordRuntimeConfig
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
