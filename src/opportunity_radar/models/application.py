"""Application tracking model (spec §6.3)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class ApplicationInfo(BaseModel):
    job_id: int
    status: str = "none"
    saved_at: datetime | None = None
    applied_at: datetime | None = None
    resume_variant: str | None = None
    referral_status: str | None = None
    referrer_name: str | None = None
    recruiter_name: str | None = None
    deadline: date | None = None
    oa_date: date | None = None
    interview_stage: str | None = None
    follow_up_date: date | None = None
    notes: str | None = None
