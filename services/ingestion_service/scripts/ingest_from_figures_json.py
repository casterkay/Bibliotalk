#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import io
import json
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bt_common.evermemos_client import EverMemOSClient
from ingestion_service.domain.errors import ConfigError
from ingestion_service.pipeline.index import IngestionIndex
from ingestion_service.pipeline.ingest import ingest_manifest
from ingestion_service.pipeline.manifest import Manifest, ManifestSourceItem
from ingestion_service.runtime.config import load_runtime_config
from ingestion_service.runtime.reporting import write_report

YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
GUTENBERG_ID_RE = re.compile(
    r"gutenberg\.org/(?:ebooks|files|cache/epub)/(\d+)", re.IGNORECASE
)
TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)


@dataclass(frozen=True, slots=True)
class SourceCacheKey:
    user_id: str
    platform: str
    external_id: str


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "_", lowered)
    lowered = lowered.strip("_")
    return lowered or "unknown"


def _stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _load_relaxed_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = json.loads(TRAILING_COMMA_RE.sub(r"\1", text))
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object keyed by figure name")
    return data


def _extract_gutenberg_id(url: str) -> str | None:
    m = GUTENBERG_ID_RE.search(url)
    if not m:
        return None
    return m.group(1)


def _extract_youtube_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host == "youtu.be":
        vid = parsed.path.strip("/").split("/")[0]
        return vid or None
    if host not in YOUTUBE_DOMAINS:
        return None
    if parsed.path == "/watch":
        values = parse_qs(parsed.query).get("v", [])
        return values[0] if values else None
    if parsed.path.startswith("/shorts/"):
        return parsed.path.split("/")[2]
    if parsed.path.startswith("/embed/"):
        return parsed.path.split("/")[2]
    return None


def _extract_youtube_playlist_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in YOUTUBE_DOMAINS:
        return None
    values = parse_qs(parsed.query).get("list", [])
    return values[0] if values else None


def _playlist_video_ids(url: str, max_items: int | None) -> list[str]:
    cmd = ["yt-dlp", "--flat-playlist", "--print", "%(id)s"]
    if max_items is not None and max_items > 0:
        cmd.extend(["--playlist-items", f"1-{max_items}"])
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "yt-dlp failed"
        raise RuntimeError(stderr)
    ids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    return [v for v in ids if re.fullmatch(r"[A-Za-z0-9_-]{6,20}", v)]


def _strip_html_markup(text: str) -> str:
    text = SCRIPT_STYLE_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_epub_text(content: bytes) -> str:
    texts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = sorted(
            name
            for name in zf.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm"))
            and not name.lower().startswith("meta-inf/")
        )
        for name in names:
            raw = zf.read(name)
            decoded = raw.decode("utf-8", errors="ignore")
            cleaned = _strip_html_markup(decoded)
            if cleaned:
                texts.append(cleaned)
    if not texts:
        raise ValueError("No readable HTML/XHTML content found in EPUB")
    return "\n\n".join(texts)


def _download_as_text(url: str) -> str:
    with httpx.Client(timeout=60.0, follow_redirects=True, trust_env=False) as client:
        resp = client.get(url)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "").lower()
        if url.lower().endswith(".epub") or "application/epub+zip" in ctype:
            return _extract_epub_text(resp.content)
        if "text/html" in ctype or url.lower().endswith((".html", ".htm")):
            return _strip_html_markup(resp.text)
        return resp.text.strip()


def _title_from_url(url: str, fallback: str) -> str:
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    if not name:
        return fallback
    stem = Path(name).stem
    return stem.replace("-", " ").replace("_", " ") or fallback


