from __future__ import annotations

import argparse
import asyncio

from bt_common.evidence_store.engine import get_session_factory, init_database

from .runtime.config import load_runtime_config
from .runtime.poller import CollectorPoller
from .runtime.reporting import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bibliotalk collector runtime")
    parser.add_argument("--figure", dest="figure_slug")
    parser.add_argument("--db", dest="db_path")
    parser.add_argument("--log-level", dest="log_level")
    parser.add_argument("--once", action="store_true")
    return parser


async def _main_async() -> int:
    args = build_parser().parse_args()
    config = load_runtime_config(
        db_path=args.db_path, figure_slug=args.figure_slug, log_level=args.log_level
    )
    logger = configure_logging(level=config.log_level)
    await init_database(config.db_path)
    poller = CollectorPoller(
        config=config,
        session_factory=get_session_factory(config.db_path),
        logger=logger,
    )
    if args.once:
        await poller.run_once()
        return 0
    await poller.run_forever()
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
