"""Politeness controls: per-domain serialization, pacing, retry with backoff.

Spec §21: descriptive user agent, per-domain semaphore, exponential backoff,
retry only retryable statuses, honor Retry-After, conditional requests.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

import httpx
import structlog

from opportunity_radar.constants import RETRYABLE_STATUS_CODES, USER_AGENT_TEMPLATE

logger = structlog.get_logger(__name__)


def build_user_agent(contact: str | None = None) -> str:
    contact_part = f"; contact: {contact}" if contact else ""
    return USER_AGENT_TEMPLATE.format(contact=contact_part)


@dataclass
class DomainGate:
    """One-at-a-time access per domain with a minimum gap between requests."""

    min_interval_seconds: float = 1.0
    _semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    _last_request_at: float = 0.0

    async def __aenter__(self) -> DomainGate:
        await self._semaphore.acquire()
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            await asyncio.sleep(self.min_interval_seconds - elapsed)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self._last_request_at = time.monotonic()
        self._semaphore.release()


class RateLimiter:
    """Global concurrency cap plus per-domain gates."""

    def __init__(self, max_global: int = 8, min_domain_interval: float = 1.0) -> None:
        self._global = asyncio.Semaphore(max_global)
        self._domains: dict[str, DomainGate] = {}
        self._min_domain_interval = min_domain_interval

    def gate_for(self, domain: str) -> DomainGate:
        if domain not in self._domains:
            self._domains[domain] = DomainGate(self._min_domain_interval)
        return self._domains[domain]

    async def fetch(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        retries: int = 3,
        backoff_seconds: tuple[float, ...] = (2.0, 8.0, 30.0),
        timeout: float = 30.0,
    ) -> httpx.Response:
        """GET with per-domain pacing, retry on retryable statuses, Retry-After support.

        Raises httpx.HTTPError (or the last retryable response is returned as-is
        for the caller to interpret) — callers must check response.status_code.
        """
        from opportunity_radar.utilities.urls import domain_of

        domain = domain_of(url)
        last_exc: Exception | None = None
        response: httpx.Response | None = None
        for attempt in range(retries + 1):
            try:
                async with self._global, self.gate_for(domain):
                    response = await client.get(url, headers=headers, timeout=timeout)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning("http_transport_error", url=url, attempt=attempt, error=str(exc))
                response = None
            if response is not None and response.status_code not in RETRYABLE_STATUS_CODES:
                return response
            if attempt >= retries:
                break
            delay = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
            if response is not None:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    with contextlib.suppress(ValueError):
                        delay = max(delay, float(retry_after))
            await asyncio.sleep(min(delay, 120.0))
        if response is not None:
            return response
        assert last_exc is not None
        raise last_exc
