from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from bt_common.exceptions import AgentNotFoundError
from bt_store.engine import get_session_factory
from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..agent.agent_factory import create_spirit_agent
from ..audit.chat_history import ChatEvent, persist_chat_event
from ..models.citation import build_verifiable_quote
from ..store import SQLiteAgentStore
from .errors import APIError, ErrorCode

router = APIRouter()


class TurnRequest(BaseModel):
    platform: str
    room_id: str
    event_id: str | None = None
    sender_platform_user_id: str
    sender_display_name: str | None = None
    text: str
    mentions: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
    modality: Literal["text", "voice"] = "text"


class Citation(BaseModel):
    segment_id: UUID
    emos_message_id: str
    source_title: str
    source_url: str
    quote: str
    content_platform: str
    timestamp: datetime | None = None


class TurnResponse(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)
    no_evidence: bool = False


def _now_utc() -> datetime:
    return datetime.now(UTC)


@router.post("/agents/{agent_id}/turn", response_model=TurnResponse)
async def create_turn(agent_id: UUID, request: TurnRequest) -> TurnResponse:
    session_factory = get_session_factory()
    store = SQLiteAgentStore(session_factory)

    try:
        agent = await create_spirit_agent(agent_id, store=store)
    except AgentNotFoundError as exc:
        raise APIError(code=ErrorCode.AGENT_NOT_FOUND, message=str(exc), http_status=404) from exc

    if not agent.is_active:
        raise APIError(code=ErrorCode.AGENT_INACTIVE, message="Agent is inactive", http_status=403)

    await persist_chat_event(
        ChatEvent(
            platform=request.platform,
            room_id=request.room_id,
            sender_platform_user_id=request.sender_platform_user_id,
            sender_agent_id=None,
            platform_event_id=request.event_id,
            modality=request.modality,
            content=request.text,
            citations=None,
        )
    )

    result = await agent.run(request.text)
    text = (result.get("text") or "").strip()
    evidence = list(result.get("evidence") or [])

    citations: list[Citation] = []
    for ev in evidence[:10]:
        quote = build_verifiable_quote(ev.text, max_chars=200)
        if not quote:
            continue
        citations.append(
            Citation(
                segment_id=ev.segment_id,
                emos_message_id=ev.emos_message_id or "",
                source_title=ev.source_title,
                source_url=ev.source_url,
                quote=quote,
                content_platform=ev.platform,
                timestamp=ev.memory_timestamp,
            )
        )

    no_evidence = not citations and "couldn't find relevant supporting evidence" in text.lower()

    citations_payload = {"version": "1", "items": [c.model_dump(mode="json") for c in citations]}
    await persist_chat_event(
        ChatEvent(
            platform=request.platform,
            room_id=request.room_id,
            sender_platform_user_id=f"agent:{agent_id}",
            sender_agent_id=agent_id,
            platform_event_id=None,
            modality=request.modality,
            content=text,
            citations=citations_payload,
        )
    )

    return TurnResponse(text=text, citations=citations, no_evidence=no_evidence)
