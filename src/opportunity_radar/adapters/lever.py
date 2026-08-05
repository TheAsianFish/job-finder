"""Lever Postings API adapter (spec §8.2).

Public, read-only:
GET https://api.lever.co/v0/postings/{site}?mode=json
Supports the EU instance via adapter_config.region: eu.
Programmatic application submission is never attempted.
"""

from __future__ import annotations

import re
from typing import Any

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities.dates import parse_datetime

_SITE_URL_RES = [
    re.compile(r"jobs\.(eu\.)?lever\.co/([A-Za-z0-9_-]+)"),
    re.compile(r"api\.(eu\.)?lever\.co/v0/postings/([A-Za-z0-9_-]+)"),
]


def extract_site(company: CompanySource) -> tuple[str | None, str]:
    """Return (site_token, region) where region is '' or 'eu.'."""
    site = company.adapter_config.get("site") or company.adapter_config.get("site_token")
    region = "eu." if str(company.adapter_config.get("region", "")).lower() == "eu" else ""
    if site:
        return str(site), region
    for url in company.career_urls:
        for pattern in _SITE_URL_RES:
            match = pattern.search(url)
            if match:
                return match.group(2), match.group(1) or ""
    return None, region


class LeverAdapter(BaseAdapter):
    name = "lever"

    def api_url(self, site: str, region: str = "", skip: int = 0, limit: int = 100) -> str:
        return (
            f"https://api.{region}lever.co/v0/postings/{site}?mode=json&skip={skip}&limit={limit}"
        )

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        site, region = extract_site(company)
        if not site:
            raise AdapterError(
                f"no Lever site token configured for {company.id}", category="config"
            )
        jobs: list[RawJob] = []
        skip = 0
        limit = 100
        while True:
            response = await ctx.get(self.api_url(site, region, skip, limit))
            self.require_status_ok(response, f"Lever site '{site}'")
            try:
                payload = response.json()
            except ValueError as exc:
                raise AdapterError(
                    f"Lever site '{site}' returned invalid JSON", category="parse"
                ) from exc
            if not isinstance(payload, list):
                raise AdapterError(
                    f"Lever site '{site}' returned unexpected payload shape",
                    category="parse",
                )
            jobs.extend(self._to_raw(item, site) for item in payload)
            if len(payload) < limit:
                break
            skip += limit
            if skip > 5000:  # sanity cap
                break
        return jobs

    def _to_raw(self, job: dict[str, Any], site: str) -> RawJob:
        categories = job.get("categories") or {}
        locations: list[str] = []
        if categories.get("location"):
            locations.append(str(categories["location"]))
        for extra in categories.get("allLocations") or []:
            if extra and str(extra) not in locations:
                locations.append(str(extra))

        workplace = str(job.get("workplaceType") or "").lower()
        remote_hint = None
        if workplace == "remote":
            remote_hint = "remote"
        elif workplace == "hybrid":
            remote_hint = "hybrid"
        elif workplace in ("onsite", "on-site"):
            remote_hint = "onsite"

        hosted_url = str(job.get("hostedUrl") or "")
        apply_url = str(job.get("applyUrl") or hosted_url)
        return RawJob(
            source_adapter=self.name,
            source_job_id=str(job.get("id", "")),
            title=str(job.get("text") or "").strip(),
            url=hosted_url,
            apply_url=apply_url or hosted_url,
            locations=locations,
            department=categories.get("department"),
            team=categories.get("team"),
            employment_type=categories.get("commitment"),
            description_html=job.get("description"),
            description_text=job.get("descriptionPlain"),
            posted_at=parse_datetime(job.get("createdAt")),
            remote_hint=remote_hint,  # type: ignore[arg-type]
            raw={"site": site, "id": job.get("id"), "country": job.get("country")},
        )
