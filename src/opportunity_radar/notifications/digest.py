"""Scheduled Discord digests (spec §15.3)."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select

from opportunity_radar.adapters.filters import PREFILTERING_ADAPTERS
from opportunity_radar.config import AppSettings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import session_scope
from opportunity_radar.db.tables import ApplicationRow, JobChangeRow, JobRow
from opportunity_radar.notifications import templates
from opportunity_radar.notifications.discord import DiscordNotifier
from opportunity_radar.utilities.dates import utcnow

logger = structlog.get_logger(__name__)

LAST_DIGEST_KEY = "last_digest_at"


_HANDLED_STATUSES = frozenset(
    {"applied", "oa", "interview", "offer", "rejected", "withdrawn", "dismissed"}
)


def _digest_relevant(job: JobRow, settings: AppSettings | None = None) -> bool:
    """Notification bar shared by every digest section: software role that a
    US citizen can actually work, and an internship or a full-time role that
    fits the candidate's start/graduation range. Score never overrides these."""
    from opportunity_radar.matching.notify import role_notifiable
    from opportunity_radar.matching.scorer import is_us_accessible

    if job.role_family in (None, "irrelevant", "adjacent"):
        return False
    if job.application is not None and job.application.status in _HANDLED_STATUSES:
        return False  # already applied to, decided on, or dismissed
    if settings is not None and not role_notifiable(
        title=job.title,
        description=job.description_text,
        eligibility_level=job.eligibility_level,
        start_min=job.start_date_min,
        settings=settings,
    ):
        return False
    return is_us_accessible(job.all_locations or [], job.compensation_currency)


def _job_line(job: JobRow) -> str:
    location = job.primary_location or job.remote_type
    return (
        f"**{job.match_score:.0f}** · [{job.title}]({job.apply_url}) — "
        f"{job.company_name} ({location})"
    )


# One prolific board (a core-tier company posting dozens of intern variants)
# must not crowd every other company out of a section: each company gets at
# most this many lines, and the rest is summarised on one trailing line.
DIGEST_PER_COMPANY_CAP = 3


def _section_lines(jobs: list[JobRow], per_company: int = DIGEST_PER_COMPANY_CAP) -> list[str]:
    """Render score-sorted jobs with a per-company cap plus an overflow note."""
    shown_per_company: dict[str, int] = {}
    overflow: dict[str, int] = {}
    lines: list[str] = []
    for job in jobs:
        count = shown_per_company.get(job.company_name, 0)
        if count < per_company:
            shown_per_company[job.company_name] = count + 1
            lines.append(_job_line(job))
        else:
            overflow[job.company_name] = overflow.get(job.company_name, 0) + 1
    if overflow:
        parts = [f"{n} more at {name}" for name, n in sorted(overflow.items(), key=lambda p: -p[1])]
        lines.append("_+ " + ", ".join(parts[:6]) + " (see dashboard)_")
    return lines


