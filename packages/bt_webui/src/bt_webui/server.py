from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.agents import router as agents_router
from .api.auth_routes import router as auth_router
from .api.collector import router as collector_router
from .api.delete import router as delete_router
from .api.emos import router as emos_router
from .api.ingest import router as ingest_router
from .api.routes import router as routes_router
from .api.sources import router as sources_router
from .api.subscriptions import router as subscriptions_router
from .db import lifespan


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[override]
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            index = Path(self.directory) / "index.html"  # type: ignore[arg-type]
            if index.is_file():
                return FileResponse(str(index))
            raise


def create_app() -> FastAPI:
    app = FastAPI(title="Bibliotalk WebUI", version="0.1.0", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router, prefix="/api")
    app.include_router(agents_router, prefix="/api")
    app.include_router(subscriptions_router, prefix="/api")
    app.include_router(routes_router, prefix="/api")
    app.include_router(sources_router, prefix="/api")
    app.include_router(collector_router, prefix="/api")
    app.include_router(ingest_router, prefix="/api")
    app.include_router(delete_router, prefix="/api")
    app.include_router(emos_router, prefix="/api")

    web_out = (os.getenv("BIBLIOTALK_WEBUI_STATIC_DIR") or "").strip()
    if web_out:
        out_dir = Path(web_out).expanduser()
    else:
        # `packages/bt_webui/web/out` after `next build` when `output: "export"`.
        out_dir = Path(__file__).resolve().parents[2] / "web" / "out"

    if out_dir.is_dir():
        app.mount("/", SPAStaticFiles(directory=str(out_dir), html=True), name="web")

    return app
