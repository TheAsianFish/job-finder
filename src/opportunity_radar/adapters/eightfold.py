"""Eightfold career-site adapter (company-specific stable JSON, spec §8.8).

Eightfold-hosted career sites (Netflix: explore.jobs.netflix.net) expose the
JSON their own search page reads:

    GET {base_url}/api/apply/v2/jobs?domain={domain}&query=intern&start=0&num=10
    GET {base_url}/api/apply/v2/jobs/{id}?domain={domain}

Search is semantic and pages are fixed at 10, so the adapter runs a few
early-career queries, keeps only titles that pass the shared early-career
rules, and fetches the description per posting. Everything is capped.

adapter_config:
  base_url: https://explore.jobs.netflix.net   (required)
  domain: netflix.com                           (required; Eightfold tenant key)
  queries: [intern, internship, new grad, university]
  max_pages: 5                                  (per query, 10 per page)
  detail_limit: 100
  early_career_only: true
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.adapters.filters import (
    config_int,
    config_list,
    early_career_only,
    looks_early_career,
)
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities.dates import parse_datetime

PAGE_SIZE = 10
DEFAULT_QUERIES = ["intern", "internship", "new grad", "university"]


def extract_eightfold_config(company: CompanySource) -> tuple[str, str] | None:
    base_url = company.adapter_config.get("base_url")
    domain = company.adapter_config.get("domain")
    if not base_url:
        for url in company.career_urls:
            if ".eightfold.ai" in url or "/api/apply/" in url or "/careers/" in url:
                base_url = url.split("/careers")[0].split("/api/")[0]
                break
    if not base_url:
        return None
    domain = domain or company.domain
    if not domain:
        return None
    return str(base_url).rstrip("/"), str(domain)


class EightfoldAdapter(BaseAdapter):
    name = "eightfold"

    @staticmethod
    def search_url(base_url: str, domain: str, query: str, start: int) -> str:
        return (
            f"{base_url}/api/apply/v2/jobs?domain={quote_plus(domain)}"
            f"&query={quote_plus(query)}&start={start}&num={PAGE_SIZE}&sort_by=relevance"
        )

    @staticmethod
    def detail_url(base_url: str, domain: str, position_id: str) -> str:
        return f"{base_url}/api/apply/v2/jobs/{position_id}?domain={quote_plus(domain)}"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        resolved = extract_eightfold_config(company)
        if resolved is None:
            raise AdapterError(
                f"no Eightfold base_url/domain configured for {company.id}", category="config"
            )
        base_url, domain = resolved
        source = f"Eightfold '{domain}'"
        await self.require_robots_allowed(ctx, self.search_url(base_url, domain, "", 0), source)
        filter_titles = early_career_only(company)
        queries = config_list(company, "queries", DEFAULT_QUERIES) if filter_titles else [""]
        max_pages = max(config_int(company, "max_pages", 5), 1)

        positions: dict[str, dict[str, Any]] = {}
        for query in queries:
            start = 0
            for _ in range(max_pages):
                response = await ctx.get(
                    self.search_url(base_url, domain, query, start),
                    headers={"Accept": "application/json"},
                )
                self.require_status_ok(response, source)
                data = self.parse_json(response, source)
                items = data.get("positions") if isinstance(data, dict) else None
                if items is None:
                    raise AdapterError(f"{source} response missing 'positions'", category="parse")
                for item in items:
                    position_id = str(item.get("id") or "")
                    title = str(item.get("name") or "")
                    if not position_id or position_id in positions:
                        continue
                    if filter_titles and not looks_early_career(title):
                        continue
                    positions[position_id] = item
                start += PAGE_SIZE
                if len(items) < PAGE_SIZE or start >= int(data.get("count") or 0):
                    break

        detail_limit = config_int(company, "detail_limit", 100)
        jobs: list[RawJob] = []
        for index, (position_id, item) in enumerate(positions.items()):
            detail: dict[str, Any] = {}
            if index < detail_limit:
                response = await ctx.get(
                    self.detail_url(base_url, domain, position_id),
                    headers={"Accept": "application/json"},
                )
                if response.status_code < 400:
                    parsed = self.parse_json(response, source)
                    detail = parsed if isinstance(parsed, dict) else {}
            jobs.append(self._to_raw(base_url, domain, item, detail))
        return jobs

    def _to_raw(
        self, base_url: str, domain: str, item: dict[str, Any], detail: dict[str, Any]
    ) -> RawJob:
        position_id = str(item.get("id") or "")
        merged = {**item, **{k: v for k, v in detail.items() if v not in (None, "", [])}}
        locations: list[str] = []
        for candidate in merged.get("locations") or [merged.get("location")]:
            if candidate and str(candidate) not in locations:
                locations.append(str(candidate).replace(",", ", ").replace(",  ", ", "))
        url = str(merged.get("canonicalPositionUrl") or f"{base_url}/careers/job/{position_id}")
        work_option = str(merged.get("work_location_option") or "").lower()
        remote_hint = "remote" if work_option == "remote" else None
        return RawJob(
            source_adapter=self.name,
            source_job_id=position_id,
            title=str(merged.get("name") or "").strip(),
            url=url,
            apply_url=url,
            locations=locations,
            department=merged.get("department") or None,
            description_html=merged.get("job_description") or None,
            posted_at=parse_datetime(_epoch(merged.get("t_create"))),
            updated_at=parse_datetime(_epoch(merged.get("t_update"))),
            remote_hint=remote_hint,  # type: ignore[arg-type]
            raw={
                "domain": domain,
                "display_job_id": merged.get("display_job_id"),
                "detail_fetched": bool(detail),
            },
        )


def _epoch(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
