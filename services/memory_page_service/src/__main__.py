from __future__ import annotations

import argparse

import uvicorn

from .app import create_app
from .config import load_runtime_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Bibliotalk memory page service")
    parser.add_argument("--db", dest="db_path")
    parser.add_argument("--host", dest="host")
    parser.add_argument("--port", dest="port", type=int)
    parser.add_argument("--log-level", dest="log_level")
    args = parser.parse_args()
    config = load_runtime_config(
        db_path=args.db_path,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )
    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
