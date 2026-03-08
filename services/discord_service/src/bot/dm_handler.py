from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from agents_service.agent.orchestrator import DMContext, DMOrchestrator
from agents_service.models.citation import (
    NO_EVIDENCE_RESPONSE,
    extract_memory_links,
    validate_evidence_links,
)

from .message_models import InboundDM, OutboundDMResponse

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class DMHandler:
    def __init__(
        self,
        *,
        orchestrator: DMOrchestrator,
        figure_slug_resolver: Callable[[str], Awaitable[str]],
    ) -> None:
        self._orchestrator = orchestrator
        self._figure_slug_resolver = figure_slug_resolver

    async def handle(self, inbound: InboundDM) -> list[OutboundDMResponse]:
        figure_slug = await self._figure_slug_resolver(str(inbound.figure_id))
        result = await self._orchestrator.run(
            DMContext(
                figure_id=inbound.figure_id,
                figure_slug=figure_slug,
                discord_user_id=inbound.discord_user_id,
                discord_channel_id=inbound.discord_channel_id,
                content=inbound.content,
            )
        )
        validated_text = validate_evidence_links(
            result.response_text,
            list(result.evidence),
            figure_emos_user_id=figure_slug,
        )
        evidence_used = [url for _, url in extract_memory_links(validated_text)]
        if not evidence_used:
            return [
                OutboundDMResponse(
                    discord_channel_id=inbound.discord_channel_id,
                    response_text=NO_EVIDENCE_RESPONSE,
                    evidence_used=[],
                    no_evidence=True,
                )
            ]
        return [
            OutboundDMResponse(
                discord_channel_id=inbound.discord_channel_id,
                response_text=chunk,
                evidence_used=evidence_used,
                no_evidence=False,
            )
            for chunk in _split_response_text(validated_text)
        ]


def _split_response_text(text: str, *, limit: int = 2000) -> list[str]:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return [compact]
    sentences = _SENTENCE_SPLIT_RE.split(compact)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = sentence.strip()
        if not candidate:
            continue
        merged = f"{current} {candidate}".strip()
        if current and len(merged) > limit:
            chunks.append(current)
            current = candidate
            continue
        if len(candidate) > limit:
            if current:
                chunks.append(current)
            current = candidate[:limit]
            continue
        current = merged
    if current:
        chunks.append(current)
    return chunks or [compact[:limit]]
