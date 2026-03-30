from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from bt_common.evermemos_client import EverMemOSClient
from bt_store.models_core import Agent
from bt_store.models_evidence import Source
from bt_store.models_ingestion import SourceIngestionState, Subscription, SubscriptionState
from bt_store.models_runtime import PlatformRoute
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .admin_auth import require_admin
from .admin_console_models import (
    AgentCreateRequest,
    AgentPatchRequest,
    AgentSummary,
    DiscordFeedRouteUpsertRequest,
    DiscordVoiceRouteUpsertRequest,
    EMOSGetMemoriesRequest,
    SubscriptionCreateRequest,
    SubscriptionPatchRequest,
)


def _route_payload(route: PlatformRoute) -> dict[str, Any]:
    return {
        "route_id": str(route.route_id),
        "platform": route.platform,
        "purpose": route.purpose,
        "agent_id": str(route.agent_id) if route.agent_id else None,
        "container_id": route.container_id,
        "config": route.config_json or None,
        "created_at": route.created_at.isoformat() if route.created_at else None,
    }


def _subscription_payload(sub: Subscription, state: SubscriptionState | None) -> dict[str, Any]:
    return {
        "subscription_id": str(sub.subscription_id),
        "agent_id": str(sub.agent_id),
        "content_platform": sub.content_platform,
        "subscription_type": sub.subscription_type,
        "subscription_url": sub.subscription_url,
        "poll_interval_minutes": sub.poll_interval_minutes,
        "is_active": bool(sub.is_active),
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "state": {
            "last_seen_external_id": state.last_seen_external_id if state else None,
            "last_published_at": state.last_published_at.isoformat()
            if (state and state.last_published_at)
            else None,
            "last_polled_at": state.last_polled_at.isoformat()
            if (state and state.last_polled_at)
            else None,
            "failure_count": int(state.failure_count) if state else 0,
            "next_retry_at": state.next_retry_at.isoformat()
            if (state and state.next_retry_at)
            else None,
            "updated_at": state.updated_at.isoformat() if state and state.updated_at else None,
        },
    }


async def _build_agent_summary(session: AsyncSession, agent: Agent) -> AgentSummary:
    subs_rows = (
        await session.execute(
            select(Subscription, SubscriptionState)
            .outerjoin(
                SubscriptionState,
                SubscriptionState.subscription_id == Subscription.subscription_id,
            )
            .where(Subscription.agent_id == agent.agent_id)
            .order_by(Subscription.created_at.desc())
        )
    ).all()

    routes = (
        (
            await session.execute(
                select(PlatformRoute).where(PlatformRoute.agent_id == agent.agent_id)
            )
        )
        .scalars()
        .all()
    )
    feed_routes = [
        _route_payload(route)
        for route in routes
        if route.platform == "discord" and route.purpose == "feed"
    ]
    voice_routes = [
        _route_payload(route)
        for route in routes
        if route.platform == "discord" and route.purpose == "voice"
    ]

    return AgentSummary(
        agent_id=agent.agent_id,
        slug=agent.slug,
        display_name=agent.display_name,
        persona_summary=agent.persona_summary,
        kind=str(agent.kind),
        is_active=bool(agent.is_active),
        created_at=agent.created_at.replace(tzinfo=None) if agent.created_at else None,
        subscriptions=[_subscription_payload(sub, state) for sub, state in subs_rows],
        discord_feed_routes=feed_routes,
        discord_voice_routes=voice_routes,
    )


