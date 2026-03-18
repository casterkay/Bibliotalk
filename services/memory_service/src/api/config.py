from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bt_common.config import load_repo_dotenv
from bt_store.engine import default_database_path, resolve_database_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..domain.errors import ConfigError
from ..runtime.config import default_index_path

load_repo_dotenv(override=True)


class MemoriesApiSettings(BaseSettings):
    bibliotalk_db_path: str | None = Field(default=None, validation_alias="BIBLIOTALK_DB_PATH")
    host: str = Field(default="127.0.0.1", validation_alias="MEMORIES_HOST")
    port: int = Field(default=8080, validation_alias="MEMORIES_PORT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    emos_base_url: str | None = Field(default=None, validation_alias="EMOS_BASE_URL")
    emos_api_key: str | None = Field(default=None, validation_alias="EMOS_API_KEY")
    emos_timeout_s: float = Field(default=15.0, validation_alias="EMOS_TIMEOUT_S")
    emos_retries: int = Field(default=3, validation_alias="EMOS_RETRIES")

    ingest_index_path: str | None = Field(default=None, validation_alias="INGEST_INDEX_PATH")

    model_config = SettingsConfigDict(extra="ignore")


@dataclass(frozen=True, slots=True)
class MemoriesApiRuntimeConfig:
    db_path: Path
    host: str
    port: int
    log_level: str
    emos_base_url: str
    emos_api_key: str | None
    emos_timeout_s: float
    emos_retries: int
    index_path: Path


def load_memories_api_config(
    *,
    db_path: str | None = None,
    host: str | None = None,
    port: int | None = None,
    log_level: str | None = None,
    emos_base_url: str | None = None,
    emos_api_key: str | None = None,
    index_path: str | None = None,
) -> MemoriesApiRuntimeConfig:
    settings = MemoriesApiSettings()

    base_url = (emos_base_url or settings.emos_base_url or "").strip()
    if not base_url:
        raise ConfigError("Missing EverMemOS base URL. Set `EMOS_BASE_URL`.")

    resolved_index = Path(
        index_path or settings.ingest_index_path or default_index_path()
    ).expanduser()
    if not resolved_index.is_absolute():
        resolved_index = (Path.cwd() / resolved_index).resolve()

    return MemoriesApiRuntimeConfig(
        db_path=resolve_database_path(
            db_path or settings.bibliotalk_db_path or default_database_path()
        ),
        host=(host or settings.host).strip(),
        port=int(port or settings.port),
        log_level=(log_level or settings.log_level).upper(),
        emos_base_url=base_url.rstrip("/"),
        emos_api_key=emos_api_key if emos_api_key is not None else settings.emos_api_key,
        emos_timeout_s=float(settings.emos_timeout_s),
        emos_retries=int(settings.emos_retries),
        index_path=resolved_index,
    )
