"""Generic configurable HTML adapter (spec §8.6).

Selector configuration in companies.yaml:

    adapter: html_generic
    adapter_config:
      list_url: https://example.com/careers
      selectors:
        card: ".job-card"
        title: ".job-card__title"
        location: ".job-card__location"
        url: "a@href"
      pagination:
        param: page          # ?page=2 style
        max_pages: 5
      fetch_details: false   # fetch each job page for its description

The "sel@attr" syntax reads an attribute instead of text.
"""

from __future__ import annotations

from bs4 import BeautifulSoup
from bs4.element import Tag

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities import robots
from opportunity_radar.utilities.hashing import _sha256
from opportunity_radar.utilities.text import html_to_text, normalize_whitespace
from opportunity_radar.utilities.urls import absolutize


def _select_value(card: Tag, selector: str) -> str | None:
    """Resolve 'css@attr' or plain 'css' selectors against a card element."""
    if "@" in selector:
        css, attr = selector.rsplit("@", 1)
        element = card.select_one(css.strip()) if css.strip() else card
        if element is None:
            return None
        value = element.get(attr.strip())
        if isinstance(value, list):
            value = value[0] if value else None
        return str(value) if value else None
    element = card.select_one(selector)
    return normalize_whitespace(element.get_text()) if element else None


class HtmlGenericAdapter(BaseAdapter):
    name = "html_generic"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        config = company.adapter_config
        list_url = config.get("list_url") or (
            company.career_urls[0] if company.career_urls else None
        )
        selectors = config.get("selectors") or {}
        if not list_url or not selectors.get("card"):
            raise AdapterError(
                f"html_generic for {company.id} needs list_url and selectors.card",
                category="config",
            )
        pagination = config.get("pagination") or {}
        max_pages = int(pagination.get("max_pages", 1))
        page_param = pagination.get("param")
        fetch_details = bool(config.get("fetch_details", False))

        jobs: list[RawJob] = []
        pages_fetched = 0
        for page in range(1, max_pages + 1):
            url = list_url
            if page_param and page > 1:
                joiner = "&" if "?" in list_url else "?"
                url = f"{list_url}{joiner}{page_param}={page}"
            if not await robots.is_allowed(ctx.client, url, ctx.user_agent):
                raise AdapterError(
                    f"robots.txt disallows {url}", category="robots", retryable=False
                )
            response = await ctx.get(url)
            self.require_status_ok(response, f"career page {url}")
            pages_fetched += 1
            page_jobs = self._parse_page(response.text, url, selectors)
            if not page_jobs:
                break
            jobs.extend(page_jobs)

        if pages_fetched > 0 and not jobs:
            soup_check = config.get("allow_empty", False)
            if not soup_check:
                # Distinguish "no jobs" from "selectors broken": if the card
                # selector matches nothing on a 200 page, treat as degraded.
                raise AdapterError(
                    f"card selector '{selectors['card']}' matched nothing on {list_url} — "
                    "adapter may be degraded (set adapter_config.allow_empty: true to accept)",
                    category="parse",
                    retryable=False,
                )

        if fetch_details:
            for job in jobs:
                await self._fill_details(job, ctx)
        return jobs

    def _parse_page(self, html: str, page_url: str, selectors: dict[str, str]) -> list[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        jobs: list[RawJob] = []
        for card in soup.select(selectors["card"]):
            title = (
                _select_value(card, selectors.get("title", ""))
                if selectors.get("title")
                else normalize_whitespace(card.get_text())
            )
            href = _select_value(card, selectors.get("url", "a@href"))
            if not title or not href:
                continue
            job_url = absolutize(page_url, href)
            location = (
                _select_value(card, selectors["location"]) if selectors.get("location") else None
            )
            jobs.append(
                RawJob(
                    source_adapter=self.name,
                    source_job_id=_sha256(f"html|{job_url}")[:16],
                    title=title,
                    url=job_url,
                    apply_url=job_url,
                    locations=[location] if location else [],
                    raw={"page_url": page_url},
                )
            )
        return jobs

    async def _fill_details(self, job: RawJob, ctx: AdapterContext) -> None:
        if not await robots.is_allowed(ctx.client, job.url, ctx.user_agent):
            return
        response = await ctx.get(job.url)
        if response.status_code >= 400:
            return
        job.description_html = response.text[:500_000]
        job.description_text = html_to_text(response.text)[:100_000]
