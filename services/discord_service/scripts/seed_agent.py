from __future__ import annotations

import argparse
import asyncio
import uuid

from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_ingestion import Subscription
from bt_store.models_runtime import PlatformRoute
from sqlalchemy import select


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed an agent and Discord mapping for local quickstart"
    )
    parser.add_argument("--agent", dest="agent_slug", required=True)
    parser.add_argument("--kind", dest="kind", default="figure")
    parser.add_argument("--display-name", dest="display_name")
    parser.add_argument("--persona-summary", dest="persona_summary")
    parser.add_argument("--subscription-url", dest="subscription_url", required=True)
    parser.add_argument(
        "--subscription-type", dest="subscription_type", default="channel"
    )
    parser.add_argument("--guild-id", dest="guild_id", required=True)
    parser.add_argument("--channel-id", dest="channel_id", required=True)
    parser.add_argument(
        "--poll-interval-minutes", dest="poll_interval_minutes", type=int, default=60
    )
    parser.add_argument("--db", dest="db_path")
    return parser


def _display_name_for_slug(slug: str) -> str:
    return " ".join(part.capitalize() for part in slug.replace("_", "-").split("-"))


async def seed_agent(
    *,
    db_path: str | None,
    agent_slug: str,
    kind: str,
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


def main() -> int:
    args = build_parser().parse_args()
    asyncio.run(
        seed_agent(
            db_path=args.db_path,
            agent_slug=args.agent_slug,
            kind=args.kind,
            display_name=args.display_name,
            persona_summary=args.persona_summary,
            subscription_url=args.subscription_url,
            subscription_type=args.subscription_type,
            guild_id=args.guild_id,
            channel_id=args.channel_id,
            poll_interval_minutes=args.poll_interval_minutes,
        )
    )
    print(
        f"Seeded agent '{args.agent_slug}' (kind={args.kind}) with subscription '{args.subscription_url}' and Discord channel '{args.channel_id}'."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
