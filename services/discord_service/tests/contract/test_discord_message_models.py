from __future__ import annotations

import uuid

import pytest
from discord_service.bot.message_models import FeedBatchMessage, FeedParentMessage
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
