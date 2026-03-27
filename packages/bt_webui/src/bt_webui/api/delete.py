from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_admin
from ..settings import load_webui_settings

router = APIRouter()


def _admin_token() -> str:
    token = (os.getenv("BIBLIOTALK_ADMIN_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Missing BIBLIOTALK_ADMIN_TOKEN")
    return token


@router.delete("/sources/{source_id}", dependencies=[Depends(require_admin)])
async def delete_source(source_id: str) -> dict:
    settings = load_webui_settings()
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.delete(
            f"{settings.memories_service_url}/v1/admin/sources/{source_id}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()
