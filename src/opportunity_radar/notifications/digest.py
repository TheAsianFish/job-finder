"""Scheduled Discord digests (spec §15.3)."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select

from opportunity_radar.config import AppSettings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import session_scope
from opportunity_radar.db.tables import ApplicationRow, JobChangeRow, JobRow
from opportunity_radar.notifications import templates
from opportunity_radar.notifications.discord import DiscordNotifier
from opportunity_radar.utilities.dates import utcnow

logger = structlog.get_logger(__name__)

LAST_DIGEST_KEY = "last_digest_at"


def _job_line(job: JobRow) -> str:
    location = job.primary_location or job.remote_type
    return (
        f"**{job.match_score:.0f}** · [{job.title}]({job.apply_url}) — "
        f"{job.company_name} ({location})"
    )


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
        changed_lines = []
        seen_jobs: set[int] = set()
        for change in changed_rows:
            if change.job_id in seen_jobs:
                continue
            seen_jobs.add(change.job_id)
            job = repo.get_job(session, change.job_id)
            if job is None or job.status != "active":
                continue
            # Same relevance bar as new-job digest entries: senior/non-SWE
            # roles score below the digest threshold and stay out.
            if job.match_score < alerts.digest_min_score:
                continue
            if change.field == "description":
                detail = f"description updated ({change.new_value or 'rewritten'})"
            else:
                detail = f"{change.field}: {change.old_value or '—'} → {change.new_value or '—'}"
            changed_lines.append(f"[{job.title}]({job.apply_url}) — {detail}")

        failures = [
            f"{state.company_id}: {state.consecutive_failures} consecutive failures — "
            f"{(state.last_error or '')[:120]}"
            for state in repo.list_source_states(session)
            if state.consecutive_failures >= 3
        ]

        sections = {
            "New high-priority": [_job_line(j) for j in high],
            "New review-worthy": [_job_line(j) for j in review],
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
