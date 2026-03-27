from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from bt_store.engine import get_session_factory, init_database
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def get_webui_session_factory() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


async def session_dep() -> AsyncIterator[AsyncSession]:
    session_factory = get_webui_session_factory()
    async with session_factory() as session:
        yield session


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_database()
    yield
