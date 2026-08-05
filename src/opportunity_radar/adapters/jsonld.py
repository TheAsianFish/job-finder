"""Generic JobPosting JSON-LD adapter (spec §8.4).

Parses <script type="application/ld+json"> blocks from configured career
pages. Accepts single objects, arrays, @graph containers, and nested
JobPosting entities. Source values are preserved as-is; nothing is invented.
Respects robots.txt for these generic page fetches.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from bs4 import BeautifulSoup

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities import robots
from opportunity_radar.utilities.dates import parse_datetime
from opportunity_radar.utilities.hashing import _sha256
from opportunity_radar.utilities.text import html_to_text
from opportunity_radar.utilities.urls import absolutize


def extract_jobpostings(data: Any) -> list[dict[str, Any]]:
    """Recursively find every JobPosting object in a parsed JSON-LD payload."""
    found: list[dict[str, Any]] = []
    if isinstance(data, list):
        for item in data:
            found.extend(extract_jobpostings(item))
    elif isinstance(data, dict):
        node_type = data.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(t).lower() == "jobposting" for t in types if t):
            found.append(data)
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in data:
                found.extend(extract_jobpostings(data[key]))
    return found


def parse_jsonld_scripts(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    postings: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or script.get_text()
        if not text or not text.strip():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue  # tolerate one malformed block; others may be fine
        postings.extend(extract_jobpostings(data))
    return postings


def _locations_from(posting: dict[str, Any]) -> list[str]:
    locations: list[str] = []
    job_location = posting.get("jobLocation")
    entries = job_location if isinstance(job_location, list) else [job_location]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        address = entry.get("address")
        if isinstance(address, dict):
            parts = [
                str(address.get(key, "")).strip()
                for key in ("addressLocality", "addressRegion", "addressCountry")
            ]
            joined = ", ".join(part for part in parts if part)
            if joined:
                locations.append(joined)
        elif isinstance(address, str) and address.strip():
            locations.append(address.strip())
        elif entry.get("name"):
            locations.append(str(entry["name"]))
    return locations


def _salary_from(
    posting: dict[str, Any],
) -> tuple[Decimal | None, Decimal | None, str | None, str | None]:
    base = posting.get("baseSalary")
    if not isinstance(base, dict):
        return None, None, None, None
    currency = base.get("currency")
    value = base.get("value")
    if isinstance(value, dict):
        try:
            min_value = Decimal(str(value["minValue"])) if value.get("minValue") else None
            max_value = Decimal(str(value["maxValue"])) if value.get("maxValue") else None
            single = Decimal(str(value["value"])) if value.get("value") else None
        except (InvalidOperation, ValueError):
            return None, None, None, currency
        unit = str(value.get("unitText") or "").lower() or None
        if single is not None and min_value is None:
            min_value = max_value = single
        return min_value, max_value, unit, currency
    return None, None, None, currency


class JsonLdAdapter(BaseAdapter):
    name = "jsonld"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        urls = list(company.adapter_config.get("urls") or company.career_urls)
        if not urls:
            raise AdapterError(
                f"no career URLs configured for JSON-LD scan of {company.id}",
                category="config",
            )
        jobs: list[RawJob] = []
        fetched_any = False
        errors: list[str] = []
        for url in urls:
            if not await robots.is_allowed(ctx.client, url, ctx.user_agent):
                errors.append(f"robots.txt disallows {url}")
                continue
            response = await ctx.get(url)
            if response.status_code >= 400:
                errors.append(f"HTTP {response.status_code} for {url}")
                continue
            fetched_any = True
            for posting in parse_jsonld_scripts(response.text):
                raw = self._to_raw(posting, url)
                if raw is not None:
                    jobs.append(raw)
        if not fetched_any:
            raise AdapterError(
                f"all JSON-LD pages failed for {company.id}: {'; '.join(errors) or 'no URLs'}",
                category="http" if errors else "config",
                retryable=bool(errors),
            )
        return jobs

    def _to_raw(self, posting: dict[str, Any], page_url: str) -> RawJob | None:
        title = str(posting.get("title") or "").strip()
        if not title:
            return None

        raw_url = posting.get("url") or posting.get("sameAs") or ""
        apply_url = absolutize(page_url, str(raw_url)) if raw_url else page_url

        identifier = posting.get("identifier")
        if isinstance(identifier, dict):
            source_id = str(identifier.get("value") or "")
        elif identifier:
            source_id = str(identifier)
        else:
            source_id = ""
        if not source_id:
            # Stable fallback identity: apply URL, or title+location fingerprint.
            source_id = _sha256(f"jsonld|{apply_url}|{title}")[:16]

        description_html = posting.get("description") or None
        remote_hint = None
        if str(posting.get("jobLocationType") or "").upper() == "TELECOMMUTE":
            remote_hint = "remote"

        employment = posting.get("employmentType")
        if isinstance(employment, list):
            employment = ", ".join(str(e) for e in employment)

        organization = posting.get("hiringOrganization")
        org_name = None
        if isinstance(organization, dict):
            org_name = organization.get("name")

        comp_min, comp_max, comp_period, comp_currency = _salary_from(posting)

        return RawJob(
            source_adapter=self.name,
            source_job_id=source_id,
            title=title,
            url=apply_url,
            apply_url=apply_url,
            locations=_locations_from(posting),
            employment_type=str(employment) if employment else None,
            description_html=str(description_html) if description_html else None,
            description_text=html_to_text(str(description_html)) if description_html else None,
            posted_at=parse_datetime(posting.get("datePosted")),
            valid_through=parse_datetime(posting.get("validThrough")),
            remote_hint=remote_hint,  # type: ignore[arg-type]
            compensation_min=comp_min,
            compensation_max=comp_max,
            compensation_period=comp_period,
            compensation_currency=comp_currency,
            raw={"page_url": page_url, "hiring_organization": org_name},
        )
