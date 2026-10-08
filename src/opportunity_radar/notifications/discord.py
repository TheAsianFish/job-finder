"""Discord incoming-webhook client (spec §15.1).

The webhook URL is a secret: it is never logged (the logging pipeline also
redacts any key containing 'webhook').
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

import httpx
import structlog

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import session_scope
from opportunity_radar.notifications import templates
from opportunity_radar.utilities.dates import utcnow

logger = structlog.get_logger(__name__)

_MAX_ATTEMPTS = 3


# Hub channels the bot creates (`discord setup`, AD-33). Each has its own
# webhook secret DISCORD_WEBHOOK_<NAME>; any that is unset falls back to
# DISCORD_WEBHOOK_URL, the original #job channel, which stays the alerts feed.
CHANNELS: dict[str, str] = {
    "resume": "Resume checks, tailored PDFs, bullet proposals to approve",
    "projects": "Project builder: proposals, plan/milestone PRs, finished projects",
    "study": "Weekly study packs and quizzes for the projects on your resume",
    "agent-log": "Weekly reviews, scans and what every agent did",
}


def webhook_env(channel: str) -> str:
    return "DISCORD_WEBHOOK_" + channel.upper().replace("-", "_")


def webhook_for(channel: str) -> str | None:
    """The webhook for a hub channel, else the default one."""
    from opportunity_radar.config import get_settings

    return os.environ.get(webhook_env(channel)) or get_settings().discord_webhook_url


def notifier_for(channel: str) -> DiscordNotifier:
    return DiscordNotifier(webhook_for(channel))


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

    async def send_files(
        self, payload: dict[str, Any], files: list[tuple[str, bytes, str]]
    ) -> bool:
        """POST a payload with file attachments (multipart; Discord limit 25 MB)."""
        if not self._webhook_url:
            logger.warning("discord_not_configured", hint="set DISCORD_WEBHOOK_URL in .env")
            return False
        import json as _json

        form = {"payload_json": _json.dumps(payload)}
        uploads = {
            f"files[{index}]": (name, data, mime) for index, (name, data, mime) in enumerate(files)
        }
        async with httpx.AsyncClient() as client:
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    response = await client.post(
                        self._webhook_url, data=form, files=uploads, timeout=60.0
                    )
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
                    await asyncio.sleep(min(retry_after, 30.0))
                    continue
                logger.error(
                    "discord_send_failed", status=response.status_code, body=response.text[:300]
                )
                return False
        return False

    async def send_markdown(self, title: str, markdown: str) -> bool:
        """Post a long markdown report as one or more embeds (4,096 chars each)."""
        chunks = templates.markdown_chunks(markdown)
        ok = True
        for index in range(0, len(chunks), 10):
            embeds = [
                {
                    "title": templates.truncate(templates.sanitize(title), 256)
                    if index + i == 0
                    else None,
                    "description": chunk,
                    "color": templates.COLOR_MEDIUM,
                }
                for i, chunk in enumerate(chunks[index : index + 10])
            ]
            payload = {
                "embeds": [{k: v for k, v in e.items() if v is not None} for e in embeds],
                "allowed_mentions": {"parse": []},
            }
            ok = await self.send(payload) and ok
        return ok

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

    async def send_new_sources_summary(
        self, company_ids: list[str], job_ids: list[int], db_url: str | None = None
    ) -> bool:
        """Single embed listing the best open matches from freshly added sources."""
        if not company_ids:
            return False
        with session_scope(db_url) as session:
            names = [c.name for c in repo.list_companies(session) if c.id in set(company_ids)]
            jobs = [j for j in (repo.get_job(session, jid) for jid in job_ids) if j is not None]
            jobs.sort(key=lambda j: j.match_score, reverse=True)
            payload = templates.build_new_sources_summary(
                names or company_ids,
                jobs,
                hidden_count=max(len(jobs) - templates.SUMMARY_LINE_LIMIT, 0),
            )
        return await self.send(payload)

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
