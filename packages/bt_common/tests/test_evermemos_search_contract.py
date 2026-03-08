from __future__ import annotations

import pytest
from bt_common.evermemos_client import EverMemOSClient


class FakeMemories:
    def __init__(self) -> None:
        self.search_calls: list[dict] = []
        self.get_calls: list[dict] = []

    async def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return {"status": "ok", "result": {"memories": []}}

    async def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return {"status": "ok", "result": {"memories": []}}


class FakeSDK:
    def __init__(self, memories: FakeMemories):
        self.v0 = type("V0", (), {})()
        self.v0.memories = memories

    async def close(self):
        return None


@pytest.mark.anyio
async def test_search_contract_uses_user_scope_and_retrieve_method() -> None:
    memories = FakeMemories()
    client = EverMemOSClient("https://emos.local", api_key="secret", sdk_client=FakeSDK(memories))

    await client.search("what is learning", user_id="alan-watts", retrieve_method="rrf", top_k=5)

    call = memories.search_calls[-1]
    assert call["extra_body"]["query"] == "what is learning"
    assert call["extra_body"]["user_id"] == "alan-watts"
    assert call["extra_body"]["retrieve_method"] == "rrf"
    assert call["extra_headers"]["Authorization"] == "Bearer secret"


@pytest.mark.anyio
async def test_get_memories_contract_filters_by_user_and_time_range() -> None:
    memories = FakeMemories()
    client = EverMemOSClient("https://emos.local", sdk_client=FakeSDK(memories))

    await client.get_memories(
        user_id="alan-watts",
        start_time="2026-03-08T12:00:00+00:00",
        end_time="2026-03-08T12:00:00+00:00",
        limit=1,
    )

    call = memories.get_calls[-1]
    assert call["extra_query"]["user_id"] == "alan-watts"
    assert call["extra_query"]["memory_type"] == "episodic_memory"
    assert call["extra_query"]["start_time"] == "2026-03-08T12:00:00+00:00"
    assert call["extra_query"]["end_time"] == "2026-03-08T12:00:00+00:00"
