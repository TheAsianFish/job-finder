"""github.careers adapter (company-specific stable JSON, spec §8.8).

GitHub's careers site serves its listing page from a JSON endpoint that
includes the full description and apply link:

    GET https://www.github.careers/api/jobs?page=1&limit=100

The board is small (under 100 postings), so every posting is kept and the
normalizer decides relevance, exactly like a Greenhouse board.

adapter_config:
  base_url: https://www.github.careers   (default)
  max_pages: 5
"""

from __future__ import annotations

from typing import Any

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.adapters.filters import config_int
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities.dates import parse_datetime

PAGE_SIZE = 100
DEFAULT_BASE_URL = "https://www.github.careers"


class GitHubCareersAdapter(BaseAdapter):
    name = "github_careers"

    @staticmethod
    def list_url(base_url: str, page: int) -> str:
        return f"{base_url}/api/jobs?page={page}&limit={PAGE_SIZE}"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        base_url = str(company.adapter_config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
        source = f"github.careers ({base_url})"
        await self.require_robots_allowed(ctx, self.list_url(base_url, 1), source)
        max_pages = max(config_int(company, "max_pages", 5), 1)
        jobs: list[RawJob] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            response = await ctx.get(
                self.list_url(base_url, page), headers={"Accept": "application/json"}
            )
            self.require_status_ok(response, source)
            data = self.parse_json(response, source)
            items = data.get("jobs") if isinstance(data, dict) else None
            if items is None:
                raise AdapterError(f"{source} response missing 'jobs'", category="parse")
            for wrapper in items:
                item = wrapper.get("data") if isinstance(wrapper, dict) else None
                if not isinstance(item, dict):
                    continue
                raw = self._to_raw(base_url, item)
                if raw.source_job_id and raw.source_job_id not in seen:
                    seen.add(raw.source_job_id)
                    jobs.append(raw)
            total = int(data.get("totalCount") or 0)
            if len(items) < PAGE_SIZE or page * PAGE_SIZE >= total:
                break
        return jobs

    def _to_raw(self, base_url: str, item: dict[str, Any]) -> RawJob:
        job_id = str(item.get("req_id") or item.get("slug") or "")
        slug = str(item.get("slug") or job_id)
        url = f"{base_url}/careers-home/jobs/{slug}"
        locations: list[str] = []
        for candidate in (item.get("location_name"), item.get("full_location")):
            if candidate and str(candidate) not in locations:
                locations.append(str(candidate))
        categories = item.get("categories") or item.get("category") or []
        department = None
        if isinstance(categories, list) and categories:
            department = str(categories[0]).strip()
        elif isinstance(categories, str):
            department = categories.strip()
        location_type = str(item.get("location_type") or "").lower()
        remote_hint = "remote" if "remote" in location_type else None
        return RawJob(
            source_adapter=self.name,
            source_job_id=job_id,
            title=str(item.get("title") or "").strip(),
            url=url,
            apply_url=str(item.get("apply_url") or url),
            locations=locations,
            department=department,
            employment_type=item.get("employment_type") or None,
            description_html=item.get("description") or None,
            posted_at=parse_datetime(item.get("posted_date") or item.get("create_date")),
            updated_at=parse_datetime(item.get("update_date")),
            remote_hint=remote_hint,  # type: ignore[arg-type]
            raw={"slug": slug, "country": item.get("country")},
        )
