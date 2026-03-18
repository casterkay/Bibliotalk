from __future__ import annotations

import argparse
import asyncio

from memory_service.ops import request_manual_ingest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Request a manual one-shot ingest for a YouTube video"
    )
    parser.add_argument("--agent", dest="agent_slug", required=True)
    parser.add_argument("--video-id", dest="video_id", required=True)
    parser.add_argument("--title", dest="title", default="(manual ingest requested)")
    parser.add_argument("--source-url", dest="source_url")
    parser.add_argument("--db", dest="db_path")
    return parser


async def trigger_manual_ingest(
    *,
    db_path: str | None,
    agent_slug: str,
    video_id: str,
    title: str,
    source_url: str | None,
) -> None:
    await request_manual_ingest(
        db_path=db_path,
        agent_slug=agent_slug,
        external_id=video_id,
        title=title,
        source_url=source_url,
    )


def main() -> int:
    args = build_parser().parse_args()
    try:
        asyncio.run(
            trigger_manual_ingest(
                db_path=args.db_path,
                agent_slug=args.agent_slug,
                video_id=args.video_id,
                title=args.title,
                source_url=args.source_url,
            )
        )
    except LookupError as exc:
        print(str(exc))
        return 1

    print(
        f"Manual ingest requested for '{args.agent_slug}' video '{args.video_id}'. Run memory_service with --once to process it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
