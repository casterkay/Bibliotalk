"""Ghost agent factory and lightweight runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from bt_common.config import get_emos_fallback_settings
from bt_common.evermemos_client import EverMemOSClient
from bt_common.exceptions import AgentNotFoundError

from ..database.store import Store
from ..models.citation import Evidence
from .providers.gemini import GeminiConfigurationError
from .tools.emit_citations import EmitCitationsTool
from .tools.memory_search import MemorySearchTool

MemorySearchFn = Callable[[str, str], Awaitable[list[Evidence]]]
EmitCitationsFn = Callable[[list[Evidence], str], Awaitable[list]]

_CACHE: dict[str, tuple[float, "GhostAgent"]] = {}
_CACHE_LOCK = asyncio.Lock()
logger = logging.getLogger("agents_service.agent")


@dataclass
class _EchoLLM:
    model_name: str

    async def generate(
        self, *, persona_prompt: str, query: str, evidence: list[Evidence]
    ) -> str:
        _ = persona_prompt
        _ = evidence
        return query


class LLMRegistry:
    _models: dict[str, Any] = {}

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
                except Exception:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            cls._models.setdefault("gemini-2.5-flash", _EchoLLM("gemini-2.5-flash"))
        cls._models.setdefault("nova-lite-v2", _EchoLLM("nova-lite-v2"))


@dataclass
class GhostAgent:
    id: str
    name: str
    instruction: str
    model: str
    llm: Any
    memory_search_fn: MemorySearchFn
    emit_citations_fn: EmitCitationsFn
    matrix_user_id: str | None = None
    is_active: bool = True

    async def run(self, query: str) -> dict[str, Any]:
        try:
            evidence = await self.memory_search_fn(query, self.id)
        except Exception:  # noqa: BLE001
            logger.exception("memory_search failed agent_id=%s", self.id)
            return {
                "text": "My memory is temporarily unavailable.",
                "citations": [],
            }
        if not evidence:
            return {
                "text": "I have no evidence to answer that right now.",
                "citations": [],
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
        except Exception as exc:  # noqa: BLE001
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
        except Exception:  # noqa: BLE001
            citations = []
        return {"text": text, "citations": citations}


async def create_ghost_agent(
    agent_id: UUID,
    *,
    store: Store | Any,
    llm_registry: Any | None = None,
    memory_search_fn: MemorySearchFn | None = None,
    emit_citations_fn: EmitCitationsFn | None = None,
    cache_ttl_seconds: int = 60,
) -> GhostAgent:
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
            segments_by_ids_provider=lambda segment_ids: store.get_segments_by_ids(
                segment_ids
            )
        )
        emit_citations_fn = emit_tool

    registry = llm_registry or LLMRegistry
    if hasattr(registry, "init_defaults"):
        registry.init_defaults()
    model = agent_row.get("llm_model", "gemini-2.5-flash")
    llm = registry.resolve(model)

    ghost = GhostAgent(
        id=key,
        name=agent_row["display_name"],
        instruction=agent_row["persona_prompt"],
        model=model,
        llm=llm,
        memory_search_fn=memory_search_fn,
        emit_citations_fn=emit_citations_fn,
        matrix_user_id=agent_row.get("matrix_user_id"),
        is_active=bool(agent_row.get("is_active", True)),
    )

    async with _CACHE_LOCK:
        _CACHE[key] = (time.time(), ghost)
    return ghost
