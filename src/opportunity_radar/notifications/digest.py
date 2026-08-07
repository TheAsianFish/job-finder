"""Scheduled Discord digests (spec §15.3)."""

from __future__ import annotations

from datetime import timedelta

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
        since = now - timedelta(hours=24)

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
            if job is not None:
                changed_lines.append(
                    f"[{job.title}]({job.apply_url}) — {change.field}: "
                    f"{change.old_value or '—'} → {change.new_value or '—'}"
                )

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
    label = "Morning" if now.astimezone().hour < 12 else "Evening"
    payload = templates.build_digest_payload(f"📋 {label} digest — Opportunity Radar", sections)
    if payload is None:
        logger.info("digest_empty", last_digest=last_digest_raw)
    return payload


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
        return False
    ok = await notifier.send(payload)
    if ok:
        with session_scope(db_url) as session:
            repo.meta_set(session, LAST_DIGEST_KEY, utcnow().isoformat())
            for job in session.scalars(select(JobRow).where(JobRow.digest_pending.is_(True))):
                job.digest_pending = False
    return ok
