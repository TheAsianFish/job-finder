"""Long-running daemon: scheduled scans, digests, catch-up after sleep.

Design (spec §19.3, §19.4): one resilient process, per-tier intervals with
jitter, per-company due times. If the machine slept past scheduled runs, the
wall-clock jump is detected and exactly one catch-up pass runs — due entries
are simply scanned once; there is no backlog of duplicate jobs.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import structlog

from opportunity_radar.config import get_settings, load_settings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import session_scope
from opportunity_radar.notifications.digest import send_digest
from opportunity_radar.notifications.discord import DiscordNotifier
from opportunity_radar.pipeline.scanner import scan_companies
from opportunity_radar.scheduler.jobs import build_schedule, due_now
from opportunity_radar.utilities.dates import utcnow

logger = structlog.get_logger(__name__)

_TICK_SECONDS = 30
_SLEEP_GAP_THRESHOLD = timedelta(minutes=10)
_FAILURE_NOTIFY_THRESHOLD = 3
LAST_MORNING_DIGEST_KEY = "last_morning_digest_date"
LAST_EVENING_DIGEST_KEY = "last_evening_digest_date"


async def run_daemon() -> None:
    settings = load_settings(reload=True)
    notifier = DiscordNotifier(settings.discord_webhook_url)
    schedule = build_schedule(settings.companies, settings.scheduler)
    logger.info(
        "daemon_started",
        companies=len(schedule),
        digest_hours=(
            settings.scheduler.morning_digest_hour,
            settings.scheduler.evening_digest_hour,
        ),
    )
    last_tick = utcnow()

    while True:
        now = utcnow()
        # Sleep/wake detection: a large wall-clock jump means the Mac slept.
        if now - last_tick > _SLEEP_GAP_THRESHOLD:
            logger.info(
                "wake_from_sleep_detected",
                gap_minutes=round((now - last_tick).total_seconds() / 60),
                action="running one catch-up pass for overdue sources",
            )
        last_tick = now

        due = due_now(schedule, now)
        if due:
            companies = [entry.company for entry in due]
            logger.info("scan_tick", due=len(companies))
            try:
                summary = await scan_companies(companies, get_settings())
            except Exception as exc:
                logger.error("scan_tick_failed", error=str(exc))
                summary = None
            for entry in due:
                entry.reschedule(get_settings().scheduler, now)
            if summary is not None:
                if summary.immediate_job_ids:
                    sent = await notifier.send_immediate_alerts(summary.immediate_job_ids)
                    logger.info("immediate_alerts_sent", count=sent)
                await _notify_persistent_failures(notifier)

        await _maybe_send_digest(notifier)
        await asyncio.sleep(_TICK_SECONDS)


async def _maybe_send_digest(notifier: DiscordNotifier) -> None:
    settings = get_settings()
    local_now = datetime.now().astimezone()
    today = local_now.date().isoformat()
    scheduler = settings.scheduler

    for hour, key in (
        (scheduler.morning_digest_hour, LAST_MORNING_DIGEST_KEY),
        (scheduler.evening_digest_hour, LAST_EVENING_DIGEST_KEY),
    ):
        if local_now.hour < hour:
            continue
        with session_scope() as session:
            already = repo.meta_get(session, key) == today
        if already:
            continue
        with session_scope() as session:
            repo.meta_set(session, key, today)
        sent = await send_digest(settings, notifier)
        logger.info("digest_tick", slot_hour=hour, sent=sent)


async def _notify_persistent_failures(notifier: DiscordNotifier) -> None:
    """Notify once when a core source crosses the consecutive-failure threshold."""
    settings = get_settings()
    core_ids = {c.id for c in settings.companies if c.tier == "core"}
    with session_scope() as session:
        states = repo.list_source_states(session)
        for state in states:
            if (
                state.company_id in core_ids
                and state.consecutive_failures >= _FAILURE_NOTIFY_THRESHOLD
                and state.failure_notified_at is None
            ):
                state.failure_notified_at = utcnow()
                asyncio.create_task(  # noqa: RUF006 — fire and forget
                    notifier.send_failure(
                        f"Core source failing: {state.company_id}",
                        f"{state.consecutive_failures} consecutive failures. "
                        f"Last error: {(state.last_error or 'unknown')[:500]}",
                    )
                )
            elif state.consecutive_failures == 0 and state.failure_notified_at is not None:
                state.failure_notified_at = None
