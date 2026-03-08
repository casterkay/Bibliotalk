from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, model_validator


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
