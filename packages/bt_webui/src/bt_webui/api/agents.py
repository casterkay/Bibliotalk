from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from bt_store.models_core import Agent
from bt_store.models_ingestion import Subscription, SubscriptionState
from bt_store.models_runtime import PlatformRoute
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..db import session_dep
from ..models import AgentCreateRequest, AgentPatchRequest, AgentSummary

router = APIRouter()


def _route_payload(route: PlatformRoute) -> dict[str, Any]:
    payload = {
        "route_id": str(route.route_id),
        "platform": route.platform,
        "purpose": route.purpose,
        "agent_id": str(route.agent_id) if route.agent_id else None,
        "container_id": route.container_id,
        "config": route.config_json or None,
        "created_at": route.created_at.isoformat() if route.created_at else None,
    }
    return payload


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
        _route_payload(r) for r in routes if r.platform == "discord" and r.purpose == "feed"
    ]
    voice_routes = [
        _route_payload(r) for r in routes if r.platform == "discord" and r.purpose == "voice"
    ]

    return AgentSummary(
        agent_id=agent.agent_id,
        slug=agent.slug,
        display_name=agent.display_name,
        persona_summary=agent.persona_summary,
        kind=str(agent.kind),
        is_active=bool(agent.is_active),
        created_at=agent.created_at.replace(tzinfo=None) if agent.created_at else None,
        subscriptions=[_subscription_payload(s, st) for s, st in subs_rows],
        discord_feed_routes=feed_routes,
        discord_voice_routes=voice_routes,
    )


@router.get("/agents", dependencies=[Depends(require_admin)], response_model=list[AgentSummary])
async def list_agents(session: AsyncSession = Depends(session_dep)) -> list[AgentSummary]:
    agents = (await session.execute(select(Agent).order_by(Agent.slug))).scalars().all()
    return [await _build_agent_summary(session, a) for a in agents]


@router.post("/agents", dependencies=[Depends(require_admin)], response_model=AgentSummary)
async def create_agent(
    body: AgentCreateRequest, session: AsyncSession = Depends(session_dep)
) -> AgentSummary:
    now = datetime.utcnow()
    agent = Agent(
        agent_id=uuid.uuid4(),
        slug=body.slug.strip(),
        display_name=body.display_name.strip(),
        persona_summary=(body.persona_summary.strip() if body.persona_summary else None),
        kind=body.kind.strip(),
        is_active=bool(body.is_active),
        created_at=now,
    )
    session.add(agent)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Agent slug already exists") from exc
    await session.refresh(agent)
    return await _build_agent_summary(session, agent)


@router.get(
    "/agents/{agent_id}", dependencies=[Depends(require_admin)], response_model=AgentSummary
)
async def get_agent(
    agent_id: uuid.UUID, session: AsyncSession = Depends(session_dep)
) -> AgentSummary:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await _build_agent_summary(session, agent)


@router.patch(
    "/agents/{agent_id}", dependencies=[Depends(require_admin)], response_model=AgentSummary
)
async def patch_agent(
    agent_id: uuid.UUID,
    body: AgentPatchRequest,
    session: AsyncSession = Depends(session_dep),
) -> AgentSummary:
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
