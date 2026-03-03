"""CLI harness for ghost conversations."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from bt_common.config import get_settings

from .agent.agent_factory import LLMRegistry, create_ghost_agent
from .database.pocketbase_store import PocketBaseConfig, PocketBaseStore
from .matrix.appservice import format_ghost_response
from .models.citation import Citation, Evidence


@dataclass
class _MockStore:
    agent_id: UUID
    tenant_prefix: str
    model: str

    async def get_agent(self, agent_id: UUID):
        return {
            "id": str(agent_id),
            "display_name": "Confucius (Ghost)",
            "matrix_user_id": "@bt_ghost_confucius:example",
            "persona_prompt": "You are Confucius.",
            "llm_model": self.model,
            "is_active": True,
        }

    async def get_agent_emos_config(self, agent_id: UUID):
        # For the CLI, default to env-backed EMOS settings with a stable tenant_prefix.
        return {"agent_id": str(agent_id), "tenant_prefix": self.tenant_prefix}

    async def get_segments_for_agent(self, agent_id: UUID):
        return [
            {
                "id": str(uuid4()),
                "source_id": str(uuid4()),
                "agent_id": str(agent_id),
                "platform": "gutenberg",
                "seq": 1,
                "text": "Learning without thought is labor lost.",
                "sha256": "hash",
                "emos_message_id": f"{agent_id}:gutenberg:3330:seg:1",
                "source_title": "The Analects",
                "source_url": "https://www.gutenberg.org/ebooks/3330",
            }
        ]

    async def get_sources_by_emos_group_ids(self, emos_group_ids: list[str]):
        _ = emos_group_ids
        return [
            {
                "id": str(uuid4()),
                "title": "The Analects",
                "external_url": "https://www.gutenberg.org/ebooks/3330",
            }
        ]

    async def get_segments_by_source_ids(self, source_ids: list[str]):
        _ = source_ids
        return await self.get_segments_for_agent(self.agent_id)

    async def get_segments_by_ids(self, segment_ids):
        return [
            {
                "id": str(segment_ids[0]),
                "agent_id": str(self.agent_id),
                "text": "Learning without thought is labor lost.",
            }
        ]


async def _resolve_agent_id_and_store(
    *, agent_slug: str, model: str, mock_emos: bool
) -> tuple[UUID, Any]:
    if mock_emos:
        agent_id = uuid4()
        return agent_id, _MockStore(
            agent_id=agent_id, tenant_prefix=agent_slug, model=model
        )

    settings = get_settings()
    if not settings.POCKETBASE_URL:
        raise RuntimeError(
            "PocketBase is required for non-mock CLI runs. Set POCKETBASE_URL and seed ghosts:\n"
            "  python -m agents_service.bootstrap seed-ghosts"
        )
    if (
        not settings.POCKETBASE_SUPERUSER_EMAIL
        or not settings.POCKETBASE_SUPERUSER_PASSWORD
    ):
        raise RuntimeError("POCKETBASE_SUPERUSER_EMAIL/PASSWORD not set")

    pb = PocketBaseStore(
        config=PocketBaseConfig(
            url=settings.POCKETBASE_URL,
            email=settings.POCKETBASE_SUPERUSER_EMAIL,
            password=settings.POCKETBASE_SUPERUSER_PASSWORD,
        )
    )
    agent = await pb.get_agent_by_tenant_prefix(agent_slug)
    if not agent:
        await pb.aclose()
        raise RuntimeError(
            f"Unknown agent tenant_prefix={agent_slug}. Seed via:\n"
            "  python -m agents_service.bootstrap seed-ghosts"
        )
    agent_id = UUID(str(agent["id"]))
    return agent_id, pb


async def _run(agent_slug: str, mock_emos: bool, model: str) -> None:
    # Avoid requiring fully-valid Settings for mock runs (mock mode should be runnable
    # without PocketBase config).
    if mock_emos:
        level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
        logging.basicConfig(level=level)
    else:
        settings = get_settings()
        logging.basicConfig(
            level=getattr(logging, str(settings.LOG_LEVEL).upper(), logging.INFO)
        )
    LLMRegistry.init_defaults()
    agent_id, store = await _resolve_agent_id_and_store(
        agent_slug=agent_slug, model=model, mock_emos=mock_emos
    )

    memory_search_fn = None
    if mock_emos:

        async def _mock_memory_search(_query: str, _agent_id: str):
            row = (await store.get_segments_for_agent(agent_id))[0]
            return [
                Evidence.model_validate(
                    {
                        "segment_id": row["id"],
                        "emos_message_id": row["emos_message_id"],
                        "source_title": row["source_title"],
                        "source_url": row["source_url"],
                        "text": row["text"],
                        "platform": row["platform"],
                    }
                )
            ]

        async def _mock_emit(evidence_items, _agent_id):
            return [
                Citation.from_evidence(
                    item, index=idx, quote="Learning without thought is labor lost."
                )
                for idx, item in enumerate(evidence_items, start=1)
            ]

        memory_search_fn = _mock_memory_search
        emit_citations_fn = _mock_emit
    else:
        emit_citations_fn = None

    try:
        agent = await create_ghost_agent(
            agent_id,
            store=store,
            llm_registry=LLMRegistry,
            memory_search_fn=memory_search_fn,
            emit_citations_fn=emit_citations_fn,
        )

        print("Type messages, Ctrl-D to exit.")
        while True:
            try:
                prompt = input("> ").strip()
            except EOFError:
                print()
                break
            if not prompt:
                continue

            response = await agent.run(prompt)
            payload = format_ghost_response(response["text"], response["citations"])
            print(payload["body"])
    finally:
        if hasattr(store, "aclose"):
            await store.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Bibliotalk CLI harness")
    parser.add_argument(
        "--agent",
        required=True,
        help="Agent tenant_prefix (PocketBase local dev) or slug (mock mode).",
    )
    parser.add_argument(
        "--mock-emos", action="store_true", help="Use mock EMOS responses"
    )
    parser.add_argument(
        "--model",
        default="nova-lite-v2",
        help="LLM model name (e.g. gemini-2.5-flash).",
    )
    args = parser.parse_args()

    asyncio.run(_run(args.agent, args.mock_emos, args.model))


if __name__ == "__main__":
    main()
