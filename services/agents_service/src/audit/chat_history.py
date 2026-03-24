from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from bt_store.engine import session_scope
from bt_store.models_runtime import TalkThread

logger = logging.getLogger("agents_service.audit")


@dataclass(frozen=True, slots=True)
class ChatEvent:
    platform: str
    room_id: str
    sender_platform_user_id: str
    content: str
    modality: str
    sender_agent_id: UUID | None = None
    platform_event_id: str | None = None
    citations: dict | None = None


async def persist_chat_event(event: ChatEvent) -> None:
    try:
        async with session_scope() as session:
            row = TalkThread(
                thread_id=uuid4(),
                platform=event.platform,
                room_id=event.room_id,
                sender_agent_id=event.sender_agent_id,
                sender_platform_user_id=event.sender_platform_user_id,
                platform_event_id=event.platform_event_id,
                modality=event.modality,
                content=event.content,
                citations_json=event.citations or {"version": "1", "items": []},
                created_at=datetime.now(UTC),
            )
            session.add(row)
            await session.commit()
    except Exception:
        logger.exception(
            "talk_threads persist failed (is bt_store migrated?) platform=%s room_id=%s",
            event.platform,
            event.room_id,
        )
