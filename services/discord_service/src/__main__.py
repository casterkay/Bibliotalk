from __future__ import annotations

import argparse
import asyncio

from .config import load_runtime_config
from .runtime import build_runtime_context, configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bibliotalk Discord runtime")
    parser.add_argument("--figure", dest="figure_slug")
    parser.add_argument("--db", dest="db_path")
    parser.add_argument("--log-level", dest="log_level")
    return parser


async def _main_async() -> int:
    args = build_parser().parse_args()
    config = load_runtime_config(
        db_path=args.db_path, figure_slug=args.figure_slug, log_level=args.log_level
    )
    logger = configure_logging(level=config.log_level)
    context = await build_runtime_context(config)
    logger.info(
        "discord runtime initialized figure_slug=%s figure_found=%s",
        context.figure_slug,
        context.figure_found,
    )
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
