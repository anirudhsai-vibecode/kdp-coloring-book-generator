"""FastAPI routes for the KDP Coloring Book Generator API."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure src/ is on path for kdp_coloring imports
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.core.queue import enqueue_book_generation, get_job, get_job_status, update_job_progress, add_job_to_user
from app.models.user import get_user_jobs
from app.models.schemas import (
    BookMetadata,
    CreateBookRequest,
    JobProgress,
    JobResponse,
    JobStatus,
    ThemeInfo,
    ThemesResponse,
)
from app.models.user import User
from app.middleware.auth import get_current_user, security
from kdp_coloring.themes import load_themes, list_theme_keys

router = APIRouter(prefix="/api/v1", tags=["books"])


@router.get("/themes", response_model=ThemesResponse)
async def list_themes() -> ThemesResponse:
    """List all available themes."""
    themes = load_themes()
    theme_list = [
        ThemeInfo(
            key=key,
            display_name=themes[key].get("display_name", key),
            subjects_count=len(themes[key].get("subjects") or []),
        )
        for key in list_theme_keys(themes)
    ]
    return ThemesResponse(themes=theme_list)


@router.post("/books", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_book(request: CreateBookRequest, background_tasks: BackgroundTasks, user: User = Depends(get_current_user)) -> JobResponse:
    """Create a new book generation job."""
    job_id = str(uuid.uuid4())
    now = datetime.now()

    # Validate theme if provided
    if request.theme:
        themes = load_themes()
        if request.theme not in themes:
            # Try display name match
            found = False
            for key, theme in themes.items():
                if theme.get("display_name", "").lower() == request.theme.lower():
                    request.theme = key
                    found = True
                    break
            if not found:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Theme '{request.theme}' not found. Use /api/v1/themes to list available themes.",
                )

    # Prepare job parameters
    job_params = {
        "theme": request.theme,
        "pages": request.pages,
        "author": request.author,
        "seed": request.seed,
        "dry_run": request.dry_run,
        "max_regen": request.max_regen,
        "require_user_review": request.require_user_review,
        "auto_approve": request.auto_approve,
        "user_id": user.id,
    }

    # Enqueue the job
    try:
        enqueue_book_generation(job_id, **job_params)
        # Add job to user's job set
        add_job_to_user(user.id, job_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue job: {str(e)}",
        )

    return JobResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        message="Book generation job queued successfully",
        created_at=now,
        updated_at=now,
    )


@router.get("/books/{job_id}", response_model=JobResponse)

@router.post("/auth/lookup", response_model=JobResponse)
async def lookup_job(job_id: str, user: User = Depends(get_current_user)):
    """Lookup a job by ID (requires authentication).

    This endpoint allows users to find any job by its ID, but only if they are
    authenticated. The job ownership check ensures users can only see jobs they
    created.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    # Ownership check
    if job.meta.get("user_id") != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Job does not belong to current user",
        )
    job_status = job.get_status()
    now = datetime.now()
    status_map = {
        "queued": JobStatus.QUEUED,
        "started": JobStatus.RUNNING,
        "finished": JobStatus.COMPLETED,
        "failed": JobStatus.FAILED,
        "deferred": JobStatus.QUEUED,
    }
    mapped_status = status_map.get(job_status, JobStatus.QUEUED)
    if job.meta.get("status") == "awaiting_review":
        mapped_status = JobStatus.AWAITING_REVIEW
    metadata = None
    if job.result and isinstance(job.result, dict):
        meta = job.result.get("metadata")
        if meta:
            metadata = BookMetadata(**meta)
    return JobResponse(
        job_id=job.id,
        status=mapped_status,
        message=job.meta.get("message", ""),
        created_at=job.created_at or now,
        updated_at=job.ended_at or job.started_at or now,
        metadata=metadata,
        error=job.exc_info,
    )
