"""amazon.jobs adapter (company-specific stable JSON, spec §8.8).

amazon.jobs serves its own search page from a JSON endpoint that includes
full descriptions and explicit intern/university flags:

    GET https://www.amazon.jobs/en/search.json?category[]=software-development
        &base_query=intern&result_limit=100&offset=0

The adapter runs a few early-career queries per configured category, keeps
postings Amazon itself flags as intern/university roles (or whose title
passes the shared early-career rules), and never fetches detail pages.

adapter_config:
  categories: [software-development]
  queries: [intern, new grad, graduate]
  country_codes: [USA]    (client-side filter on Amazon's country_code; [] = all)
  max_pages: 3            (100 results per page, per query)
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

PAGE_SIZE = 100
BASE_URL = "https://www.amazon.jobs"
DEFAULT_CATEGORIES = ["software-development"]
DEFAULT_QUERIES = ["intern", "new grad", "graduate"]
DEFAULT_COUNTRY_CODES = ["USA"]


class AmazonJobsAdapter(BaseAdapter):
    name = "amazon_jobs"

    @staticmethod
    def search_url(category: str, query: str, offset: int) -> str:
        return (
            f"{BASE_URL}/en/search.json?category[]={quote_plus(category)}"
            f"&base_query={quote_plus(query)}&result_limit={PAGE_SIZE}&offset={offset}"
        )

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        source = "amazon.jobs search"
        await self.require_robots_allowed(
            ctx, self.search_url("software-development", "", 0), source
        )
        filter_titles = early_career_only(company)
        categories = config_list(company, "categories", DEFAULT_CATEGORIES)
        queries = config_list(company, "queries", DEFAULT_QUERIES) if filter_titles else [""]
        max_pages = max(config_int(company, "max_pages", 3), 1)
        raw_countries = company.adapter_config.get("country_codes", DEFAULT_COUNTRY_CODES)
        country_codes = {
            str(code).upper() for code in (raw_countries if isinstance(raw_countries, list) else [])
        }

        seen: dict[str, dict[str, Any]] = {}
        for category in categories:
            for query in queries:
                offset = 0
                for _ in range(max_pages):
                    response = await ctx.get(
                        self.search_url(category, query, offset),
                        headers={"Accept": "application/json"},
                    )
                    self.require_status_ok(response, source)
                    data = self.parse_json(response, source)
                    if not isinstance(data, dict) or "jobs" not in data:
                        raise AdapterError(f"{source} response missing 'jobs'", category="parse")
                    if data.get("error"):
                        raise AdapterError(f"{source} error: {data['error']}", category="http")
                    items = data.get("jobs") or []
                    for item in items:
                        job_id = str(item.get("id_icims") or item.get("id") or "")
                        if not job_id or job_id in seen:
                            continue
                        if filter_titles and not self._is_early_career(item):
                            continue
                        if (
                            country_codes
                            and str(item.get("country_code") or "").upper() not in country_codes
                        ):
                            continue
                        seen[job_id] = item
                    offset += PAGE_SIZE
                    if len(items) < PAGE_SIZE or offset >= int(data.get("hits") or 0):
                        break
        return [self._to_raw(item) for item in seen.values()]

    @staticmethod
    def _is_early_career(item: dict[str, Any]) -> bool:
        if item.get("is_intern") or item.get("university_job"):
            return True
        return looks_early_career(str(item.get("title") or ""))

    def _to_raw(self, item: dict[str, Any]) -> RawJob:
        job_id = str(item.get("id_icims") or item.get("id") or "")
        path = str(item.get("job_path") or f"/en/jobs/{job_id}")
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        locations: list[str] = []
        for candidate in (item.get("normalized_location"), item.get("location")):
            if candidate and str(candidate) not in locations:
                locations.append(str(candidate))
        for extra in item.get("locations") or []:
            if isinstance(extra, str) and extra not in locations:
                locations.append(extra)
        parts: list[str] = []
        if item.get("description"):
            parts.append(f"<p>{item['description']}</p>")
        for key, heading in (
            ("basic_qualifications", "Basic qualifications"),
            ("preferred_qualifications", "Preferred qualifications"),
        ):
            if item.get(key):
                parts.append(f"<h3>{heading}</h3><p>{item[key]}</p>")
        return RawJob(
            source_adapter=self.name,
            source_job_id=job_id,
            title=str(item.get("title") or "").strip(),
            url=url,
            apply_url=str(item.get("url_next_step") or url),
            locations=locations,
            department=item.get("job_category") or None,
            team=(item.get("team") or {}).get("label")
            if isinstance(item.get("team"), dict)
            else None,
            employment_type=item.get("job_schedule_type") or None,
            description_html="\n".join(parts) or None,
            posted_at=parse_datetime(item.get("posted_date")),
            raw={
                "business_category": item.get("business_category"),
                "is_intern": bool(item.get("is_intern")),
                "university_job": bool(item.get("university_job")),
                "country_code": item.get("country_code"),
            },
        )
