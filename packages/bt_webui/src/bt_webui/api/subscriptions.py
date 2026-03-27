from __future__ import annotations

import uuid
from datetime import UTC, datetime

from bt_store.models_ingestion import Subscription, SubscriptionState
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..db import session_dep
from ..models import SubscriptionCreateRequest, SubscriptionPatchRequest

router = APIRouter()


@router.get(
    "/agents/{agent_id}/subscriptions",
    dependencies=[Depends(require_admin)],
)
async def list_agent_subscriptions(
    agent_id: uuid.UUID, session: AsyncSession = Depends(session_dep)
) -> list[dict]:
    rows = (
        await session.execute(
            select(Subscription, SubscriptionState)
            .outerjoin(
                SubscriptionState, SubscriptionState.subscription_id == Subscription.subscription_id
            )
            .where(Subscription.agent_id == agent_id)
            .order_by(Subscription.created_at.desc())
        )
    ).all()
    out = []
    for sub, st in rows:
        out.append(
            {
                "subscription_id": str(sub.subscription_id),
                "agent_id": str(sub.agent_id),
                "content_platform": sub.content_platform,
                "subscription_type": sub.subscription_type,
                "subscription_url": sub.subscription_url,
                "poll_interval_minutes": sub.poll_interval_minutes,
                "is_active": bool(sub.is_active),
                "created_at": sub.created_at.isoformat() if sub.created_at else None,
                "state": {
                    "last_seen_external_id": st.last_seen_external_id if st else None,
                    "last_published_at": st.last_published_at.isoformat()
                    if (st and st.last_published_at)
                    else None,
                    "last_polled_at": st.last_polled_at.isoformat()
                    if (st and st.last_polled_at)
                    else None,
                    "failure_count": int(st.failure_count) if st else 0,
                    "next_retry_at": st.next_retry_at.isoformat()
                    if (st and st.next_retry_at)
                    else None,
                    "updated_at": st.updated_at.isoformat() if (st and st.updated_at) else None,
                },
            }
        )
    return out


@router.post(
    "/agents/{agent_id}/subscriptions",
    dependencies=[Depends(require_admin)],
)
async def create_subscription(
    agent_id: uuid.UUID,
    body: SubscriptionCreateRequest,
    session: AsyncSession = Depends(session_dep),
) -> dict:
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


@router.patch(
    "/subscriptions/{subscription_id}",
    dependencies=[Depends(require_admin)],
)
async def patch_subscription(
    subscription_id: uuid.UUID,
    body: SubscriptionPatchRequest,
    session: AsyncSession = Depends(session_dep),
) -> dict:
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
