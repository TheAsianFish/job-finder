"""Greenhouse Job Board API adapter (spec §8.1).

Public, unauthenticated, read-only:
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
The application submission endpoint is never used.
"""

from __future__ import annotations

import html as html_module
import re
from typing import Any

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities.dates import parse_datetime

_BOARD_URL_RES = [
    re.compile(r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)"),
    re.compile(r"job-boards\.greenhouse\.io/([A-Za-z0-9_-]+)"),
    re.compile(r"boards-api\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)"),
]


def extract_board_token(company: CompanySource) -> str | None:
    token = company.adapter_config.get("board_token")
    if token:
        return str(token)
    for url in company.career_urls:
        for pattern in _BOARD_URL_RES:
            match = pattern.search(url)
            if match:
                return match.group(1)
    return None


class GreenhouseAdapter(BaseAdapter):
    name = "greenhouse"

    def api_url(self, token: str) -> str:
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        token = extract_board_token(company)
        if not token:
            raise AdapterError(
                f"no Greenhouse board token configured for {company.id}",
                category="config",
            )
        response = await ctx.get(self.api_url(token))
        self.require_status_ok(response, f"Greenhouse board '{token}'")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterError(
                f"Greenhouse board '{token}' returned invalid JSON",
                category="parse",
            ) from exc
        jobs_data = payload.get("jobs")
        if jobs_data is None:
            raise AdapterError(
                f"Greenhouse board '{token}' response missing 'jobs' key",
                category="parse",
            )
        return [self._to_raw(job, token) for job in jobs_data]

    def _to_raw(self, job: dict[str, Any], token: str) -> RawJob:
        # Greenhouse returns HTML-escaped content.
        content = job.get("content") or ""
        description_html = html_module.unescape(content) if content else None

        locations: list[str] = []
        location_obj = job.get("location") or {}
        if isinstance(location_obj, dict) and location_obj.get("name"):
            locations.append(str(location_obj["name"]))
        for office in job.get("offices") or []:
            name = office.get("name") if isinstance(office, dict) else None
            if name and name not in locations:
                locations.append(str(name))

        departments = [
            str(d.get("name"))
            for d in job.get("departments") or []
            if isinstance(d, dict) and d.get("name")
        ]

        absolute_url = str(job.get("absolute_url") or "")
        return RawJob(
            source_adapter=self.name,
            source_job_id=str(job.get("id", "")),
            title=str(job.get("title") or "").strip(),
            url=absolute_url,
            apply_url=absolute_url,
            locations=locations,
            department=departments[0] if departments else None,
            description_html=description_html,
            posted_at=parse_datetime(job.get("first_published")),
            updated_at=parse_datetime(job.get("updated_at")),
            raw={"board_token": token, "id": job.get("id")},
        )