def create_admin_console_router(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    evermemos_client: EverMemOSClient,
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_admin)])

    @router.get("/agents", response_model=list[AgentSummary])
    async def list_agents() -> list[AgentSummary]:
        async with session_factory() as session:
            agents = (await session.execute(select(Agent).order_by(Agent.slug))).scalars().all()
            return [await _build_agent_summary(session, agent) for agent in agents]

    @router.post("/agents", response_model=AgentSummary)
    async def create_agent(body: AgentCreateRequest) -> AgentSummary:
        now = datetime.now(tz=UTC)
        agent = Agent(
            agent_id=uuid.uuid4(),
            slug=body.slug.strip(),
            display_name=body.display_name.strip(),
            persona_summary=(body.persona_summary.strip() if body.persona_summary else None),
            kind=body.kind.strip(),
            is_active=bool(body.is_active),
            created_at=now,
        )
        async with session_factory() as session:
            session.add(agent)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(status_code=409, detail="Agent slug already exists") from exc
            await session.refresh(agent)
            return await _build_agent_summary(session, agent)

    @router.get("/agents/{agent_id}", response_model=AgentSummary)
    async def get_agent(agent_id: uuid.UUID) -> AgentSummary:
        async with session_factory() as session:
            agent = await session.get(Agent, agent_id)
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")
            return await _build_agent_summary(session, agent)

    @router.patch("/agents/{agent_id}", response_model=AgentSummary)
    async def patch_agent(agent_id: uuid.UUID, body: AgentPatchRequest) -> AgentSummary:
        async with session_factory() as session:
            agent = await session.get(Agent, agent_id)
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")

            if body.display_name is not None:
                agent.display_name = body.display_name.strip()
            if body.persona_summary is not None:
                agent.persona_summary = body.persona_summary.strip() or None
            if body.kind is not None:
                agent.kind = body.kind.strip()
            if body.is_active is not None:
                agent.is_active = bool(body.is_active)

            await session.commit()
            await session.refresh(agent)
            return await _build_agent_summary(session, agent)

    @router.get("/agents/{agent_id}/subscriptions")
    async def list_agent_subscriptions(agent_id: uuid.UUID) -> list[dict[str, Any]]:
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(Subscription, SubscriptionState)
                    .outerjoin(
                        SubscriptionState,
                        SubscriptionState.subscription_id == Subscription.subscription_id,
                    )
                    .where(Subscription.agent_id == agent_id)
                    .order_by(Subscription.created_at.desc())
                )
            ).all()
            return [_subscription_payload(sub, state) for sub, state in rows]

    @router.post("/agents/{agent_id}/subscriptions")
    async def create_subscription(
        agent_id: uuid.UUID, body: SubscriptionCreateRequest
    ) -> dict[str, str]:
        now = datetime.now(tz=UTC)
        sub = Subscription(
            agent_id=agent_id,
            content_platform=body.content_platform.strip(),
            subscription_type=body.subscription_type.strip(),
            subscription_url=body.subscription_url.strip(),
            poll_interval_minutes=int(body.poll_interval_minutes),
            is_active=bool(body.is_active),
            created_at=now,
        )

        async with session_factory() as session:
            session.add(sub)
            try:
                await session.flush()
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(status_code=409, detail="Subscription already exists") from exc

            session.add(SubscriptionState(subscription_id=sub.subscription_id, updated_at=now))
            await session.commit()
            await session.refresh(sub)
            return {"subscription_id": str(sub.subscription_id)}

    @router.patch("/subscriptions/{subscription_id}")
    async def patch_subscription(
        subscription_id: uuid.UUID, body: SubscriptionPatchRequest
    ) -> dict[str, bool]:
        async with session_factory() as session:
            sub = await session.get(Subscription, subscription_id)
            if sub is None:
                raise HTTPException(status_code=404, detail="Subscription not found")

            if body.subscription_url is not None:
                sub.subscription_url = body.subscription_url.strip()
            if body.subscription_type is not None:
                sub.subscription_type = body.subscription_type.strip()
            if body.poll_interval_minutes is not None:
                sub.poll_interval_minutes = int(body.poll_interval_minutes)
            if body.is_active is not None:
                sub.is_active = bool(body.is_active)

            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(
                    status_code=409, detail="Subscription conflicts with existing row"
                ) from exc
            return {"ok": True}

    @router.get("/agents/{agent_id}/routes/discord/feed")
    async def get_discord_feed_route(agent_id: uuid.UUID) -> dict[str, Any]:
        async with session_factory() as session:
            route = (
                (
                    await session.execute(
                        select(PlatformRoute).where(
                            PlatformRoute.platform == "discord",
                            PlatformRoute.purpose == "feed",
                            PlatformRoute.agent_id == agent_id,
                        )
                    )
                )
                .scalars()
                .first()
            )
            if route is None:
                return {"route": None}
            return {
                "route": {
                    "route_id": str(route.route_id),
                    "guild_id": str((route.config_json or {}).get("guild_id") or ""),
                    "channel_id": str(route.container_id),
                    "created_at": route.created_at.isoformat() if route.created_at else None,
                }
            }

    @router.put("/agents/{agent_id}/routes/discord/feed")
    async def upsert_discord_feed_route(
        agent_id: uuid.UUID, body: DiscordFeedRouteUpsertRequest
    ) -> dict[str, Any]:
        now = datetime.now(tz=UTC)
        async with session_factory() as session:
            route = (
                (
                    await session.execute(
                        select(PlatformRoute).where(
                            PlatformRoute.platform == "discord",
                            PlatformRoute.purpose == "feed",
                            PlatformRoute.agent_id == agent_id,
                        )
                    )
                )
                .scalars()
                .first()
            )

            if route is None:
                route = PlatformRoute(
                    route_id=uuid.uuid4(),
                    platform="discord",
                    purpose="feed",
                    agent_id=agent_id,
                    container_id=body.channel_id.strip(),
                    config_json={"guild_id": body.guild_id.strip()},
                    created_at=now,
                )
                session.add(route)
            else:
                route.container_id = body.channel_id.strip()
                route.config_json = {"guild_id": body.guild_id.strip()}

            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(
                    status_code=409, detail="Route conflicts with existing row"
                ) from exc

            return {"ok": True, "route_id": str(route.route_id)}

    @router.get("/agents/{agent_id}/routes/discord/voice")
    async def list_discord_voice_routes(agent_id: uuid.UUID) -> dict[str, Any]:
        async with session_factory() as session:
            routes = (
                (
                    await session.execute(
                        select(PlatformRoute)
                        .where(
                            PlatformRoute.platform == "discord",
                            PlatformRoute.purpose == "voice",
                            PlatformRoute.agent_id == agent_id,
                        )
                        .order_by(PlatformRoute.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            out: list[dict[str, Any]] = []
            for route in routes:
                cfg = route.config_json or {}
                out.append(
                    {
                        "route_id": str(route.route_id),
                        "guild_id": str(route.container_id),
                        "voice_channel_id": str(cfg.get("voice_channel_id") or ""),
                        "text_channel_id": cfg.get("text_channel_id"),
                        "text_thread_id": cfg.get("text_thread_id"),
                        "updated_by_user_id": cfg.get("updated_by_user_id"),
                        "updated_at": cfg.get("updated_at"),
                        "created_at": route.created_at.isoformat() if route.created_at else None,
                    }
                )
            return {"routes": out}

    @router.put("/agents/{agent_id}/routes/discord/voice")
    async def upsert_discord_voice_route(
        agent_id: uuid.UUID, body: DiscordVoiceRouteUpsertRequest
    ) -> dict[str, Any]:
        clean_guild_id = body.guild_id.strip()
        now = datetime.now(tz=UTC)
        config_payload = {
            "voice_channel_id": body.voice_channel_id.strip(),
            "text_channel_id": (body.text_channel_id or "").strip() or None,
            "text_thread_id": (body.text_thread_id or "").strip() or None,
            "updated_by_user_id": body.updated_by_user_id.strip(),
            "updated_at": now.isoformat(),
        }

        async with session_factory() as session:
            route = (
                (
                    await session.execute(
                        select(PlatformRoute).where(
                            PlatformRoute.platform == "discord",
                            PlatformRoute.purpose == "voice",
                            PlatformRoute.agent_id == agent_id,
                            PlatformRoute.container_id == clean_guild_id,
                        )
                    )
                )
                .scalars()
                .one_or_none()
            )
            if route is None:
                route = PlatformRoute(
                    route_id=uuid.uuid4(),
                    platform="discord",
                    purpose="voice",
                    agent_id=agent_id,
                    container_id=clean_guild_id,
                    config_json=config_payload,
                    created_at=now,
                )
                session.add(route)
            else:
                route.config_json = config_payload

            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(
                    status_code=409, detail="Route conflicts with existing row"
                ) from exc
            return {"ok": True, "route_id": str(route.route_id)}

    @router.get("/agents/{agent_id}/sources")
    async def list_agent_sources(agent_id: uuid.UUID, limit: int = 200) -> dict[str, Any]:
        clean_limit = min(500, max(1, int(limit)))
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(Source, SourceIngestionState)
                    .outerjoin(
                        SourceIngestionState,
                        SourceIngestionState.source_id == Source.source_id,
                    )
                    .where(Source.agent_id == agent_id)
                    .order_by(Source.published_at.desc().nullslast(), Source.created_at.desc())
                    .limit(clean_limit)
                )
            ).all()
            out: list[dict[str, Any]] = []
            for source, state in rows:
                out.append(
                    {
                        "source_id": str(source.source_id),
                        "agent_id": str(source.agent_id),
                        "subscription_id": str(source.subscription_id)
                        if source.subscription_id
                        else None,
                        "content_platform": source.content_platform,
                        "external_id": source.external_id,
                        "external_url": source.external_url,
                        "title": source.title,
                        "author": source.author or source.channel_name,
                        "published_at": source.published_at.isoformat()
                        if source.published_at
                        else None,
                        "emos_group_id": source.emos_group_id,
                        "meta_synced_at": source.meta_synced_at.isoformat()
                        if source.meta_synced_at
                        else None,
                        "created_at": source.created_at.isoformat() if source.created_at else None,
                        "ingestion": {
                            "ingest_status": state.ingest_status if state else None,
                            "failure_count": int(state.failure_count) if state else 0,
                            "last_attempt_at": state.last_attempt_at.isoformat()
                            if (state and state.last_attempt_at)
                            else None,
                            "next_retry_at": state.next_retry_at.isoformat()
                            if (state and state.next_retry_at)
                            else None,
                            "skip_reason": state.skip_reason if state else None,
                            "manual_requested_at": state.manual_requested_at.isoformat()
                            if (state and state.manual_requested_at)
                            else None,
                            "updated_at": state.updated_at.isoformat()
                            if (state and state.updated_at)
                            else None,
                        },
                    }
                )
            return {"sources": out}

    @router.post("/emos/memories/get")
    async def emos_get_memories(body: EMOSGetMemoriesRequest) -> dict[str, Any]:
        async with session_factory() as session:
            agent = (
                (await session.execute(select(Agent).where(Agent.agent_id == body.agent_id)))
                .scalars()
                .first()
            )
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found")

        payload = await evermemos_client.get_memories(
            user_id=agent.slug,
            group_id=body.group_id,
            memory_type=body.memory_type,
            limit=int(body.limit),
            offset=int(body.offset),
        )
        return payload

    return router
