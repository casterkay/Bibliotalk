from __future__ import annotations

import asyncio
import time
from uuid import uuid4

import pytest
from memory_service.runtime.poller import SubscriptionConcurrencyGate


@pytest.mark.anyio
async def test_same_subscription_id_runs_serially() -> None:
    gate = SubscriptionConcurrencyGate(global_limit=4)
    subscription_id = uuid4()
    events: list[str] = []

    async def task(name: str) -> str:
        events.append(f"start:{name}")
        await asyncio.sleep(0.05)
        events.append(f"end:{name}")
        return name

    started = time.perf_counter()
    results = await asyncio.gather(
        gate.run(subscription_id, lambda: task("first")),
        gate.run(subscription_id, lambda: task("second")),
    )
    elapsed = time.perf_counter() - started

    assert results == ["first", "second"]
    assert events == ["start:first", "end:first", "start:second", "end:second"]
    assert elapsed >= 0.09


@pytest.mark.anyio
async def test_different_subscription_ids_can_run_in_parallel() -> None:
    gate = SubscriptionConcurrencyGate(global_limit=4)
    first_id = uuid4()
    second_id = uuid4()

    async def task(name: str) -> str:
        await asyncio.sleep(0.05)
        return name

    started = time.perf_counter()
    results = await asyncio.gather(
        gate.run(first_id, lambda: task("first")),
        gate.run(second_id, lambda: task("second")),
    )
    elapsed = time.perf_counter() - started

    assert results == ["first", "second"]
    assert elapsed < 0.09
