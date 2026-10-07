"""Scan orchestrator: fetch -> normalize -> dedupe -> persist -> classify alerts.

Baseline safety (spec §14.1): the first ever scan imports without alerting.
If `scan` is invoked before any baseline and the database is empty, the scan
is automatically treated as a baseline run and a warning is logged.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from dataclasses import dataclass, field

import httpx
import structlog

from opportunity_radar.adapters.base import AdapterContext, AdapterError
from opportunity_radar.adapters.registry import fetch_with_fallback
from opportunity_radar.config import AppSettings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import session_scope
from opportunity_radar.matching.scorer import decide_alert_level, is_us_accessible
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import JobRecord, RawJob
from opportunity_radar.models.scan import ScanOutcome
from opportunity_radar.pipeline import change_detector, closure_detector, deduper, normalizer
from opportunity_radar.pipeline.company_resolver import CompanyResolver
from opportunity_radar.utilities.dates import ensure_utc, utcnow
from opportunity_radar.utilities.rate_limit import RateLimiter, build_user_agent

logger = structlog.get_logger(__name__)

BASELINE_DONE_KEY = "baseline_done"


@dataclass
class ScanSummary:
    outcomes: list[ScanOutcome] = field(default_factory=list)
    immediate_job_ids: list[int] = field(default_factory=list)
    digest_job_ids: list[int] = field(default_factory=list)
    changed_job_ids: list[int] = field(default_factory=list)
    baseline: bool = False
    # Sources scanned successfully for the first time in this run: their
    # whole board is "new", so they are imported without per-job alerts and
    # summarised once instead (spec §14.1 applied per source, not just per DB).
    baselined_company_ids: list[str] = field(default_factory=list)
    baselined_job_ids: list[int] = field(default_factory=list)

    @property
    def total_new(self) -> int:
        return sum(o.new_count for o in self.outcomes)

    @property
    def total_changed(self) -> int:
        return sum(o.changed_count for o in self.outcomes)

    @property
    def total_closed(self) -> int:
        return sum(o.closed_count for o in self.outcomes)

    @property
    def total_found(self) -> int:
        return sum(o.jobs_found for o in self.outcomes if o.success)

    @property
    def failures(self) -> list[ScanOutcome]:
        return [o for o in self.outcomes if not o.success]


async def scan_companies(
    companies: list[CompanySource],
    settings: AppSettings,
    *,
    baseline: bool = False,
    db_url: str | None = None,
) -> ScanSummary:
    summary = ScanSummary(baseline=baseline)

    # Baseline auto-guard: never flood alerts on a fresh database.
    with session_scope(db_url) as session:
        repo.sync_companies(session, companies)
        baseline_done = repo.meta_get(session, BASELINE_DONE_KEY) == "1"
        job_count = repo.count_jobs(session)
    if not baseline and not baseline_done and job_count == 0:
        logger.warning(
            "auto_baseline",
            reason="first run with an empty database — importing without alerts",
        )
        baseline = True
        summary.baseline = True

    scheduler = settings.scheduler
    limiter = RateLimiter(
        max_global=scheduler.max_concurrency_global,
        min_domain_interval=1.0,
    )
    user_agent = build_user_agent(settings.contact)
    db_lock = asyncio.Lock()
    task_semaphore = asyncio.Semaphore(scheduler.max_concurrency_global)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        ctx = AdapterContext(
            client=client,
            limiter=limiter,
            user_agent=user_agent,
            timeout=float(scheduler.request_timeout_seconds),
            retries=scheduler.retries,
            backoff_seconds=tuple(scheduler.backoff_seconds),
        )

        async def scan_one(company: CompanySource) -> None:
            async with task_semaphore:
                outcome = await _scan_company(
                    company, ctx, settings, baseline, db_lock, db_url, summary
                )
                summary.outcomes.append(outcome)

        await asyncio.gather(*(scan_one(c) for c in companies if c.enabled))

    if baseline:
        with session_scope(db_url) as session:
            repo.meta_set(session, BASELINE_DONE_KEY, "1")
    return summary


async def _scan_company(
    company: CompanySource,
    ctx: AdapterContext,
    settings: AppSettings,
    baseline: bool,
    db_lock: asyncio.Lock,
    db_url: str | None,
    summary: ScanSummary,
) -> ScanOutcome:
    started = utcnow()
    t0 = time.monotonic()
    adapter_name = company.adapter
    log = logger.bind(company_id=company.id, adapter=adapter_name)
    async with db_lock:
        with session_scope(db_url) as session:
            known_ids = repo.list_company_source_job_ids(session, company.id)
    company_ctx = dataclasses.replace(ctx, known_job_ids=frozenset(known_ids))
    try:
        adapter, raw_jobs = await fetch_with_fallback(company, company_ctx)
        adapter_name = adapter.name
    except AdapterError as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        log.error(
            "scan_failed",
            error=str(exc),
            category=exc.category,
            retryable=exc.retryable,
            duration_ms=duration_ms,
        )
        async with db_lock:
            with session_scope(db_url) as session:
                failures = repo.update_source_state_failure(session, company.id, str(exc))
                outcome = ScanOutcome(
                    company_id=company.id,
                    adapter=adapter_name,
                    success=False,
                    duration_ms=duration_ms,
                    http_status=exc.http_status,
                    error=str(exc),
                    error_category=exc.category,
                    retryable=exc.retryable,
                    started_at=started,
                    finished_at=utcnow(),
                )
                repo.record_scan_run(session, outcome)
        outcome.error = f"{exc} (consecutive failures: {failures})"
        return outcome

    async with db_lock:
        try:
            outcome = _persist_company_jobs(
                company,
                adapter_name,
                raw_jobs,
                settings,
                baseline,
                db_url,
                summary,
                secondary=adapter.secondary,
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            log.error("persist_failed", error=str(exc), duration_ms=duration_ms)
            with session_scope(db_url) as session:
                repo.update_source_state_failure(session, company.id, f"persist: {exc}")
                outcome = ScanOutcome(
                    company_id=company.id,
                    adapter=adapter_name,
                    success=False,
                    jobs_found=len(raw_jobs),
                    duration_ms=duration_ms,
                    error=f"persistence error: {exc}",
                    error_category="persist",
                    started_at=started,
                    finished_at=utcnow(),
                )
                repo.record_scan_run(session, outcome)
            return outcome
    outcome.started_at = started
    outcome.finished_at = utcnow()
    outcome.duration_ms = int((time.monotonic() - t0) * 1000)
    log.info(
        "scan_complete",
        jobs_found=outcome.jobs_found,
        new=outcome.new_count,
        changed=outcome.changed_count,
        closed=outcome.closed_count,
        duration_ms=outcome.duration_ms,
    )
    return outcome


def _persist_company_jobs(
    company: CompanySource,
    adapter_name: str,
    raw_jobs: list[RawJob],
    settings: AppSettings,
    baseline: bool,
    db_url: str | None,
    summary: ScanSummary,
    *,
    secondary: bool = False,
) -> ScanOutcome:
    """Persist one source's jobs.

    A primary source's jobs all belong to ``company``. A secondary source
    (Simplify) lists many employers: each job is resolved to its company,
    employers the registry scans directly are skipped, and every stored job
    carries ``source_name = company.id`` (the source) so closure and
    baseline accounting stay per source.
    """
    outcome = ScanOutcome(
        company_id=company.id,
        adapter=adapter_name,
        success=True,
        jobs_found=len(raw_jobs),
    )
    now = utcnow()
    alerts = settings.scoring.alerts

    resolver = (
        CompanyResolver(settings.companies, default_tier=company.tier, source_id=company.id)
        if secondary
        else None
    )
    ensured_company_ids: set[str] = set()
    skipped_direct = 0

    with session_scope(db_url) as session:
        state = repo.get_source_state(session, company.id)
        previous_count = state.last_job_count
        # A source with no stored jobs is baselined on its own: adding 40
        # companies to a live registry must not fire 400 alerts, and neither
        # must re-pointing a seed that "succeeded" with 0 jobs for months.
        stored = (
            repo.count_source_jobs(session, company.id)
            if secondary
            else repo.count_company_jobs(session, company.id)
        )
        source_baseline = baseline or stored == 0
        if source_baseline and not baseline and raw_jobs:
            summary.baselined_company_ids.append(company.id)
            logger.info("source_baseline", company_id=company.id, jobs=len(raw_jobs))
        seen_hashes: set[str] = set()

        for raw in raw_jobs:
            job_company = company
            if resolver is not None:
                job_company = resolver.resolve(
                    str(raw.raw.get("company_name") or ""), raw.apply_url or raw.url
                )
                if not resolver.should_ingest(job_company):
                    skipped_direct += 1
                    continue
                if job_company.id not in ensured_company_ids:
                    if repo.get_company(session, job_company.id) is None:
                        repo.sync_companies(session, [job_company])
                    ensured_company_ids.add(job_company.id)
            record = _normalize(raw, job_company, company, settings, now=now)
            seen_hashes.add(record.identity_hash)
            existing = deduper.find_existing(session, record)

            if existing is None:
                job_row = repo.insert_job(
                    session,
                    record,
                    normalizer.alias_hashes_for(record),
                    is_baseline=source_baseline,
                )
                outcome.new_count += 1
                outcome.new_job_ids.append(job_row.id)
                if not source_baseline:
                    _classify_alert(job_row.id, record, job_company, alerts, summary, session)
                elif not baseline and _worth_summarising(record, job_company, alerts):
                    summary.baselined_job_ids.append(job_row.id)
            else:
                # Per-posting-detail adapters skip the detail request for
                # postings we already hold; keep the detail-derived fields
                # so the record does not degrade (and does not flip-flop as
                # a "changed" job every scan).
                if raw.raw.get("detail_fetched") is False:
                    raw = _reuse_detail_fields(raw, existing)
                # Recompute with the original first-seen time so freshness decays.
                record = _normalize(
                    raw,
                    job_company,
                    company,
                    settings,
                    first_seen_at=ensure_utc(existing.first_seen_at),
                    now=now,
                )
                seen_hashes.add(record.identity_hash)
                changes = change_detector.detect_changes(existing, record)
                for change in changes:
                    repo.record_change(
                        session,
                        existing.id,
                        change.field,
                        change.old_value,
                        change.new_value,
                        change.meaningful,
                    )
                reopened = existing.status == "closed"
                repo.apply_record_to_row(existing, record)
                existing.status = "active"
                existing.closed_at = None
                existing.consecutive_misses = 0
                deduper.register(session, existing, record)
                if change_detector.has_meaningful_change(changes) or reopened:
                    outcome.changed_count += 1
                    outcome.changed_job_ids.append(existing.id)
                    # Changed jobs face the same relevance bar as new ones:
                    # senior/non-SWE roles never reach the digest.
                    if (
                        not baseline
                        and alerts.alert_on_changes
                        and existing.match_score >= alerts.digest_min_score
                        and existing.role_family not in (None, "irrelevant", "adjacent")
                        and is_us_accessible(
                            existing.all_locations or [], existing.compensation_currency
                        )
                    ):
                        summary.changed_job_ids.append(existing.id)
                        existing.digest_pending = True

        if skipped_direct:
            logger.info(
                "secondary_skipped_direct",
                source=company.id,
                skipped=skipped_direct,
                reason="employer scanned directly",
            )
        outcome.closed_count = closure_detector.process_closures(
            session,
            company.id,
            seen_hashes,
            jobs_found=len(raw_jobs),
            previous_job_count=previous_count,
        )
        repo.update_source_state_success(session, company.id, len(raw_jobs))
        repo.record_scan_run(session, outcome)
    return outcome


def _normalize(
    raw: RawJob,
    job_company: CompanySource,
    source: CompanySource,
    settings: AppSettings,
    *,
    first_seen_at=None,
    now=None,
) -> JobRecord:
    record = normalizer.normalize(raw, job_company, settings, first_seen_at=first_seen_at, now=now)
    if job_company.id != source.id:
        record = record.model_copy(update={"source_name": source.id})
    return record


def _reuse_detail_fields(raw: RawJob, existing) -> RawJob:
    """Fill a listing-only RawJob from the stored row's detail-derived fields.

    Listing payloads carry weaker versions of several fields (Workday's
    "2 Locations", a constructed URL instead of the canonical one, no
    description, no posted date). The title stays listing-authoritative.
    """
    update: dict = {}
    if raw.description_html is None and raw.description_text is None:
        update["description_html"] = existing.description_html
        update["description_text"] = existing.description_text or None
    if existing.all_locations:
        update["locations"] = list(existing.all_locations)
    if existing.apply_url:
        update["apply_url"] = existing.apply_url
    if existing.source_url:
        update["url"] = existing.source_url
    for field_name in ("posted_at", "employment_type", "department"):
        if getattr(raw, field_name) is None and getattr(existing, field_name) is not None:
            update[field_name] = getattr(existing, field_name)
    if raw.remote_hint is None and existing.remote_type in ("remote", "hybrid"):
        update["remote_hint"] = existing.remote_type
    return raw.model_copy(update=update) if update else raw


def _worth_summarising(record: JobRecord, company: CompanySource, alerts) -> bool:
    """Would this job have reached Discord had the source already been live?"""
    from opportunity_radar.matching.season_parser import SeasonResult
    from opportunity_radar.matching.title_classifier import classify

    season = SeasonResult(
        season=record.season,
        year=record.season_year,
        confidence=record.season_confidence,
        start_min=record.start_date_min,
        start_max=record.start_date_max,
    )
    level = decide_alert_level(
        score=record.match_score,
        season=season,
        classification=classify(record.title, record.description_text),
        company_tier=company.tier,
        posted_at=record.posted_at,
        deadline=None,
        thresholds_immediate=alerts.immediate_min_score,
        thresholds_digest=alerts.digest_min_score,
        thresholds_dashboard=alerts.dashboard_min_score,
        thresholds_suppress=alerts.suppress_below_score,
        us_accessible=is_us_accessible(record.all_locations, record.compensation_currency),
    )
    return level in ("immediate", "digest")


def _classify_alert(
    job_id: int,
    record: JobRecord,
    company: CompanySource,
    alerts,  # AlertSettings
    summary: ScanSummary,
    session,
) -> None:
    from opportunity_radar.matching.season_parser import SeasonResult
    from opportunity_radar.matching.title_classifier import classify

    season = SeasonResult(
        season=record.season,
        year=record.season_year,
        confidence=record.season_confidence,
        start_min=record.start_date_min,
        start_max=record.start_date_max,
    )
    classification = classify(record.title, record.description_text)
    level = decide_alert_level(
        score=record.match_score,
        season=season,
        classification=classification,
        company_tier=company.tier,
        posted_at=record.posted_at,
        deadline=None,
        thresholds_immediate=alerts.immediate_min_score,
        thresholds_digest=alerts.digest_min_score,
        thresholds_dashboard=alerts.dashboard_min_score,
        thresholds_suppress=alerts.suppress_below_score,
        us_accessible=is_us_accessible(record.all_locations, record.compensation_currency),
    )
    if level == "immediate":
        summary.immediate_job_ids.append(job_id)
    elif level == "digest":
        summary.digest_job_ids.append(job_id)
        row = repo.get_job(session, job_id)
        if row is not None:
            row.digest_pending = True
