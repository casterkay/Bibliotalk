from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bt_common.evidence_store.models import Figure, Subscription
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import RuntimeConfig


@dataclass(slots=True)
class PollerSnapshot:
    active_subscriptions: int
    figure_slug: str | None


class CollectorPoller:
    def __init__(
        self,
        *,
        config: RuntimeConfig,
        session_factory: async_sessionmaker[AsyncSession],
        logger,
    ):
        self.config = config
        self.session_factory = session_factory
        self.logger = logger
        self._stopped = asyncio.Event()

    async def run_once(self) -> PollerSnapshot:
        async with self.session_factory() as session:
            stmt = (
                select(Subscription)
                .join(Figure, Figure.figure_id == Subscription.figure_id)
                .where(Subscription.is_active.is_(True))
            )
            if self.config.figure_slug:
                stmt = stmt.where(Figure.emos_user_id == self.config.figure_slug)
            subscriptions = (await session.execute(stmt)).scalars().all()
        self.logger.info(
            "collector poll tick figure_slug=%s subscriptions=%s",
            self.config.figure_slug or "*",
            len(subscriptions),
        )
        return PollerSnapshot(
            active_subscriptions=len(subscriptions), figure_slug=self.config.figure_slug
        )

    async def run_forever(self) -> None:
        while not self._stopped.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=self.config.poll_interval_minutes * 60,
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stopped.set()
