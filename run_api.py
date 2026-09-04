"""HTTP API entrypoint (FastAPI / Uvicorn)."""

from __future__ import annotations

import logging
import sys

import uvicorn

from config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)


def main() -> None:
    config = load_config()
    uvicorn.run(
        "api.main:create_app",
        factory=True,
        host=config.api_host,
        port=config.api_port,
        reload=config.environment == "development",
        log_level="info",
    )


if __name__ == "__main__":
    main()
