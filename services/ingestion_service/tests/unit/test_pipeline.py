from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from ingestion_service.domain.models import Source, SourceContent, TranscriptContent, TranscriptLine
from ingestion_service.pipeline.index import IngestionIndex
from ingestion_service.pipeline.ingest import ingest_sources


class StubEverMemOS:
    def __init__(self) -> None:
        self.memorize_calls: list[dict] = []
        self.meta_calls: list[dict] = []

    async def memorize(self, payload: dict) -> dict:
        self.memorize_calls.append(payload)
        return {"ok": True}

    async def save_conversation_meta(self, *, group_id: str, source_meta: dict) -> dict:
        self.meta_calls.append({"group_id": group_id, "source_meta": source_meta})
        return {"ok": True}


@pytest.mark.anyio
async def test_segment_cache_matches_memorize_payload_and_skips_do_not_append(
    tmp_path,
) -> None:
    db = tmp_path / "index.sqlite3"
    await init_database(db)
    session_factory = get_session_factory(db)
    idx = IngestionIndex(session_factory, path=db)
    client = StubEverMemOS()
    cache_dir = tmp_path / "segment_cache"

    async with session_factory() as session:
        session.add(
            Agent(
                agent_id=uuid.uuid4(),
                kind="figure",
                slug="u1",
                display_name="Test Figure",
                persona_summary=None,
                is_active=True,
                created_at=datetime.now(tz=UTC),
            )
        )
        await session.commit()

    src = Source(
        user_id="u1",
        external_id="e1",
        title="T",
        source_url="https://www.youtube.com/watch?v=e1",
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    sc = SourceContent(
        source=src,
        content=TranscriptContent(
            lines=[
                TranscriptLine(text="One.", start_ms=0, end_ms=500),
                TranscriptLine(text="Two.", start_ms=700, end_ms=1200),
                TranscriptLine(text="Three.", start_ms=1400, end_ms=1900),
            ]
        ),
    )

    r1 = await ingest_sources(sources=[sc], index=idx, client=client, segment_cache_dir=cache_dir)
    assert r1.status == "done"
    assert len(client.memorize_calls) > 0

    cache_path = cache_dir / "u1.jsonl"
    assert cache_path.exists()
    cached_first = [json.loads(line) for line in cache_path.read_text().splitlines()]
    assert cached_first == client.memorize_calls
    for row in cached_first:
        assert "run_id" not in row
        assert "cached_at" not in row
        assert "segment" not in row

    client.memorize_calls.clear()
    r2 = await ingest_sources(sources=[sc], index=idx, client=client, segment_cache_dir=cache_dir)
    assert r2.sources[0].segments_skipped_unchanged > 0
    assert len(client.memorize_calls) == 0
    cached_second = [json.loads(line) for line in cache_path.read_text().splitlines()]
    assert cached_second == cached_first
