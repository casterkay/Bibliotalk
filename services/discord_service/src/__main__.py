from __future__ import annotations

import argparse
import asyncio

from .config import load_runtime_config
from .runtime import build_live_discord_runtime, configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bibliotalk Discord runtime")
    parser.add_argument("--figure", dest="figure_slug")
    parser.add_argument("--db", dest="db_path")
    parser.add_argument("--log-level", dest="log_level")
    parser.add_argument("--discord-token", dest="discord_token")
    return parser


async def _main_async() -> int:
    args = build_parser().parse_args()
    config = load_runtime_config(
        db_path=args.db_path,
        figure_slug=args.figure_slug,
        log_level=args.log_level,
        discord_token=args.discord_token,
    )
    logger = configure_logging(level=config.log_level)
    if not config.discord_token:
        logger.error(
            "discord runtime missing token figure_slug=%s expected_env=DISCORD_TOKEN or scoped token",
            config.figure_slug,
        )
        return 1
    runtime = await build_live_discord_runtime(config, logger_=logger)
    logger.info(
        "starting discord runtime figure_slug=%s display_name=%s",
        runtime.context.figure_slug,
        runtime.context.display_name,
    )
    await runtime.client.start(config.discord_token)
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
