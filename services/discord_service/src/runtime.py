from __future__ import annotations

import logging
from dataclasses import dataclass

import discord
from agents_service.agent.agent_factory import create_spirit_agent
from agents_service.agent.orchestrator import DMOrchestrator
from agents_service.store import SQLiteAgentStore
from bt_common.logging import JsonFormatter
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_runtime import PlatformRoute
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .bot.client import BibliotalkDiscordClient
from .bot.concierge import DMConcierge
from .config import DiscordRuntimeConfig
from .feed.discord_transport import DiscordPyFeedTransport
from .feed.publisher import DiscordFeedTransport, FeedPublisher
from .talks.agent_directory import AgentDirectory
from .talks.router import FacilitatorRouter
from .talks.service import TalkService
from .talks.transport import DiscordPyTalkTransport, TalkTransport


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
class LiveDiscordRuntime:
    client: BibliotalkDiscordClient


@dataclass(frozen=True, slots=True)
class FeedPublicationSummary:
    attempted_agents: int = 0
    attempted_sources: int = 0
    published_sources: int = 0
    failed_sources: int = 0


async def publish_pending_feeds(
    config: DiscordRuntimeConfig,
    *,
    transport: DiscordFeedTransport,
    agent_slug: str | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    logger_: logging.Logger | None = None,
) -> FeedPublicationSummary:
    logger_ = logger_ or logging.getLogger("discord_service")
    await init_database(config.db_path)
    session_factory = session_factory or get_session_factory(config.db_path)

    async with session_factory() as session:
        query = (
            select(Agent.agent_id, Agent.slug, PlatformRoute.container_id)
            .join(PlatformRoute, PlatformRoute.agent_id == Agent.agent_id)
            .where(
                Agent.is_active.is_(True),
                PlatformRoute.platform == "discord",
                PlatformRoute.purpose == "feed",
            )
        )
        if agent_slug:
            query = query.where(Agent.slug == agent_slug)
        rows = (await session.execute(query.order_by(Agent.slug))).all()

    publisher = FeedPublisher(session_factory, transport=transport)
    attempted_sources = 0
    published_sources = 0
    failed_sources = 0
    for agent_id, agent_slug, channel_id in rows:
        publication = await publisher.publish_pending_sources(
            agent_id=agent_id,
            channel_id=str(channel_id),
        )
        logger_.info(
            "feed publication complete agent_slug=%s attempted=%s published=%s failed=%s",
            agent_slug,
            publication.attempted_sources,
            publication.published_sources,
            publication.failed_sources,
        )
        attempted_sources += publication.attempted_sources
        published_sources += publication.published_sources
        failed_sources += publication.failed_sources

    return FeedPublicationSummary(
        attempted_agents=len(rows),
        attempted_sources=attempted_sources,
        published_sources=published_sources,
        failed_sources=failed_sources,
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

    store = SQLiteAgentStore(session_factory)
    orchestrator = DMOrchestrator(
        agent_factory=lambda agent_id: create_spirit_agent(agent_id, store=store)
    )

    directory = AgentDirectory(session_factory=session_factory)
    await directory.refresh()

    router = FacilitatorRouter()

    # Circular dependency: TalkService needs a transport backed by the live Discord client.
    # We construct the client first, then inject it into the transport instance.
    talk_transport: TalkTransport = DiscordPyTalkTransport(client=None)
    talk_service = TalkService(
        session_factory=session_factory,
        agent_directory=directory,
        router=router,
        orchestrator=orchestrator,
        transport=talk_transport,
        hub_channel_name="bibliotalk",
        logger_=logger_,
    )

    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True
    intents.guilds = True
    intents.messages = True

    client = BibliotalkDiscordClient(
        config=config,
        talk_service=talk_service,
        agent_directory=directory,
        dm_concierge=DMConcierge(agent_directory=directory, logger_=logger_),
        on_ready_callback=None,
        logger=logger_,
        intents=intents,
    )
    client.on_ready_callback = lambda: _on_ready(
        client=client,
        config=config,
        session_factory=session_factory,
        logger_=logger_,
    )

    # Inject live client into talk transport.
    assert isinstance(talk_transport, DiscordPyTalkTransport)
    talk_transport.client = client

    return LiveDiscordRuntime(client=client)


async def _on_ready(
    *,
    client: BibliotalkDiscordClient,
    config: DiscordRuntimeConfig,
    session_factory: async_sessionmaker[AsyncSession],
    logger_: logging.Logger,
) -> None:
    # Best-effort feed publication; talk UX does not depend on it.
    try:
        transport = DiscordPyFeedTransport(client)
        await publish_pending_feeds(
            config,
            transport=transport,
            session_factory=session_factory,
            logger_=logger_,
        )
    except Exception:
        logger_.exception("feed publication on ready failed")
