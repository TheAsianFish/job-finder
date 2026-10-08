"""Fetch a posting's full description from its apply link.

Roles discovered through the Simplify feed only carry a one-line synthetic
description, which is useless for judging resume fit. Most of their apply
links point at a public ATS whose official job-board API returns the full
posting: Greenhouse, Lever, Ashby, or a Workday tenant. One request each
(Ashby: one per board), the same polite User-Agent as the scanner, and a
plain None when the link is anything else (company career sites).
"""

from __future__ import annotations

import re

import httpx

from opportunity_radar.constants import USER_AGENT_TEMPLATE
from opportunity_radar.utilities.text import html_to_text

_GREENHOUSE_RE = re.compile(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)")
_GREENHOUSE_GH_JID_RE = re.compile(r"[?&]gh_jid=(\d+)")
_LEVER_RE = re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w.-]+)/([0-9a-f-]{36})")
_ASHBY_RE = re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)/([0-9a-f-]{36})")
_WORKDAY_RE = re.compile(
    r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)(/job/[^?#]+)"
)
TIMEOUT = 20.0


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT_TEMPLATE.format(contact=""),
            "Accept": "application/json",
        },
    )


def fetch_description(url: str, client: httpx.Client | None = None) -> str | None:
    """Full plain-text description for a public-ATS apply link, else None."""
    own = client is None
    http = client or _client()
    try:
        return _fetch(url, http)
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    finally:
        if own:
            http.close()


def _fetch(url: str, http: httpx.Client) -> str | None:
    if m := _GREENHOUSE_RE.search(url):
        data = http.get(
            f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}"
        ).json()
        import html

        return html_to_text(html.unescape(data.get("content") or "")) or None
    if m := _LEVER_RE.search(url):
        data = http.get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}").json()
        parts = [data.get("descriptionPlain") or ""]
        for block in data.get("lists") or []:
            parts.append(block.get("text", ""))
            parts.append(html_to_text(block.get("content", "")))
        parts.append(data.get("additionalPlain") or "")
        return "\n".join(p for p in parts if p).strip() or None
    if m := _ASHBY_RE.search(url):
        data = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}").json()
        for job in data.get("jobs") or []:
            if job.get("id") == m.group(2):
                return (
                    job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml")) or None
                )
        return None
    if m := _WORKDAY_RE.search(url):
        tenant, pod, site, path = m.groups()
        data = http.get(
            f"https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}"
        ).json()
        info = data.get("jobPostingInfo") or {}
        return html_to_text(info.get("jobDescription")) or None
    return None
