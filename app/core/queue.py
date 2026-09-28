"""Redis/RQ queue setup for async job processing."""

from __future__ import annotations

import redis
from rq import Queue, Worker
from rq.job import Job

from app.core.config import settings


def get_redis_connection() -> redis.Redis:
    """Get Redis connection from settings."""
    return redis.from_url(settings.redis_url, decode_responses=True)


def get_queue() -> Queue:
    """Get the RQ queue for book generation."""
    return Queue(settings.rq_queue_name, connection=get_redis_connection())


def enqueue_book_generation(job_id: str, **kwargs) -> Job:
    """Enqueue a book generation job."""
    queue = get_queue()
    from app.workers.tasks import generate_book_job  # local import to avoid circular
    job = queue.enqueue(
        generate_book_job,
        kwargs,
        job_id=job_id,
        timeout=settings.rq_worker_ttl,
        result_ttl=86400,  # 24 hours
    )
    return job


def get_job(job_id: str) -> Job | None:
    """Get a job by ID."""
    try:
        return Job.fetch(job_id, connection=get_redis_connection())
    except Exception:
        return None


def get_job_status(job_id: str) -> dict | None:
    """Get job status and metadata."""
    job = get_job(job_id)
    if not job:
        return None
    return {
        "job_id": job.id,
        "status": job.get_status(),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "ended_at": job.ended_at,
        "result": job.result,
        "exc_info": job.exc_info,
        "meta": job.meta,
    }


def update_job_progress(job_id: str, **progress_data) -> bool:
    """Update job progress in meta."""
    job = get_job(job_id)
    if not job:
        return False
    job.meta.update(progress_data)
    job.save_meta()
    return True