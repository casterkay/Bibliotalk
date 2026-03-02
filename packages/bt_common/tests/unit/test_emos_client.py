from __future__ import annotations

import httpx
import pytest
from bt_common.evermemos_client import EverMemOSClient
from bt_common.exceptions import EMOSConnectionError, EMOSError, EMOSValidationError


class APIConnectionError(Exception):
    pass


class FakeStatusError(Exception):
    def __init__(
        self, status_code: int, body: dict | None = None, message: str = "error"
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = body or {}
        self.message = message


class FakeMemories:
    def __init__(self):
        self.add_calls: list[dict] = []
        self.search_calls: list[dict] = []
        self.add_results: list = []
        self.search_results: list = []

    async def add(self, **kwargs):
        self.add_calls.append(kwargs)
        value = self.add_results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    async def search(self, **kwargs):
        self.search_calls.append(kwargs)
        value = self.search_results.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class FakeSDK:
    def __init__(self, memories: FakeMemories):
        self.v0 = type("V0", (), {})()
        self.v0.memories = memories

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_memorize_request_serialization() -> None:
    memories = FakeMemories()
    memories.add_results = [{"status": "ok", "result": {"status_info": "extracted"}}]
    client = EverMemOSClient(
        "https://emos.local",
        api_key="k",
        sdk_client=FakeSDK(memories),
    )

    payload = {
        "message_id": "a:b:c:seg:1",
        "create_time": "2025-01-01T00:00:00Z",
        "sender": "agent",
        "content": "text",
        "group_id": "a:b:c",
        "group_name": "src",
        "role": "assistant",
    }
    result = await client.memorize(payload)

    assert result["result"]["status_info"] == "extracted"
    call = memories.add_calls[-1]
    assert call["message_id"] == "a:b:c:seg:1"
    assert call["extra_headers"]["Authorization"] == "Bearer k"


@pytest.mark.asyncio
async def test_search_with_rrf_retrieve_method() -> None:
    memories = FakeMemories()
    memories.search_results = [{"status": "ok", "result": {"memories": []}}]
    client = EverMemOSClient("https://emos.local", sdk_client=FakeSDK(memories))

    await client.search("virtue", user_id="agent", retrieve_method="rrf")

    call = memories.search_calls[-1]
    assert call["extra_body"]["retrieve_method"] == "rrf"


@pytest.mark.asyncio
async def test_status_info_extracted_and_accumulated_handling() -> None:
    memories = FakeMemories()
    memories.add_results = [
        {"status": "ok", "result": {"status_info": "extracted"}},
        {"status": "ok", "result": {"status_info": "accumulated"}},
    ]
    client = EverMemOSClient("https://emos.local", sdk_client=FakeSDK(memories))

    one = await client.memorize({"message_id": "1", "sender": "s", "content": "c"})
    two = await client.memorize({"message_id": "2", "sender": "s", "content": "c"})

    assert one["result"]["status_info"] == "extracted"
    assert two["result"]["status_info"] == "accumulated"
    assert len(memories.add_calls) == 2


@pytest.mark.asyncio
async def test_5xx_retry_logic() -> None:
    memories = FakeMemories()
    memories.search_results = [
        FakeStatusError(500, {"message": "down"}),
        FakeStatusError(502, {"message": "still down"}),
        {"status": "ok", "result": {"memories": []}},
    ]
    client = EverMemOSClient(
        "https://emos.local", retries=3, sdk_client=FakeSDK(memories)
    )

    result = await client.search("virtue", user_id="agent")

    assert result["status"] == "ok"
    assert len(memories.search_calls) == 3


@pytest.mark.asyncio
async def test_4xx_no_retry() -> None:
    memories = FakeMemories()
    memories.search_results = [
        FakeStatusError(422, {"code": "INVALID_PARAMETER", "message": "bad query"})
    ]
    client = EverMemOSClient(
        "https://emos.local", retries=3, sdk_client=FakeSDK(memories)
    )

    with pytest.raises(EMOSValidationError):
        await client.search("", user_id="agent")

    assert len(memories.search_calls) == 1


@pytest.mark.asyncio
async def test_connection_error_retry() -> None:
    memories = FakeMemories()
    memories.search_results = [
        APIConnectionError("network down"),
        {"status": "ok", "result": {"memories": []}},
    ]
    client = EverMemOSClient(
        "https://emos.local", retries=2, sdk_client=FakeSDK(memories)
    )

    result = await client.search("virtue", user_id="agent")

    assert result["status"] == "ok"
    assert len(memories.search_calls) == 2


@pytest.mark.asyncio
async def test_httpx_transport_error_retry() -> None:
    memories = FakeMemories()
    memories.search_results = [
        httpx.RemoteProtocolError("peer closed connection"),
        {"status": "ok", "result": {"memories": []}},
    ]
    client = EverMemOSClient(
        "https://emos.local", retries=2, sdk_client=FakeSDK(memories)
    )

    result = await client.search("virtue", user_id="agent")

    assert result["status"] == "ok"
    assert len(memories.search_calls) == 2


@pytest.mark.asyncio
async def test_error_envelope_parsing() -> None:
    memories = FakeMemories()
    memories.search_results = [
        FakeStatusError(500, {"code": "SYSTEM_ERROR", "message": "boom"})
    ]
    client = EverMemOSClient(
        "https://emos.local", retries=1, sdk_client=FakeSDK(memories)
    )

    with pytest.raises(EMOSError):
        await client.search("virtue", user_id="agent")


@pytest.mark.asyncio
async def test_connection_error_after_retries_raises_connection_error() -> None:
    memories = FakeMemories()
    memories.search_results = [
        APIConnectionError("offline"),
        APIConnectionError("offline"),
    ]
    client = EverMemOSClient(
        "https://emos.local", retries=2, sdk_client=FakeSDK(memories)
    )

    with pytest.raises(EMOSConnectionError):
        await client.search("virtue", user_id="agent")
