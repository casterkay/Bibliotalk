from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bt_common.config import load_repo_dotenv
from bt_common.evidence_store.engine import default_database_path, resolve_database_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_repo_dotenv()


class DiscordSettings(BaseSettings):
    bibliotalk_db_path: str | None = Field(
        default=None, validation_alias="BIBLIOTALK_DB_PATH"
    )
    figure_slug: str | None = Field(default=None, validation_alias="BIBLIOTALK_FIGURE")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    model_config = SettingsConfigDict(extra="ignore")


@dataclass(frozen=True, slots=True)
class DiscordRuntimeConfig:
    db_path: Path
    figure_slug: str | None
    log_level: str


def load_runtime_config(
    *,
    db_path: str | None = None,
    figure_slug: str | None = None,
    log_level: str | None = None,
) -> DiscordRuntimeConfig:
    settings = DiscordSettings()
    return DiscordRuntimeConfig(
        db_path=resolve_database_path(
            db_path or settings.bibliotalk_db_path or default_database_path()
        ),
        figure_slug=(figure_slug or settings.figure_slug or "").strip() or None,
        log_level=(log_level or settings.log_level).upper(),
    )
