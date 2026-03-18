from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_evidence import Segment, Source
from fastapi.testclient import TestClient
from memory_service.api.app import create_app
from memory_service.api.config import load_memories_api_config


class FakeEverMemOS:
    def __init__(self, *, memcells: list[dict]):
        self._memcells = memcells

    async def aclose(self) -> None:
        return None

    async def get_memories(self, **kwargs):
        group_id = kwargs.get("group_id")
        user_id = kwargs.get("user_id")
        start_time = kwargs.get("start_time")
        end_time = kwargs.get("end_time")
        offset = int(kwargs.get("offset") or 0)
        limit = int(kwargs.get("limit") or 200)

        items = list(self._memcells)
        if group_id:
            items = [m for m in items if m.get("group_id") == group_id]
        if user_id:
            items = [m for m in items if m.get("user_id") == user_id]
        if start_time and end_time:
            items = [m for m in items if m.get("timestamp") == start_time]

        page = items[offset : offset + limit]
        return {
            "result": {
                "memories": page,
                "has_more": (offset + limit) < len(items),
            }
        }

    async def search(
        self, query: str, *, user_id: str, retrieve_method: str, top_k: int, memory_types=None
    ):
        _ = query
        _ = retrieve_method
        _ = top_k
        _ = memory_types
        items = [m for m in self._memcells if m.get("user_id") == user_id]
        return {
            "result": {
                "memories": [
                    {
                        "episodic_memory": items,
                    }
                ]
            }
        }


@pytest.mark.anyio
async def test_memories_routes_render_and_join_chunks(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)

    agent_slug = "alan-watts"
    agent_id = uuid.uuid4()
    source_id = uuid.uuid4()
    published_at = datetime(2026, 3, 8, 11, 59, 0, tzinfo=UTC)
    group_id = f"{agent_slug}:youtube:abc123"

    # Three chunks at 60s, 70s, 120s after publish.
    t0 = published_at + timedelta(seconds=60)
    t1 = published_at + timedelta(seconds=70)
    t2 = published_at + timedelta(seconds=120)

    async with session_factory() as session:
        session.add(
            Agent(
                agent_id=agent_id,
                kind="figure",
                slug=agent_slug,
                display_name="Alan Watts",
                persona_summary=None,
                is_active=True,
            )
        )
        session.add(
            Source(
                source_id=source_id,
                agent_id=agent_id,
                subscription_id=None,
                content_platform="youtube",
                external_id="abc123",
                external_url="https://www.youtube.com/watch?v=abc123",
                title="Alan Watts Lecture",
                author=None,
                channel_name=None,
                published_at=published_at,
                raw_meta_json=None,
                emos_group_id=group_id,
                meta_synced_at=None,
                created_at=datetime.now(tz=UTC),
            )
        )
        session.add_all(
            [
                Segment(
                    segment_id=uuid.uuid4(),
                    source_id=source_id,
                    agent_id=agent_id,
                    seq=0,
                    text="First chunk.",
                    sha256="a" * 64,
                    speaker=None,
                    start_ms=60_000,
                    end_ms=61_000,
                    emos_message_id=f"{group_id}:seg:0",
                    create_time=t0,
                    is_superseded=False,
                    created_at=datetime.now(tz=UTC),
                ),
                Segment(
                    segment_id=uuid.uuid4(),
                    source_id=source_id,
                    agent_id=agent_id,
                    seq=1,
                    text="Second chunk.",
                    sha256="b" * 64,
                    speaker=None,
                    start_ms=70_000,
                    end_ms=71_000,
                    emos_message_id=f"{group_id}:seg:1",
                    create_time=t1,
                    is_superseded=False,
                    created_at=datetime.now(tz=UTC),
                ),
                Segment(
                    segment_id=uuid.uuid4(),
                    source_id=source_id,
                    agent_id=agent_id,
                    seq=2,
                    text="Third chunk.",
                    sha256="c" * 64,
                    speaker=None,
                    start_ms=120_000,
                    end_ms=121_000,
                    emos_message_id=f"{group_id}:seg:2",
                    create_time=t2,
                    is_superseded=False,
                    created_at=datetime.now(tz=UTC),
                ),
            ]
        )
        await session.commit()

    memcells = [
        {
            "group_id": group_id,
            "user_id": agent_slug,
            "timestamp": t1.isoformat(),
            "summary": "First episode",
        },
        {
            "group_id": group_id,
            "user_id": agent_slug,
            "timestamp": t2.isoformat(),
            "summary": "Second episode",
        },
    ]

    config = load_memories_api_config(db_path=str(db), emos_base_url="https://emos.local")
    client = TestClient(create_app(config, evermemos_client=FakeEverMemOS(memcells=memcells)))

    # HTML route by id (memcell boundary timestamp).
    response = client.get("/memories/alan-watts_20260308T120010Z")
    assert response.status_code == 200
    assert "Alan Watts Lecture" in response.text
    assert "Second chunk." in response.text
    assert "Third chunk." not in response.text

    # JSON list by source_id.
    response = client.get(f"/v1/memories?source_id={group_id}&limit=10&offset=0")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    assert payload[0]["id"].endswith("T120010Z")
    assert len(payload[0]["chunks"]) == 2
    assert len(payload[1]["chunks"]) == 1

    # Search joins chunks.
    response = client.get(
        "/v1/search", params={"agent_slug": agent_slug, "q": "learning", "top_k": 2}
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results and results[0]["chunks"]
