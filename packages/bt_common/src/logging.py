"""Structured JSON logging with request-scoped correlation IDs."""

from __future__ import annotations

import contextvars
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


class JsonFormatter(logging.Formatter):
    """Emit log records as compact JSON for ingestion pipelines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def set_correlation_id(correlation_id: str | None = None) -> str:
    cid = correlation_id or str(uuid4())
    _correlation_id_var.set(cid)
    return cid


def get_correlation_id() -> str:
    return _correlation_id_var.get() or ""


def get_request_logger(name: str) -> logging.Logger:
    """Get a logger configured for JSON output."""

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
    return logger
