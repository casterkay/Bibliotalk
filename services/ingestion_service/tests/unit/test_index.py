from __future__ import annotations

import uuid

import pytest
from bt_common.evidence_store.engine import get_session_factory, init_database
from bt_common.evidence_store.models import Figure, Source
from ingestion_service.pipeline.index import IngestionIndex


@pytest.mark.anyio
async def test_index_roundtrip(tmp_path) -> None:
    db = tmp_path / "index.sqlite3"
    await init_database(db)
    session_factory = get_session_factory(db)

    async with session_factory() as session:
        figure = Figure(figure_id=uuid.uuid4(), display_name="Test Figure", emos_user_id="u1")
        session.add(figure)
        await session.flush()
        session.add(
            Source(
                figure_id=figure.figure_id,
                external_id="video-1",
                group_id="u1:youtube:video-1",
                title="Video 1",
                source_url="https://example.com/video-1",
            )
        )
        await session.commit()

    idx = IngestionIndex(session_factory, path=db)

    await idx.set_source_meta_saved(
        user_id="u1", group_id="u1:youtube:video-1", source_fingerprint="fp"
    )
    assert await idx.get_source_meta_saved(user_id="u1", group_id="u1:youtube:video-1") is True

    await idx.upsert_segment_status(
        user_id="u1",
        group_id="u1:youtube:video-1",
        message_id="u1:youtube:video-1:seg:0",
        seq=0,
        sha256="s1",
        status="ingested",
    )
    rec = await idx.get_segment(user_id="u1", message_id="u1:youtube:video-1:seg:0")
    assert rec is not None
    assert rec.message_id == "u1:youtube:video-1:seg:0"
    assert rec.sha256 == "s1"
    assert rec.status == "ingested"
