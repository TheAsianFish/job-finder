"""Draft tool: find pollable ATS boards for YC companies currently hiring.

Part of the draft proposal in docs/proposals/yc-spring-radar.md — this is
NOT wired into the pipeline. It emits draft registry entries (enabled: false)
to a review file; nothing is auto-registered and nothing scans until a human
pastes entries into config/companies.yaml and enables them.

Data source: yc-oss/api public JSON (daily dump of YC's directory), one GET.
Discovery reuses the repo's robots-respecting career_links.discover().

Usage:
    uv run python scripts/yc_discover.py --limit 15
    uv run python scripts/yc_discover.py --limit 100 --min-team 10 \
        --out data/yc_candidates.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from opportunity_radar.adapters.base import AdapterContext
from opportunity_radar.config import config_dir, load_settings
from opportunity_radar.discovery.career_links import discover
from opportunity_radar.utilities.rate_limit import RateLimiter, build_user_agent

HIRING_URL = "https://yc-oss.github.io/api/companies/hiring.json"

# Substring match against industry + industries + tags, case-insensitive.
SOFTWARE_HINTS = [
    "software",
    "developer",
    "artificial intelligence",
    "machine learning",
    "infrastructure",
    "data",
    "security",
    "fintech",
    "finance",
    "b2b",
    "saas",
    "engineering",
    "analytics",
    "api",
    "open source",
    "robotic",
]

POLLABLE_ADAPTERS = {"greenhouse", "lever", "ashby"}


def _software_ish(company: dict) -> bool:
    haystack = " | ".join(
        [company.get("industry") or ""]
        + (company.get("industries") or [])
        + (company.get("tags") or [])
    ).lower()
    return any(hint in haystack for hint in SOFTWARE_HINTS)


def _us_based(company: dict) -> bool:
    regions = " | ".join(company.get("regions") or [])
    return "United States" in regions or "America" in regions


def _domain(company: dict) -> str | None:
    website = company.get("website") or ""
    host = urlparse(website).netloc.lower().removeprefix("www.")
    return host or None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_candidates(min_team: int, existing_domains: set[str]) -> list[dict]:
    response = httpx.get(HIRING_URL, timeout=30, follow_redirects=True)
    response.raise_for_status()
    companies = response.json()
    picked = []
    for company in companies:
        domain = _domain(company)
        if not domain or domain in existing_domains:
            continue
        if not _us_based(company) or not _software_ish(company):
            continue
        if (company.get("team_size") or 0) < min_team and not company.get("top_company"):
            continue
        picked.append(company)
    # Highest-signal first: YC "top companies", then bigger teams.
    picked.sort(key=lambda c: (not c.get("top_company"), -(c.get("team_size") or 0)))
    return picked


async def fingerprint_all(companies: list[dict], concurrency: int = 2) -> list[dict]:
    settings = load_settings()
    limiter = RateLimiter(max_global=concurrency, min_domain_interval=1.0)
    semaphore = asyncio.Semaphore(concurrency)
    entries: list[dict] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        ctx = AdapterContext(
            client=client,
            limiter=limiter,
            user_agent=build_user_agent(settings.contact),
            timeout=20.0,
            retries=1,
            backoff_seconds=(2.0,),
        )

        async def probe(company: dict) -> None:
            domain = _domain(company)
            assert domain is not None
            async with semaphore:
                try:
                    result = await discover(domain, ctx)
                except Exception as exc:  # keep the sweep going
                    print(f"  {domain}: discovery failed ({exc})")
                    return
            fp = result.fingerprint
            status = f"{fp.adapter} {fp.config}" if fp else "no pollable ATS found"
            print(f"  {company['name']:<28} {domain:<28} -> {status}")
            if fp is None or fp.adapter not in POLLABLE_ADAPTERS:
                return
            batch_tag = re.sub(r"[^a-z0-9]+", "", (company.get("batch") or "").lower())
            entries.append(
                {
                    "id": _slug(company["name"]),
                    "name": company["name"],
                    "domain": domain,
                    "tier": "exploratory",
                    "adapter": fp.adapter,
                    "adapter_config": fp.config,
                    "career_urls": result.career_urls[:2],
                    "tags": ["yc"] + ([f"yc-{batch_tag}"] if batch_tag else []),
                    "enabled": False,
                    "notes": (
                        f"YC {company.get('batch', '?')}, team ~{company.get('team_size', '?')}"
                        f" — auto-discovered draft ({company.get('one_liner', '')[:60]})."
                        " Validate with `companies validate` before enabling."
                    ),
                }
            )

        await asyncio.gather(*(probe(c) for c in companies))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=15, help="max companies to probe")
    parser.add_argument("--min-team", type=int, default=10, help="min team size")
    parser.add_argument("--out", default="data/yc_candidates.yaml", help="output draft file")
    args = parser.parse_args()

    with (config_dir() / "companies.yaml").open() as handle:
        registry = yaml.safe_load(handle)["companies"]
    existing = {c.get("domain", "").lower().removeprefix("www.") for c in registry}

    candidates = load_candidates(args.min_team, existing)
    print(f"{len(candidates)} YC hiring companies pass filters; probing first {args.limit}\n")
    entries = asyncio.run(fingerprint_all(candidates[: args.limit]))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "# DRAFT registry entries from scripts/yc_discover.py — review, then\n"
        "# paste chosen entries into config/companies.yaml and set enabled: true.\n"
        + yaml.safe_dump({"companies": entries}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(f"\n{len(entries)} pollable draft entr{'y' if len(entries) == 1 else 'ies'}")
    print(f"written to {out_path} (draft — nothing registered)")


if __name__ == "__main__":
    main()
