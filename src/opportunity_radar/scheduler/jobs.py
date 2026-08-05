"""Per-company schedule bookkeeping for the daemon."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from opportunity_radar.config import SchedulerSettings
from opportunity_radar.models.company import CompanySource
from opportunity_radar.utilities.dates import utcnow


@dataclass
class ScheduledCompany:
    company: CompanySource
    next_run_at: datetime = field(default_factory=utcnow)

    def reschedule(self, scheduler: SchedulerSettings, now: datetime | None = None) -> None:
        now = now or utcnow()
        interval = self.company.interval_minutes(scheduler.tier_intervals())
        jitter = random.uniform(0, scheduler.jitter_seconds)
        self.next_run_at = now + timedelta(minutes=interval, seconds=jitter)


def build_schedule(
    companies: list[CompanySource], scheduler: SchedulerSettings
) -> list[ScheduledCompany]:
    """Initial schedule: spread first runs over a short window to avoid a
    thundering herd at daemon start."""
    now = utcnow()
    scheduled = []
    for index, company in enumerate(company for company in companies if company.enabled):
        offset = timedelta(seconds=index * 2 + random.uniform(0, 5))
        scheduled.append(ScheduledCompany(company=company, next_run_at=now + offset))
    return scheduled


def due_now(
    schedule: list[ScheduledCompany], now: datetime | None = None
) -> list[ScheduledCompany]:
    now = now or utcnow()
    return [entry for entry in schedule if entry.next_run_at <= now]
