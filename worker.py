#!/usr/bin/env python3
"""RQ Worker entrypoint for book generation jobs with health endpoint."""

from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Ensure src/ is on path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from rq import SimpleWorker, Queue, Job

from app.core.config import settings
from app.core.queue import get_redis_connection, update_job_progress, get_paused_jobs, remove_paused_job
from app.models.schemas import JobStatus
from datetime import datetime

# Minimal FastAPI for health endpoint (required by Render port scan)
from fastapi import FastAPI
import uvicorn


app = FastAPI()


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "kdp-coloring-book-worker"}


def run_worker():
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


def check_paused_jobs():
    """Background task to check for paused jobs due to quota and resume them if ready."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__ + ".quota_checker")
    logger.info("Quota checker thread started")

    redis_conn = get_redis_connection()
    queue_name = settings.rq_queue_name
    queue = Queue(queue_name, connection=redis_conn)

    while True:
        try:
            time.sleep(60)  # Check every minute
            logger.info("Checking for paused jobs due to quota...")

            paused_job_ids = get_paused_jobs()
            if not paused_job_ids:
                logger.info("No paused jobs found")
                continue

            logger.info("Found %d paused job(s)", len(paused_job_ids))

            for job_id in paused_job_ids:
                job = get_job(job_id)
                if not job:
                    logger.warning("Job %s not found, removing from paused set", job_id)
                    remove_paused_job(job_id)
                    continue

                # Check if quota reset time has passed
                estimated_reset = job.meta.get("estimated_reset_time")
                if not estimated_reset:
                    logger.info("Job %s has no estimated reset time, keeping paused", job_id)
                    continue

                try:
                    reset_time = datetime.fromisoformat(estimated_reset)
                    if datetime.now() >= reset_time:
                        logger.info("Quota reset time passed for job %s, resuming...", job_id)
                        # Re-queue the job
                        queue.enqueue_job(job)
                        # Update status back to queued
                        update_job_progress(job_id, status=JobStatus.QUEUED.value, message="Resumed after quota reset")
                        # Remove from paused set
                        remove_paused_job(job_id)
                    else:
                        logger.info("Job %s still waiting for quota reset at %s", job_id, estimated_reset)
                except Exception as e:
                    logger.error("Error checking job %s: %s", job_id, e)

        except Exception as e:
            logger.error("Error in quota checker: %s", e)


def get_job(job_id: str) -> Job | None:
    """Get a job by ID."""
    try:
        return Job.fetch(job_id, connection=get_redis_connection())
    except Exception:
        return None


if __name__ == "__main__":
    # Start RQ worker in background thread
    worker_thread = threading.Thread(target=run_worker, daemon=True)
    worker_thread.start()
    logger.info("RQ worker thread started")

    # Start quota checker thread
    checker_thread = threading.Thread(target=check_paused_jobs, daemon=True)
    checker_thread.start()
    logger.info("Quota checker thread started")

    # Run health endpoint on port from environment
    port = int(settings.app_port)
    uvicorn.run(app, host="0.0.0.0", port=port)