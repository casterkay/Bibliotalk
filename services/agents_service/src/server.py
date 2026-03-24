from __future__ import annotations

from fastapi import FastAPI

from .api.errors import install_error_handlers
from .api.live import router as live_router
from .api.turns import router as turns_router


def create_app() -> FastAPI:
    app = FastAPI(title="Bibliotalk Agents Service", version="0.1.0")
    install_error_handlers(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(turns_router, prefix="/v1")
    app.include_router(live_router, prefix="/v1")
    return app


app = create_app()
