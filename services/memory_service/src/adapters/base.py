from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain.models import SourceContent


@dataclass(frozen=True, slots=True)
class AdapterResult:
    source_content: SourceContent


class Adapter(Protocol):
    async def load(self) -> AdapterResult: ...
