from __future__ import annotations

import re

import httpx

from ..domain.errors import AdapterError, InvalidInputError
from ..domain.models import PlainTextContent, Source, SourceContent

_START_RE = re.compile(
    r"^\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK",
    flags=re.IGNORECASE,
)
_END_RE = re.compile(
    r"^\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK",
    flags=re.IGNORECASE,
)
_CHAPTER_HEADING_RE = re.compile(
    r"\n\n(chapter|chap|book|part|section)\.?\s+([ivxlcdm\d\s.-]+)\b.*\n\n",
    flags=re.IGNORECASE,
)
_LIST_ITEM_RE = re.compile(r"^\s*[\d*-]+\.")


def _strip_gutenberg_boilerplate(text: str) -> str:
    lines = text.splitlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if start_idx is None and _START_RE.search(line):
            start_idx = i + 1
        if _END_RE.search(line):
            end_idx = i
            break
    if start_idx is None:
        start_idx = 0
    if end_idx is None:
        end_idx = len(lines)
    return "\n".join(lines[start_idx:end_idx]).strip()


def _looks_like_heading(line: str) -> bool:
    collapsed = " ".join(line.split())
    if not collapsed or len(collapsed) > 120:
        return False
    if _CHAPTER_HEADING_RE.match(collapsed):
        return True
    if collapsed.isupper() and 1 <= len(collapsed.split()) <= 10:
        return True
    return False


def _normalize_linebreaks(text: str) -> str:
    lines = [
        line.rstrip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    paragraphs: list[str] = []
    buf: list[str] = []

    def flush_buffer() -> None:
        nonlocal buf
        if not buf:
            return
        paragraph = " ".join(piece.strip() for piece in buf if piece.strip())
        if paragraph:
            paragraphs.append(paragraph)
        buf = []

    for raw in lines:
        line = raw.strip()
        if not line:
            flush_buffer()
            continue
        if line.startswith("[") and line.endswith("]") and "pg " in line.lower():
            # Drop Project Gutenberg page-number markers such as [Pg 12].
            continue
        if _looks_like_heading(line):
            flush_buffer()
            paragraphs.append(" ".join(line.split()))
            continue
        if _LIST_ITEM_RE.match(raw):
            flush_buffer()
        buf.append(line)

    flush_buffer()
    return "\n\n".join(paragraphs).strip()


def _extract_chapter_titles(text: str) -> list[str]:
    titles: list[str] = []
    for paragraph in text.split("\n\n"):
        line = paragraph.strip()
        if _looks_like_heading(line):
            if line not in titles:
                titles.append(line)
    return titles


async def load_gutenberg_source(
    *,
    user_id: str,
    external_id: str,
    title: str,
    gutenberg_id: str,
    source_url: str | None = None,
    author: str | None = None,
) -> SourceContent:
    if not gutenberg_id.strip().isdigit():
        raise InvalidInputError("gutenberg_id must be numeric")
    book_id = gutenberg_id.strip()

    url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
    async with httpx.AsyncClient(
        timeout=30.0, follow_redirects=True, trust_env=False
    ) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise AdapterError(
                f"Failed to download Gutenberg text (HTTP {resp.status_code})"
            )
        text = resp.text

    cleaned = _normalize_linebreaks(_strip_gutenberg_boilerplate(text))
    chapter_titles = _extract_chapter_titles(cleaned)
    source = Source(
        user_id=user_id,
        platform="gutenberg",
        external_id=external_id or book_id,
        title=title,
        source_url=source_url or f"https://www.gutenberg.org/ebooks/{book_id}",
        author=author,
        raw_meta={
            "gutenberg_id": book_id,
            "chapter_titles": chapter_titles,
            "conversation_strategy": "chapter_heading_split",
            "message_separator": "\\n\\n",
        },
    )
    return SourceContent(source=source, content=PlainTextContent(text=cleaned))
