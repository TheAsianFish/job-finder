"""Ashby public Job Posting API adapter (spec §8.3).

GET https://api.ashbyhq.com/posting-api/job-board/{JOB_BOARD_NAME}?includeCompensation=true
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities.dates import parse_datetime

_BOARD_URL_RES = [
    re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.%-]+)"),
]


def extract_board_name(company: CompanySource) -> str | None:
    name = company.adapter_config.get("job_board_name") or company.adapter_config.get("board_name")
    if name:
        return str(name)
    for url in company.career_urls:
        for pattern in _BOARD_URL_RES:
            match = pattern.search(url)
            if match:
                return match.group(1)
    return None


class AshbyAdapter(BaseAdapter):
    name = "ashby"

    def api_url(self, board_name: str) -> str:
        return (
            f"https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true"
        )

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        board_name = extract_board_name(company)
        if not board_name:
            raise AdapterError(
                f"no Ashby job board name configured for {company.id}", category="config"
            )
        response = await ctx.get(self.api_url(board_name))
        self.require_status_ok(response, f"Ashby board '{board_name}'")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterError(
                f"Ashby board '{board_name}' returned invalid JSON", category="parse"
            ) from exc
        jobs_data = payload.get("jobs")
        if jobs_data is None:
            raise AdapterError(
                f"Ashby board '{board_name}' response missing 'jobs' key", category="parse"
            )
        return [self._to_raw(job, board_name) for job in jobs_data if job.get("isListed", True)]

    def _to_raw(self, job: dict[str, Any], board_name: str) -> RawJob:
        locations: list[str] = []
        if job.get("location"):
            locations.append(str(job["location"]))
        for secondary in job.get("secondaryLocations") or []:
            name = secondary.get("location") if isinstance(secondary, dict) else secondary
            if name and str(name) not in locations:
                locations.append(str(name))

        remote_hint = "remote" if job.get("isRemote") else None

        comp_min = comp_max = None
        comp_currency = comp_period = None
        compensation = job.get("compensation") or {}
        tiers = compensation.get("compensationTierSummaries") or []
        if tiers:
            first = tiers[0]
            components = first.get("compensationComponents") or []
            for component in components:
                if component.get("compensationType") in ("Salary", "Hourly", None):
                    min_value = component.get("minValue")
                    max_value = component.get("maxValue")
                    comp_min = Decimal(str(min_value)) if min_value is not None else None
                    comp_max = Decimal(str(max_value)) if max_value is not None else None
                    comp_currency = component.get("currencyCode")
                    interval = str(component.get("interval") or "")
                    if "YEAR" in interval.upper():
                        comp_period = "year"
                    elif "HOUR" in interval.upper():
                        comp_period = "hour"
                    break

        job_url = str(job.get("jobUrl") or "")
        apply_url = str(job.get("applyUrl") or job_url)
        return RawJob(
            source_adapter=self.name,
            source_job_id=str(job.get("id", "")),
            title=str(job.get("title") or "").strip(),
            url=job_url,
            apply_url=apply_url or job_url,
            locations=locations,
            department=job.get("department"),
            team=job.get("team"),
            employment_type=job.get("employmentType"),
            description_html=job.get("descriptionHtml"),
            description_text=job.get("descriptionPlain"),
            posted_at=parse_datetime(job.get("publishedAt")),
            remote_hint=remote_hint,  # type: ignore[arg-type]
            compensation_min=comp_min,
            compensation_max=comp_max,
            compensation_period=comp_period,
            compensation_currency=comp_currency,
            raw={"board_name": board_name, "id": job.get("id")},
        )
