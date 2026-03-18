FROM python:3.12-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/tmp/uv-cache

RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir uv

COPY . /app

# Install only what the Memories API needs.
RUN uv sync --frozen --package memory_service


FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    MEMORIES_HOST=0.0.0.0 \
    MEMORIES_PORT=8080

COPY --from=builder /app /app

RUN useradd --create-home --uid 10001 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

CMD ["uvicorn", "memory_service.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
