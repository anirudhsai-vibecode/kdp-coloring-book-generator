#!/usr/bin/env python3
"""RQ Worker entrypoint for book generation jobs."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure src/ is on path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from rq import SimpleWorker

from app.core.config import settings
from app.core.queue import get_redis_connection


def main():
    """Run the RQ worker."""
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
    main()