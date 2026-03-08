"""Google Gemini (text) providers.

This module intentionally depends on Google ADK when available. We keep imports
lazy so the rest of the service can run tests without requiring network access
or a configured API key.
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass
from uuid import uuid4

from ...models.citation import Evidence


class GeminiConfigurationError(RuntimeError):
    pass


def _uses_socks_proxy() -> bool:
    for key in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = (os.getenv(key) or "").strip().lower()
        if (
            value.startswith("socks5://")
            or value.startswith("socks5h://")
            or value.startswith("socks4://")
            or value.startswith("socks://")
        ):
            return True
    return False


def _truncate(text: str, *, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _build_prompt(query: str, evidence: list[Evidence]) -> str:
    lines: list[str] = []
    lines.append("Question:")
    lines.append(query.strip())
    lines.append("")
    lines.append("Evidence excerpts (do not invent facts beyond these excerpts):")
    for idx, item in enumerate(evidence, start=1):
        excerpt = _truncate(item.text, max_chars=1200)
        header = f"[{idx}] {item.source_title} ({item.platform})"
        lines.append(header)
        lines.append(excerpt)
        lines.append("")

    lines.append("Rules:")
    lines.append("- Use ONLY the evidence excerpts above.")
    lines.append(
        '- If evidence is insufficient, reply exactly: "I couldn\'t find relevant supporting evidence for that question."'
    )
    lines.append("- Do not use citation indices or a trailing Sources section.")
    lines.append("- Keep the answer concise and grounded in the provided evidence.")
    return "\n".join(lines).strip()


@dataclass
class AdkGeminiLLM:
    """Gemini-backed LLM using Google ADK's execution model."""

    model_name: str
    app_name: str = "bibliotalk"
    temperature: float = 0.2
    max_output_tokens: int = 800

    async def generate(self, *, persona_prompt: str, query: str, evidence: list[Evidence]) -> str:
        google_api_key = os.getenv("GOOGLE_API_KEY")
        if not google_api_key:
            raise GeminiConfigurationError("Missing GOOGLE_API_KEY for Gemini via ADK.")

        if _uses_socks_proxy():
            try:
                import socksio  # noqa: F401
            except Exception as exc:
                raise GeminiConfigurationError(
                    "SOCKS proxy detected but dependencies are missing. "
                    "Install httpx socks support (e.g. `uv sync` after adding `httpx[socks]`) "
                    "or unset ALL_PROXY/HTTP_PROXY/HTTPS_PROXY."
                ) from exc

        try:
            from google.adk.agents import Agent
            from google.adk.runners import InMemoryRunner
            from google.genai import types
        except Exception as exc:
            raise GeminiConfigurationError(
                "Google ADK/Gemini dependencies are not installed."
            ) from exc

        instruction = textwrap.dedent(
            f"""
            You are a Bibliotalk Ghost.

            Persona:
            {persona_prompt.strip()}

            You must be evidence-grounded (言必有據) and follow the rules in the user's message.
            """
        ).strip()

        prompt = _build_prompt(query, evidence)

        agent = Agent(
            name="ghost",
            model=self.model_name,
            instruction=instruction,
            generate_content_config=types.GenerateContentConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
            ),
        )

        runner = InMemoryRunner(agent=agent, app_name=self.app_name)
        user_id = "discord"
        session_id = f"stateless-{uuid4()}"
        await runner.session_service.create_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
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

        final_text = (final_text or "").strip()
        if not final_text:
            raise RuntimeError("Gemini returned an empty response.")
        return final_text
