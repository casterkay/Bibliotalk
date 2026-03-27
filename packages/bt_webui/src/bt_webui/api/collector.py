from __future__ import annotations

import os

import httpx
from bt_store.models_core import Agent
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..db import session_dep
from ..models import CollectorRunOnceRequest
from ..settings import load_webui_settings

router = APIRouter()


def _admin_token() -> str:
    token = (os.getenv("BIBLIOTALK_ADMIN_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Missing BIBLIOTALK_ADMIN_TOKEN")
    return token


@router.post("/collector/run-once", dependencies=[Depends(require_admin)])
async def collector_run_once(
    body: CollectorRunOnceRequest, session: AsyncSession = Depends(session_dep)
) -> dict:
    agent_slug = None
    if body.agent_id is not None:
        agent = (
            (await session.execute(select(Agent).where(Agent.agent_id == body.agent_id)))
            .scalars()
            .first()
        )
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        agent_slug = agent.slug

    settings = load_webui_settings()
    url = f"{settings.memories_service_url}/v1/admin/collector/run-once"
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={"agent_slug": agent_slug},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()
