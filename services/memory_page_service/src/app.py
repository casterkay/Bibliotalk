from __future__ import annotations

from html import escape

from bt_common.config import get_emos_fallback_settings
from bt_common.evermemos_client import EverMemOSClient
from bt_common.evidence_store.engine import get_session_factory
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .config import MemoryPageRuntimeConfig
from .resolver import MemoryPageResolver


async def handle_memory_page_request(
    page_id: str, *, resolver: MemoryPageResolver
) -> dict:
    page = await resolver.resolve(page_id)
    return {
        "status": 200,
        "body": page.to_dict(),
    }


def create_app(
    config: MemoryPageRuntimeConfig,
    *,
    evermemos_client: EverMemOSClient | None = None,
) -> FastAPI:
    app = FastAPI(title="Bibliotalk Memory Pages")
    session_factory = get_session_factory(config.db_path)
    client = evermemos_client or _build_evermemos_client()
    resolver = MemoryPageResolver(session_factory, evermemos_client=client)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/memory/{page_id}", response_class=HTMLResponse)
    async def memory_page(page_id: str) -> HTMLResponse:
        try:
            result = await resolver.resolve(page_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(
            content=_render_memory_page_html(result.to_dict()), status_code=200
        )

    return app


def _build_evermemos_client() -> EverMemOSClient:
    fallback = get_emos_fallback_settings()
    return EverMemOSClient(
        fallback.EMOS_BASE_URL or "",
        api_key=fallback.EMOS_API_KEY,
    )


def _render_memory_page_html(page: dict) -> str:
    summary = escape(
        str(
            page["memory_item"].get("summary")
            or page["memory_item"].get("content")
            or ""
        )
    )
    segment_text = escape(str(page["segment_text"]))
    source_title = escape(str(page["source_title"]))
    source_url = escape(str(page["source_url"]))
    video_url = escape(str(page["video_url_with_timestamp"]))
    timestamp = escape(str(page["memory_timestamp"]))
    return f"""
<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{source_title} | Bibliotalk Memory</title>
    <style>
      body {{ font-family: Georgia, serif; margin: 2rem auto; max-width: 760px; padding: 0 1rem; line-height: 1.6; color: #1f1a17; background: #f7f2ea; }}
      main {{ background: #fffaf2; border: 1px solid #dcc9ad; border-radius: 18px; padding: 2rem; box-shadow: 0 10px 30px rgba(80, 60, 20, 0.08); }}
      h1 {{ margin-top: 0; font-size: 2rem; }}
      .meta {{ color: #6f5c4b; font-size: 0.95rem; }}
      blockquote {{ margin: 1.5rem 0; padding-left: 1rem; border-left: 4px solid #b48a5a; }}
      a {{ color: #8a4b08; }}
    </style>
  </head>
  <body>
    <main>
      <h1>{source_title}</h1>
      <p class=\"meta\">Memory timestamp: {timestamp}</p>
      <p><strong>Resolved memory</strong></p>
      <blockquote>{summary}</blockquote>
      <p><strong>Verbatim segment</strong></p>
      <blockquote>{segment_text}</blockquote>
      <p><a href=\"{video_url}\">Open the source video at this timepoint</a></p>
      <p><a href=\"{source_url}\">Open the source video root URL</a></p>
    </main>
  </body>
</html>
""".strip()
