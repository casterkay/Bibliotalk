from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request


def _expected_token() -> str:
    token = (os.getenv("BIBLIOTALK_ADMIN_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Missing BIBLIOTALK_ADMIN_TOKEN")
    return token


def _extract_bearer_token(request: Request) -> str | None:
    auth = (request.headers.get("authorization") or "").strip()
    if not auth:
        return None
    prefix = "bearer "
    if auth.lower().startswith(prefix):
        value = auth[len(prefix) :].strip()
        return value or None
    return None


async def require_admin(request: Request) -> None:
    try:
        expected = _expected_token()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    supplied = _extract_bearer_token(request)
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
