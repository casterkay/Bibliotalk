"""Segment and source models plus simple BM25 reranking."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class Source(BaseModel):
    id: UUID
    agent_id: UUID | None = Field(
        default=None, validation_alias=AliasChoices("agent_id", "figure_id")
    )
    platform: str
    external_id: str
    external_url: str | None = None
    title: str
    author: str | None = None
    published_at: datetime | None = None
    raw_meta: dict | None = None
    emos_group_id: str


class Segment(BaseModel):
    id: UUID
    source_id: UUID
    agent_id: UUID | None = Field(
        default=None, validation_alias=AliasChoices("agent_id", "figure_id")
    )
    platform: str
    seq: int
    text: str
    speaker: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    sha256: str
    create_time: datetime | None = None
    group_id: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    published_at: datetime | None = None
    emos_message_id: str | None = None


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def bm25_rerank(query: str, segments: list[Segment], top_k: int = 8) -> list[Segment]:
    if not segments:
        return []
    tokens = _tokenize(query)
    if not tokens:
        return segments[:top_k]

    doc_tokens = [_tokenize(segment.text) for segment in segments]
    doc_lens = [len(tokens_) for tokens_ in doc_tokens]
    avgdl = sum(doc_lens) / max(len(doc_lens), 1)

    df: Counter[str] = Counter()
    for terms in doc_tokens:
        for term in set(terms):
            df[term] += 1

    n_docs = len(segments)
    k1 = 1.5
    b = 0.75

    scored: list[tuple[float, Segment]] = []
    for idx, segment in enumerate(segments):
        tf = Counter(doc_tokens[idx])
        score = 0.0
        doc_len = max(doc_lens[idx], 1)
        for term in tokens:
            if tf[term] == 0:
                continue
            idf = math.log(1 + ((n_docs - df[term] + 0.5) / (df[term] + 0.5)))
            denom = tf[term] + k1 * (1 - b + b * doc_len / max(avgdl, 1))
            score += idf * (tf[term] * (k1 + 1) / denom)
        scored.append((score, segment))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [segment for _, segment in scored[:top_k]]
