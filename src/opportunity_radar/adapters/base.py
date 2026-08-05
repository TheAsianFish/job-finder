"""Adapter contract (spec §7).

Adapters fetch RawJob lists from one source type. Normalization into
JobRecord happens centrally in pipeline/normalizer so every adapter benefits
from the same season/eligibility/scoring logic.

Failure semantics: fetch_jobs either returns a list (possibly empty, meaning
"the source really has zero jobs") or raises AdapterError. It never returns
an empty list to mask a failure — closure detection depends on this.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.models.scan import ValidationResult
from opportunity_radar.utilities.rate_limit import RateLimiter


class AdapterError(Exception):
    """Structured adapter failure."""

    def __init__(
        self,
        message: str,
        *,
        category: str = "unknown",  # config | network | http | parse | unsupported | robots
        retryable: bool = False,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.http_status = http_status


@dataclass
class AdapterContext:
    """Shared resources handed to adapters for one scan."""

    client: httpx.AsyncClient
    limiter: RateLimiter
    user_agent: str
    timeout: float = 30.0
    retries: int = 3
    backoff_seconds: tuple[float, ...] = (2.0, 8.0, 30.0)

    async def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        merged = {"User-Agent": self.user_agent, **(headers or {})}
        try:
            return await self.limiter.fetch(
                self.client,
                url,
                headers=merged,
                retries=self.retries,
                backoff_seconds=self.backoff_seconds,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise AdapterError(
                f"network error fetching {url}: {exc}", category="network", retryable=True
            ) from exc


class BaseAdapter(ABC):
    """Base class for all job source adapters."""

    name: str = "base"

    @abstractmethod
    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        """Fetch all current jobs. Raises AdapterError on failure."""

    async def validate(self, company: CompanySource, ctx: AdapterContext) -> ValidationResult:
        """Default validation: run a fetch and report the job count."""
        try:
            jobs = await self.fetch_jobs(company, ctx)
        except AdapterError as exc:
            return ValidationResult(ok=False, adapter=self.name, detail=str(exc))
        return ValidationResult(
            ok=True,
            adapter=self.name,
            detail=f"fetched {len(jobs)} jobs",
            job_count=len(jobs),
        )

    @staticmethod
    def require_status_ok(response: httpx.Response, source: str) -> None:
        if response.status_code == 404:
            raise AdapterError(
                f"{source} returned 404 — token/board name is likely wrong",
                category="config",
                retryable=False,
                http_status=404,
            )
        if response.status_code == 429:
            raise AdapterError(
                f"{source} rate limited (429)",
                category="http",
                retryable=True,
                http_status=429,
            )
        if response.status_code >= 400:
            raise AdapterError(
                f"{source} returned HTTP {response.status_code}",
                category="http",
                retryable=response.status_code >= 500,
                http_status=response.status_code,
            )
