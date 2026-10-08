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
    """Word-boundary regex where spaces/hyphens in the term are interchangeable.

    'engineer' also matches its gerund: boards title the same discipline both
    ways ('Civil Engineer Intern' / 'Civil Engineering Internship'), and a
    signal that misses one form silently misclassifies the role.
    """
    parts = re.split(r"[\s\-]+", term.strip().lower())
    pieces = []
    for part in parts:
        if not part:
            continue
        escaped = re.escape(part)
        if part == "engineer":
            escaped += "(?:ing)?"
        pieces.append(escaped)
    flexible = r"[\s\-]+".join(pieces)
    return re.compile(rf"(?<![a-z0-9]){flexible}(?![a-z0-9])", re.IGNORECASE)


@dataclass(frozen=True)
class _Term:
    """A rule term plus a cheap literal pre-check.

    Running ~150 word-boundary regexes over every multi-kilobyte description
    dominated scan CPU time. Any match of the regex contains the term's
    longest word (case-insensitively; "engineer" is also inside
    "engineering"), so a plain substring test on the lowered text skips the
    regex whenever the word is absent — identical results, a fraction of the
    work.
    """

    term: str
    literal: str
    pattern: re.Pattern[str]

    def search(self, text: str, lowered: str) -> bool:
        return self.literal in lowered and self.pattern.search(text) is not None


def _term(term: str) -> _Term:
    parts = [part for part in re.split(r"[\s\-]+", term.strip().lower()) if part]
    literal = max(parts, key=len) if parts else ""
    return _Term(term=term, literal=literal, pattern=_term_to_regex(term))


class _Rules:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.positive_titles = [_term(t) for t in raw.get("positive_titles", [])]
        self.early_career = [_term(t) for t in raw.get("early_career_signals", [])]
        self.hard_exclusions = [_term(t) for t in raw.get("hard_exclusions", [])]
        self.description_exclusions = [_term(t) for t in raw.get("description_exclusions", [])]
        self.non_software = [_term(t) for t in raw.get("non_software_signals", [])]
        self.role_families: dict[str, list[_Term]] = {
            family: [_term(t) for t in terms]
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


@lru_cache(maxsize=1)
def rules_fingerprint() -> str:
    """Hash of the title rules file in effect (part of every job's raw_hash)."""
    import hashlib

    for candidate in (config_dir() / "title_rules.yaml", _DEFAULT_RULES_PATH):
        if candidate.exists():
            return hashlib.sha256(candidate.read_bytes()).hexdigest()
    return "none"


def _any_match(terms: list[_Term], text: str, lowered: str | None = None) -> bool:
    lowered = text.lower() if lowered is None else lowered
    return any(term.search(text, lowered) for term in terms)


def _first_match(terms: list[_Term], text: str, lowered: str | None = None) -> str | None:
    lowered = text.lower() if lowered is None else lowered
    for term in terms:
        if term.search(text, lowered):
            return term.term
    return None


# Graduate-degree-only titles ("PhD Research Intern", "Master's Software
# Intern", "MS/PhD Intern"). Excluded even on intern titles, unless the title
# also opens the role to undergraduates ("BS/MS Intern"): a bachelor's
# candidate cannot apply, so they are never relevant.
_GRAD_TITLE_RE = re.compile(
    r"\bph\.?\s?d\b|doctoral|doctorate|post[\s\-]?doc|\bmba\b"
    # "Graduate Intern" = grad-student internship ("Graduate Software
    # Engineer" is a new-grad role and is NOT matched).
    r"|graduate\s+(?:student\s+)?intern"
    # Bare "MS" only inside "(...)" or "/" degree lists ("(MS)", "MS/PhD"):
    # never "MS Teams" or a Mississippi location ("Southaven, MS").
    r"|master'?s|\bm\.?s\.?(?=\s*[/)])|(?<=[(/])\s?m\.?s\b",
    re.IGNORECASE,
)
_UNDERGRAD_TITLE_RE = re.compile(
    r"\bb\.?s\.?(?=[\s/,)\-]|$)|\bb\.?a\.?(?=[\s/,)\-]|$)|bachelor|undergrad|\bug\b",
    re.IGNORECASE,
)


def graduate_only_title(title: str) -> bool:
    return bool(_GRAD_TITLE_RE.search(title or "")) and not _UNDERGRAD_TITLE_RE.search(title or "")


def classify(title: str, description: str = "") -> TitleClassification:
    rules = load_rules()
    result = TitleClassification()
    title_text = title or ""
    desc_text = description or ""
    combined = f"{title_text}\n{desc_text}"
    title_l = title_text.lower()
    desc_l = desc_text.lower()
    combined_l = f"{title_l}\n{desc_l}"

    early_in_title = _any_match(rules.early_career, title_text, title_l)
    early_in_desc = _any_match(rules.early_career, desc_text, desc_l)
    result.is_early_career = early_in_title or early_in_desc
    if early_in_title:
        result.matched_signals.append("early_career_title")
    elif early_in_desc:
        result.matched_signals.append("early_career_description")

    # Hard exclusion applies only on the title, and never overrides an explicit
    # intern/new-grad signal in the title (spec: exclude only with high confidence).
    excluded_term = _first_match(rules.hard_exclusions, title_text, title_l)
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

    if not result.hard_excluded and graduate_only_title(title_text):
        result.hard_excluded = True
        result.exclusion_reason = "title targets graduate-degree students only (PhD/MS/MBA)"

    desc_excluded = _first_match(rules.description_exclusions, desc_text, desc_l)
    if desc_excluded:
        result.downrank_flags.append(f"description_exclusion:{desc_excluded}")

    positive = _any_match(rules.positive_titles, title_text, title_l)
    non_software_term = _first_match(rules.non_software, title_text, title_l)

    # Role family: title matches are authoritative; description matches are a fallback.
    family = None
    for candidate in _FAMILY_ORDER:
        if _any_match(rules.role_families.get(candidate, []), title_text, title_l):
            family = candidate
            break
    if family is None:
        for candidate in _FAMILY_ORDER:
            if _any_match(rules.role_families.get(candidate, []), combined, combined_l):
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
    rules_fingerprint.cache_clear()
