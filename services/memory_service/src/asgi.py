from __future__ import annotations

from memory_service.api.app import create_app
from memory_service.api.config import load_memories_api_config

_config = load_memories_api_config()
app = create_app(_config)
