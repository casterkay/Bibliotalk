from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from uuid import uuid4

from .agent_directory import AgentInfo

logger = logging.getLogger("discord_service")


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    speaker_slugs: list[str]
    facilitator_note: str | None = None
    used_ai: bool = False


class FacilitatorRouter:
    """AI facilitator that chooses which character(s) should reply.

    This is best-effort: when Gemini is not configured, the caller should fall back
    to deterministic routing.
    """

    def __init__(self, *, model: str = "gemini-2.5-flash") -> None:
        self._model = model

    async def route(
        self,
        *,
        message: str,
        participants: list[AgentInfo],
        last_speaker_slug: str | None,
    ) -> RoutingDecision | None:
        if not participants:
            return None
        if os.getenv("BIBLIOTALK_ENABLE_AI_ROUTER", "").strip().lower() not in {
            "1",
            "true",
            "yes",
        }:
            return None
        if not (os.getenv("GOOGLE_API_KEY") or "").strip():
            return None

        try:
            from google.adk.agents import Agent
            from google.adk.runners import InMemoryRunner
            from google.genai import types
        except Exception:
            return None

        roster_lines = [
            f"- {p.display_name} (slug: {p.agent_slug})" for p in participants
        ]
        roster = "\n".join(roster_lines)
        previous = last_speaker_slug or ""

        prompt = (
            "You are the Bibliotalk facilitator.\n"
            "Choose which character(s) should respond to the user's message.\n\n"
            f"Participants:\n{roster}\n\n"
            f"Previous speaker slug (may be empty): {previous}\n\n"
            "User message:\n"
            f"{(message or '').strip()}\n\n"
            "Return ONLY valid JSON with this schema:\n"
            '{ "speakers": ["slug1"], "facilitator_note": "optional short note or null" }\n\n'
            "Rules:\n"
            "- Choose 1 speaker by default; choose 2 only if clearly helpful.\n"
            "- Speakers MUST be slugs from the participant list.\n"
            "- facilitator_note is optional and should be <= 200 characters.\n"
        ).strip()

        agent = Agent(
            name="facilitator",
            model=self._model,
            instruction="Be strict. Output JSON only.",
            generate_content_config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=256,
            ),
        )

        runner = InMemoryRunner(agent=agent, app_name="bibliotalk")
        user_id = "discord"
        session_id = f"facilitator-{uuid4()}"
        await runner.session_service.create_session(
            app_name="bibliotalk", user_id=user_id, session_id=session_id
        )

        final_text: str | None = None
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(parts=[types.Part(text=prompt)]),
        ):
            if event.is_final_response():
                parts = getattr(getattr(event, "content", None), "parts", None)
                if parts:
                    final_text = getattr(parts[0], "text", None)

        raw = (final_text or "").strip()
        if not raw:
            return None

        try:
            payload = json.loads(raw)
        except Exception:
            logger.warning("facilitator router returned non-json response")
            return None

        allowed = {p.agent_slug for p in participants}
        speakers = [
            str(item).strip()
            for item in list(payload.get("speakers") or [])
            if str(item).strip()
        ]
        speakers = [slug for slug in speakers if slug in allowed][:2]
        if not speakers:
            return None

        note = payload.get("facilitator_note")
        note_text = str(note).strip() if isinstance(note, str) else None
        if note_text and len(note_text) > 200:
            note_text = note_text[:197].rstrip() + "..."

        return RoutingDecision(
            speaker_slugs=speakers,
            facilitator_note=note_text or None,
            used_ai=True,
        )
