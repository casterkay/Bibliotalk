from __future__ import annotations

import uuid

from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_ingestion import Subscription
from bt_store.models_runtime import PlatformRoute
from sqlalchemy import select


def _display_name_for_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-"))


async def seed_agent(
    *,
    db_path: str | None,
    agent_slug: str,
    kind: str = "figure",
    display_name: str | None,
    persona_summary: str | None,
    subscription_url: str,
    subscription_type: str,
    guild_id: str,
    channel_id: str,
    poll_interval_minutes: int,
) -> None:
    await init_database(db_path)
    session_factory = get_session_factory(db_path)

    async with session_factory() as session:
        agent = (
            (await session.execute(select(Agent).where(Agent.slug == agent_slug)))
            .scalars()
            .first()
        )
        if agent is None:
            agent = Agent(
                agent_id=uuid.uuid4(),
                display_name=display_name or _display_name_for_slug(agent_slug),
                slug=agent_slug,
                persona_summary=persona_summary,
                kind=kind,
                is_active=True,
            )
            session.add(agent)
            await session.flush()
        else:
            if display_name:
                agent.display_name = display_name
            if persona_summary:
                agent.persona_summary = persona_summary
            agent.kind = kind
            agent.is_active = True

        subscription = (
            (
                await session.execute(
                    select(Subscription).where(
                        Subscription.agent_id == agent.agent_id,
                        Subscription.content_platform == "youtube",
                        Subscription.subscription_url == subscription_url,
                    )
                )
            )
            .scalars()
            .first()
        )
        if subscription is None:
            subscription = Subscription(
                agent_id=agent.agent_id,
                content_platform="youtube",
                subscription_type=f"youtube.{subscription_type}",
                subscription_url=subscription_url,
                poll_interval_minutes=max(1, poll_interval_minutes),
                is_active=True,
            )
            session.add(subscription)
        else:
            subscription.subscription_type = f"youtube.{subscription_type}"
            subscription.poll_interval_minutes = max(1, poll_interval_minutes)
            subscription.is_active = True

        discord_route = (
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
        if discord_route is None:
            session.add(
                PlatformRoute(
                    route_id=uuid.uuid4(),
                    platform="discord",
                    purpose="feed",
                    agent_id=agent.agent_id,
                    container_id=channel_id,
                    config_json={"guild_id": guild_id},
                )
            )
        else:
            discord_route.container_id = channel_id
            config = dict(discord_route.config_json or {})
            config["guild_id"] = guild_id
            discord_route.config_json = config

        await session.commit()
