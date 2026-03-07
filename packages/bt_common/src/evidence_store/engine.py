from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from bt_common.config import get_settings
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_ENGINES: dict[str, AsyncEngine] = {}
_SESSION_FACTORIES: dict[str, async_sessionmaker[AsyncSession]] = {}


def default_database_path() -> Path:
    return Path.home() / ".bibliotalk" / "bibliotalk.db"


def resolve_database_path(db_path: str | Path | None = None) -> Path:
    if db_path is None:
        settings = get_settings()
        candidate = settings.BIBLIOTALK_DB_PATH or default_database_path()
    else:
        candidate = db_path

    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def database_url_for_path(db_path: str | Path | None = None) -> str:
    path = resolve_database_path(db_path)
    return f"sqlite+aiosqlite:///{path}"


def get_async_engine(db_path: str | Path | None = None) -> AsyncEngine:
    url = database_url_for_path(db_path)
    engine = _ENGINES.get(url)
    if engine is None:
        engine = create_async_engine(url, future=True)
        _ENGINES[url] = engine
    return engine


def get_session_factory(db_path: str | Path | None = None) -> async_sessionmaker[AsyncSession]:
    url = database_url_for_path(db_path)
    factory = _SESSION_FACTORIES.get(url)
    if factory is None:
        factory = async_sessionmaker(get_async_engine(db_path), expire_on_commit=False)
        _SESSION_FACTORIES[url] = factory
    return factory


@asynccontextmanager
async def get_session(db_path: str | Path | None = None):
    session_factory = get_session_factory(db_path)
    async with session_factory() as session:
        yield session


async def init_database(db_path: str | Path | None = None) -> None:
    from .models import Base

    engine = get_async_engine(db_path)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
