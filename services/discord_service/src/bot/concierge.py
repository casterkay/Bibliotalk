from __future__ import annotations

import logging
import os
from uuid import uuid4

import discord

from discord_service.talks.agent_directory import AgentDirectory

logger = logging.getLogger("discord_service")


class DMConcierge:
    def __init__(
        self,
        *,
        agent_directory: AgentDirectory,
        logger_: logging.Logger | None = None,
        model: str = "gemini-2.5-flash",
    ) -> None:
        self._directory = agent_directory
        self._logger = logger_ or logger
        self._model = model

    async def handle(
        self,
        *,
        channel: discord.DMChannel,
        author: discord.User | discord.Member,
        content: str,
    ) -> None:
        message = (content or "").strip()
        if not message:
            return

        reply = await self._generate_reply(message)
        await channel.send(
            reply[:2000], allowed_mentions=discord.AllowedMentions.none()
        )

    async def _generate_reply(self, message: str) -> str:
        agents = self._directory.list_agents()
        roster = ", ".join(sorted({a.display_name for a in agents})) or "(none seeded)"

        if os.getenv("BIBLIOTALK_ENABLE_AI_CONCIERGE", "").strip().lower() not in {
            "1",
            "true",
            "yes",
        }:
            return self._fallback_reply(message, roster=roster)
        if not (os.getenv("GOOGLE_API_KEY") or "").strip():
            return self._fallback_reply(message, roster=roster)

        try:
            from google.adk.agents import Agent
            from google.adk.runners import InMemoryRunner
            from google.genai import types
        except Exception:
            return self._fallback_reply(message, roster=roster)

        prompt = (
            "You are Bibliotalk Concierge.\n"
            "Your job is to help the user start or find private talks.\n\n"
            f"Available characters: {roster}\n\n"
            "User message:\n"
            f"{message}\n\n"
            "Guidelines:\n"
            "- Be concise.\n"
            "- Tell them to use `/talk Character A, Character B` to start a talk.\n"
            "- Tell them to use `/talks` to list recent talks.\n"
            "- Do not role-play as a character; stay as concierge.\n"
        ).strip()

        agent = Agent(
            name="concierge",
            model=self._model,
            instruction="Be helpful and concise.",
            generate_content_config=types.GenerateContentConfig(
                temperature=0.4,
                max_output_tokens=256,
            ),
        )
        runner = InMemoryRunner(agent=agent, app_name="bibliotalk")
        user_id = "discord"
        session_id = f"concierge-{uuid4()}"
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

        text = (final_text or "").strip()
        if not text:
            return self._fallback_reply(message, roster=roster)
        return text

    def _fallback_reply(self, message: str, *, roster: str) -> str:
        _ = message
        return (
            "To start a private talk, DM me and run:\n"
            "`/talk Character A, Character B`\n\n"
            "To list past talks:\n"
            "`/talks`\n\n"
            f"Available characters: {roster}"
        )
