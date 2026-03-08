from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bt_common.config import load_repo_dotenv
from bt_common.evidence_store.engine import default_database_path, resolve_database_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_repo_dotenv()


class MemoryPageSettings(BaseSettings):
    bibliotalk_db_path: str | None = Field(
        default=None, validation_alias="BIBLIOTALK_DB_PATH"
    )
    host: str = Field(default="127.0.0.1", validation_alias="MEMORY_PAGE_HOST")
    port: int = Field(default=8080, validation_alias="MEMORY_PAGE_PORT")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    model_config = SettingsConfigDict(extra="ignore")


@dataclass(frozen=True, slots=True)
class MemoryPageRuntimeConfig:
    db_path: Path
    host: str
    port: int
    log_level: str


def load_runtime_config(
    *,
    db_path: str | None = None,
    host: str | None = None,
    port: int | None = None,
    log_level: str | None = None,
) -> MemoryPageRuntimeConfig:
    settings = MemoryPageSettings()
    return MemoryPageRuntimeConfig(
        db_path=resolve_database_path(
            db_path or settings.bibliotalk_db_path or default_database_path()
        ),
        host=(host or settings.host).strip(),
        port=port or settings.port,
        log_level=(log_level or settings.log_level).upper(),
    )
