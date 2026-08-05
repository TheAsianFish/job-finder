"""Sitemap and RSS/Atom feed adapter (spec §8.5).

Reads sitemap.xml (including sitemap indexes) or configured feeds, filters
candidate URLs by job-related terms, then extracts JobPosting JSON-LD from a
bounded number of candidate pages. Never crawls recursively beyond that.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import feedparser

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.adapters.jsonld import JsonLdAdapter, parse_jsonld_scripts
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities import robots

_JOB_URL_TERMS = re.compile(
    r"job|jobs|career|careers|position|opening|requisition|vacan", re.IGNORECASE
)
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

DEFAULT_MAX_PAGES = 30
DEFAULT_MAX_SITEMAPS = 5


def parse_sitemap(xml_text: str) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemap_urls) from a sitemap document."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return [], []
    pages: list[str] = []
    children: list[str] = []
    if root.tag == f"{_SITEMAP_NS}sitemapindex":
        for sitemap in root.findall(f"{_SITEMAP_NS}sitemap"):
            loc = sitemap.find(f"{_SITEMAP_NS}loc")
            if loc is not None and loc.text:
                children.append(loc.text.strip())
    elif root.tag == f"{_SITEMAP_NS}urlset":
        for url in root.findall(f"{_SITEMAP_NS}url"):
            loc = url.find(f"{_SITEMAP_NS}loc")
            if loc is not None and loc.text:
                pages.append(loc.text.strip())
    return pages, children


def filter_job_urls(urls: list[str]) -> list[str]:
    return [url for url in urls if _JOB_URL_TERMS.search(url)]


class SitemapAdapter(BaseAdapter):
    name = "sitemap"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        config = company.adapter_config
        sitemap_urls = list(config.get("sitemap_urls") or [])
        feed_urls = list(config.get("feed_urls") or [])
        if not sitemap_urls and not feed_urls and company.domain:
            sitemap_urls = [f"https://{company.domain}/sitemap.xml"]
        if not sitemap_urls and not feed_urls:
            raise AdapterError(
                f"no sitemap/feed URLs configured for {company.id}", category="config"
            )

        max_pages = int(config.get("max_pages", DEFAULT_MAX_PAGES))
        candidate_urls: list[str] = []

        for sitemap_url in sitemap_urls:
            candidate_urls.extend(
                await self._collect_from_sitemap(sitemap_url, ctx, DEFAULT_MAX_SITEMAPS)
            )
        for feed_url in feed_urls:
            candidate_urls.extend(await self._collect_from_feed(feed_url, ctx))

        seen: set[str] = set()
        unique_candidates = []
        for url in candidate_urls:
            if url not in seen:
                seen.add(url)
                unique_candidates.append(url)
        job_urls = filter_job_urls(unique_candidates)[:max_pages]

        if not job_urls:
            return []

        jsonld = JsonLdAdapter()
        jobs: list[RawJob] = []
        for url in job_urls:
            if not await robots.is_allowed(ctx.client, url, ctx.user_agent):
                continue
            response = await ctx.get(url)
            if response.status_code >= 400:
                continue
            for posting in parse_jsonld_scripts(response.text):
                raw = jsonld._to_raw(posting, url)
                if raw is not None:
                    raw.source_adapter = self.name
                    jobs.append(raw)
        return jobs

    async def _collect_from_sitemap(
        self, sitemap_url: str, ctx: AdapterContext, max_depth: int
    ) -> list[str]:
        if max_depth <= 0:
            return []
        if not await robots.is_allowed(ctx.client, sitemap_url, ctx.user_agent):
            return []
        response = await ctx.get(sitemap_url)
        if response.status_code >= 400:
            return []
        pages, children = parse_sitemap(response.text)
        urls = list(pages)
        # Prefer careers-specific child sitemaps; bound total fetches.
        prioritized = sorted(children, key=lambda u: 0 if _JOB_URL_TERMS.search(u) else 1)[
            :max_depth
        ]
        for child in prioritized:
            urls.extend(await self._collect_from_sitemap(child, ctx, max_depth - 1))
        return urls

    async def _collect_from_feed(self, feed_url: str, ctx: AdapterContext) -> list[str]:
        response = await ctx.get(feed_url)
        if response.status_code >= 400:
            return []
        parsed = feedparser.parse(response.text)
        return [entry.get("link", "") for entry in parsed.entries if entry.get("link")]
