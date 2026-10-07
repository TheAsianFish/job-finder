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
from typing import Any

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
    # Source job ids already stored for the company being scanned. Adapters
    # that need one request per posting for the description skip it for
    # these; the scanner keeps the stored description (see
    # pipeline/scanner.py). Empty for adapters that get everything in one
    # payload, and for validation runs.
    known_job_ids: frozenset[str] = frozenset()

    async def get(self, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
        return await self._request("GET", url, headers=headers)

    async def post_json(
        self, url: str, payload: Any, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        """Read-only JSON search request (some ATS search APIs are POST-only).

        Same pacing/retry rules as GET; never used to submit anything.
        """
        return await self._request("POST", url, headers=headers, json=payload)

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        merged = {"User-Agent": self.user_agent, **(headers or {})}
        try:
            return await self.limiter.fetch(
                self.client,
                url,
                headers=merged,
                retries=self.retries,
                backoff_seconds=self.backoff_seconds,
                timeout=self.timeout,
                method=method,
                json=json,
            )
        except httpx.HTTPError as exc:
            raise AdapterError(
                f"network error fetching {url}: {exc}", category="network", retryable=True
            ) from exc


class BaseAdapter(ABC):
    """Base class for all job source adapters."""

    name: str = "base"
    # Secondary sources (spec §28) list postings from many employers. Their
    # RawJobs carry raw["company_name"] and the scanner resolves each one
    # to a company; see pipeline/company_resolver.py.
    secondary: bool = False

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
    async def require_robots_allowed(ctx: AdapterContext, url: str, source: str) -> None:
        """Site-hosted JSON (not a vendor's documented API) honours robots.txt."""
        from opportunity_radar.utilities import robots

        if not await robots.is_allowed(ctx.client, url, ctx.user_agent):
            raise AdapterError(
                f"{source}: robots.txt disallows {url}", category="robots", retryable=False
            )

    @staticmethod
    def parse_json(response: httpx.Response, source: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise AdapterError(f"{source} returned invalid JSON", category="parse") from exc

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
