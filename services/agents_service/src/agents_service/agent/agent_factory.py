"""Spirit agent factory and lightweight runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ClassVar
from uuid import UUID

from bt_common.config import get_emos_fallback_settings
from bt_common.evermemos_client import EverMemOSClient
from bt_common.exceptions import AgentNotFoundError

from ..models.citation import (
    NO_EVIDENCE_RESPONSE,
    Evidence,
    extract_memory_links,
    validate_evidence_links,
)
from ..store import Store
from .providers.gemini import GeminiConfigurationError
from .tools.emit_citations import EmitCitationsTool
from .tools.memory_search import MemorySearchTool

MemorySearchFn = Callable[[str, str], Awaitable[list[Evidence]]]
EmitCitationsFn = Callable[[list[Evidence], str], Awaitable[list]]

_CACHE: dict[str, tuple[float, SpiritAgent]] = {}
_CACHE_LOCK = asyncio.Lock()
logger = logging.getLogger("agents_service.agent")


@dataclass
class _EchoLLM:
    model_name: str

    async def generate(self, *, persona_prompt: str, query: str, evidence: list[Evidence]) -> str:
        _ = persona_prompt
        _ = evidence
        return query


class LLMRegistry:
    _models: ClassVar[dict[str, Any]] = {}

    @classmethod
    def register(cls, model: str, llm: Any) -> None:
        cls._models[model] = llm

    @classmethod
    def resolve(cls, model: str) -> Any:
        if model not in cls._models:
            if model.startswith("gemini-"):
                try:
                    from .providers.gemini import AdkGeminiLLM

                    cls._models[model] = AdkGeminiLLM(model_name=model)
                except Exception:
                    cls._models[model] = _EchoLLM(model_name=model)
            else:
                cls._models[model] = _EchoLLM(model_name=model)
        return cls._models[model]

    @classmethod
    def init_defaults(cls) -> None:
        # Prefer ADK-backed Gemini when available; fall back to echo for local tests.
        try:
            from .providers.gemini import AdkGeminiLLM

            cls._models.setdefault("gemini-2.5-flash", AdkGeminiLLM("gemini-2.5-flash"))
        except Exception:
            cls._models.setdefault("gemini-2.5-flash", _EchoLLM("gemini-2.5-flash"))


@dataclass
class SpiritAgent:
    id: str
    agent_slug: str
    name: str
    instruction: str
    model: str
    llm: Any
    memory_search_fn: MemorySearchFn
    emit_citations_fn: EmitCitationsFn
    is_active: bool = True

    async def run(self, query: str) -> dict[str, Any]:
        try:
            evidence = await self.memory_search_fn(query, self.id)
        except Exception:
            logger.exception("memory_search failed agent_id=%s", self.id)
            return {
                "text": "My memory is temporarily unavailable.",
                "citations": [],
            }
        if not evidence:
            return {
                "text": NO_EVIDENCE_RESPONSE,
                "citations": [],
                "evidence": [],
            }

        try:
            text = await self.llm.generate(
                persona_prompt=self.instruction, query=query, evidence=evidence
            )
        except GeminiConfigurationError:
            return {
                "text": "My language model is not configured right now.",
                "citations": [],
            }
        except Exception as exc:
            logger.exception("llm.generate failed agent_id=%s model=%s", self.id, self.model)
            if os.getenv("LOG_LEVEL", "").upper() == "DEBUG":
                detail = str(exc).strip() or type(exc).__name__
                return {
                    "text": f"I ran into an error while composing a response. ({type(exc).__name__}: {detail})",
                    "citations": [],
                }
            return {
                "text": "I ran into an error while composing a response. (Set LOG_LEVEL=DEBUG to see details.)",
                "citations": [],
            }

        try:
            citations = await self.emit_citations_fn(evidence, self.id)
        except Exception:
            citations = []
        response_text = text.strip()
        if citations and not extract_memory_links(response_text):
            response_text = f"{response_text} {citations[0]}".strip()
        response_text = validate_evidence_links(
            response_text,
            evidence,
            agent_emos_user_id=self.agent_slug,
        )
        if not extract_memory_links(response_text):
            response_text = NO_EVIDENCE_RESPONSE
            citations = []
            evidence = []
        return {"text": response_text, "citations": citations, "evidence": evidence}


async def create_spirit_agent(
    agent_id: UUID,
    *,
    store: Store,
    llm_registry: Any | None = None,
    memory_search_fn: MemorySearchFn | None = None,
    emit_citations_fn: EmitCitationsFn | None = None,
    cache_ttl_seconds: int = 60,
) -> SpiritAgent:
    key = str(agent_id)
    now = time.time()

    async with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and (now - cached[0]) < cache_ttl_seconds:
            return cached[1]

    agent_row = await store.get_agent(agent_id)
    if not agent_row:
        raise AgentNotFoundError(f"Agent {agent_id} not found")

    if memory_search_fn is None:
        memory_tool: MemorySearchTool | None = None
        emos_user_id: str | None = None

        async def _default_memory_search(query: str, _agent_id: str) -> list[Evidence]:
            nonlocal memory_tool
            nonlocal emos_user_id
            if memory_tool is None:
                emos_config = await store.get_agent_emos_config(agent_id) or {}
                emos_fallback = get_emos_fallback_settings()
                emos_user_id = str(emos_config.get("tenant_prefix") or agent_id)
                evermemos_client = EverMemOSClient(
                    emos_config.get("emos_base_url") or emos_fallback.EMOS_BASE_URL or "",
                    api_key=(
                        emos_config.get("emos_api_key_encrypted")
                        or emos_config.get("emos_api_key")
                        or emos_fallback.EMOS_API_KEY
                    ),
                )
                memory_tool = MemorySearchTool(
                    evermemos_client=evermemos_client,
                    sources_by_group_ids_provider=lambda group_ids: store.get_sources_by_emos_group_ids(
                        group_ids
                    ),
                    segments_by_source_ids_provider=lambda source_ids: store.get_segments_by_source_ids(
                        source_ids
                    ),
                    segments_for_agent_provider=lambda lookup_agent_id: store.get_segments_for_agent(
                        UUID(lookup_agent_id)
                    ),
                )
            # EverMemOS user_id is a tenant prefix (local dev: a slug like "confucius").
            return await memory_tool(query, emos_user_id or str(agent_id))

        memory_search_fn = _default_memory_search

    if emit_citations_fn is None:
        emit_tool = EmitCitationsTool(
            segments_by_ids_provider=lambda segment_ids: store.get_segments_by_ids(segment_ids)
        )
        emit_citations_fn = emit_tool

    registry = llm_registry or LLMRegistry
    if hasattr(registry, "init_defaults"):
        registry.init_defaults()
    model = agent_row.get("llm_model", "gemini-2.5-flash")
    llm = registry.resolve(model)

    spirit = SpiritAgent(
        id=key,
        agent_slug=agent_row.get("emos_user_id", key),
        name=agent_row["display_name"],
        instruction=agent_row["persona_prompt"],
        model=model,
        llm=llm,
        memory_search_fn=memory_search_fn,
        emit_citations_fn=emit_citations_fn,
        is_active=bool(agent_row.get("is_active", True)),
    )

    async with _CACHE_LOCK:
        _CACHE[key] = (time.time(), spirit)
    return spirit