async def get_book_job(job_id: str, user: User = Depends(get_current_user)) -> JobResponse:
    """Get job status and result."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Check job ownership
    if job.meta.get("user_id") != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Job does not belong to current user",
        )

    job_status = job.get_status()
    now = datetime.now()

    # Map RQ status to our JobStatus
    status_map = {
        "queued": JobStatus.QUEUED,
        "started": JobStatus.RUNNING,
        "finished": JobStatus.COMPLETED,
        "failed": JobStatus.FAILED,
        "deferred": JobStatus.QUEUED,
    }
    mapped_status = status_map.get(job_status, JobStatus.QUEUED)

    # Check for awaiting review status in meta
    if job.meta.get("status") == "awaiting_review":
        mapped_status = JobStatus.AWAITING_REVIEW

    metadata = None
    if job.result and isinstance(job.result, dict):
        meta = job.result.get("metadata")
        if meta:
            metadata = BookMetadata(**meta)

    return JobResponse(
        job_id=job.id,
        status=mapped_status,
        message=job.meta.get("message", ""),
        created_at=job.created_at or now,
        updated_at=job.ended_at or job.started_at or now,
        metadata=metadata,
        error=job.exc_info,
    )


@router.get("/books/{job_id}/progress", response_model=JobProgress)
async def get_book_progress(job_id: str, user: User = Depends(get_current_user)) -> JobProgress:
    """Get real-time progress of a running job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Check job ownership
    if job.meta.get("user_id") != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Job does not belong to current user",
        )

    return JobProgress(
        job_id=job.id,
        status=JobStatus(job.meta.get("status", "queued")),
        current_page=job.meta.get("current_page", 0),
        total_pages=job.meta.get("total_pages", 0),
        current_subject=job.meta.get("current_subject"),
        attempt=job.meta.get("attempt", 0),
        max_regen=job.meta.get("max_regen", 0),
        message=job.meta.get("message", ""),
        updated_at=datetime.now(),
    )


@router.get("/books", response_model=list[JobResponse])
async def list_user_jobs(user: User = Depends(get_current_user)) -> list[JobResponse]:
    """List all jobs for the current user."""
    job_ids = get_user_jobs(user.id)
    jobs = []
    for job_id in job_ids:
        job = get_job(job_id)
        if job:
            job_status = job.get_status()
            now = datetime.now()

            # Map RQ status to our JobStatus
            status_map = {
                "queued": JobStatus.QUEUED,
                "started": JobStatus.RUNNING,
                "finished": JobStatus.COMPLETED,
                "failed": JobStatus.FAILED,
                "deferred": JobStatus.QUEUED,
            }
            mapped_status = status_map.get(job_status, JobStatus.QUEUED)

            # Check for awaiting review status in meta
            if job.meta.get("status") == "awaiting_review":
                mapped_status = JobStatus.AWAITING_REVIEW

            metadata = None
            if job.result and isinstance(job.result, dict):
                meta = job.result.get("metadata")
                if meta:
                    metadata = BookMetadata(**meta)

            jobs.append(JobResponse(
                job_id=job.id,
                status=mapped_status,
                message=job.meta.get("message", ""),
                created_at=job.created_at or now,
                updated_at=job.ended_at or job.started_at or now,
                metadata=metadata,
                error=job.exc_info,
            ))
    return jobs


@router.get("/books/{job_id}/download/{file_type}")
async def download_book_file(job_id: str, file_type: str, user: User = Depends(get_current_user)) -> FileResponse:
    """Download generated PDF files (interior or cover)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Check job ownership
    if job.meta.get("user_id") != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Job does not belong to current user",
        )

    if job.get_status() != "finished":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job not completed yet",
        )

    if not job.result or not isinstance(job.result, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No result data available",
        )

    metadata = job.result.get("metadata")
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No metadata available",
        )

    if file_type == "interior":
        file_path = metadata.get("interior_pdf")
        filename = f"{job_id}_interior.pdf"
    elif file_type == "cover":
        file_path = metadata.get("cover_pdf")
        filename = f"{job_id}_cover.pdf"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="file_type must be 'interior' or 'cover'",
        )

    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{file_type.capitalize()} PDF not found",
        )

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/pdf",
    )


@router.post("/books/{job_id}/approve")
async def approve_book(job_id: str, user: User = Depends(get_current_user)) -> JSONResponse:
    """Approve a book awaiting user review (creates USER_APPROVED.json)."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    # Check job ownership
    if job.meta.get("user_id") != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Job does not belong to current user",
        )

    if not job.result or not isinstance(job.result, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No result data available",
        )

    metadata = job.result.get("metadata")
    if not metadata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No metadata available",
        )

    # Get book directory from interior_pdf path
    interior_pdf = metadata.get("interior_pdf", "")
    if not interior_pdf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No interior PDF path in metadata",
        )
    book_dir = Path(interior_pdf).parent
    if not book_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book directory not found",
        )

    # Create USER_APPROVED.json
    approved_file = book_dir / "USER_APPROVED.json"
    approved_file.write_text(
        '{"approved": true, "approved_at": "' + datetime.now().isoformat() + '"}',
        encoding="utf-8",
    )

    # Update job status
    update_job_progress(job_id, status=JobStatus.RUNNING.value, message="User approved, packaging...")

    return JSONResponse({"message": "Approved. Packaging will proceed."})


@router.delete("/books/{job_id}")
async def cancel_job(job_id: str, user: User = Depends(get_current_user)) -> JSONResponse:
    """Cancel a queued or running job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    job_status = job.get_status()
    if job_status in ("finished", "failed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel job with status: {job_status}",
        )

    job.cancel()
    return JSONResponse({"message": f"Job {job_id} cancelled"})