from __future__ import annotations

import uuid

import pytest
from bt_store.engine import get_session_factory, init_database
from bt_store.models_core import Agent
from bt_store.models_evidence import Source
from bt_store.models_ingestion import SourceIngestionState
from memory_service.pipeline.index import IngestionIndex
from sqlalchemy import select


@pytest.mark.anyio
async def test_index_roundtrip(tmp_path) -> None:
    db = tmp_path / "index.sqlite3"
    await init_database(db)
    session_factory = get_session_factory(db)

    async with session_factory() as session:
        agent_id = uuid.uuid4()
        session.add(
            Agent(
                agent_id=agent_id,
                kind="figure",
                slug="u1",
                display_name="Test Figure",
                persona_summary=None,
                is_active=True,
            )
        )
        session.add(
            Source(
                source_id=uuid.uuid4(),
                agent_id=agent_id,
                content_platform="youtube",
                external_id="video-1",
                emos_group_id="u1:youtube:video-1",
                title="Video 1",
                external_url="https://example.com/video-1",
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


@pytest.mark.anyio
async def test_existing_source_is_not_treated_as_meta_synced_until_marked(tmp_path) -> None:
    db = tmp_path / "index.sqlite3"
    await init_database(db)
    session_factory = get_session_factory(db)

    async with session_factory() as session:
        agent_id = uuid.uuid4()
        source_id = uuid.uuid4()
        session.add(
            Agent(
                agent_id=agent_id,
                kind="figure",
                slug="u1",
                display_name="Test Figure",
                persona_summary=None,
                is_active=True,
            )
        )
        session.add(
            Source(
                source_id=source_id,
                agent_id=agent_id,
                content_platform="youtube",
                external_id="video-1",
                emos_group_id="u1:youtube:video-1",
                title="Video 1",
                external_url="https://example.com/video-1",
            )
        )
        session.add(SourceIngestionState(source_id=source_id, ingest_status="pending"))
        await session.commit()

    idx = IngestionIndex(session_factory, path=db)
    assert await idx.get_source_meta_saved(user_id="u1", group_id="u1:youtube:video-1") is False
    await idx.upsert_segment_status(
        user_id="u1",
        group_id="u1:youtube:video-1",
        message_id="u1:youtube:video-1:seg:1",
        seq=1,
        sha256="failed",
        status="failed",
    )

    async with session_factory() as session:
        stored = (await session.execute(select(Source))).scalar_one()
        state = await session.get(SourceIngestionState, stored.source_id)

    assert stored.meta_synced_at is None
    assert state is not None
    assert state.ingest_status == "pending"
