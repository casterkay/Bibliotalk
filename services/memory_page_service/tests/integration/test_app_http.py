from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from bt_common.evidence_store.engine import get_session_factory, init_database
from bt_common.evidence_store.models import Figure, Segment, Source
from fastapi.testclient import TestClient
from memory_page_service.app import create_app
from memory_page_service.config import load_runtime_config


class FakeEverMemOS:
    async def get_memories(self, **kwargs):
        return {
            "result": {
                "memories": [
                    {
                        "user_id": kwargs["user_id"],
                        "timestamp": kwargs["start_time"],
                        "summary": "Discussed learning",
                        "content": "Learning without thought is labor lost.",
                    }
                ]
            }
        }


@pytest.mark.anyio
async def test_memory_page_http_route_renders_html(tmp_path) -> None:
    db = tmp_path / "bibliotalk.db"
    await init_database(db)
    session_factory = get_session_factory(db)
    timestamp = datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC)

    async with session_factory() as session:
        figure = Figure(
            figure_id=uuid.uuid4(),
            display_name="Alan Watts",
            emos_user_id="alan-watts",
        )
        session.add(figure)
        await session.flush()
        source = Source(
            figure_id=figure.figure_id,
            external_id="abc123",
            group_id="alan-watts:youtube:abc123",
            title="Alan Watts Lecture",
            source_url="https://www.youtube.com/watch?v=abc123",
            transcript_status="ingested",
            published_at=datetime(2026, 3, 8, 11, 59, 0, tzinfo=UTC),
        )
        session.add(source)
        await session.flush()
        session.add(
            Segment(
                source_id=source.source_id,
                seq=0,
                text="Learning without thought is labor lost.",
                sha256="a" * 64,
                start_ms=60_000,
                end_ms=62_000,
                create_time=timestamp,
            )
        )
        await session.commit()

    config = load_runtime_config(db_path=str(db))
    client = TestClient(create_app(config, evermemos_client=FakeEverMemOS()))

    response = client.get("/memory/alan-watts_20260308T120000Z")

    assert response.status_code == 200
    assert "Alan Watts Lecture" in response.text
    assert "Open the source video at this timepoint" in response.text