def _manifest_items_for_source(
    *,
    figure_name: str,
    user_id: str,
    avatar: str | None,
    bio: str | None,
    source_url: str,
    max_playlist_items: int | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    common_meta = {
        "figure_name": figure_name,
        "avatar": avatar,
        "bio": bio,
        "source_url": source_url,
    }

    gutenberg_id = _extract_gutenberg_id(source_url)
    if gutenberg_id:
        items.append(
            {
                "user_id": user_id,
                "platform": "gutenberg",
                "external_id": gutenberg_id,
                "title": f"{figure_name} - Gutenberg {gutenberg_id}",
                "source_url": f"https://www.gutenberg.org/ebooks/{gutenberg_id}",
                "author": figure_name,
                "gutenberg_id": gutenberg_id,
                "raw_meta": common_meta,
            }
        )
        return items

    video_id = _extract_youtube_video_id(source_url)
    if video_id:
        items.append(
            {
                "user_id": user_id,
                "platform": "youtube",
                "external_id": video_id,
                "title": f"{figure_name} - YouTube {video_id}",
                "source_url": f"https://www.youtube.com/watch?v={video_id}",
                "youtube_video_id": video_id,
                "raw_meta": common_meta,
            }
        )
        return items

    playlist_id = _extract_youtube_playlist_id(source_url)
    if playlist_id:
        ids = _playlist_video_ids(source_url, max_playlist_items=max_playlist_items)
        for video_id in ids:
            items.append(
                {
                    "user_id": user_id,
                    "platform": "youtube",
                    "external_id": video_id,
                    "title": f"{figure_name} - YouTube {video_id}",
                    "source_url": f"https://www.youtube.com/watch?v={video_id}",
                    "youtube_video_id": video_id,
                    "raw_meta": {
                        **common_meta,
                        "playlist_id": playlist_id,
                    },
                }
            )
        return items

    text = _download_as_text(source_url)
    items.append(
        {
            "user_id": user_id,
            "platform": "local",
            "external_id": _stable_id(source_url),
            "title": _title_from_url(source_url, fallback=f"{figure_name} - Source"),
            "source_url": source_url,
            "author": figure_name,
            "text": text,
            "raw_meta": common_meta,
        }
    )
    return items


def _append_segment_cache(
    *,
    report: Any,
    cache_dir: Path,
    lookup: dict[SourceCacheKey, dict[str, Any]],
) -> int:
    cache_dir.mkdir(parents=True, exist_ok=True)
    lines_written = 0
    for source in report.sources:
        key = SourceCacheKey(
            user_id=source.user_id,
            platform=source.platform,
            external_id=source.external_id,
        )
        context = lookup.get(key, {})
        output_path = cache_dir / f"{source.user_id}.jsonl"
        segments = source.segments or []
        if not segments:
            continue
        with output_path.open("a", encoding="utf-8") as fh:
            for seg in segments:
                record = {
                    "run_id": report.run_id,
                    "source_status": source.status,
                    "user_id": source.user_id,
                    "platform": source.platform,
                    "external_id": source.external_id,
                    "group_id": source.group_id,
                    "title": source.title,
                    "source_url": source.source_url,
                    "figure_name": context.get("figure_name"),
                    "source_url": context.get("source_url"),
                    "segment": seg.model_dump(mode="json"),
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                lines_written += 1
    return lines_written


async def _run(args: argparse.Namespace) -> int:
    figures = _load_relaxed_json(args.input)
    manifest_sources: list[dict[str, Any]] = []
    lookup: dict[SourceCacheKey, dict[str, Any]] = {}
    unsupported: list[str] = []

    for figure_name, details_any in figures.items():
        if not isinstance(details_any, dict):
            unsupported.append(f"{figure_name}: entry must be an object")
            continue
        avatar = details_any.get("avatar")
        bio = details_any.get("bio")
        sources = details_any.get("sources")
        if not isinstance(sources, list):
            unsupported.append(f"{figure_name}: sources must be a list")
            continue
        user_id = _slugify(figure_name)
        for source_url_any in sources:
            if not isinstance(source_url_any, str):
                unsupported.append(f"{figure_name}: non-string source skipped")
                continue
            source_url = source_url_any.strip()
            if not source_url:
                continue
            try:
                items = _manifest_items_for_source(
                    figure_name=figure_name,
                    user_id=user_id,
                    avatar=avatar if isinstance(avatar, str) else None,
                    bio=bio if isinstance(bio, str) else None,
                    source_url=source_url,
                    max_playlist_items=args.max_playlist_items,
                )
                manifest_sources.extend(items)
                for item in items:
                    key = SourceCacheKey(
                        user_id=item["user_id"],
                        platform=item["platform"],
                        external_id=str(item["external_id"]),
                    )
                    lookup[key] = {
                        "figure_name": figure_name,
                        "source_url": source_url,
                    }
            except Exception as exc:  # noqa: BLE001
                unsupported.append(f"{figure_name}: {source_url} -> {exc}")

    if not manifest_sources:
        print("No ingestible sources were produced from input JSON.", file=sys.stderr)
        for line in unsupported:
            print(f"- {line}", file=sys.stderr)
        return 2

    manifest = Manifest(
        version="1",
        run_name=args.run_name,
        sources=[ManifestSourceItem.model_validate(item) for item in manifest_sources],
    )

    try:
        cfg = load_runtime_config(index_path=args.index_path)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    index = IngestionIndex(cfg.index_path)
    client = EverMemOSClient(
        cfg.emos_base_url,
        api_key=cfg.emos_api_key,
        timeout=cfg.emos_timeout_s,
        retries=cfg.emos_retries,
    )
    try:
        report = await ingest_manifest(
            manifest=manifest,
            index=index,
            client=client,
            redact_secrets=[cfg.emos_api_key or ""],
            include_segment_details=True,
        )
    finally:
        await client.aclose()

    report_path = args.report_path
    if report_path is None:
        report_path = str(
            (
                Path.cwd() / ".ingestion_service" / "reports" / f"{report.run_id}.json"
            ).resolve()
        )
    write_report(report, path=Path(report_path), secrets=[cfg.emos_api_key or ""])

    cache_lines = _append_segment_cache(
        report=report,
        cache_dir=args.cache_dir,
        lookup=lookup,
    )

    print(
        f"run_id={report.run_id} status={report.status} "
        f"sources_total={report.summary.sources_total} "
        f"succeeded={report.summary.sources_succeeded} "
        f"failed={report.summary.sources_failed}"
    )
    print(f"report_path={report_path}")
    print(f"segment_cache_lines_written={cache_lines}")

    if unsupported:
        print("unsupported_or_failed_source_parsing:")
        for line in unsupported:
            print(f"- {line}")
        if args.strict:
            return 2

    return 0 if report.status == "done" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest figure JSON sources into EverMemOS and cache segment results as JSONL."
    )
    parser.add_argument("--input", type=Path, required=True, help="Path to JSON file")
    parser.add_argument(
        "--run-name", default="figures-json-ingest", help="Optional run name"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(".ingestion_service/segment_cache"),
        help="Directory for per-user JSONL segment cache",
    )
    parser.add_argument(
        "--index-path", default=None, help="Optional ingestion index SQLite path"
    )
    parser.add_argument(
        "--report-path", default=None, help="Optional ingestion report path"
    )
    parser.add_argument(
        "--max-playlist-items",
        type=int,
        default=20,
        help="Limit videos expanded from a playlist URL",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero if any source URL could not be parsed/downloaded",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
