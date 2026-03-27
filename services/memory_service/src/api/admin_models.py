from __future__ import annotations

from pydantic import BaseModel, Field


class CollectorRunOnceRequest(BaseModel):
    agent_slug: str | None = Field(default=None, description="If set, only poll this agent.")
