"""Discord incoming-webhook client (spec §15.1).

The webhook URL is a secret: it is never logged (the logging pipeline also
redacts any key containing 'webhook').
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import httpx
import structlog

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import session_scope
from opportunity_radar.notifications import templates
from opportunity_radar.utilities.dates import utcnow

logger = structlog.get_logger(__name__)

_MAX_ATTEMPTS = 3


class DiscordError(Exception):
    pass


class DiscordNotifier:
    def __init__(self, webhook_url: str | None) -> None:
        self._webhook_url = webhook_url

    @property
    def configured(self) -> bool:
        return bool(self._webhook_url)

    async def send(self, payload: dict[str, Any]) -> bool:
        """POST a payload to the webhook. Returns True on success."""
        if not self._webhook_url:
            logger.warning("discord_not_configured", hint="set DISCORD_WEBHOOK_URL in .env")
            return False
        async with httpx.AsyncClient() as client:
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    response = await client.post(self._webhook_url, json=payload, timeout=15.0)
                except httpx.HTTPError as exc:
                    logger.warning("discord_network_error", attempt=attempt, error=str(exc))
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                if response.status_code in (200, 204):
                    return True
                if response.status_code == 429:
                    retry_after = 2.0
                    with contextlib.suppress(Exception):
                        retry_after = float(response.json().get("retry_after", retry_after))
                    logger.warning("discord_rate_limited", retry_after=retry_after)
                    await asyncio.sleep(min(retry_after, 30.0))
                    continue
                logger.error(
                    "discord_send_failed",
                    status=response.status_code,
                    body=response.text[:300],
                )
                return False
        return False

    async def send_test(self) -> bool:
        return await self.send(templates.build_test_payload())

    async def send_failure(self, subject: str, detail: str) -> bool:
        return await self.send(templates.build_failure_payload(subject, detail))

    async def send_immediate_alerts(self, job_ids: list[int], db_url: str | None = None) -> int:
        """Send one embed per job; never re-alert a job that already alerted."""
        sent = 0
        for job_id in job_ids:
            with session_scope(db_url) as session:
                job = repo.get_job(session, job_id)
                if job is None or job.alerted_at is not None:
                    continue
                payload = templates.build_job_embed(job)
            if await self.send(payload):
                with session_scope(db_url) as session:
                    job = repo.get_job(session, job_id)
                    if job is not None:
                        job.alerted_at = utcnow()
                sent += 1
        return sent

    async def send_baseline_summary(self, db_url: str | None = None) -> bool:
        with session_scope(db_url) as session:
            jobs = repo.list_jobs(session, status="active", limit=100_000)
            by_source: dict[str, int] = {}
            bands = {"80-100": 0, "60-79": 0, "35-59": 0, "<35": 0}
            for job in jobs:
                by_source[job.source_adapter] = by_source.get(job.source_adapter, 0) + 1
                if job.match_score >= 80:
                    bands["80-100"] += 1
                elif job.match_score >= 60:
                    bands["60-79"] += 1
                elif job.match_score >= 35:
                    bands["35-59"] += 1
                else:
                    bands["<35"] += 1
            payload = templates.build_baseline_summary(len(jobs), by_source, bands)
        return await self.send(payload)
