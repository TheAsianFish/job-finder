"""Playwright fallback adapter (spec §8.7). Last resort only.

Used when a page is JavaScript-rendered and no API, JSON-LD, feed, sitemap,
or stable HTML path exists. Requirements honored here:
- Chromium only, fresh isolated context per fetch
- images/fonts/media blocked
- waits for a configured selector, hard timeout
- one page per domain at a time (upstream limiter enforces per-domain serialization)
- never attempts CAPTCHA solving or login

Playwright is an optional dependency: install with
    uv sync --extra browser && uv run playwright install chromium
"""

from __future__ import annotations

from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.adapters.html_generic import HtmlGenericAdapter
from opportunity_radar.adapters.jsonld import JsonLdAdapter, parse_jsonld_scripts
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import RawJob
from opportunity_radar.utilities import robots

_BLOCKED_RESOURCES = {"image", "font", "media", "stylesheet"}


class PlaywrightAdapter(BaseAdapter):
    name = "playwright"

    async def fetch_jobs(self, company: CompanySource, ctx: AdapterContext) -> list[RawJob]:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AdapterError(
                "Playwright is not installed. Run: uv sync --extra browser && "
                "uv run playwright install chromium",
                category="config",
            ) from exc

        config = company.adapter_config
        url = config.get("list_url") or (company.career_urls[0] if company.career_urls else None)
        if not url:
            raise AdapterError(
                f"no URL configured for Playwright fetch of {company.id}",
                category="config",
            )
        if not await robots.is_allowed(ctx.client, url, ctx.user_agent):
            raise AdapterError(f"robots.txt disallows {url}", category="robots")

        wait_selector = config.get("wait_selector")
        timeout_ms = int(config.get("timeout_ms", 30_000))

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=ctx.user_agent)
                page = await context.new_page()
                await page.route(
                    "**/*",
                    lambda route: (
                        route.abort()
                        if route.request.resource_type in _BLOCKED_RESOURCES
                        else route.continue_()
                    ),
                )
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                if wait_selector:
                    await page.wait_for_selector(wait_selector, timeout=timeout_ms)
                html = await page.content()
            finally:
                await browser.close()

        # Prefer structured data if the rendered page embeds it.
        postings = parse_jsonld_scripts(html)
        if postings:
            jsonld = JsonLdAdapter()
            jobs = []
            for posting in postings:
                raw = jsonld._to_raw(posting, url)
                if raw is not None:
                    raw.source_adapter = self.name
                    jobs.append(raw)
            return jobs

        selectors = config.get("selectors") or {}
        if selectors.get("card"):
            html_adapter = HtmlGenericAdapter()
            jobs = html_adapter._parse_page(html, url, selectors)
            for job in jobs:
                job.source_adapter = self.name
            return jobs

        raise AdapterError(
            f"rendered page for {company.id} had no JSON-LD and no selectors configured",
            category="config",
        )
