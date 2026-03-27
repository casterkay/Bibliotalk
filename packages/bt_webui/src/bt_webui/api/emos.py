from __future__ import annotations

from bt_common.config import get_settings
from bt_common.evermemos_client import EverMemOSClient
from bt_store.models_core import Agent
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..db import session_dep
from ..models import EMOSGetMemoriesRequest

router = APIRouter()


@router.post("/emos/memories/get", dependencies=[Depends(require_admin)])
async def emos_get_memories(
    body: EMOSGetMemoriesRequest, session: AsyncSession = Depends(session_dep)
) -> dict:
    agent = (
        (await session.execute(select(Agent).where(Agent.agent_id == body.agent_id)))
        .scalars()
        .first()
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    settings = get_settings()
    base_url = (settings.EMOS_BASE_URL or "").strip()
    if not base_url:
        raise HTTPException(status_code=500, detail="Missing EMOS_BASE_URL")

    client = EverMemOSClient(base_url, api_key=settings.EMOS_API_KEY)
    try:
        payload = await client.get_memories(
            user_id=agent.slug,
            group_id=body.group_id,
            memory_type=body.memory_type,
            limit=int(body.limit),
            offset=int(body.offset),
        )
        return payload
    finally:
        await client.aclose()
