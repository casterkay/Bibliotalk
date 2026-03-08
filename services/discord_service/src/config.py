from __future__ import annotations

import os
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
    discord_token: str | None = Field(default=None, validation_alias="DISCORD_TOKEN")

    model_config = SettingsConfigDict(extra="ignore")


@dataclass(frozen=True, slots=True)
class DiscordRuntimeConfig:
    db_path: Path
    figure_slug: str | None
    log_level: str
    discord_token: str | None


def discord_token_env_name(figure_slug: str) -> str:
    normalized = figure_slug.strip().upper().replace("-", "_")
    return f"DISCORD_TOKEN_{normalized}"


def resolve_discord_token(
    *, figure_slug: str | None, explicit_token: str | None = None
) -> str | None:
    if explicit_token:
        return explicit_token.strip() or None
    if figure_slug:
        scoped = os.getenv(discord_token_env_name(figure_slug), "").strip()
        if scoped:
            return scoped
    generic = os.getenv("DISCORD_TOKEN", "").strip()
    return generic or None


def load_runtime_config(
    *,
    db_path: str | None = None,
    figure_slug: str | None = None,
    log_level: str | None = None,
    discord_token: str | None = None,
) -> DiscordRuntimeConfig:
    settings = DiscordSettings()
    resolved_figure_slug = (figure_slug or settings.figure_slug or "").strip() or None
    return DiscordRuntimeConfig(
        db_path=resolve_database_path(
            db_path or settings.bibliotalk_db_path or default_database_path()
        ),
        figure_slug=resolved_figure_slug,
        log_level=(log_level or settings.log_level).upper(),
        discord_token=resolve_discord_token(
            figure_slug=resolved_figure_slug,
            explicit_token=discord_token or settings.discord_token,
        ),
    )
