from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bt_common.config import load_repo_dotenv
from bt_store.engine import default_database_path, resolve_database_path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..domain.errors import ConfigError

# Ensure the shared repo-root `.env` is loaded for memory_service.
# Use `override=True` so local runs are deterministic even if the parent shell
# already has stale env vars exported.
load_repo_dotenv(override=True)


class IngestSettings(BaseSettings):
    bibliotalk_db_path: str | None = Field(default=None, validation_alias="BIBLIOTALK_DB_PATH")
    agent_slug: str | None = Field(default=None, validation_alias="BIBLIOTALK_AGENT")
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
    youtube_transcript_providers: str = Field(
        default="youtube_transcript_api,yt_dlp",
        validation_alias="BIBLIOTALK_YOUTUBE_TRANSCRIPT_PROVIDERS",
    )
    youtube_transcript_langs: str | None = Field(
        default=None, validation_alias="BIBLIOTALK_YOUTUBE_TRANSCRIPT_LANGS"
    )
    youtube_allow_auto_captions: bool = Field(
        default=True, validation_alias="BIBLIOTALK_YOUTUBE_ALLOW_AUTO_CAPTIONS"
    )
    yt_dlp_cookiefile: str | None = Field(
        default=None, validation_alias="BIBLIOTALK_YT_DLP_COOKIEFILE"
    )
    yt_dlp_impersonate: str | None = Field(
        default="", validation_alias="BIBLIOTALK_YT_DLP_IMPERSONATE"
    )
    youtube_request_delay_s: float = Field(
        default=0.25, validation_alias="BIBLIOTALK_YOUTUBE_REQUEST_DELAY_S"
    )
    youtube_request_jitter_s: float = Field(
        default=0.5, validation_alias="BIBLIOTALK_YOUTUBE_REQUEST_JITTER_S"
    )

    model_config = SettingsConfigDict(extra="ignore")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    db_path: Path
    agent_slug: str | None
    global_concurrency: int
    source_concurrency: int
    poll_interval_minutes: int
    log_level: str
    emos_base_url: str
    emos_api_key: str | None
    emos_timeout_s: float
    emos_retries: int
    index_path: Path
    youtube_transcript_providers: tuple[str, ...]
    youtube_transcript_langs: tuple[str, ...] | None
    youtube_allow_auto_captions: bool
    yt_dlp_cookiefile: str | None
    yt_dlp_impersonate_target: str | None
    youtube_request_delay_s: float
    youtube_request_jitter_s: float


def default_index_path() -> Path:
    # Local, repo-friendly default. This directory is expected to be gitignored.
    return Path.cwd() / ".memory_service" / "index.sqlite3"


def load_runtime_config(
    *,
    db_path: str | None = None,
    agent_slug: str | None = None,
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
        agent_slug=(agent_slug or settings.agent_slug or "").strip() or None,
        global_concurrency=max(1, int(settings.global_concurrency)),
        source_concurrency=max(1, int(settings.source_concurrency)),
        poll_interval_minutes=max(1, int(settings.poll_interval_minutes)),
        log_level=(log_level or settings.log_level).upper(),
        emos_base_url=base_url.rstrip("/"),
        emos_api_key=emos_api_key if emos_api_key is not None else settings.emos_api_key,
        emos_timeout_s=float(settings.emos_timeout_s),
        emos_retries=int(settings.emos_retries),
        index_path=resolved_index,
        youtube_transcript_providers=tuple(
            [
                item.strip()
                for item in (settings.youtube_transcript_providers or "").split(",")
                if item.strip()
            ]
        )
        or ("yt_dlp", "youtube_transcript_api"),
        youtube_transcript_langs=tuple(
            [
                item.strip()
                for item in (settings.youtube_transcript_langs or "").split(",")
                if item.strip()
            ]
        )
        or None,
        youtube_allow_auto_captions=bool(settings.youtube_allow_auto_captions),
        yt_dlp_cookiefile=(settings.yt_dlp_cookiefile or "").strip() or None,
        yt_dlp_impersonate_target=(settings.yt_dlp_impersonate or "").strip() or None,
        youtube_request_delay_s=max(0.0, float(settings.youtube_request_delay_s)),
        youtube_request_jitter_s=max(0.0, float(settings.youtube_request_jitter_s)),
    )
