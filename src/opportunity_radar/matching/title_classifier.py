"""Title and role-family classification (spec §10).

Rules live in config/title_rules.yaml so they are editable without code
changes; built-in defaults ship in the repo copy of that file. Matching is
case-insensitive on word boundaries, with hyphen/space flexibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from opportunity_radar.config import config_dir

# Order matters: more specific families are checked before general_swe.
_FAMILY_ORDER = [
    "quant_developer",
    "ml_systems",
    "data_infrastructure",
    "developer_tools",
    "infrastructure",
    "security",
    "robotics",
    "embedded",
    "backend",
    "frontend",
    "fullstack",
    "research_engineering",
    "general_swe",
]


@dataclass
class TitleClassification:
    is_software: bool = False
    is_early_career: bool = False
    role_family: str = "irrelevant"
    seniority: str | None = None
    hard_excluded: bool = False
    exclusion_reason: str | None = None
    downrank_flags: list[str] = field(default_factory=list)
    matched_signals: list[str] = field(default_factory=list)


def _term_to_regex(term: str) -> re.Pattern[str]:
    """Word-boundary regex where spaces/hyphens in the term are interchangeable."""
    parts = re.split(r"[\s\-]+", term.strip().lower())
    flexible = r"[\s\-]+".join(re.escape(part) for part in parts if part)
    return re.compile(rf"(?<![a-z0-9]){flexible}(?![a-z0-9])", re.IGNORECASE)


class _Rules:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.positive_titles = [_term_to_regex(t) for t in raw.get("positive_titles", [])]
        self.early_career = [_term_to_regex(t) for t in raw.get("early_career_signals", [])]
        self.hard_exclusions = [(t, _term_to_regex(t)) for t in raw.get("hard_exclusions", [])]
        self.description_exclusions = [
            (t, _term_to_regex(t)) for t in raw.get("description_exclusions", [])
        ]
        self.non_software = [(t, _term_to_regex(t)) for t in raw.get("non_software_signals", [])]
        self.role_families: dict[str, list[re.Pattern[str]]] = {
            family: [_term_to_regex(t) for t in terms]
            for family, terms in raw.get("role_families", {}).items()
        }


_DEFAULT_RULES_PATH = Path(__file__).resolve().parents[3] / "config" / "title_rules.yaml"


@lru_cache(maxsize=1)
def load_rules(path: str | None = None) -> _Rules:
    candidates = [
        Path(path) if path else None,
        config_dir() / "title_rules.yaml",
        _DEFAULT_RULES_PATH,
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            with candidate.open("r", encoding="utf-8") as handle:
                return _Rules(yaml.safe_load(handle) or {})
    return _Rules({})


def _any_match(patterns: list[re.Pattern[str]], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def _first_match(patterns: list[tuple[str, re.Pattern[str]]], text: str) -> str | None:
    for term, pattern in patterns:
        if pattern.search(text):
            return term
    return None


def classify(title: str, description: str = "") -> TitleClassification:
    rules = load_rules()
    result = TitleClassification()
    title_text = title or ""
    desc_text = description or ""
    combined = f"{title_text}\n{desc_text}"

    early_in_title = _any_match(rules.early_career, title_text)
    early_in_desc = _any_match(rules.early_career, desc_text)
    result.is_early_career = early_in_title or early_in_desc
    if early_in_title:
        result.matched_signals.append("early_career_title")
    elif early_in_desc:
        result.matched_signals.append("early_career_description")

    # Hard exclusion applies only on the title, and never overrides an explicit
    # intern/new-grad signal in the title (spec: exclude only with high confidence).
    excluded_term = _first_match(rules.hard_exclusions, title_text)
    if excluded_term and not early_in_title:
        result.hard_excluded = True
        result.exclusion_reason = f"title matches exclusion pattern '{excluded_term}'"
        result.seniority = (
            "senior_plus"
            if excluded_term
            in {
                "senior",
                "sr.",
                "staff",
                "principal",
                "lead",
                "manager",
                "director",
                "vp",
                "head of",
                "architect",
                "distinguished",
                "fellow",
            }
            else None
        )

    desc_excluded = _first_match(rules.description_exclusions, desc_text)
    if desc_excluded:
        result.downrank_flags.append(f"description_exclusion:{desc_excluded}")

    positive = _any_match(rules.positive_titles, title_text)
    non_software_term = _first_match(rules.non_software, title_text)

    # Role family: title matches are authoritative; description matches are a fallback.
    family = None
    for candidate in _FAMILY_ORDER:
        if _any_match(rules.role_families.get(candidate, []), title_text):
            family = candidate
            break
    if family is None:
        for candidate in _FAMILY_ORDER:
            if _any_match(rules.role_families.get(candidate, []), combined):
                family = candidate
                break

    if non_software_term and not positive and family is None:
        result.role_family = "irrelevant"
        result.is_software = False
        result.matched_signals.append(f"non_software:{non_software_term}")
        return result

    if family is not None:
        result.role_family = family
        result.is_software = True
    elif positive:
        result.role_family = "general_swe"
        result.is_software = True
    elif result.is_early_career and re.search(
        r"(?<![a-z])(engineer|engineering|developer|software|technology)(?![a-z])",
        title_text,
        re.IGNORECASE,
    ):
        # e.g. "Engineering Intern" without a specific family keyword.
        result.role_family = "general_swe"
        result.is_software = True
    else:
        result.role_family = "adjacent" if positive or result.is_early_career else "irrelevant"

    if result.seniority is None:
        result.seniority = "early_career" if result.is_early_career else None
    return result


def clear_rules_cache() -> None:
    load_rules.cache_clear()
