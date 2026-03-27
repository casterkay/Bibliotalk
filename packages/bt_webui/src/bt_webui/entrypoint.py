from __future__ import annotations

import asyncio

import uvicorn


async def run_webui(
    *,
    host: str = "127.0.0.1",
    port: int = 8090,
    log_level: str = "INFO",
) -> int:
    await asyncio.to_thread(
        uvicorn.run,
        "bt_webui.asgi:app",
        host=host,
        port=port,
        log_level=(log_level or "INFO").lower(),
    )
    return 0


def run_webui_sync(**kwargs) -> int:
    return asyncio.run(run_webui(**kwargs))
