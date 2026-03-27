from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

ADMIN_COOKIE_NAME = "bt_admin_token"


@dataclass(frozen=True, slots=True)
class AdminAuthConfig:
    token: str
    cookie_secure: bool = True
    cookie_samesite: str = "lax"


def load_admin_auth_config() -> AdminAuthConfig:
    token = (os.getenv("BIBLIOTALK_ADMIN_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("Missing BIBLIOTALK_ADMIN_TOKEN")

    secure_raw = (os.getenv("BIBLIOTALK_WEBUI_COOKIE_SECURE") or "").strip().lower()
    cookie_secure = True if secure_raw in {"", "1", "true", "yes"} else False
    samesite = (os.getenv("BIBLIOTALK_WEBUI_COOKIE_SAMESITE") or "lax").strip().lower()
    if samesite not in {"lax", "strict", "none"}:
        samesite = "lax"
    return AdminAuthConfig(token=token, cookie_secure=cookie_secure, cookie_samesite=samesite)


def _extract_bearer_token(request: Request) -> str | None:
    auth = (request.headers.get("authorization") or "").strip()
    if not auth:
        return None
    prefix = "bearer "
    if auth.lower().startswith(prefix):
        value = auth[len(prefix) :].strip()
        return value or None
    return None


def _extract_cookie_token(request: Request) -> str | None:
    value = (request.cookies.get(ADMIN_COOKIE_NAME) or "").strip()
    return value or None


async def require_admin(request: Request) -> None:
    try:
        cfg = load_admin_auth_config()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    supplied = _extract_bearer_token(request) or _extract_cookie_token(request)
    if not supplied or not secrets.compare_digest(supplied, cfg.token):
        raise HTTPException(status_code=401, detail="Unauthorized")


def set_admin_cookie(response: Response, *, token: str, cfg: AdminAuthConfig) -> None:
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
        path="/",
        max_age=60 * 60 * 24 * 7,
    )


def clear_admin_cookie(response: Response, *, cfg: AdminAuthConfig) -> None:
    response.delete_cookie(
        key=ADMIN_COOKIE_NAME,
        path="/",
        secure=cfg.cookie_secure,
        samesite=cfg.cookie_samesite,
    )
