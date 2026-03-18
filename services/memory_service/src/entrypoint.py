from __future__ import annotations

import asyncio

from bt_common.evermemos_client import EverMemOSClient
from bt_store.engine import get_session_factory, init_database

from .runtime.config import load_runtime_config
from .runtime.poller import CollectorPoller
from .runtime.reporting import configure_logging


async def run_collector(
    *,
    agent_slug: str | None = None,
    db_path: str | None = None,
    log_level: str | None = None,
    once: bool = False,
) -> int:
    config = load_runtime_config(db_path=db_path, agent_slug=agent_slug, log_level=log_level)
    logger = configure_logging(level=config.log_level)
    await init_database(config.db_path)
    client = EverMemOSClient(
        config.emos_base_url,
        api_key=config.emos_api_key,
        timeout=config.emos_timeout_s,
        retries=config.emos_retries,
    )
    poller = CollectorPoller(
        config=config,
        session_factory=get_session_factory(config.db_path),
        logger=logger,
        client=client,
    )
    try:
        if once:
            await poller.run_once()
            return 0
        await poller.run_forever()
        return 0
    finally:
        await client.aclose()


def run_collector_sync(**kwargs) -> int:
    return asyncio.run(run_collector(**kwargs))
