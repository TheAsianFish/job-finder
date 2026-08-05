"""Placeholder adapters for ATS platforms without stable public APIs (spec §8.8).

Workday, SmartRecruiters, iCIMS, Eightfold, SAP SuccessFactors, and Taleo do
not expose documented public job-board APIs suitable for polling, and their
internal endpoints change without notice. Rather than build on undocumented
endpoints, these adapters fail with a clear explanation and pointers.

If a specific company's site turns out to expose stable structured data,
configure it with `adapter: jsonld`, `adapter: sitemap`, `adapter:
html_generic`, or (last resort) `adapter: playwright` instead — see
docs in README "Adding a company".
"""

from __future__ import annotations

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob

_GUIDANCE = (
    "has no stable public job-board API. Options: (1) point career_urls at a "
    "page with JobPosting JSON-LD and use adapter: jsonld; (2) use adapter: "
    "sitemap; (3) configure CSS selectors with adapter: html_generic; (4) use "
    "adapter: playwright as a last resort."
)


class _UnsupportedAdapter(BaseAdapter):
    platform = "unknown"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        raise AdapterError(f"{self.platform} {_GUIDANCE}", category="unsupported", retryable=False)


class WorkdayAdapter(_UnsupportedAdapter):
    name = "workday"
    platform = "Workday"


class SmartRecruitersAdapter(_UnsupportedAdapter):
    name = "smartrecruiters"
    platform = "SmartRecruiters"


class ICIMSAdapter(_UnsupportedAdapter):
    name = "icims"
    platform = "iCIMS"


class EightfoldAdapter(_UnsupportedAdapter):
    name = "eightfold"
    platform = "Eightfold"


class SuccessFactorsAdapter(_UnsupportedAdapter):
    name = "successfactors"
    platform = "SAP SuccessFactors"


class TaleoAdapter(_UnsupportedAdapter):
    name = "taleo"
    platform = "Taleo"
