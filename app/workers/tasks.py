"""RQ worker tasks for book generation."""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure src/ is on path for kdp_coloring imports
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rq import get_current_job

from app.core.config import get_output_path, get_failed_dump_path, settings
from app.core.queue import update_job_progress
from app.models.schemas import JobStatus

# Import the pipeline function
from kdp_coloring.pipeline import generate_book as pipeline_generate_book

logger = logging.getLogger(__name__)


def generate_book_job(params: dict[str, Any]) -> dict[str, Any]:
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

        # Generate the book using the pipeline
        # Note: pipeline doesn't yet support max_regen, require_user_review, auto_approve
        # We'll need to handle those in the pipeline or extend it
        interior_path, cover_path, metadata = pipeline_generate_book(
            theme_name=theme,
            pages=pages,
            author=author,
            seed=seed,
            dry_run=dry_run,
        )

        # Update progress: generation complete
        update_job_progress(job_id,
            status=JobStatus.RUNNING,
            current_page=pages,
            total_pages=pages,
            message="Book generation complete, packaging PDFs...",
        )

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