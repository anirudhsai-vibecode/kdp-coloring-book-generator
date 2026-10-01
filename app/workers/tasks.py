"""RQ worker tasks for book generation."""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure src/ is on path for kdp_coloring imports
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rq import get_current_job

from app.core.config import get_output_path, get_failed_dump_path, settings
from app.core.queue import get_redis_connection, update_job_progress, add_paused_job, remove_paused_job, get_paused_jobs
from app.models.schemas import JobStatus
from app.models.user import add_job_to_user

# Import the pipeline function
from kdp_coloring.pipeline import generate_book as pipeline_generate_book
from src.kdp_coloring.image_gen import CloudflarePausedError, _is_cf_quota_error
from app.core.queue import store_pdf_bytes

logger = logging.getLogger(__name__)


def generate_book_job(params: dict[str, Any], timeout: int = 3600) -> dict[str, Any]:
    """
    RQ job to generate a coloring book.

    Args:
        params: Dictionary with keys:
            - theme: str | None
            - pages: int
            - author: str | None
            - seed: int | None
            - dry_run: bool
            - max_regen: int
            - require_user_review: bool
            - auto_approve: bool

    Returns:
        Dictionary with job result metadata
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    logger.info("Starting book generation job %s with params: %s", job_id, params)

    try:
        # Update progress: starting
        update_job_progress(job_id,
            status=JobStatus.RUNNING,
            current_page=0,
            total_pages=params.get("pages", 0),
            message="Initializing book generation...",
        )

        # Extract parameters
        theme = params.get("theme")
        pages = params.get("pages", 25)
        author = params.get("author")
        seed = params.get("seed")
        dry_run = params.get("dry_run", False)
        max_regen = params.get("max_regen", 0)
        require_user_review = params.get("require_user_review", True)
        auto_approve = params.get("auto_approve", False)
        user_id = params.get("user_id")

        # Generate the book using the pipeline
        # Note: pipeline doesn't yet support max_regen, require_user_review, auto_approve
        # We'll need to handle those in the pipeline or extend it
        try:
            interior_path, cover_path, metadata = pipeline_generate_book(
                theme_name=theme,
                pages=pages,
                author=author,
                seed=seed,
                dry_run=dry_run,
            )
        except Exception as pipeline_error:
            # Check if this is a Cloudflare quota error
            from src.kdp_coloring.image_gen import CloudflarePausedError, _is_cf_quota_error
            if isinstance(pipeline_error, CloudflarePausedError) or _is_cf_quota_error(pipeline_error):
                # Update job to paused with quota status
                update_job_progress(job_id,
                    status=JobStatus.PAUSED_WITH_QUOTA,
                    message="Generation paused: Cloudflare daily quota exhausted",
                )
                # Add to paused jobs set
                add_paused_job(job_id)
                # Add quota metadata
                if metadata:
                    metadata["quota_exceeded_at"] = datetime.now().isoformat()
                    # Estimate reset time (Cloudflare resets daily at ~00:00 UTC)
                    # For simplicity, we'll set it to 24 hours from now
                    estimated_reset = datetime.now() + timedelta(hours=24)
                    metadata["estimated_reset_time"] = estimated_reset.isoformat()
                    # Update job with quota metadata
                    update_job_progress(job_id,
                        status=JobStatus.PAUSED_WITH_QUOTA,
                        message="Generation paused: Cloudflare daily quota exhausted",
                        **{k: v for k, v in metadata.items() if k in ["quota_exceeded_at", "estimated_reset_time"]}
                    )
                logger.info("Book generation job %s paused due to Cloudflare quota", job_id)
                # Return paused result instead of raising
                result = {
                    "job_id": job_id,
                    "status": JobStatus.PAUSED_WITH_QUOTA.value,
                    "metadata": metadata,
                    "paused_at": datetime.now().isoformat(),
                    "message": "Generation paused: Cloudflare daily quota exhausted",
                }
                return result
            else:
                # Re-raise if not a quota error
                raise pipeline_error

        # Update progress: generation complete
        update_job_progress(job_id,
            status=JobStatus.RUNNING,
            current_page=pages,
            total_pages=pages,
            message="Book generation complete, packaging PDFs...",
        )

        # Read generated PDF bytes for Redis storage (API and worker are separate services)
        with open(interior_path, "rb") as f:
            interior_bytes = f.read()
        with open(cover_path, "rb") as f:
            cover_bytes = f.read()
        # Store PDFs in Redis so API can serve them (different filesystem)
        logger.info(f"Storing PDFsoring PDFs in Redis for job {job_id}: interior={len(interior_bytes)} bytes, cover={len(cover_bytes)} bytes")
        store_pdf_bytes(job_id, "interior", interior_bytes)
        store_pdf_bytes(job_id, "cover", cover_bytes)

        # Add user_id to metadata
        metadata["user_id"] = user_id

        # Build result
        result = {
            "job_id": job_id,
            "status": JobStatus.COMPLETED.value,
            "metadata": metadata,
            "completed_at": datetime.now().isoformat(),
        }

        logger.info("Book generation job %s completed successfully", job_id)
        return result

    except Exception as e:
        logger.exception("Book generation job %s failed: %s", job_id, e)
        update_job_progress(job_id,
            status=JobStatus.FAILED,
            message=f"Generation failed: {str(e)}",
        )
        raise


def generate_book_job_with_progress(params: dict[str, Any]) -> dict[str, Any]:
    """
    Enhanced book generation job with real-time progress updates.
    This version would integrate with the full main.py logic including QA gates.
    """
    job = get_current_job()
    job_id = job.id if job else "unknown"

    logger.info("Starting enhanced book generation job %s", job_id)

    # For now, delegate to the simpler version
    # In the future, this would call the full main.py generation logic
    # with progress callbacks for each page
    return generate_book_job(params)