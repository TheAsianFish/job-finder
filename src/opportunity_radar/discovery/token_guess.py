"""Guess public ATS board tokens from a company's own identifiers.

Career pages are usually JavaScript-rendered and embed their ATS in ways the
HTML fingerprint misses, yet the board token is almost always the company's
slug (``xai``, ``waymo``, ``perplexity``) or a close variant. Probing the
three public board APIs with a handful of candidates is cheap (one GET per
candidate, at most ~12 requests) and resolved 30+ silent seeds in one pass.

Only a board that answers 200 with at least one job counts: Greenhouse and
Ashby answer 200 for unknown tokens with empty payloads in some cases, so an
empty board is treated as "no match", never as success.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from opportunity_radar.adapters.base import AdapterContext
from opportunity_radar.discovery.ats_fingerprint import FingerprintResult

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class GuessResult:
    fingerprint: FingerprintResult
    job_count: int


def candidate_tokens(company_id: str, domain: str | None, name: str | None = None) -> list[str]:
    """Ordered, de-duplicated token candidates: id, bare domain, name slug, variants."""
    seen: list[str] = []

    def push(value: str | None) -> None:
        if not value:
            return
        token = value.strip().lower()
        if token and token not in seen:
            seen.append(token)

    push(company_id)
    push(company_id.replace("-", ""))
    if domain:
        bare = domain.lower().split("/")[0]
        bare = re.sub(r"^www\.", "", bare)
        label = bare.split(".")[0]
        push(label)
        push(label.replace("-", ""))
        # x.ai -> xai, together.ai -> togetherai
        push(_SLUG_RE.sub("", bare))
    if name:
        slug = _SLUG_RE.sub("", name.lower())
        push(slug)
        push(_SLUG_RE.sub("-", name.lower()).strip("-"))
    return seen[:6]


def _board_urls(token: str) -> list[tuple[str, str, str]]:
    return [
        ("greenhouse", "board_token", f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"),
        ("ashby", "job_board_name", f"https://api.ashbyhq.com/posting-api/job-board/{token}"),
        ("lever", "site", f"https://api.lever.co/v0/postings/{token}?mode=json"),
    ]


def _count_jobs(adapter: str, payload: object) -> int:
    if adapter == "lever":
        return len(payload) if isinstance(payload, list) else 0
    if isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        return len(payload["jobs"])
    return 0


async def guess_board(
    ctx: AdapterContext,
    company_id: str,
    domain: str | None,
    name: str | None = None,
    *,
    max_candidates: int = 4,
) -> GuessResult | None:
    """Probe public board APIs for likely tokens; first non-empty board wins."""
    for token in candidate_tokens(company_id, domain, name)[:max_candidates]:
        for adapter, config_key, url in _board_urls(token):
            try:
                response = await ctx.get(url, headers={"Accept": "application/json"})
            except Exception:
                continue
            if response.status_code != 200:
                continue
            try:
                payload = response.json()
            except ValueError:
                continue
            count = _count_jobs(adapter, payload)
            if count > 0:
                return GuessResult(
                    fingerprint=FingerprintResult(
                        adapter=adapter,
                        config={config_key: token},
                        evidence=f"token guess: {url} ({count} jobs)",
                    ),
                    job_count=count,
                )
    return None
