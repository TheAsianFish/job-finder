"""Skill / ATS-keyword demand across stored internship postings.

Answers "what do the internships I target actually ask for, and which of
those does my profile cover?" from the job descriptions already in the
database, with no model calls. The vocabulary lives in
config/skills_vocabulary.yaml; the profile skills come from profile.yaml.

Only postings with a real description count (Simplify-sourced rows carry a
one-line synthetic description and would dilute every percentage).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from opportunity_radar.config import ProfileConfig, config_dir
from opportunity_radar.db.tables import JobRow
from opportunity_radar.matching.scorer import is_us_accessible

MIN_DESCRIPTION_CHARS = 400
_DEFAULT_VOCAB = Path(__file__).resolve().parents[3] / "config" / "skills_vocabulary.yaml"
_INTERN_RE = re.compile(r"intern|co-?op", re.IGNORECASE)


@dataclass(frozen=True)
class Skill:
    name: str
    category: str
    patterns: tuple[re.Pattern[str], ...]

    def found_in(self, text: str) -> bool:
        return any(p.search(text) for p in self.patterns)


@dataclass
class SkillStat:
    name: str
    category: str
    postings: int
    share: float
    on_profile: bool
    by_family: dict[str, float] = field(default_factory=dict)


@dataclass
class SkillReport:
    generated: date
    postings: int
    stats: list[SkillStat]
    families: dict[str, int]

    @property
    def gaps(self) -> list[SkillStat]:
        return [s for s in self.stats if not s.on_profile and s.category != "soft"]

    @property
    def strengths(self) -> list[SkillStat]:
        return [s for s in self.stats if s.on_profile]


def _compile(pattern: str) -> re.Pattern[str]:
    # Word boundaries unless the pattern anchors itself.
    has_anchor = pattern.startswith(("\\b", "(?<")) or pattern.endswith(("\\b", ")"))
    body = pattern if has_anchor else rf"(?<![a-z0-9]){pattern}(?![a-z0-9])"
    return re.compile(body, re.IGNORECASE)


def load_vocabulary(path: Path | None = None) -> list[Skill]:
    candidates = [path, config_dir() / "skills_vocabulary.yaml", _DEFAULT_VOCAB]
    for candidate in candidates:
        if candidate and candidate.exists():
            raw: dict[str, Any] = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            return [
                Skill(
                    name=str(entry["name"]),
                    category=str(entry.get("category", "other")),
                    patterns=tuple(_compile(p) for p in entry.get("patterns", [])),
                )
                for entry in raw.get("skills", [])
            ]
    return []


@lru_cache(maxsize=1)
def default_vocabulary() -> tuple[Skill, ...]:
    return tuple(load_vocabulary())


def keyword_fit(
    text: str, profile: ProfileConfig, vocabulary: tuple[Skill, ...] | None = None
) -> tuple[list[str], list[str]]:
    """(skills the posting asks for that you have, ones you don't), in
    vocabulary order, soft skills excluded."""
    vocab = vocabulary if vocabulary is not None else default_vocabulary()
    terms = _profile_terms(profile)
    have: list[str] = []
    missing: list[str] = []
    for skill in vocab:
        if skill.category == "soft" or not skill.found_in(text):
            continue
        (have if on_profile(skill, terms) else missing).append(skill.name)
    return have, missing


def _profile_terms(profile: ProfileConfig) -> list[str]:
    skills = profile.skills
    return [s.lower() for s in skills.languages + skills.technologies + skills.concepts]


def on_profile(skill: Skill, profile_terms: list[str]) -> bool:
    """A vocabulary skill counts as covered when any profile entry matches it."""
    return any(skill.found_in(term) or term == skill.name.lower() for term in profile_terms)


def select_postings(session: Session, internships_only: bool = True) -> list[JobRow]:
    rows = session.scalars(
        select(JobRow).where(
            JobRow.status == "active",
            JobRow.is_early_career.is_(True),
            JobRow.match_score > 0,
            JobRow.role_family.notin_(["irrelevant", "adjacent"]),
            # Roles the eligibility engine says you cannot take (PhD/MS-only,
            # graduation window) would skew "what do my internships want".
            JobRow.eligibility_level.notin_(["likely_ineligible", "confirmed_ineligible"]),
        )
    )
    chosen = []
    for row in rows:
        if len(row.description_text or "") < MIN_DESCRIPTION_CHARS:
            continue
        if internships_only and not _INTERN_RE.search(row.title or ""):
            continue
        if not is_us_accessible(row.all_locations or [], row.compensation_currency):
            continue
        chosen.append(row)
    return chosen


def build_report(
    postings: list[JobRow],
    vocabulary: list[Skill],
    profile: ProfileConfig,
    today: date | None = None,
) -> SkillReport:
    profile_terms = _profile_terms(profile)
    totals: Counter[str] = Counter()
    family_totals: Counter[str] = Counter()
    family_hits: dict[str, Counter[str]] = {}
    for row in postings:
        text = f"{row.title}\n{row.description_text}"
        family = row.role_family or "general_swe"
        family_totals[family] += 1
        for skill in vocabulary:
            if skill.found_in(text):
                totals[skill.name] += 1
                family_hits.setdefault(skill.name, Counter())[family] += 1
    n = len(postings) or 1
    stats = [
        SkillStat(
            name=skill.name,
            category=skill.category,
            postings=totals[skill.name],
            share=totals[skill.name] / n,
            on_profile=on_profile(skill, profile_terms),
            by_family={
                fam: family_hits.get(skill.name, Counter())[fam] / family_totals[fam]
                for fam in family_totals
                if family_totals[fam] >= 15
            },
        )
        for skill in vocabulary
    ]
    stats.sort(key=lambda s: s.postings, reverse=True)
    return SkillReport(
        generated=today or date.today(),
        postings=len(postings),
        stats=stats,
        families=dict(family_totals.most_common()),
    )


def render_markdown(report: SkillReport, top: int = 40) -> str:
    def pct(x: float) -> str:
        return f"{x * 100:.0f}%"

    lines = [
        "# Internship skill & ATS-keyword demand",
        "",
        f"Generated {report.generated.isoformat()} by `opportunity-radar insights skills` "
        f"from **{report.postings}** active, US-workable internship postings with full "
        "descriptions. Share = fraction of postings mentioning the skill.",
        "",
        "## Biggest gaps (asked for often, not on your profile)",
        "",
        "| Skill | Category | Share of postings |",
        "|---|---|---|",
    ]
    lines += [f"| {s.name} | {s.category} | {pct(s.share)} |" for s in report.gaps[:15]]
    lines += [
        "",
        "## Top demanded skills",
        "",
        "| # | Skill | Category | Share | On profile |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {i} | {s.name} | {s.category} | {pct(s.share)} | {'yes' if s.on_profile else '**no**'} |"
        for i, s in enumerate(report.stats[:top], 1)
    ]
    families = [f for f, count in report.families.items() if count >= 15]
    if families:
        lines += [
            "",
            "## By role family (top 8 skills each)",
            "",
        ]
        for fam in families:
            ranked = sorted(
                (s for s in report.stats if fam in s.by_family),
                key=lambda s: s.by_family[fam],
                reverse=True,
            )[:8]
            items = ", ".join(f"{s.name} {pct(s.by_family[fam])}" for s in ranked)
            lines.append(f"- **{fam}** ({report.families[fam]} postings): {items}")
    lines += [
        "",
        "## How to use this",
        "",
        "- A gap you genuinely have experience with: add the exact keyword to the resume.",
        "- A gap you lack: candidate for the next project (see docs/roadmap.md).",
        "- Never add a keyword you cannot defend in an interview.",
        "",
    ]
    return "\n".join(lines)
