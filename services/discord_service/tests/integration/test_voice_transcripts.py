from __future__ import annotations

from collections import deque

import pytest

from discord_service.bot.voice_transcripts import VoiceTranscriptPublisher


class _FakeRateLimitError(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class _FakeMessage:
    def __init__(
        self, content: str, *, edit_failures: list[Exception] | None = None
    ) -> None:
        self.content = content
        self.edits: list[str] = []
        self._edit_failures: deque[Exception] = deque(edit_failures or [])

    async def edit(self, *, content: str, allowed_mentions=None):
        _ = allowed_mentions
        if self._edit_failures:
            raise self._edit_failures.popleft()
        self.content = content
        self.edits.append(content)
        return self


class _FakeTextChannel:
    def __init__(
        self,
        channel_id: int,
        *,
        send_failures: list[Exception] | None = None,
        message_edit_failures: list[Exception] | None = None,
    ) -> None:
        self.id = channel_id
        self.sent: list[str] = []
        self.messages: list[_FakeMessage] = []
        self._send_failures: deque[Exception] = deque(send_failures or [])
        self._message_edit_failures = list(message_edit_failures or [])

    async def send(self, content: str, allowed_mentions=None):
        _ = allowed_mentions
        if self._send_failures:
            raise self._send_failures.popleft()
        self.sent.append(content)
        message = _FakeMessage(content, edit_failures=self._message_edit_failures)
        self.messages.append(message)
        return message


class _FakeClient:
    def __init__(self, channels: dict[int, _FakeTextChannel]) -> None:
        self._channels = channels

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)

    async def fetch_channel(self, channel_id: int):
        return self._channels.get(channel_id)


@pytest.mark.anyio
async def test_transcript_chunks_coalesce_with_rolling_edits_and_idle_boundary() -> (
    None
):
    channel = _FakeTextChannel(11)
    publisher = VoiceTranscriptPublisher(
        client=_FakeClient({11: channel}),
        debounce_seconds=0.05,
    )

    await publisher.publish_input(
        {"bridge_id": "bridge-1", "text_channel_id": "11", "text": "hello"}
    )
    await publisher.publish_input(
        {"bridge_id": "bridge-1", "text_channel_id": "11", "text": "there"}
    )
    await publisher._sleep(0.08)
    assert len(channel.sent) == 1
    assert "hello there" in channel.sent[0]

    await publisher.publish_input(
        {"bridge_id": "bridge-1", "text_channel_id": "11", "text": "friend"}
    )
    await publisher._sleep(0.08)
    assert len(channel.sent) == 1
    assert channel.messages[0].edits
    assert "hello there friend" in channel.messages[0].content

    await publisher._sleep(0.08)
    await publisher.publish_input(
        {"bridge_id": "bridge-1", "text_channel_id": "11", "text": "new turn"}
    )
    await publisher._sleep(0.08)
    assert len(channel.sent) == 2
    assert "new turn" in channel.sent[1]

    await publisher.close()


@pytest.mark.anyio
async def test_transcript_channels_are_isolated_per_direction() -> None:
    input_channel = _FakeTextChannel(21)
    output_channel = _FakeTextChannel(22)
    publisher = VoiceTranscriptPublisher(
        client=_FakeClient({21: input_channel, 22: output_channel}),
        debounce_seconds=0.05,
    )

    await publisher.publish_input(
        {"bridge_id": "bridge-iso", "text_channel_id": "21", "text": "user asked"}
    )
    await publisher.publish_output(
        {"bridge_id": "bridge-iso", "text_channel_id": "22", "text": "bot answered"}
    )
    await publisher._sleep(0.08)

    assert len(input_channel.sent) == 1
    assert input_channel.sent[0].startswith("🧑 ")
    assert len(output_channel.sent) == 1
    assert output_channel.sent[0].startswith("🤖 ")

    await publisher.close()


@pytest.mark.anyio
async def test_transcript_post_retries_on_rate_limit_without_duplicates() -> None:
    channel = _FakeTextChannel(31, send_failures=[_FakeRateLimitError(0.01)])
    publisher = VoiceTranscriptPublisher(
        client=_FakeClient({31: channel}),
        debounce_seconds=0.05,
    )

    await publisher.publish_input(
        {"bridge_id": "bridge-rl", "text_channel_id": "31", "text": "retry me"}
    )
    await publisher._sleep(0.12)

    assert len(channel.sent) == 1
    assert "retry me" in channel.sent[0]

    await publisher.close()
