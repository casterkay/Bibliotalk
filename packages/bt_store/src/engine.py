from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from bt_common.config import get_settings
from sqlalchemy.exc import OperationalError
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
async def session_scope(db_path: str | Path | None = None):
    session_factory = get_session_factory(db_path)
    async with session_factory() as session:
        yield session


async def init_database(db_path: str | Path | None = None) -> None:
    from .models import Base

    engine = get_async_engine(db_path)
    # Multiple services can start concurrently and race on SQLite DDL (even with
    # `checkfirst=True`). Use a simple file lock to serialize schema creation.
    lock_path = resolve_database_path(db_path).with_suffix(".schema.lock")

    try:
        import fcntl  # Unix-only; safe to skip on platforms without it.
    except Exception:  # pragma: no cover
        fcntl = None  # type: ignore[assignment]

    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        if fcntl is not None:  # pragma: no branch
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

        async with engine.begin() as conn:
            try:
                await conn.run_sync(Base.metadata.create_all)
            except OperationalError as exc:
                # If another service beat us to a table/index creation, treat it as ok.
                msg = str(getattr(exc, "orig", exc)).lower()
                if "already exists" not in msg:
                    raise
    finally:
        try:
            if fcntl is not None:  # pragma: no branch
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()
