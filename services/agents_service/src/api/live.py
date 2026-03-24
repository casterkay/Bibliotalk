from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from bt_common.exceptions import AgentNotFoundError
from bt_store.engine import get_session_factory
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..agent.agent_factory import create_spirit_agent
from ..audit.chat_history import ChatEvent, persist_chat_event
from ..live.gemini_live_backend import (
    DEFAULT_GEMINI_LIVE_MODEL,
    GeminiLiveBackend,
    GeminiLiveConfig,
)
from ..live.session_manager import LiveSessionManager
from ..store import SQLiteAgentStore
from .errors import APIError, ErrorCode

router = APIRouter()
_sessions = LiveSessionManager()


class CreateSessionRequest(BaseModel):
    platform: str
    room_id: str
    initiator_platform_user_id: str
    modality: Literal["text", "voice"]


class CreateSessionResponse(BaseModel):
    session_id: str
    ws_url: str


def _ts() -> str:
    return datetime.now(UTC).isoformat()


def _ws_url(request: Request, session_id: str) -> str:
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host") or request.url.netloc
    return f"{scheme}://{host}/v1/agents/live/ws?session_id={session_id}"


@router.post("/agents/{agent_id}/live/sessions", response_model=CreateSessionResponse)
async def create_live_session(
    agent_id: UUID, request: Request, body: CreateSessionRequest
) -> CreateSessionResponse:
    session_factory = get_session_factory()
    store = SQLiteAgentStore(session_factory)
    try:
        agent = await create_spirit_agent(agent_id, store=store)
    except AgentNotFoundError as exc:
        raise APIError(code=ErrorCode.AGENT_NOT_FOUND, message=str(exc), http_status=404) from exc
    if not agent.is_active:
        raise APIError(code=ErrorCode.AGENT_INACTIVE, message="Agent is inactive", http_status=403)

    session = await _sessions.create_session(
        agent_id=agent_id,
        platform=body.platform,
        room_id=body.room_id,
        initiator_platform_user_id=body.initiator_platform_user_id,
        modality=body.modality,
    )
    return CreateSessionResponse(
        session_id=session.session_id, ws_url=_ws_url(request, session.session_id)
    )


