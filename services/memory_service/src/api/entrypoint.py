from __future__ import annotations

import asyncio

import uvicorn

from .app import create_app
from .config import load_memories_api_config


async def run_memories_api(
    *,
    db_path: str | None = None,
    host: str | None = None,
    port: int | None = None,
    log_level: str | None = None,
) -> int:
    config = load_memories_api_config(db_path=db_path, host=host, port=port, log_level=log_level)
    await asyncio.to_thread(
        uvicorn.run,
        create_app(config),
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )
    return 0
