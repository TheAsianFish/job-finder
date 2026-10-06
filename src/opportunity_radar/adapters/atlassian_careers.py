"""Atlassian careers adapter (company-specific stable JSON, spec §8.8).

Atlassian's careers pages are rendered from one JSON listing:

    GET https://www.atlassian.com/endpoint/careers/listings

It carries every posting with title, locations, category, the three
description sections and the apply URL, so the whole board is stored and
the normalizer decides relevance (same model as a Greenhouse board).

adapter_config:
  url: https://www.atlassian.com/endpoint/careers/listings   (default)
"""

from __future__ import annotations

from typing import Any

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob

DEFAULT_URL = "https://www.atlassian.com/endpoint/careers/listings"
DETAIL_URL = "https://www.atlassian.com/company/careers/details/{id}"


class AtlassianCareersAdapter(BaseAdapter):
    name = "atlassian_careers"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        url = str(company.adapter_config.get("url") or DEFAULT_URL)
        source = "Atlassian careers listing"
        await self.require_robots_allowed(ctx, url, source)
        response = await ctx.get(url, headers={"Accept": "application/json"})
        self.require_status_ok(response, source)
        data = self.parse_json(response, source)
        if not isinstance(data, list):
            raise AdapterError(f"{source} did not return a list", category="parse")
        jobs: list[RawJob] = []
        for item in data:
            if isinstance(item, dict) and item.get("id") and item.get("title"):
                jobs.append(self._to_raw(item))
        return jobs

    def _to_raw(self, item: dict[str, Any]) -> RawJob:
        job_id = str(item["id"])
        locations = [str(loc).strip() for loc in item.get("locations") or [] if loc]
        parts = [
            str(item[key])
            for key in ("overview", "responsibilities", "qualifications")
            if item.get(key)
        ]
        url = DETAIL_URL.format(id=job_id)
        return RawJob(
            source_adapter=self.name,
            source_job_id=job_id,
            title=str(item.get("title") or "").strip(),
            url=url,
            apply_url=str(item.get("applyUrl") or url),
            locations=locations,
            department=item.get("category") or None,
            employment_type=item.get("type") or None,
            description_html="\n".join(parts) or None,
            raw={"portal_id": item.get("portalId")},
        )
