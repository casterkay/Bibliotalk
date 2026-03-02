from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bt_common.evermemos_client import EverMemOSClient
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .adapters.local_text import load_file_source, load_text_source
from .domain.errors import ConfigError, IngestError, InvalidInputError
from .domain.models import IngestReport
from .pipeline.index import IngestionIndex
from .pipeline.ingest import ingest_manifest as ingest_manifest_pipeline
from .pipeline.ingest import ingest_sources
from .pipeline.manifest import Manifest
from .runtime.config import RuntimeConfig, load_runtime_config
from .runtime.reporting import write_report

app = FastAPI(title="Bibliotalk Ingestion Service", version="0.1.0")


class TextIngestRequest(BaseModel):
    user_id: str
    platform: str
    external_id: str
    title: str
    text: str
    source_url: str | None = None
    author: str | None = None
    published_at: str | None = None
    index_path: str | None = None
    report_path: str | None = None


class FileIngestRequest(BaseModel):
    user_id: str
    platform: str
    external_id: str
    title: str
    path: str
    source_url: str | None = None
    author: str | None = None
    published_at: str | None = None
    index_path: str | None = None
    report_path: str | None = None


class ManifestIngestRequest(BaseModel):
    manifest: Manifest
    index_path: str | None = None
    report_path: str | None = None


@dataclass(frozen=True, slots=True)
class _Runtime:
    cfg: RuntimeConfig
    index: IngestionIndex
    client: EverMemOSClient


def _default_report_path(*, run_id: str) -> Path:
    return (Path.cwd() / ".ingestion_service" / "reports" / f"{run_id}.json").resolve()


def _resolve_report_path(path: str | None, *, run_id: str) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    return _default_report_path(run_id=run_id)


def _build_runtime(*, index_path: str | None) -> _Runtime:
    cfg = load_runtime_config(index_path=index_path)
    index = IngestionIndex(cfg.index_path)
    client = EverMemOSClient(
        cfg.emos_base_url,
        api_key=cfg.emos_api_key,
        timeout=cfg.emos_timeout_s,
        retries=cfg.emos_retries,
    )
    return _Runtime(cfg=cfg, index=index, client=client)


def _to_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ConfigError, InvalidInputError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, IngestError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=500, detail="Internal ingestion error")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest/text", response_model=IngestReport)
async def ingest_text(req: TextIngestRequest) -> IngestReport:
    try:
        rt = _build_runtime(index_path=req.index_path)
        try:
            source_content = load_text_source(
                user_id=req.user_id,
                platform=req.platform,
                external_id=req.external_id,
                title=req.title,
                text=req.text,
                source_url=req.source_url,
                author=req.author,
                published_at=req.published_at,
            )
            report = await ingest_sources(
                sources=[source_content],
                index=rt.index,
                client=rt.client,
                redact_secrets=[rt.cfg.emos_api_key or ""],
            )
        finally:
            await rt.client.aclose()
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc

    write_report(
        report,
        path=_resolve_report_path(req.report_path, run_id=report.run_id),
        secrets=[rt.cfg.emos_api_key or ""],
    )
    return report


@app.post("/ingest/file", response_model=IngestReport)
async def ingest_file(req: FileIngestRequest) -> IngestReport:
    try:
        rt = _build_runtime(index_path=req.index_path)
        try:
            source_content = load_file_source(
                user_id=req.user_id,
                platform=req.platform,
                external_id=req.external_id,
                title=req.title,
                path=Path(req.path),
                source_url=req.source_url,
                author=req.author,
                published_at=req.published_at,
            )
            report = await ingest_sources(
                sources=[source_content],
                index=rt.index,
                client=rt.client,
                redact_secrets=[rt.cfg.emos_api_key or ""],
            )
        finally:
            await rt.client.aclose()
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc

    write_report(
        report,
        path=_resolve_report_path(req.report_path, run_id=report.run_id),
        secrets=[rt.cfg.emos_api_key or ""],
    )
    return report


@app.post("/ingest/manifest", response_model=IngestReport)
async def ingest_manifest(req: ManifestIngestRequest) -> IngestReport:
    try:
        rt = _build_runtime(index_path=req.index_path)
        try:
            report = await ingest_manifest_pipeline(
                manifest=req.manifest,
                index=rt.index,
                client=rt.client,
                redact_secrets=[rt.cfg.emos_api_key or ""],
            )
        finally:
            await rt.client.aclose()
    except Exception as exc:  # noqa: BLE001
        raise _to_http_error(exc) from exc

    write_report(
        report,
        path=_resolve_report_path(req.report_path, run_id=report.run_id),
        secrets=[rt.cfg.emos_api_key or ""],
    )
    return report


def create_app() -> FastAPI:
    return app
