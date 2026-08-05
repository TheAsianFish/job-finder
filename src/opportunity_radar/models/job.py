"""RawJob (adapter output) and JobRecord (normalized schema, spec §6.1)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

Season = Literal["winter", "spring", "summer", "fall", "off_cycle", "year_round", "unspecified"]
RemoteType = Literal["remote", "hybrid", "onsite", "unknown"]
JobStatus = Literal["active", "closed", "unknown"]


class RawJob(BaseModel):
    """Minimally-processed listing as returned by a source adapter."""

    source_adapter: str
    source_job_id: str
    title: str
    url: str
    apply_url: str | None = None
    locations: list[str] = Field(default_factory=list)
    department: str | None = None
    team: str | None = None
    employment_type: str | None = None
    description_html: str | None = None
    description_text: str | None = None
    posted_at: datetime | None = None
    updated_at: datetime | None = None
    valid_through: datetime | None = None
    remote_hint: RemoteType | None = None
    compensation_min: Decimal | None = None
    compensation_max: Decimal | None = None
    compensation_period: str | None = None
    compensation_currency: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class JobRecord(BaseModel):
    """The single normalized job schema every adapter output is mapped into."""

    source_name: str
    source_adapter: str
    source_job_id: str
    company_id: str
    company_name: str

    title: str
    normalized_title: str
    description_html: str | None = None
    description_text: str = ""
    department: str | None = None
    team: str | None = None

    primary_location: str | None = None
    all_locations: list[str] = Field(default_factory=list)
    remote_type: RemoteType = "unknown"
    country_codes: list[str] = Field(default_factory=list)

    employment_type: str | None = None
    role_family: str | None = None
    seniority: str | None = None

    season: Season = "unspecified"
    season_year: int | None = None
    start_date_min: date | None = None
    start_date_max: date | None = None
    duration_weeks: int | None = None
    full_time_required: bool | None = None

    degree_levels: list[str] = Field(default_factory=list)
    graduation_min: date | None = None
    graduation_max: date | None = None
    requires_return_to_school: bool | None = None
    work_authorization_text: str | None = None
    citizenship_required: bool | None = None
    clearance_required: bool | None = None

    compensation_min: Decimal | None = None
    compensation_max: Decimal | None = None
    compensation_period: str | None = None
    compensation_currency: str | None = None

    posted_at: datetime | None = None
    updated_at: datetime | None = None
    first_seen_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None = None

    apply_url: str
    canonical_url: str
    source_url: str

    content_hash: str
    identity_hash: str
    status: JobStatus = "active"

    match_score: float = 0.0
    score_components: dict[str, float] = Field(default_factory=dict)
    match_reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    eligibility_level: str = "uncertain"
    eligibility_text: str | None = None
    season_confidence: float = 0.0
    eligibility_confidence: float = 0.0
    is_early_career: bool = False