def build_digest(settings: AppSettings, db_url: str | None = None) -> dict | None:
    """Collect digest sections; returns None when there is nothing to say."""
    alerts = settings.scoring.alerts
    now = utcnow()
    with session_scope(db_url) as session:
        last_digest_raw = repo.meta_get(session, LAST_DIGEST_KEY)
        # Changes are reported once: everything since the previous digest,
        # falling back to 24h when no digest has ever been sent.
        since = now - timedelta(hours=24)
        if last_digest_raw:
            with contextlib.suppress(ValueError):
                since = datetime.fromisoformat(last_digest_raw)

        pending = list(
            session.scalars(
                select(JobRow).where(JobRow.digest_pending.is_(True), JobRow.status == "active")
            )
        )
        # Non-software and non-US roles never notify, whatever their score
        # (belt to the scanner's suspenders: stale pending flags survive rule
        # changes).
        pending = [j for j in pending if _digest_relevant(j, settings)]
        # Best first: sections truncate to 10 lines, so the cut must keep the
        # top-scored roles, not an arbitrary insertion-order slice.
        pending.sort(key=lambda j: j.match_score, reverse=True)
        high = [j for j in pending if j.match_score >= alerts.immediate_min_score]
        review = [
            j
            for j in pending
            if alerts.digest_min_score <= j.match_score < alerts.immediate_min_score
        ]

        deadlines = list(
            session.scalars(
                select(ApplicationRow).where(
                    ApplicationRow.deadline.isnot(None),
                    ApplicationRow.deadline <= (now + timedelta(days=7)).date(),
                    ApplicationRow.status.notin_(["applied", "rejected", "dismissed"]),
                )
            )
        )
        deadline_lines = []
        for app in deadlines:
            job = repo.get_job(session, app.job_id)
            if job is not None:
                deadline_lines.append(
                    f"{app.deadline}: [{job.title}]({job.apply_url}) — {job.company_name}"
                )

        changed_rows = list(
            session.scalars(
                select(JobChangeRow)
                .where(JobChangeRow.meaningful.is_(True), JobChangeRow.changed_at >= since)
                .order_by(JobChangeRow.changed_at.desc())
                .limit(30)
            )
        )
        scored_changes: list[tuple[float, str]] = []
        seen_jobs: set[int] = set()
        for change in changed_rows:
            if change.job_id in seen_jobs:
                continue
            seen_jobs.add(change.job_id)
            job = repo.get_job(session, change.job_id)
            if job is None or job.status != "active":
                continue
            # Same relevance bar as new-job digest entries: senior/non-SWE
            # and non-US roles never notify, whatever their score.
            if job.match_score < alerts.digest_min_score or not _digest_relevant(job, settings):
                continue
            if change.field == "description":
                detail = f"description updated ({change.new_value or 'rewritten'})"
            else:
                detail = f"{change.field}: {change.old_value or '—'} → {change.new_value or '—'}"
            scored_changes.append((job.match_score, f"[{job.title}]({job.apply_url}) — {detail}"))
        scored_changes.sort(key=lambda pair: pair[0], reverse=True)
        changed_lines = [line for _, line in scored_changes]

        enabled_ids = {c.id for c in settings.companies if c.enabled}
        failures = [
            f"{state.company_id}: {state.consecutive_failures} consecutive failures — "
            f"{(state.last_error or '')[:120]}"
            for state in repo.list_source_states(session)
            if state.consecutive_failures >= 3
            and (not settings.companies or state.company_id in enabled_ids)
        ]
        # A source that "succeeds" with zero jobs is almost always a stale
        # board token, not an empty company — surface it next to hard failures.
        prefiltering = {c.id for c in settings.companies if c.adapter in PREFILTERING_ADAPTERS}
        silent = sorted(
            state.company_id
            for state in repo.list_source_states(session)
            if state.consecutive_failures < 3
            and state.last_success_at is not None
            and state.last_job_count == 0
            and state.company_id not in prefiltering
            and (not settings.companies or state.company_id in enabled_ids)
        )
        if silent:
            failures.append(
                f"{len(silent)} source(s) returning 0 jobs (run `companies repair`): "
                + ", ".join(silent[:12])
                + (" …" if len(silent) > 12 else "")
            )

        sections = {
            "New high-priority": _section_lines(high),
            "New review-worthy": _section_lines(review),
            "Deadlines approaching": deadline_lines,
            "Changed / reopened": changed_lines,
            "Source failures": failures,
        }
    payload = templates.build_digest_payload(_digest_title(now), sections)
    if payload is None:
        logger.info("digest_empty", last_digest=last_digest_raw)
    return payload


def _digest_title(now) -> str:
    label = "Morning" if now.astimezone().hour < 12 else "Evening"
    return f"📋 {label} digest — Opportunity Radar"


def build_quiet_digest(db_url: str | None = None) -> dict:
    """'Nothing new' notice sent when a scheduled digest has no content."""
    from opportunity_radar.utilities.dates import humanize_age

    with session_scope(db_url) as session:
        last_digest_raw = repo.meta_get(session, LAST_DIGEST_KEY)
    detail = "No new updates in the last 24 hours."
    if last_digest_raw:
        with contextlib.suppress(ValueError):
            last_at = datetime.fromisoformat(last_digest_raw)
            detail = f"No new updates since the last digest ({humanize_age(last_at)})."
    return templates.build_quiet_digest_payload(_digest_title(utcnow()), detail)


LAST_MORNING_DIGEST_KEY = "last_morning_digest_date"
LAST_EVENING_DIGEST_KEY = "last_evening_digest_date"


async def send_digest_if_due(
    settings: AppSettings, notifier: DiscordNotifier, db_url: str | None = None
) -> bool:
    """Send the morning/evening digest if its local-time slot has arrived today.

    Used by both the daemon tick and cloud-mode runs (`notify digest --if-due`).
    Each slot fires at most once per calendar day, tracked in the meta table.
    """
    from datetime import datetime

    local_now = datetime.now().astimezone()
    today = local_now.date().isoformat()
    scheduler = settings.scheduler
    sent_any = False
    for hour, key in (
        (scheduler.morning_digest_hour, LAST_MORNING_DIGEST_KEY),
        (scheduler.evening_digest_hour, LAST_EVENING_DIGEST_KEY),
    ):
        if local_now.hour < hour:
            continue
        with session_scope(db_url) as session:
            if repo.meta_get(session, key) == today:
                continue
            repo.meta_set(session, key, today)
        sent = await send_digest(settings, notifier, db_url)
        logger.info("digest_slot", slot_hour=hour, sent=sent)
        sent_any = sent_any or sent
    return sent_any


async def send_digest(
    settings: AppSettings, notifier: DiscordNotifier, db_url: str | None = None
) -> bool:
    payload = build_digest(settings, db_url)
    if payload is None:
        # Say so explicitly — a quiet channel should mean "no updates",
        # never "is the monitor even running?".
        payload = build_quiet_digest(db_url)
    ok = await notifier.send(payload)
    if ok:
        with session_scope(db_url) as session:
            repo.meta_set(session, LAST_DIGEST_KEY, utcnow().isoformat())
            for job in session.scalars(select(JobRow).where(JobRow.digest_pending.is_(True))):
                job.digest_pending = False
    return ok
