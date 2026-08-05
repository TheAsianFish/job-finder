"""robots.txt checks for generic page crawling.

Official/public ATS APIs (Greenhouse, Lever, Ashby) are polled directly; robots
checks apply to generic HTML/sitemap crawling of employer pages. robots.txt is a
crawler preference mechanism, not authorization — we honor it and also keep
request volume minimal regardless (spec §3, §21).
"""

from __future__ import annotations

import urllib.robotparser
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger(__name__)

_CACHE: dict[str, urllib.robotparser.RobotFileParser | None] = {}


async def is_allowed(client: httpx.AsyncClient, url: str, user_agent: str) -> bool:
    """Return False only when robots.txt explicitly disallows this URL.

    Network failures fetching robots.txt fail open (allowed) but are logged;
    a 401/403 on robots.txt fails closed per RFC 9309 guidance.
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in _CACHE:
        robots_url = f"{origin}/robots.txt"
        parser = urllib.robotparser.RobotFileParser()
        try:
            response = await client.get(robots_url, timeout=15.0)
        except httpx.HTTPError as exc:
            logger.debug("robots_fetch_failed", url=robots_url, error=str(exc))
            _CACHE[origin] = None
            return True
        if response.status_code in (401, 403):
            parser.parse(["User-agent: *", "Disallow: /"])
            _CACHE[origin] = parser
        elif response.status_code >= 400:
            _CACHE[origin] = None
            return True
        else:
            parser.parse(response.text.splitlines())
            _CACHE[origin] = parser
    cached = _CACHE[origin]
    if cached is None:
        return True
    return cached.can_fetch(user_agent, url)


def clear_cache() -> None:
    _CACHE.clear()
