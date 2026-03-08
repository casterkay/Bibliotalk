from __future__ import annotations

from .resolver import MemoryPageResolver


async def handle_memory_page_request(
    page_id: str, *, resolver: MemoryPageResolver
) -> dict:
    page = await resolver.resolve(page_id)
    return {
        "status": 200,
        "body": page.to_dict(),
    }
