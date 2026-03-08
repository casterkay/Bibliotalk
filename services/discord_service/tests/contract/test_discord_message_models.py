from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from discord_service.bot.message_models import (
    FeedBatchMessage,
    FeedParentMessage,
    InboundDM,
    OutboundDMResponse,
)
from pydantic import ValidationError


def test_feed_parent_message_matches_contract_shape() -> None:
    message = FeedParentMessage(
        figure_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        channel_id="1234567890",
        text="Alan Watts Lecture\nhttps://www.youtube.com/watch?v=abc123",
    )

    assert message.channel_id == "1234567890"
    assert "https://www.youtube.com/watch?v=abc123" in message.text


def test_feed_batch_message_renders_seq_label_and_text() -> None:
    batch = FeedBatchMessage(
        figure_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        thread_id="thread-1",
        text="Verbatim transcript text.",
        seq_label="[00:01:23]",
    )

    assert batch.render_text() == "[00:01:23]\nVerbatim transcript text."


def test_feed_batch_message_rejects_rendered_content_above_discord_limit() -> None:
    with pytest.raises(ValidationError):
        FeedBatchMessage(
            figure_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            batch_id=uuid.uuid4(),
            thread_id="thread-1",
            text="x" * 1_995,
            seq_label="[00:00:00]",
        )


def test_inbound_dm_and_outbound_response_match_contract_shapes() -> None:
    inbound = InboundDM(
        discord_message_id="msg-1",
        discord_user_id="user-1",
        discord_channel_id="chan-1",
        figure_id=uuid.uuid4(),
        content="What did he say about learning?",
        received_at=datetime.now(tz=UTC),
    )
    outbound = OutboundDMResponse(
        discord_channel_id="chan-1",
        response_text="Answer [Learning without thought is labor lost.](https://www.bibliotalk.space/memory/alan-watts_20260308T120000Z)",
        evidence_used=[
            "https://www.bibliotalk.space/memory/alan-watts_20260308T120000Z"
        ],
        no_evidence=False,
    )

    assert inbound.discord_user_id == "user-1"
    assert outbound.no_evidence is False
