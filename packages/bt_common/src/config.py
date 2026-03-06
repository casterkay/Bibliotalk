"""Shared application configuration."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_repo_env_file(filename: str = ".env") -> str | None:
    """Find a repo-root `.env` when running from service subdirectories.

    Searches the current working directory and parents for `filename`.
    Returns an absolute path string if found, otherwise None.
    """

    start = Path.cwd().resolve()
    for candidate_dir in (start, *start.parents):
        candidate = candidate_dir / filename
        if candidate.is_file():
            return str(candidate)
    return None


_ENV_FILE = _resolve_repo_env_file(".env")


class Settings(BaseSettings):
    """Environment-backed settings used by all service modules."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    GOOGLE_API_KEY: str | None = None
    # Storage (agents_service canonical store)
    # - Local dev default is SQLite (see agents_service.database.sqlalchemy_store.default_sqlite_url()).
    # - Production target is Postgres with the same SQLAlchemy ORM models.
    DATABASE_URL: str | None = None
    EMOS_BASE_URL: str
    EMOS_API_KEY: str | None = None
    AWS_REGION: str = "us-east-1"
    MATRIX_HOMESERVER_URL: str
    MATRIX_AS_TOKEN: str
    MATRIX_HS_TOKEN: str
    # Optional: Synapse admin login for scripted local provisioning
    MATRIX_SERVER_NAME: str | None = None
    MATRIX_ADMIN_USER: str | None = None
    MATRIX_ADMIN_PASSWORD: str | None = None
    LOG_LEVEL: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


class EMOSFallbackSettings(BaseSettings):
    """Optional EMOS values loaded from .env for local/dev fallback."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    EMOS_BASE_URL: str | None = None
    EMOS_API_KEY: str | None = None


@lru_cache(maxsize=1)
def get_emos_fallback_settings() -> EMOSFallbackSettings:
    return EMOSFallbackSettings()
