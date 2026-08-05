"""Scan and validation result models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    ok: bool
    adapter: str
    detail: str = ""
    job_count: int | None = None


class ScanOutcome(BaseModel):
    """Result of scanning one company with one adapter."""

    company_id: str
    adapter: str
    success: bool
    jobs_found: int = 0
    new_count: int = 0
    changed_count: int = 0
    closed_count: int = 0
    duration_ms: int = 0
    http_status: int | None = None
    error: str | None = None
    error_category: str | None = None
    retryable: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    new_job_ids: list[int] = Field(default_factory=list)
    changed_job_ids: list[int] = Field(default_factory=list)
