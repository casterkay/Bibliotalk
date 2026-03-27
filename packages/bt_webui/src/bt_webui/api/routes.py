from __future__ import annotations

import uuid
from datetime import UTC, datetime

from bt_store.models_runtime import PlatformRoute
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..db import session_dep
from ..models import DiscordFeedRouteUpsertRequest, DiscordVoiceRouteUpsertRequest

router = APIRouter()


@router.get(
    "/agents/{agent_id}/routes/discord/feed",
    dependencies=[Depends(require_admin)],
)
async def get_discord_feed_route(
    agent_id: uuid.UUID, session: AsyncSession = Depends(session_dep)
) -> dict:
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


@router.put(
    "/agents/{agent_id}/routes/discord/feed",
    dependencies=[Depends(require_admin)],
)
async def upsert_discord_feed_route(
    agent_id: uuid.UUID,
    body: DiscordFeedRouteUpsertRequest,
    session: AsyncSession = Depends(session_dep),
) -> dict:
    now = datetime.now(tz=UTC)
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
        raise HTTPException(status_code=409, detail="Route conflicts with existing row") from exc

    return {"ok": True, "route_id": str(route.route_id)}


@router.get(
    "/agents/{agent_id}/routes/discord/voice",
    dependencies=[Depends(require_admin)],
)
async def list_discord_voice_routes(
    agent_id: uuid.UUID, session: AsyncSession = Depends(session_dep)
) -> dict:
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
    out = []
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


@router.put(
    "/agents/{agent_id}/routes/discord/voice",
    dependencies=[Depends(require_admin)],
)
async def upsert_discord_voice_route(
    agent_id: uuid.UUID,
    body: DiscordVoiceRouteUpsertRequest,
    session: AsyncSession = Depends(session_dep),
) -> dict:
    clean_guild_id = body.guild_id.strip()
    now = datetime.now(tz=UTC)
    config_payload = {
        "voice_channel_id": body.voice_channel_id.strip(),
        "text_channel_id": (body.text_channel_id or "").strip() or None,
        "text_thread_id": (body.text_thread_id or "").strip() or None,
        "updated_by_user_id": body.updated_by_user_id.strip(),
        "updated_at": now.isoformat(),
    }

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
        raise HTTPException(status_code=409, detail="Route conflicts with existing row") from exc
    return {"ok": True, "route_id": str(route.route_id)}
