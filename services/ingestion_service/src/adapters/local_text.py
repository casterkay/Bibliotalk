from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..domain.errors import InvalidInputError
from ..domain.models import PlainTextContent, Source, SourceContent


def load_text_source(
    *,
    user_id: str,
    platform: str,
    external_id: str,
    title: str,
    text: str,
    source_url: str | None = None,
    author: str | None = None,
    published_at: str | datetime | None = None,
) -> SourceContent:
    source = Source(
        user_id=user_id,
        platform=platform,
        external_id=external_id,
        title=title,
        source_url=source_url,
        author=author,
        published_at=published_at,
    )
    return SourceContent(source=source, content=PlainTextContent(text=text))


def load_file_source(
    *,
    user_id: str,
    platform: str,
    external_id: str,
    title: str,
    path: Path,
    source_url: str | None = None,
    author: str | None = None,
    published_at: str | None = None,
) -> SourceContent:
    if not path.is_absolute():
        raise InvalidInputError("--path must be absolute")
    if not path.exists():
        raise InvalidInputError(f"File not found: {path}")
    text = path.read_text(encoding="utf-8")
    return load_text_source(
        user_id=user_id,
        platform=platform,
        external_id=external_id,
        title=title,
        text=text,
        source_url=source_url,
        author=author,
        published_at=published_at,
    )
