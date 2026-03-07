from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bt_common.config import load_repo_dotenv
from bt_common.evidence_store.engine import default_database_path, resolve_database_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..domain.errors import ConfigError

# Ensure the shared repo-root `.env` is loaded for ingestion_service.
load_repo_dotenv()


class IngestSettings(BaseSettings):
    bibliotalk_db_path: str | None = Field(default=None, validation_alias="BIBLIOTALK_DB_PATH")
    figure_slug: str | None = Field(default=None, validation_alias="BIBLIOTALK_FIGURE")
    global_concurrency: int = Field(default=4, validation_alias="BIBLIOTALK_GLOBAL_CONCURRENCY")
    source_concurrency: int = Field(default=1, validation_alias="BIBLIOTALK_SOURCE_CONCURRENCY")
    poll_interval_minutes: int = Field(
        default=30, validation_alias="BIBLIOTALK_POLL_INTERVAL_MINUTES"
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    emos_base_url: str | None = Field(default=None, validation_alias="EMOS_BASE_URL")
    emos_api_key: str | None = Field(default=None, validation_alias="EMOS_API_KEY")
    emos_timeout_s: float = Field(default=15.0, validation_alias="EMOS_TIMEOUT_S")
    emos_retries: int = Field(default=3, validation_alias="EMOS_RETRIES")
    ingest_index_path: str | None = Field(default=None, validation_alias="INGEST_INDEX_PATH")

    model_config = SettingsConfigDict(extra="ignore")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    db_path: Path
    figure_slug: str | None
    global_concurrency: int
    source_concurrency: int
    poll_interval_minutes: int
    log_level: str
    emos_base_url: str
    emos_api_key: str | None
    emos_timeout_s: float
    emos_retries: int
    index_path: Path


def default_index_path() -> Path:
    # Local, repo-friendly default. This directory is expected to be gitignored.
    return Path.cwd() / ".ingestion_service" / "index.sqlite3"


def load_runtime_config(
    *,
    db_path: str | None = None,
    figure_slug: str | None = None,
    log_level: str | None = None,
    emos_base_url: str | None = None,
    emos_api_key: str | None = None,
    index_path: str | None = None,
) -> RuntimeConfig:
    settings = IngestSettings()

    base_url = (emos_base_url or settings.emos_base_url or "").strip()
    if not base_url:
        raise ConfigError(
            "Missing EverMemOS base URL. Set `EMOS_BASE_URL` or pass `--emos-base-url`."
        )

    resolved_db_path = resolve_database_path(
        db_path or settings.bibliotalk_db_path or default_database_path()
    )
    resolved_index = Path(
        index_path or settings.ingest_index_path or default_index_path()
    ).expanduser()
    if not resolved_index.is_absolute():
        resolved_index = (Path.cwd() / resolved_index).resolve()

    return RuntimeConfig(
        db_path=resolved_db_path,
        figure_slug=(figure_slug or settings.figure_slug or "").strip() or None,
        global_concurrency=max(1, int(settings.global_concurrency)),
        source_concurrency=max(1, int(settings.source_concurrency)),
        poll_interval_minutes=max(1, int(settings.poll_interval_minutes)),
        log_level=(log_level or settings.log_level).upper(),
        emos_base_url=base_url.rstrip("/"),
        emos_api_key=emos_api_key if emos_api_key is not None else settings.emos_api_key,
        emos_timeout_s=float(settings.emos_timeout_s),
        emos_retries=int(settings.emos_retries),
        index_path=resolved_index,
    )
