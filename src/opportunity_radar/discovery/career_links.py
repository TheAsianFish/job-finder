"""Career-page discovery for `opportunity-radar companies discover`.

Given a company domain, fetch the homepage (robots permitting), look for
career/jobs links, and fingerprint them for a known ATS. No paid search API
required; if SEARCH_API_KEY is configured it could be added later behind a
feature flag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from opportunity_radar.adapters.base import AdapterContext
from opportunity_radar.discovery.ats_fingerprint import FingerprintResult, detect
from opportunity_radar.utilities import robots
from opportunity_radar.utilities.urls import absolutize

_CAREER_LINK_RE = re.compile(r"career|jobs|join[\s\-]?us|work[\s\-]?with|hiring", re.IGNORECASE)
_COMMON_PATHS = ["/careers", "/jobs", "/careers/jobs", "/company/careers", "/about/careers"]


@dataclass
class DiscoveryResult:
    career_urls: list[str] = field(default_factory=list)
    fingerprint: FingerprintResult | None = None
    notes: list[str] = field(default_factory=list)


async def discover(domain: str, ctx: AdapterContext) -> DiscoveryResult:
    result = DiscoveryResult()
    base = f"https://{domain}"

    homepage_html = ""
    if await robots.is_allowed(ctx.client, base, ctx.user_agent):
        try:
            response = await ctx.get(base)
            if response.status_code < 400:
                homepage_html = response.text
        except Exception as exc:
            result.notes.append(f"homepage fetch failed: {exc}")
    else:
        result.notes.append("robots.txt disallows homepage fetch")

    candidates: list[str] = []
    if homepage_html:
        soup = BeautifulSoup(homepage_html, "lxml")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            label = anchor.get_text() or ""
            if _CAREER_LINK_RE.search(href) or _CAREER_LINK_RE.search(label):
                candidates.append(absolutize(base, href))
        # Direct ATS fingerprint from the homepage itself.
        fingerprint = detect(base, homepage_html)
        if fingerprint:
            result.fingerprint = fingerprint

    for path in _COMMON_PATHS:
        candidates.append(f"{base}{path}")

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        fingerprint = detect(candidate)
        if fingerprint and result.fingerprint is None:
            result.fingerprint = fingerprint
        if len(result.career_urls) < 5:
            result.career_urls.append(candidate)

    # Probe the most promising career pages for embedded ATS boards.
    if result.fingerprint is None:
        for candidate in result.career_urls[:3]:
            if not await robots.is_allowed(ctx.client, candidate, ctx.user_agent):
                continue
            try:
                response = await ctx.get(candidate)
            except Exception:
                continue
            if response.status_code >= 400:
                continue
            fingerprint = detect(candidate, response.text)
            if fingerprint:
                result.fingerprint = fingerprint
                break
    return result
