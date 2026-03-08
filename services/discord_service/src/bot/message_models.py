from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class InboundDM(BaseModel):
    discord_message_id: str = Field(min_length=1)
    discord_user_id: str = Field(min_length=1)
    discord_channel_id: str = Field(min_length=1)
    figure_id: uuid.UUID
    content: str = Field(min_length=1)
    received_at: datetime


class OutboundDMResponse(BaseModel):
    discord_channel_id: str = Field(min_length=1)
    response_text: str = Field(min_length=1, max_length=2000)
    evidence_used: list[str]
    no_evidence: bool = False

    @model_validator(mode="after")
    def validate_no_evidence_shape(self) -> OutboundDMResponse:
        if self.no_evidence and self.evidence_used:
            raise ValueError(
                "no-evidence responses cannot contain evidence_used entries"
            )
        return self


class FeedParentMessage(BaseModel):
    """Exactly one parent feed message per source."""

    figure_id: uuid.UUID
    source_id: uuid.UUID
    channel_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=2000)


class FeedBatchMessage(BaseModel):
    """One transcript batch message posted into a per-video thread."""

    figure_id: uuid.UUID
    source_id: uuid.UUID
    batch_id: uuid.UUID
    thread_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=2000)
    seq_label: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_rendered_length(self) -> FeedBatchMessage:
        if len(self.render_text()) > 2000:
            raise ValueError(
                "rendered batch message exceeds Discord 2000 character limit"
            )
        return self

    def render_text(self) -> str:
        return f"{self.seq_label}\n{self.text}"
