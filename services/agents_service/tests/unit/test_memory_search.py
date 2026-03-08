from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agents_service.agent.tools.memory_search import MemorySearchTool


class FakeEverMemOS:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int]] = []

    async def search(self, query: str, *, user_id: str, retrieve_method: str, top_k: int):
        self.calls.append((query, user_id, retrieve_method, top_k))
        return {
            "result": {
                "memories": [
                    {
                        "episodic_memory": [
                            {
                                "group_id": "alan-watts:youtube:abc123",
                                "user_id": "alan-watts",
                                "timestamp": "2026-03-08T12:00:00+00:00",
                                "summary": "Learning without thought is labor lost.",
                            }
                        ]
                    }
                ]
            }
        }


@pytest.mark.anyio
async def test_memory_search_reranks_local_segments_and_builds_evidence() -> None:
    tool = MemorySearchTool(
        evermemos_client=FakeEverMemOS(),
        sources_by_group_ids_provider=lambda group_ids: [
            {
                "id": str(uuid4()),
                "title": "Alan Watts Lecture",
                "external_url": "https://www.youtube.com/watch?v=abc123",
                "published_at": "2026-03-08T11:59:00+00:00",
                "emos_group_id": group_ids[0],
                "memory_user_id": "alan-watts",
            }
        ],
        segments_by_source_ids_provider=lambda source_ids: [
            {
                "id": str(uuid4()),
                "figure_id": str(uuid4()),
                "source_id": source_ids[0],
                "platform": "youtube",
                "seq": 0,
                "text": "Learning without thought is labor lost.",
                "sha256": "a" * 64,
                "source_title": "Alan Watts Lecture",
                "source_url": "https://www.youtube.com/watch?v=abc123",
                "create_time": "2026-03-08T12:00:00+00:00",
                "group_id": "alan-watts:youtube:abc123",
                "published_at": "2026-03-08T11:59:00+00:00",
            },
            {
                "id": str(uuid4()),
                "figure_id": str(uuid4()),
                "source_id": source_ids[0],
                "platform": "youtube",
                "seq": 1,
                "text": "Completely unrelated text.",
                "sha256": "b" * 64,
                "source_title": "Alan Watts Lecture",
                "source_url": "https://www.youtube.com/watch?v=abc123",
                "create_time": "2026-03-08T12:01:00+00:00",
                "group_id": "alan-watts:youtube:abc123",
                "published_at": "2026-03-08T11:59:00+00:00",
            },
        ],
        segments_for_agent_provider=lambda agent_id: [],
    )

    evidence = await tool("What did you say about learning?", "alan-watts")

    assert evidence[0].text == "Learning without thought is labor lost."
    assert evidence[0].memory_user_id == "alan-watts"
    assert evidence[0].memory_timestamp == datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC)
    assert (
        evidence[0].memory_url == "https://www.bibliotalk.space/memory/alan-watts_20260308T120000Z"
    )
