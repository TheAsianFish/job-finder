"""Simplify job-list adapter (secondary source, spec §28).

SimplifyJobs publishes its curated lists as structured JSON in public
GitHub repos, regenerated as postings are added and retired:

    https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json
    https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json

raw.githubusercontent.com serves no robots.txt and caches for five minutes,
so polling it every few minutes is both permitted and fresh. One request
returns every listing; the adapter keeps active, visible postings in the
configured categories whose terms are not all in the past.

Each posting names its employer in raw["company_name"]; the scanner maps
it onto a registry company (or a synthetic one) and skips employers the
registry already scans directly. Listings carry no description, so the
adapter writes a short factual one from the list's own fields (terms,
category, degrees, sponsorship) — that is what lets the season parser see
"Summer 2027" and the classifier see "new grad". Nothing is invented: every
sentence restates a field of the listing.

adapter_config:
  url: <listings.json URL>                      (required)
  list_kind: internship | new_grad              (default internship)
  categories: [Software, AI/ML/Data, Quant, ...] (default below)
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.adapters.filters import config_list
from opportunity_radar.matching.season_parser import season_window
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities.dates import parse_datetime, utcnow

DEFAULT_CATEGORIES = [
    "Software",
    "Software Engineering",
    "AI/ML/Data",
    "Data Science, AI & Machine Learning",
    "Quant",
]
_TERM_RE = re.compile(r"(winter|spring|summer|fall|autumn)\s+(20\d{2})", re.IGNORECASE)
# Simplify abbreviates a few big metros; expand them so location scoring and
# the US-workability gate recognise them.
_LOCATION_EXPANSIONS = {
    "SF": "San Francisco, CA",
    "NYC": "New York, NY",
    "LA": "Los Angeles, CA",
    "DC": "Washington, DC",
    "Remote in USA": "Remote (US)",
    "Remote in US": "Remote (US)",
}


def term_is_live(term: str, today: date) -> bool:
    """False only for a parseable 'Season YYYY' whose start window has ended."""
    match = _TERM_RE.search(term or "")
    if not match:
        return True
    _start, end = season_window(match.group(1), int(match.group(2)))
    return end is None or end >= today


class SimplifyAdapter(BaseAdapter):
    name = "simplify"
    secondary = True

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        url = company.adapter_config.get("url")
        if not url:
            raise AdapterError(
                f"no Simplify listings url configured for {company.id}", category="config"
            )
        source = f"Simplify list '{company.id}'"
        response = await ctx.get(str(url), headers={"Accept": "application/json"})
        self.require_status_ok(response, source)
        data = self.parse_json(response, source)
        if not isinstance(data, list):
            raise AdapterError(f"{source} did not return a list", category="parse")
        if data and not isinstance(data[0], dict):
            raise AdapterError(f"{source} entries are not objects", category="parse")

        kind = str(company.adapter_config.get("list_kind") or "internship")
        categories = set(config_list(company, "categories", DEFAULT_CATEGORIES))
        today = utcnow().date()
        jobs: list[RawJob] = []
        for item in data:
            if not item.get("active") or not item.get("is_visible", True):
                continue
            if categories and item.get("category") not in categories:
                continue
            terms = [str(t) for t in item.get("terms") or [] if t]
            if terms and not any(term_is_live(t, today) for t in terms):
                continue
            if not item.get("id") or not item.get("title") or not item.get("url"):
                continue
            jobs.append(self._to_raw(item, kind, terms))
        return jobs

    def _to_raw(self, item: dict[str, Any], kind: str, terms: list[str]) -> RawJob:
        locations = [
            _LOCATION_EXPANSIONS.get(str(loc).strip(), str(loc).strip())
            for loc in item.get("locations") or []
            if loc
        ]
        url = str(item["url"])
        return RawJob(
            source_adapter=self.name,
            source_job_id=str(item["id"]),
            title=str(item["title"]).strip(),
            url=url,
            apply_url=url,
            locations=locations,
            department=item.get("category") or None,
            description_text=self._description(item, kind, terms),
            posted_at=parse_datetime(item.get("date_posted")),
            updated_at=parse_datetime(item.get("date_updated")),
            raw={
                "company_name": str(item.get("company_name") or "").strip(),
                "company_url": item.get("company_url"),
                "list_kind": kind,
                "terms": terms,
                "sponsorship": item.get("sponsorship"),
            },
        )

    @staticmethod
    def _description(item: dict[str, Any], kind: str, terms: list[str]) -> str:
        parts = [
            "New grad position listed on the Simplify New-Grad-Positions list."
            if kind == "new_grad"
            else "Internship listed on the Simplify internships list."
        ]
        live_terms = [t for t in terms if t and t.upper() != "N/A"]
        if live_terms:
            parts.append(f"Terms: {', '.join(live_terms)}.")
        if item.get("category"):
            parts.append(f"Category: {item['category']}.")
        degrees = [str(d) for d in item.get("degrees") or [] if d]
        if degrees:
            parts.append(f"Degrees: {', '.join(degrees)}.")
        sponsorship = str(item.get("sponsorship") or "")
        if sponsorship and sponsorship.lower() != "other":
            parts.append(f"Sponsorship: {sponsorship}.")
        return " ".join(parts)
