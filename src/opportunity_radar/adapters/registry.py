"""Adapter registry and auto-resolution."""

from __future__ import annotations

import structlog

from opportunity_radar.adapters.ashby import AshbyAdapter, extract_board_name
from opportunity_radar.adapters.base import AdapterContext, AdapterError, BaseAdapter
from opportunity_radar.adapters.greenhouse import GreenhouseAdapter, extract_board_token
from opportunity_radar.adapters.html_generic import HtmlGenericAdapter
from opportunity_radar.adapters.jsonld import JsonLdAdapter
from opportunity_radar.adapters.lever import LeverAdapter, extract_site
from opportunity_radar.adapters.playwright_generic import PlaywrightAdapter
from opportunity_radar.adapters.sitemap import SitemapAdapter
from opportunity_radar.adapters.unsupported import (
    EightfoldAdapter,
    ICIMSAdapter,
    SmartRecruitersAdapter,
    SuccessFactorsAdapter,
    TaleoAdapter,
    WorkdayAdapter,
)
from opportunity_radar.discovery.ats_fingerprint import detect_from_url
from opportunity_radar.models.company import CompanySource

logger = structlog.get_logger(__name__)

_ADAPTERS: dict[str, BaseAdapter] = {
    adapter.name: adapter
    for adapter in [
        GreenhouseAdapter(),
        LeverAdapter(),
        AshbyAdapter(),
        JsonLdAdapter(),
        SitemapAdapter(),
        HtmlGenericAdapter(),
        PlaywrightAdapter(),
        WorkdayAdapter(),
        SmartRecruitersAdapter(),
        ICIMSAdapter(),
        EightfoldAdapter(),
        SuccessFactorsAdapter(),
        TaleoAdapter(),
    ]
}


def get_adapter(name: str) -> BaseAdapter:
    adapter = _ADAPTERS.get(name)
    if adapter is None:
        raise AdapterError(f"unknown adapter '{name}'", category="config")
    return adapter


def available_adapters() -> list[str]:
    return sorted(_ADAPTERS)


def resolve_adapter(company: CompanySource) -> BaseAdapter:
    """Pick the adapter for a company, resolving 'auto' from config and URLs."""
    if company.adapter and company.adapter != "auto":
        return get_adapter(company.adapter)

    # Explicit adapter_config keys win.
    if extract_board_token(company):
        return _ADAPTERS["greenhouse"]
    site, _region = extract_site(company)
    if site:
        return _ADAPTERS["lever"]
    if extract_board_name(company):
        return _ADAPTERS["ashby"]

    # URL fingerprinting.
    for url in company.career_urls:
        result = detect_from_url(url)
        if result is not None:
            adapter = _ADAPTERS.get(result.adapter)
            if adapter is not None:
                # Merge discovered config so the adapter can use the token.
                for key, value in result.config.items():
                    company.adapter_config.setdefault(key, value)
                logger.debug(
                    "adapter_autodetected",
                    company_id=company.id,
                    adapter=result.adapter,
                    evidence=result.evidence,
                )
                return adapter

    # Generic fallbacks.
    if company.adapter_config.get("selectors"):
        return _ADAPTERS["html_generic"]
    if company.adapter_config.get("sitemap_urls") or company.adapter_config.get("feed_urls"):
        return _ADAPTERS["sitemap"]
    if company.career_urls:
        return _ADAPTERS["jsonld"]
    raise AdapterError(
        f"cannot resolve an adapter for '{company.id}': no adapter, tokens, "
        "career_urls, or selectors configured",
        category="config",
    )


async def fetch_with_fallback(
    company: CompanySource, ctx: AdapterContext
) -> tuple[BaseAdapter, list]:
    """Fetch using the resolved adapter; for auto companies, fall back
    jsonld -> sitemap when the primary generic attempt finds nothing."""
    adapter = resolve_adapter(company)
    try:
        jobs = await adapter.fetch_jobs(company, ctx)
    except AdapterError:
        if company.adapter == "auto" and adapter.name == "jsonld" and company.domain:
            sitemap = _ADAPTERS["sitemap"]
            jobs = await sitemap.fetch_jobs(company, ctx)
            return sitemap, jobs
        raise
    if not jobs and company.adapter == "auto" and adapter.name == "jsonld" and company.domain:
        sitemap = _ADAPTERS["sitemap"]
        try:
            sitemap_jobs = await sitemap.fetch_jobs(company, ctx)
        except AdapterError:
            return adapter, jobs
        if sitemap_jobs:
            return sitemap, sitemap_jobs
    return adapter, jobs
