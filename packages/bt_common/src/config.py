"""Shared application configuration."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
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


def load_repo_dotenv(*, override: bool = False) -> None:
    """Load the repo-root `.env` into `os.environ` for all packages.

    This is a thin wrapper around `python-dotenv` that centralizes how we
    discover and load the shared `.env` file. It is safe to call multiple
    times; later calls will be no-ops unless `override=True`.
    """

    if _ENV_FILE:
        load_dotenv(_ENV_FILE, override=override)


class Settings(BaseSettings):
    """Environment-backed settings used by all service modules."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    GOOGLE_API_KEY: str | None = None
    BIBLIOTALK_DB_PATH: str | None = None
    DATABASE_URL: str | None = None
    EMOS_BASE_URL: str | None = None
    EMOS_API_KEY: str | None = None
    AWS_REGION: str = "us-east-1"
    LOG_LEVEL: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_repo_dotenv()
    return Settings()


class EMOSFallbackSettings(BaseSettings):
    """Optional EMOS values loaded from .env for local/dev fallback."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    EMOS_BASE_URL: str | None = None
    EMOS_API_KEY: str | None = None


@lru_cache(maxsize=1)
def get_emos_fallback_settings() -> EMOSFallbackSettings:
    return EMOSFallbackSettings()
