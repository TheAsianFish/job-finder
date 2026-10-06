"""SmartRecruiters Posting API adapter (documented, public, read-only).

    GET https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=N
    GET https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}

The list carries title/location/date but no description, so early-career
postings get one detail GET each (paced by the shared limiter). An unknown
company identifier answers 200 with `totalFound: 0`, which is reported as a
config error rather than an empty board — a tracked employer with literally
zero postings is far rarer than a mistyped identifier.

adapter_config:
  company: ServiceNow          (required unless derivable from career_urls)
  early_career_only: true
  detail_limit: 200
  max_pages: 20                (100 postings per page)
"""

from __future__ import annotations

import re
from typing import Any

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.adapters.filters import config_int, early_career_only, looks_early_career
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities.dates import parse_datetime

PAGE_SIZE = 100
_URL_RES = [
    re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    re.compile(r"api\.smartrecruiters\.com/v1/companies/([A-Za-z0-9_-]+)"),
]


def extract_company(company: CompanySource) -> str | None:
    identifier = company.adapter_config.get("company") or company.adapter_config.get(
        "company_identifier"
    )
    if identifier:
        return str(identifier)
    for url in company.career_urls:
        for pattern in _URL_RES:
            match = pattern.search(url)
            if match:
                return match.group(1)
    return None


class SmartRecruitersAdapter(BaseAdapter):
    name = "smartrecruiters"

    @staticmethod
    def list_url(identifier: str, offset: int) -> str:
        return (
            f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings"
            f"?limit={PAGE_SIZE}&offset={offset}"
        )

    @staticmethod
    def detail_url(identifier: str, posting_id: str) -> str:
        return f"https://api.smartrecruiters.com/v1/companies/{identifier}/postings/{posting_id}"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        identifier = extract_company(company)
        if not identifier:
            raise AdapterError(
                f"no SmartRecruiters company identifier configured for {company.id}",
                category="config",
            )
        source = f"SmartRecruiters '{identifier}'"
        filter_titles = early_career_only(company)
        max_pages = max(config_int(company, "max_pages", 20), 1)

        postings: list[dict[str, Any]] = []
        offset = 0
        total = 0
        for _ in range(max_pages):
            response = await ctx.get(self.list_url(identifier, offset))
            self.require_status_ok(response, source)
            data = self.parse_json(response, source)
            content = data.get("content") if isinstance(data, dict) else None
            if content is None:
                raise AdapterError(f"{source} response missing 'content'", category="parse")
            total = int(data.get("totalFound") or 0)
            if offset == 0 and total == 0:
                raise AdapterError(
                    f"{source} reports 0 postings — company identifier is likely wrong",
                    category="config",
                )
            for item in content:
                if not filter_titles or looks_early_career(str(item.get("name") or "")):
                    postings.append(item)
            offset += PAGE_SIZE
            if not content or offset >= total:
                break

        detail_limit = config_int(company, "detail_limit", 200)
        jobs: list[RawJob] = []
        fetched = 0
        for item in postings:
            detail: dict[str, Any] = {}
            posting_id = str(item.get("id") or "")
            if posting_id and posting_id not in ctx.known_job_ids and fetched < detail_limit:
                fetched += 1
                response = await ctx.get(self.detail_url(identifier, posting_id))
                if response.status_code < 400:
                    parsed = self.parse_json(response, source)
                    detail = parsed if isinstance(parsed, dict) else {}
            jobs.append(self._to_raw(identifier, item, detail))
        return jobs

    def _to_raw(self, identifier: str, item: dict[str, Any], detail: dict[str, Any]) -> RawJob:
        posting_id = str(item.get("id") or "")
        location = detail.get("location") or item.get("location") or {}
        locations: list[str] = []
        if isinstance(location, dict):
            parts = [
                str(location.get(key)) for key in ("city", "region", "country") if location.get(key)
            ]
            if parts:
                locations.append(", ".join(parts))
            if location.get("remote"):
                locations.append("Remote")
        sections = (detail.get("jobAd") or {}).get("sections") or {}
        html_parts: list[str] = []
        for key in ("jobDescription", "qualifications", "additionalInformation"):
            section = sections.get(key) or {}
            text = section.get("text") if isinstance(section, dict) else None
            if text:
                title = section.get("title")
                if title and key != "jobDescription":
                    html_parts.append(f"<h3>{title}</h3>")
                html_parts.append(str(text))
        posting_url = str(
            detail.get("postingUrl")
            or f"https://jobs.smartrecruiters.com/{identifier}/{posting_id}"
        )
        apply_url = str(detail.get("applyUrl") or posting_url)
        department = item.get("department") or detail.get("department") or {}
        employment = item.get("typeOfEmployment") or detail.get("typeOfEmployment") or {}
        return RawJob(
            source_adapter=self.name,
            source_job_id=posting_id,
            title=str(detail.get("name") or item.get("name") or "").strip(),
            url=posting_url,
            apply_url=apply_url,
            locations=locations,
            department=department.get("label") if isinstance(department, dict) else None,
            employment_type=employment.get("label") if isinstance(employment, dict) else None,
            description_html="\n".join(html_parts) or None,
            posted_at=parse_datetime(item.get("releasedDate") or detail.get("releasedDate")),
            raw={
                "company": identifier,
                "ref_number": item.get("refNumber"),
                "detail_fetched": bool(detail),
            },
        )
