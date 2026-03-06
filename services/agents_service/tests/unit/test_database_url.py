from __future__ import annotations

from agents_service.database import sqlalchemy_store


def test_normalize_database_url_sqlite_relative_is_repo_root_relative(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(sqlalchemy_store, "_repo_root", lambda: tmp_path)

    raw = "sqlite+aiosqlite:///./.agents_service/bibliotalk.sqlite"
    normalized = sqlalchemy_store.normalize_database_url(raw)

    expected_path = tmp_path / ".agents_service" / "bibliotalk.sqlite"
    assert str(expected_path) in normalized
    assert (tmp_path / ".agents_service").is_dir()


def test_normalize_database_url_memory_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sqlalchemy_store, "_repo_root", lambda: tmp_path)

    raw = "sqlite+aiosqlite:///:memory:"
    assert sqlalchemy_store.normalize_database_url(raw) == raw


def test_normalize_database_url_non_sqlite_noop() -> None:
    raw = "postgresql+asyncpg://user:pass@localhost:5432/db"
    assert sqlalchemy_store.normalize_database_url(raw) == raw
