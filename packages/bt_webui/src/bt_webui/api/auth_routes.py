from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..auth import clear_admin_cookie, load_admin_auth_config, set_admin_cookie

router = APIRouter()


class LoginRequest(BaseModel):
    token: str


@router.post("/auth/login")
async def login(body: LoginRequest, response: Response) -> dict:
    cfg = load_admin_auth_config()
    supplied = (body.token or "").strip()
    if not supplied or supplied != cfg.token:
        raise HTTPException(status_code=401, detail="Invalid token")
    set_admin_cookie(response, token=supplied, cfg=cfg)
    return {"ok": True}


@router.post("/auth/logout")
async def logout(response: Response) -> dict:
    cfg = load_admin_auth_config()
    clear_admin_cookie(response, cfg=cfg)
    return {"ok": True}


@router.get("/auth/whoami")
async def whoami(request: Request) -> dict:
    cfg = load_admin_auth_config()
    token = (request.cookies.get("bt_admin_token") or "").strip()
    return {"ok": True, "authenticated": bool(token and token == cfg.token)}
