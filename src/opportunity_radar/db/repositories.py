"""Repository helpers wrapping common queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from opportunity_radar.db.tables import (
    ApplicationRow,
    CompanyRow,
    JobAliasRow,
    JobChangeRow,
    JobRow,
    MetaRow,
    ScanRunRow,
    SourceStateRow,
)
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import JobRecord
from opportunity_radar.models.scan import ScanOutcome
from opportunity_radar.utilities.dates import utcnow

# ---------------------------------------------------------------------------
# Companies


def sync_companies(session: Session, companies: list[CompanySource]) -> int:
    """Upsert registry entries from config into the DB. Returns count synced."""
    now = utcnow()
    for company in companies:
        row = session.get(CompanyRow, company.id)
        if row is None:
            row = CompanyRow(id=company.id, created_at=now, updated_at=now, name=company.name)
            session.add(row)
        row.name = company.name
        row.domain = company.domain
        row.tier = company.tier
        row.enabled = company.enabled
        row.adapter = company.adapter
        row.adapter_config = company.adapter_config
        row.career_urls = company.career_urls
        row.tags = company.tags
        row.scan_interval_minutes = company.scan_interval_minutes
        row.notes = company.notes
        row.updated_at = now
    return len(companies)


def get_company(session: Session, company_id: str) -> CompanyRow | None:
    return session.get(CompanyRow, company_id)


def list_companies(session: Session, enabled_only: bool = False) -> list[CompanyRow]:
    stmt = select(CompanyRow).order_by(CompanyRow.tier, CompanyRow.id)
    if enabled_only:
        stmt = stmt.where(CompanyRow.enabled.is_(True))
    return list(session.scalars(stmt))


def set_company_enabled(session: Session, company_id: str, enabled: bool) -> bool:
    row = session.get(CompanyRow, company_id)
    if row is None:
        return False
    row.enabled = enabled
    row.updated_at = utcnow()
    return True


# ---------------------------------------------------------------------------
# Jobs


def find_job_by_alias(session: Session, alias_hashes: dict[str, str]) -> JobRow | None:
    """Look up a job by any identity (kind -> hash), strongest first."""
    for kind in ("identity", "url", "fuzzy"):
        alias_hash = alias_hashes.get(kind)
        if not alias_hash:
            continue
        stmt = (
            select(JobAliasRow)
            .where(JobAliasRow.alias_kind == kind, JobAliasRow.alias_hash == alias_hash)
            .limit(1)
        )
        alias = session.scalars(stmt).first()
        if alias is not None:
            return session.get(JobRow, alias.job_id)
    return None


def _record_to_row_fields(record: JobRecord) -> dict[str, Any]:
    return {
        "identity_hash": record.identity_hash,
        "content_hash": record.content_hash,
        "source_name": record.source_name,
        "source_adapter": record.source_adapter,
        "source_job_id": record.source_job_id,
        "company_id": record.company_id,
        "company_name": record.company_name,
        "title": record.title,
        "normalized_title": record.normalized_title,
        "description_html": record.description_html,
        "description_text": record.description_text,
        "department": record.department,
        "team": record.team,
        "primary_location": record.primary_location,
        "all_locations": record.all_locations,
        "remote_type": record.remote_type,
        "country_codes": record.country_codes,
        "employment_type": record.employment_type,
        "role_family": record.role_family,
        "seniority": record.seniority,
        "season": record.season,
        "season_year": record.season_year,
        "start_date_min": record.start_date_min,
        "start_date_max": record.start_date_max,
        "duration_weeks": record.duration_weeks,
        "full_time_required": record.full_time_required,
        "degree_levels": record.degree_levels,
        "graduation_min": record.graduation_min,
        "graduation_max": record.graduation_max,
        "requires_return_to_school": record.requires_return_to_school,
        "work_authorization_text": record.work_authorization_text,
        "citizenship_required": record.citizenship_required,
        "clearance_required": record.clearance_required,
        "compensation_min": float(record.compensation_min)
        if record.compensation_min is not None
        else None,
        "compensation_max": float(record.compensation_max)
        if record.compensation_max is not None
        else None,
        "compensation_period": record.compensation_period,
        "compensation_currency": record.compensation_currency,
        "posted_at": record.posted_at,
        "updated_at": record.updated_at,
        "apply_url": record.apply_url,
        "canonical_url": record.canonical_url,
        "source_url": record.source_url,
        "status": record.status,
        "match_score": record.match_score,
        "score_components": record.score_components,
        "match_reasons": record.match_reasons,
        "risk_flags": record.risk_flags,
        "eligibility_level": record.eligibility_level,
        "eligibility_text": record.eligibility_text,
        "season_confidence": record.season_confidence,
        "eligibility_confidence": record.eligibility_confidence,
        "is_early_career": record.is_early_career,
    }


def insert_job(
    session: Session,
    record: JobRecord,
    alias_hashes: dict[str, str],
    is_baseline: bool = False,
) -> JobRow:
    row = JobRow(
        **_record_to_row_fields(record),
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        is_baseline=is_baseline,
    )
    session.add(row)
    session.flush()
    now = utcnow()
    for kind, alias_hash in alias_hashes.items():
        session.add(
            JobAliasRow(
                job_id=row.id,
                alias_kind=kind,
                alias_hash=alias_hash,
                source_adapter=record.source_adapter,
                source_job_id=record.source_job_id,
                url=record.apply_url,
                location=record.primary_location,
                first_seen_at=now,
            )
        )
    return row


def add_missing_aliases(
    session: Session, job: JobRow, alias_hashes: dict[str, str], record: JobRecord
) -> None:
    """Attach this record's identities to the job.

    (kind, hash) is globally unique. A hash already owned by a DIFFERENT job
    is skipped: e.g. a title change can make one job's fuzzy key collide with
    another job's — the two jobs stay distinct and the alias keeps pointing
    at its original owner (spec §6.2: never merge on title similarity alone).
    """
    owned = {
        (alias.alias_kind, alias.alias_hash)
        for alias in session.scalars(
            select(JobAliasRow).where(JobAliasRow.alias_hash.in_(list(alias_hashes.values())))
        )
    }
    now = utcnow()
    for kind, alias_hash in alias_hashes.items():
        if (kind, alias_hash) not in owned:
            session.add(
                JobAliasRow(
                    job_id=job.id,
                    alias_kind=kind,
                    alias_hash=alias_hash,
                    source_adapter=record.source_adapter,
                    source_job_id=record.source_job_id,
                    url=record.apply_url,
                    location=record.primary_location,
                    first_seen_at=now,
                )
            )


def apply_record_to_row(row: JobRow, record: JobRecord) -> None:
    for field, value in _record_to_row_fields(record).items():
        setattr(row, field, value)
    row.last_seen_at = record.last_seen_at


def record_change(
    session: Session,
    job_id: int,
    field: str,
    old_value: str | None,
    new_value: str | None,
    meaningful: bool,
) -> None:
    session.add(
        JobChangeRow(
            job_id=job_id,
            changed_at=utcnow(),
            field=field,
            old_value=old_value,
            new_value=new_value,
            meaningful=meaningful,
        )
    )


def get_job(session: Session, job_id: int) -> JobRow | None:
    return session.get(JobRow, job_id)


def active_jobs_for_company(session: Session, company_id: str) -> list[JobRow]:
    stmt = select(JobRow).where(JobRow.company_id == company_id, JobRow.status == "active")
    return list(session.scalars(stmt))


def list_jobs(
    session: Session,
    *,
    status: str | None = None,
    season: str | None = None,
    season_year: int | None = None,
    min_score: float | None = None,
    company_id: str | None = None,
    role_family: str | None = None,
    remote_type: str | None = None,
    application_status: str | None = None,
    eligibility_level: str | None = None,
    search: str | None = None,
    order_by: str = "score",
    limit: int = 200,
    offset: int = 0,
) -> list[JobRow]:
    stmt = select(JobRow)
    if status:
        stmt = stmt.where(JobRow.status == status)
    if season:
        stmt = stmt.where(JobRow.season == season)
    if season_year:
        stmt = stmt.where(JobRow.season_year == season_year)
    if min_score is not None:
        stmt = stmt.where(JobRow.match_score >= min_score)
    if company_id:
        stmt = stmt.where(JobRow.company_id == company_id)
    if role_family:
        stmt = stmt.where(JobRow.role_family == role_family)
    if remote_type:
        stmt = stmt.where(JobRow.remote_type == remote_type)
    if eligibility_level:
        stmt = stmt.where(JobRow.eligibility_level == eligibility_level)
    if application_status:
        stmt = stmt.join(ApplicationRow, ApplicationRow.job_id == JobRow.id).where(
            ApplicationRow.status == application_status
        )
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            func.lower(JobRow.title).like(pattern)
            | func.lower(JobRow.company_name).like(pattern)
            | func.lower(JobRow.description_text).like(pattern)
        )
    if order_by == "score":
        stmt = stmt.order_by(JobRow.match_score.desc(), JobRow.first_seen_at.desc())
    elif order_by == "first_seen":
        stmt = stmt.order_by(JobRow.first_seen_at.desc())
    elif order_by == "posted":
        stmt = stmt.order_by(JobRow.posted_at.desc().nulls_last())
    return list(session.scalars(stmt.limit(limit).offset(offset)))


def count_jobs(session: Session, status: str | None = None) -> int:
    stmt = select(func.count(JobRow.id))
    if status:
        stmt = stmt.where(JobRow.status == status)
    return session.scalar(stmt) or 0


# ---------------------------------------------------------------------------
# Applications


def get_or_create_application(session: Session, job_id: int) -> ApplicationRow:
    row = session.get(ApplicationRow, job_id)
    if row is None:
        row = ApplicationRow(job_id=job_id, status="none", updated_at=utcnow())
        session.add(row)
        session.flush()
    return row


def set_application_status(
    session: Session, job_id: int, status: str, **fields: Any
) -> ApplicationRow:
    row = get_or_create_application(session, job_id)
    row.status = status
    now = utcnow()
    if status == "saved" and row.saved_at is None:
        row.saved_at = now
    if status == "applied" and row.applied_at is None:
        row.applied_at = now
    for key, value in fields.items():
        if hasattr(row, key) and value is not None:
            setattr(row, key, value)
    row.updated_at = now
    return row


# ---------------------------------------------------------------------------
# Scan runs and source state


def record_scan_run(session: Session, outcome: ScanOutcome) -> ScanRunRow:
    row = ScanRunRow(
        company_id=outcome.company_id,
        adapter=outcome.adapter,
        started_at=outcome.started_at or utcnow(),
        finished_at=outcome.finished_at or utcnow(),
        success=outcome.success,
        jobs_found=outcome.jobs_found,
        new_count=outcome.new_count,
        changed_count=outcome.changed_count,
        closed_count=outcome.closed_count,
        duration_ms=outcome.duration_ms,
        http_status=outcome.http_status,
        error=outcome.error,
        error_category=outcome.error_category,
    )
    session.add(row)
    return row


def get_source_state(session: Session, company_id: str) -> SourceStateRow:
    row = session.get(SourceStateRow, company_id)
    if row is None:
        row = SourceStateRow(company_id=company_id, consecutive_failures=0)
        session.add(row)
        session.flush()
    return row


def update_source_state_success(session: Session, company_id: str, job_count: int) -> None:
    row = get_source_state(session, company_id)
    row.last_success_at = utcnow()
    row.last_attempt_at = row.last_success_at
    row.consecutive_failures = 0
    row.last_error = None
    row.last_job_count = job_count


def update_source_state_failure(session: Session, company_id: str, error: str) -> int:
    row = get_source_state(session, company_id)
    row.last_attempt_at = utcnow()
    row.consecutive_failures += 1
    row.last_error = error[:2000]
    return row.consecutive_failures


def list_source_states(session: Session) -> list[SourceStateRow]:
    return list(session.scalars(select(SourceStateRow)))


def recent_scan_runs(session: Session, limit: int = 50) -> list[ScanRunRow]:
    stmt = select(ScanRunRow).order_by(ScanRunRow.started_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def last_successful_scan(session: Session, company_id: str) -> datetime | None:
    row = session.get(SourceStateRow, company_id)
    return row.last_success_at if row else None


# ---------------------------------------------------------------------------
# Meta key-value store


def meta_get(session: Session, key: str) -> str | None:
    row = session.get(MetaRow, key)
    return row.value if row else None


def meta_set(session: Session, key: str, value: str | None) -> None:
    row = session.get(MetaRow, key)
    if row is None:
        session.add(MetaRow(key=key, value=value))
    else:
        row.value = value
