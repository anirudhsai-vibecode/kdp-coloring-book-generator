"""Pydantic models for API requests/responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"


class CreateBookRequest(BaseModel):
    theme: Optional[str] = Field(None, description="Theme key or display name")
    pages: int = Field(25, ge=1, le=50, description="Number of coloring pages")
    author: Optional[str] = Field(None, description="Author name on cover")
    seed: Optional[int] = Field(None, description="RNG seed for reproducibility")
    dry_run: bool = Field(False, description="Generate placeholder images (no API calls)")
    max_regen: int = Field(0, ge=0, description="Max regeneration attempts per page (0 = unlimited)")
    require_user_review: bool = Field(True, description="Require manual approval before packaging")
    auto_approve: bool = Field(False, description="Skip user review gate (automation)")


class BookMetadata(BaseModel):
    title: str
    author: str
    theme_key: str
    theme_display: str
    pages: int
    seed: Optional[int] = None
    dry_run: bool = False
    created_at: datetime
    interior_pdf: str
    cover_pdf: str
    images_dir: str
    failed_dump_dir: str
    spine_width_in: float
    cover_size_in: list[float]
    paper: str
    subjects: list[str] = []


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    message: str
    created_at: datetime
    updated_at: datetime
    metadata: Optional[BookMetadata] = None
    error: Optional[str] = None


class JobProgress(BaseModel):
    job_id: str
    status: JobStatus
    current_page: int = 0
    total_pages: int = 0
    current_subject: Optional[str] = None
    attempt: int = 0
    max_regen: int = 0
    message: str = ""
    updated_at: datetime


class ThemeInfo(BaseModel):
    key: str
    display_name: str
    subjects_count: int


class ThemesResponse(BaseModel):
    themes: list[ThemeInfo]