@router.websocket("/agents/live/ws")
async def live_ws(websocket: WebSocket, session_id: str):
    session = await _sessions.get(session_id)
    if session is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()

    session_factory = get_session_factory()
    store = SQLiteAgentStore(session_factory)
    try:
        agent = await create_spirit_agent(session.agent_id, store=store)
    except AgentNotFoundError:
        await websocket.close(code=4404)
        return

    voice_backend: GeminiLiveBackend | None = None
    voice_forward_task: asyncio.Task | None = None

    async def ensure_voice_backend() -> GeminiLiveBackend | None:
        nonlocal voice_backend
        nonlocal voice_forward_task

        if voice_backend is not None:
            return voice_backend

        google_api_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
        if not google_api_key:
            await send_envelope(
                "error",
                session.active_turn_id or "",
                {"code": "INTERNAL_ERROR", "message": "Missing GOOGLE_API_KEY for voice"},
            )
            return None

        model = (os.getenv("GEMINI_LIVE_MODEL") or "").strip() or DEFAULT_GEMINI_LIVE_MODEL
        voice_backend = GeminiLiveBackend(
            GeminiLiveConfig(google_api_key=google_api_key, model=model)
        )
        await voice_backend.connect()

        async def _forward() -> None:
            assert voice_backend is not None
            async for ev in voice_backend.events():
                turn_id = session.active_turn_id or ""
                if not turn_id:
                    continue
                if ev.get("type") == "audio":
                    data: bytes = ev["data"]
                    await send_envelope(
                        "output.audio.chunk",
                        turn_id,
                        {"pcm24k_b64": base64.b64encode(data).decode("ascii")},
                    )
                elif ev.get("type") == "transcription.input":
                    await send_envelope(
                        "output.transcription.input",
                        turn_id,
                        {"text": ev.get("text") or "", "is_final": True},
                    )
                elif ev.get("type") == "transcription.output":
                    await send_envelope(
                        "output.transcription.output",
                        turn_id,
                        {"text": ev.get("text") or "", "is_final": True},
                    )

        voice_forward_task = asyncio.create_task(_forward())
        return voice_backend

    async def send_envelope(type_: str, turn_id: str, payload: dict[str, Any]) -> None:
        await websocket.send_text(
            json.dumps({"type": type_, "ts": _ts(), "turn_id": turn_id, "payload": payload})
        )

    async def run_turn(turn_id: str, text: str) -> None:
        result = await agent.run(text)
        out_text = (result.get("text") or "").strip()
        evidence = list(result.get("evidence") or [])

        citations: list[dict[str, Any]] = []
        for ev in evidence[:10]:
            quote = " ".join((ev.text or "").split()).strip()
            quote = quote[:200] if len(quote) > 200 else quote
            if not quote:
                continue
            citations.append(
                {
                    "segment_id": str(ev.segment_id),
                    "emos_message_id": ev.emos_message_id or "",
                    "source_title": ev.source_title,
                    "source_url": ev.source_url,
                    "quote": quote,
                    "content_platform": ev.platform,
                    "timestamp": ev.memory_timestamp.isoformat() if ev.memory_timestamp else None,
                }
            )

        if out_text:
            chunk = max(1, len(out_text) // 3)
            for i in range(0, len(out_text), chunk):
                await send_envelope("output.text.delta", turn_id, {"text": out_text[i : i + chunk]})
                await asyncio.sleep(0)

        await send_envelope("output.text.final", turn_id, {"text": out_text})
        await send_envelope("output.citations.final", turn_id, {"version": "1", "items": citations})
        await send_envelope(
            "output.turn.end",
            turn_id,
            {"no_evidence": not citations, "has_citations": bool(citations)},
        )

        await persist_chat_event(
            ChatEvent(
                platform=session.platform,
                room_id=session.room_id,
                sender_platform_user_id=f"agent:{session.agent_id}",
                sender_agent_id=session.agent_id,
                modality=session.modality,
                content=out_text,
                citations={"version": "1", "items": citations},
            )
        )

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")
            turn_id = str(msg.get("turn_id") or "")

            if msg_type == "input.text":
                payload = msg.get("payload") or {}
                text = str(payload.get("text") or "")

                await persist_chat_event(
                    ChatEvent(
                        platform=session.platform,
                        room_id=session.room_id,
                        sender_platform_user_id=session.initiator_platform_user_id,
                        sender_agent_id=None,
                        modality=session.modality,
                        content=text,
                        citations=None,
                    )
                )

                if session.active_task and not session.active_task.done():
                    prev_turn = session.active_turn_id
                    session.active_task.cancel()
                    if prev_turn:
                        await send_envelope(
                            "output.interrupted", prev_turn, {"reason": "superseded"}
                        )

                session.active_turn_id = turn_id
                session.active_task = asyncio.create_task(run_turn(turn_id, text))
                continue

            if msg_type == "input.cancel":
                if (
                    session.active_task
                    and not session.active_task.done()
                    and session.active_turn_id == turn_id
                ):
                    session.active_task.cancel()
                    await send_envelope("output.interrupted", turn_id, {"reason": "cancelled"})
                    session.active_task = None
                    session.active_turn_id = None
                continue

            if msg_type in {"input.audio.chunk", "input.audio.stream_end"}:
                if session.modality != "voice":
                    await send_envelope(
                        "error",
                        turn_id,
                        {"code": "INTERNAL_ERROR", "message": "Session modality is not voice"},
                    )
                    continue

                backend = await ensure_voice_backend()
                if backend is None:
                    continue

                session.active_turn_id = turn_id or session.active_turn_id

                if msg_type == "input.audio.chunk":
                    payload = msg.get("payload") or {}
                    pcm_b64 = payload.get("pcm16k_b64") or ""
                    try:
                        pcm = base64.b64decode(pcm_b64)
                    except Exception:
                        await send_envelope(
                            "error",
                            turn_id,
                            {"code": "INTERNAL_ERROR", "message": "Invalid base64 audio payload"},
                        )
                        continue
                    await backend.send_audio_chunk(pcm16k=pcm)
                # input.audio.stream_end is currently a no-op when VAD is enabled (MVP).
                continue

            await send_envelope(
                "error",
                turn_id,
                {"code": "INTERNAL_ERROR", "message": f"Unknown message type: {msg_type}"},
            )

    except WebSocketDisconnect:
        if session.active_task and not session.active_task.done():
            session.active_task.cancel()
    except Exception:
        await websocket.close(code=1011)
    finally:
        if voice_forward_task and not voice_forward_task.done():
            voice_forward_task.cancel()
        if voice_backend is not None:
            await voice_backend.aclose()
