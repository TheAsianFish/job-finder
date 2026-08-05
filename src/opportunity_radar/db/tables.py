"""SQLAlchemy table definitions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {
        dict[str, Any]: JSON,
        list[str]: JSON,
        dict[str, float]: JSON,
    }


class CompanyRow(Base):
    __tablename__ = "companies"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tier: Mapped[str] = mapped_column(String(20), default="broad")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    adapter: Mapped[str] = mapped_column(String(50), default="auto")
    adapter_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    career_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    scan_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("identity_hash", name="uq_jobs_identity_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identity_hash: Mapped[str] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))

    source_name: Mapped[str] = mapped_column(String(100))
    source_adapter: Mapped[str] = mapped_column(String(50))
    source_job_id: Mapped[str] = mapped_column(String(200))
    company_id: Mapped[str] = mapped_column(String(100), ForeignKey("companies.id"), index=True)
    company_name: Mapped[str] = mapped_column(String(200))

    title: Mapped[str] = mapped_column(String(500))
    normalized_title: Mapped[str] = mapped_column(String(500))
    description_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_text: Mapped[str] = mapped_column(Text, default="")
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    team: Mapped[str | None] = mapped_column(String(200), nullable=True)

    primary_location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    all_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    remote_type: Mapped[str] = mapped_column(String(20), default="unknown")
    country_codes: Mapped[list[str]] = mapped_column(JSON, default=list)

    employment_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role_family: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    seniority: Mapped[str | None] = mapped_column(String(50), nullable=True)

    season: Mapped[str] = mapped_column(String(20), default="unspecified", index=True)
    season_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_date_min: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date_max: Mapped[date | None] = mapped_column(Date, nullable=True)
    duration_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    full_time_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    degree_levels: Mapped[list[str]] = mapped_column(JSON, default=list)
    graduation_min: Mapped[date | None] = mapped_column(Date, nullable=True)
    graduation_max: Mapped[date | None] = mapped_column(Date, nullable=True)
    requires_return_to_school: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    work_authorization_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    citizenship_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    clearance_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    compensation_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    compensation_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    compensation_period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    compensation_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    apply_url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    consecutive_misses: Mapped[int] = mapped_column(Integer, default=0)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    digest_pending: Mapped[bool] = mapped_column(Boolean, default=False)

    match_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_components: Mapped[dict[str, float]] = mapped_column(JSON, default=dict)
    match_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    eligibility_level: Mapped[str] = mapped_column(String(30), default="uncertain")
    eligibility_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    season_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    eligibility_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_early_career: Mapped[bool] = mapped_column(Boolean, default=False)

    aliases: Mapped[list[JobAliasRow]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    changes: Mapped[list[JobChangeRow]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    application: Mapped[ApplicationRow | None] = relationship(
        back_populates="job", cascade="all, delete-orphan", uselist=False
    )


class JobAliasRow(Base):
    """Alternate identities for one logical job (spec §6.2)."""

    __tablename__ = "job_aliases"
    __table_args__ = (UniqueConstraint("alias_kind", "alias_hash", name="uq_alias_kind_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), index=True)
    alias_kind: Mapped[str] = mapped_column(String(20))  # identity | url | fuzzy
    alias_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_adapter: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_job_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    job: Mapped[JobRow] = relationship(back_populates="aliases")


class JobChangeRow(Base):
    __tablename__ = "job_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    field: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    meaningful: Mapped[bool] = mapped_column(Boolean, default=False)

    job: Mapped[JobRow] = relationship(back_populates="changes")


class ApplicationRow(Base):
    __tablename__ = "applications"

    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="none", index=True)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resume_variant: Mapped[str | None] = mapped_column(String(50), nullable=True)
    referral_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    referrer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    recruiter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    oa_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    interview_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[JobRow] = relationship(back_populates="application")


class ScanRunRow(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(100), index=True)
    adapter: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    jobs_found: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)


class SourceStateRow(Base):
    __tablename__ = "source_state"

    company_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_job_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    etag: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MetaRow(Base):
    """Small key-value store for app state (baseline flag, digest timestamps)."""

    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
