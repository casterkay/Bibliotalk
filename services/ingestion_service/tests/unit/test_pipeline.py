from __future__ import annotations

import json

import pytest

from ingestion_service.domain.models import PlainTextContent, Source, SourceContent
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


@pytest.mark.asyncio
async def test_segment_cache_matches_memorize_payload_and_skips_do_not_append(
    tmp_path,
) -> None:
    idx = IngestionIndex(tmp_path / "index.sqlite3")
    client = StubEverMemOS()
    cache_dir = tmp_path / "segment_cache"

    src = Source(user_id="u1", platform="local", external_id="e1", title="T")
    sc = SourceContent(source=src, content=PlainTextContent(text="One.\n\nTwo.\n\nThree."))

    r1 = await ingest_sources(
        sources=[sc], index=idx, client=client, segment_cache_dir=cache_dir
    )
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
    r2 = await ingest_sources(
        sources=[sc], index=idx, client=client, segment_cache_dir=cache_dir
    )
    assert r2.sources[0].segments_skipped_unchanged > 0
    assert len(client.memorize_calls) == 0
    cached_second = [json.loads(line) for line in cache_path.read_text().splitlines()]
    assert cached_second == cached_first
