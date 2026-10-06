"""robots.txt checks for generic page crawling.

Official/public ATS APIs (Greenhouse, Lever, Ashby, SmartRecruiters) are
polled directly; robots checks apply to crawling employer-hosted pages and
site-specific JSON (Workday, Eightfold, amazon.jobs, ...). robots.txt is a
crawler preference mechanism, not authorization — we honor it and also keep
request volume minimal regardless (spec §3, §21).

Matching follows RFC 9309: the most specific (longest) matching rule wins,
and Allow beats Disallow on equal length. The stdlib parser applies rules in
file order instead, which wrongly blocks the common
"Disallow: / … Allow: /api/apply" pattern career sites use to expose their
own job JSON.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, path pattern)


class RobotsRules:
    """Minimal RFC 9309 matcher for one origin."""

    def __init__(self, groups: list[_Group]) -> None:
        self._groups = groups

    @classmethod
    def parse(cls, text: str) -> RobotsRules:
        groups: list[_Group] = []
        current: _Group | None = None
        expecting_agents = False
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if current is None or not expecting_agents:
                    current = _Group()
                    groups.append(current)
                current.agents.append(value.lower())
                expecting_agents = True
            elif key in ("allow", "disallow"):
                if current is None:
                    continue
                expecting_agents = False
                if value:
                    current.rules.append((key == "allow", value))
                elif key == "disallow":
                    # "Disallow:" (empty) means allow everything — no rule needed.
                    pass
            else:
                expecting_agents = False
        return cls(groups)

    @staticmethod
    def disallow_all() -> RobotsRules:
        return RobotsRules([_Group(agents=["*"], rules=[(False, "/")])])

    def _group_for(self, user_agent: str) -> _Group | None:
        token = user_agent.split("/", 1)[0].strip().lower()
        best: _Group | None = None
        best_len = -1
        for group in self._groups:
            for agent in group.agents:
                if agent == "*":
                    if best is None and best_len < 0:
                        best = group
                elif agent in token and len(agent) > best_len:
                    best, best_len = group, len(agent)
        return best

    def can_fetch(self, user_agent: str, url: str) -> bool:
        group = self._group_for(user_agent)
        if group is None:
            return True
        parsed = urlparse(url)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        winner: tuple[int, bool] | None = None  # (specificity, allow)
        for allow, pattern in group.rules:
            if not _matches(pattern, path):
                continue
            specificity = len(pattern)
            if (
                winner is None
                or specificity > winner[0]
                or (specificity == winner[0] and allow and not winner[1])
            ):
                winner = (specificity, allow)
        return True if winner is None else winner[1]


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    regex = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.match(regex + ("$" if anchored else ""), path) is not None


_CACHE: dict[str, RobotsRules | None] = {}


async def is_allowed(client: httpx.AsyncClient, url: str, user_agent: str) -> bool:
    """Return False only when robots.txt explicitly disallows this URL.

    Network failures fetching robots.txt fail open (allowed) but are logged;
    a 401/403 on robots.txt fails closed per RFC 9309 guidance.
    """
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in _CACHE:
        robots_url = f"{origin}/robots.txt"
        try:
            response = await client.get(robots_url, timeout=15.0)
        except httpx.HTTPError as exc:
            logger.debug("robots_fetch_failed", url=robots_url, error=str(exc))
            _CACHE[origin] = None
            return True
        if response.status_code in (401, 403):
            _CACHE[origin] = RobotsRules.disallow_all()
        elif response.status_code >= 400:
            _CACHE[origin] = None
            return True
        else:
            _CACHE[origin] = RobotsRules.parse(response.text)
    cached = _CACHE[origin]
    if cached is None:
        return True
    return cached.can_fetch(user_agent, url)


def clear_cache() -> None:
    _CACHE.clear()
