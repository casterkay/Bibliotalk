from __future__ import annotations

from html import escape

from .models import ApiMemCellRecord


def render_memcell_html(record: ApiMemCellRecord) -> str:
    source_title = escape(record.source.title)
    source_url = escape(record.source.url)
    memory_id = escape(record.id)
    timestamp = escape(record.timestamp.isoformat())
    summary = escape(str(record.memcell.get("summary") or record.memcell.get("content") or ""))

    chunks_html = "\n".join(
        f"<blockquote>{escape(chunk.text)}</blockquote>" for chunk in record.chunks
    )
    video_url = escape(record.links.video_at_timepoint or "")

    video_block = ""
    if record.links.video_at_timepoint:
        video_block = f'<p><a href="{video_url}">Open the source at this timepoint</a></p>'

    source_link_block = ""
    if record.source.url:
        source_link_block = f'<p><a href="{source_url}">Open the source</a></p>'

    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{source_title} | Bibliotalk Memory</title>
    <style>
      body {{ font-family: Georgia, serif; margin: 2rem auto; max-width: 820px; padding: 0 1rem; line-height: 1.6; color: #1f1a17; background: #f7f2ea; }}
      main {{ background: #fffaf2; border: 1px solid #dcc9ad; border-radius: 18px; padding: 2rem; box-shadow: 0 10px 30px rgba(80, 60, 20, 0.08); }}
      h1 {{ margin-top: 0; font-size: 2rem; }}
      .meta {{ color: #6f5c4b; font-size: 0.95rem; }}
      blockquote {{ margin: 1.2rem 0; padding-left: 1rem; border-left: 4px solid #b48a5a; white-space: pre-wrap; }}
      a {{ color: #8a4b08; }}
      code {{ background: rgba(0,0,0,0.04); padding: 0.1rem 0.3rem; border-radius: 6px; }}
    </style>
  </head>
  <body>
    <main>
      <h1>{source_title}</h1>
      <p class="meta">Memory: <code>{memory_id}</code></p>
      <p class="meta">Timestamp: <code>{timestamp}</code></p>
      <p><strong>MemCell summary</strong></p>
      <blockquote>{summary}</blockquote>
      <p><strong>Source chunks</strong></p>
      {chunks_html}
      {video_block}
      {source_link_block}
    </main>
  </body>
</html>
""".strip()
