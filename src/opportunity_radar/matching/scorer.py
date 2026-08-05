"""Deterministic weighted scoring (spec §13).

Every component is stored separately so each score is fully explainable.
Clamped to 0-100.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from opportunity_radar.config import ProfileConfig, ScoringConfig, TargetWindow
from opportunity_radar.matching.eligibility import EligibilityResult
from opportunity_radar.matching.season_parser import SeasonResult
from opportunity_radar.matching.title_classifier import TitleClassification
from opportunity_radar.utilities.dates import utcnow

_PRODUCTION_SIGNALS = [
    "production",
    "distributed systems",
    "scalab",
    "high availability",
    "reliability",
    "infrastructure",
    "microservice",
    "low latency",
    "concurren",
    "real-time",
    "large-scale",
    "cloud",
]

_US_LOCATION_HINTS = re.compile(
    r"\b(united states|usa|u\.s\.|remote[\s\-]?\(?us|ca|ny|wa|tx|ma|il|co|ga|nc|va|az|or|ut|pa|fl)\b"
    r"|california|new york|seattle|austin|boston|chicago|denver|atlanta|san francisco"
    r"|mountain view|palo alto|sunnyvale|san jose|los angeles|san diego|bellevue|redmond"
    r"|portland|salt lake|raleigh|arlington|washington",
    re.IGNORECASE,
)
_NON_US_HINTS = re.compile(
    r"london|dublin|toronto|vancouver|bangalore|bengaluru|hyderabad|singapore|sydney"
    r"|amsterdam|berlin|munich|paris|zurich|tokyo|tel aviv|warsaw|krakow|mexico city"
    r"|s[aã]o paulo|shanghai|beijing|seoul|taipei",
    re.IGNORECASE,
)


@dataclass
class ScoreResult:
    total: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    matched_skills: list[str] = field(default_factory=list)
    suppressed: bool = False


def _skill_pattern(skill: str) -> re.Pattern[str]:
    escaped = re.escape(skill.lower())
    return re.compile(rf"(?<![a-z0-9#+]){escaped}(?![a-z0-9])", re.IGNORECASE)


def _score_timing(
    season: SeasonResult, windows: list[TargetWindow], is_early_career: bool
) -> float:
    """0-20 based on overlap between the inferred start window and target windows."""
    if season.season == "year_round":
        return 14.0
    if season.season == "off_cycle":
        # Off-cycle is exactly what community lists miss — high value.
        return 18.0 * max(season.confidence, 0.5)
    if season.season == "unspecified" or not windows:
        # Borderline stays in the review queue, not silently discarded.
        return 7.0 if is_early_career else 3.0

    start_min = season.start_min
    start_max = season.start_max
    if start_min is None and season.year is not None:
        start_min = date(season.year, 1, 1)
        start_max = date(season.year, 12, 31)
    if start_min is None:
        # Season known but no year: partial credit.
        return 9.0 * season.confidence

    best_priority = 0
    for window in windows:
        overlaps = start_min <= window.end and (start_max or start_min) >= window.start
        if overlaps:
            best_priority = max(best_priority, window.priority)
    if best_priority == 0:
        return 2.0
    return 20.0 * (best_priority / 100.0) * max(season.confidence, 0.6)


def _score_skills(text: str, profile: ProfileConfig) -> tuple[float, list[str]]:
    matched: list[str] = []
    points = 0.0
    for skill in profile.skills.languages + profile.skills.technologies:
        if _skill_pattern(skill).search(text):
            matched.append(skill)
            points += 2.5
    for concept in profile.skills.concepts:
        if _skill_pattern(concept).search(text):
            matched.append(concept)
            points += 1.5
    return min(points, 15.0), matched


def _score_production(text: str) -> float:
    lowered = text.lower()
    hits = sum(1 for signal in _PRODUCTION_SIGNALS if signal in lowered)
    return min(hits * 2.5, 10.0)


def _score_location(locations: list[str], remote_type: str, profile: ProfileConfig) -> float:
    if remote_type == "remote" and profile.preferences.allow_remote:
        return 5.0
    joined = " | ".join(locations)
    if not joined:
        return 2.0
    if _US_LOCATION_HINTS.search(joined):
        for preferred in profile.preferences.preferred_locations:
            if preferred.lower() in joined.lower():
                return 5.0
        return 4.0
    if _NON_US_HINTS.search(joined) and not _US_LOCATION_HINTS.search(joined):
        return 0.0
    return 2.0  # unknown — willing to relocate keeps it neutral


def _score_freshness(first_seen_at: datetime, now: datetime | None = None) -> float:
    now = now or utcnow()
    if first_seen_at.tzinfo is None:
        first_seen_at = first_seen_at.replace(tzinfo=UTC)
    age_hours = max((now - first_seen_at).total_seconds() / 3600.0, 0.0)
    if age_hours < 6:
        return 5.0
    if age_hours < 24:
        return 4.0
    if age_hours < 72:
        return 3.0
    if age_hours < 24 * 7:
        return 2.0
    if age_hours < 24 * 30:
        return 1.0
    return 0.0


def _eligibility_adjustment(eligibility: EligibilityResult) -> float:
    if eligibility.level == "confirmed_ineligible":
        return -50.0
    if eligibility.level == "likely_ineligible":
        return -30.0
    if eligibility.level == "uncertain":
        risky = {
            "us_citizenship_required",
            "security_clearance_required",
            "sponsorship_not_available",
            "graduate_students_only",
        } & set(eligibility.flags)
        return -min(len(risky) * 5.0, 15.0)
    return 0.0


def _risk_adjustment(classification: TitleClassification, is_early_career: bool) -> float:
    penalty = 0.0
    if any(flag.startswith("description_exclusion") for flag in classification.downrank_flags):
        penalty -= 15.0
    if not is_early_career:
        penalty -= 10.0
    if not classification.is_software:
        penalty -= 5.0
    return max(penalty, -30.0)


def score_job(
    *,
    title: str,
    description_text: str,
    locations: list[str],
    remote_type: str,
    company_tier: str,
    classification: TitleClassification,
    season: SeasonResult,
    eligibility: EligibilityResult,
    first_seen_at: datetime,
    profile: ProfileConfig,
    scoring: ScoringConfig,
    now: datetime | None = None,
) -> ScoreResult:
    result = ScoreResult()
    if classification.hard_excluded:
        result.suppressed = True
        result.components["hard_excluded"] = 0.0
        return result

    text = f"{title}\n{description_text}"
    components = result.components

    components["company_quality"] = scoring.company_tier_points.get(company_tier, 8.0)
    components["role_fit"] = scoring.role_family_weights.get(classification.role_family, 0.0)
    components["timing"] = round(
        _score_timing(season, scoring.target_windows, classification.is_early_career), 2
    )
    skill_points, matched_skills = _score_skills(text, profile)
    components["skills"] = round(skill_points, 2)
    result.matched_skills = matched_skills
    components["production_relevance"] = _score_production(text)
    components["location"] = _score_location(locations, remote_type, profile)
    components["freshness"] = _score_freshness(first_seen_at, now)
    components["eligibility_adjustment"] = _eligibility_adjustment(eligibility)
    components["risk_adjustment"] = _risk_adjustment(classification, classification.is_early_career)

    result.total = round(min(max(sum(components.values()), 0.0), 100.0), 1)
    return result


def decide_alert_level(
    *,
    score: float,
    season: SeasonResult,
    classification: TitleClassification,
    company_tier: str,
    posted_at: datetime | None,
    deadline: date | None,
    thresholds_immediate: int,
    thresholds_digest: int,
    thresholds_dashboard: int,
    thresholds_suppress: int,
    now: datetime | None = None,
) -> str:
    """Return one of: immediate, digest, dashboard, suppress (spec §13.5)."""
    now = now or utcnow()
    if score < thresholds_suppress:
        return "suppress"

    if score >= thresholds_immediate:
        return "immediate"

    # Override: explicit Winter/Spring/Fall SWE role at a core/strong company.
    if (
        classification.is_software
        and classification.is_early_career
        and season.season in ("winter", "spring", "fall", "off_cycle")
        and season.confidence >= 0.9
        and company_tier in ("core", "strong")
        and score >= thresholds_digest
    ):
        return "immediate"

    # Override: posted within last 24h with score >= 75.
    if posted_at is not None and (now - posted_at).total_seconds() < 24 * 3600 and score >= 75:
        return "immediate"

    # Override: deadline within 5 days with score >= 70.
    if deadline is not None and 0 <= (deadline - now.date()).days <= 5 and score >= 70:
        return "immediate"

    if score >= thresholds_digest:
        return "digest"
    if score >= thresholds_dashboard:
        return "dashboard"
    return "dashboard" if classification.is_early_career else "suppress"
