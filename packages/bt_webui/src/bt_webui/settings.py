from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WebUISettings:
    memories_service_url: str


def load_webui_settings() -> WebUISettings:
    memories = (os.getenv("MEMORIES_SERVICE_URL") or "").strip()
    if not memories:
        memories = "http://localhost:8080"
    return WebUISettings(memories_service_url=memories.rstrip("/"))
