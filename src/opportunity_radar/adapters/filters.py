"""Shared helpers for adapters that must pre-filter large boards.

Greenhouse/Lever/Ashby return a whole board in one request, so every job is
stored and the normalizer decides relevance. Enterprise ATSes (Workday,
SmartRecruiters, Eightfold, amazon.jobs) expose thousands of postings behind
paginated search endpoints and need a per-job detail request for the
description, so those adapters only pull postings that look early-career.
The check reuses the same title rules the classifier applies downstream, so
nothing an adapter keeps is later judged "not early-career" on title alone.
"""

from __future__ import annotations

from opportunity_radar.matching.title_classifier import classify
from opportunity_radar.models.company import CompanySource


def looks_early_career(title: str) -> bool:
    return classify(title or "").is_early_career


def early_career_only(company: CompanySource) -> bool:
    """Adapters default to early-career filtering; `early_career_only: false`
    in adapter_config pulls the whole board (expensive, rarely wanted)."""
    return bool(company.adapter_config.get("early_career_only", True))


def config_int(company: CompanySource, key: str, default: int) -> int:
    value = company.adapter_config.get(key, default)
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def config_list(company: CompanySource, key: str, default: list[str]) -> list[str]:
    value = company.adapter_config.get(key)
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [v for v in value if v.strip()] or list(default)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return list(default)
