#!/usr/bin/env python3
"""RQ Worker entrypoint for book generation jobs with health endpoint."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

# Ensure src/ is on path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from rq import SimpleWorker

from app.core.config import settings
from app.core.queue import get_redis_connection

# Minimal FastAPI for health endpoint (required by Render port scan)
from fastapi import FastAPI
import uvicorn


app = FastAPI()


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "kdp-coloring-book-worker"}


def run_worker():
    """Run the RQ worker in a background thread."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    logger.info("Starting RQ worker for queue: %s", settings.rq_queue_name)
    logger.info("Redis URL: %s", settings.redis_url)

    redis_conn = get_redis_connection()
    worker = SimpleWorker([settings.rq_queue_name], connection=redis_conn)
    logger.info("Worker started, listening for jobs...")
    worker.work()


if __name__ == "__main__":
    # Start RQ worker in background thread
    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()

    # Run health endpoint on port from environment
    port = int(settings.app_port)
    uvicorn.run(app, host="0.0.0.0", port=port)