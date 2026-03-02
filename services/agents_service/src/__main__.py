"""CLI harness for ghost conversations."""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID, uuid4

from .agent.agent_factory import LLMRegistry, create_ghost_agent
from .matrix.appservice import format_ghost_response
from .models.citation import Citation, Evidence


class _MockSupabase:
    def __init__(self, agent_id: UUID, *, model: str):
        self.agent_id = agent_id
        self.model = model

    async def get_agent(self, agent_id: UUID):
        return {
            "id": str(agent_id),
            "display_name": "Confucius (Ghost)",
            "matrix_user_id": "@btghost_confucius:example",
            "persona_prompt": "You are Confucius.",
            "llm_model": self.model,
            "is_active": True,
        }

    async def get_agent_emos_config(self, agent_id: UUID):
        return {"agent_id": str(agent_id), "emos_base_url": "https://emos.local"}

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


async def _run(agent_slug: str, mock_emos: bool, model: str) -> None:
    _ = agent_slug
    _ = mock_emos
    agent_id = uuid4()
    LLMRegistry.init_defaults()
    supabase = _MockSupabase(agent_id, model=model)

    memory_search_fn = None
    if mock_emos:

        async def _mock_memory_search(_query: str, _agent_id: str):
            row = (await supabase.get_segments_for_agent(agent_id))[0]
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

    agent = await create_ghost_agent(
        agent_id,
        supabase_helpers=supabase,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Bibliotalk CLI harness")
    parser.add_argument("--agent", required=True, help="Agent slug")
    parser.add_argument(
        "--mock-emos", action="store_true", help="Use mock EMOS responses"
    )
    parser.add_argument(
        "--model",
        default="nova-lite-v2",
        help="LLM model name (e.g. gemini-2.0-flash).",
    )
    args = parser.parse_args()

    asyncio.run(_run(args.agent, args.mock_emos, args.model))


if __name__ == "__main__":
    main()
