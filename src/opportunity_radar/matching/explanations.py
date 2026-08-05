"""Human-readable match explanations (spec §26).

Explanations cite concrete extracted facts (tier, season evidence, matched
skills, eligibility sentences) — never generic claims.
"""

from __future__ import annotations

from opportunity_radar.matching.eligibility import EligibilityResult
from opportunity_radar.matching.scorer import ScoreResult
from opportunity_radar.matching.season_parser import SeasonResult
from opportunity_radar.matching.title_classifier import TitleClassification

_TIER_LABELS = {
    "core": "Core target company",
    "strong": "Strong target company",
    "broad": "Broad-list company",
    "exploratory": "Exploratory company",
}

_FAMILY_LABELS = {
    "general_swe": "General software engineering role",
    "backend": "Backend role family",
    "infrastructure": "Infrastructure/platform role family",
    "ml_systems": "ML systems role family",
    "data_infrastructure": "Data infrastructure role family",
    "developer_tools": "Developer tools role family",
    "fullstack": "Full-stack role family",
    "frontend": "Frontend role family",
    "embedded": "Embedded software role family",
    "robotics": "Robotics software role family",
    "security": "Security engineering role family",
    "quant_developer": "Quantitative developer role family",
    "research_engineering": "Research engineering role family",
}

_RISK_LABELS = {
    "requires_full_academic_term_after_internship": "Requires returning to school after the internship",
    "graduate_students_only": "Graduate students only",
    "phd_only": "PhD students only",
    "us_citizenship_required": "U.S. citizenship required",
    "citizenship_status_unconfigured": "Citizenship status not configured in profile",
    "security_clearance_required": "Security clearance required",
    "graduation_window_uncertain": "Graduation window language unclear",
    "graduation_window_mismatch": "Stated graduation window may not match December 2027",
    "fall_2027_conflicts_with_expected_graduation": "Fall 2027 term conflicts with expected graduation",
    "sponsorship_not_available": "Employer states sponsorship is not available",
    "international_work_authorization_unknown": "Work authorization needs not configured in profile",
}


def build_reasons(
    *,
    company_tier: str,
    classification: TitleClassification,
    season: SeasonResult,
    eligibility: EligibilityResult,
    score: ScoreResult,
    freshness_label: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    tier_label = _TIER_LABELS.get(company_tier)
    if tier_label:
        reasons.append(tier_label)

    if season.season not in ("unspecified",) and season.confidence >= 0.9:
        label = season.season.replace("_", "-").title()
        year = f" {season.year}" if season.year else ""
        reasons.append(f"Explicit {label}{year} timing ({season.evidence})")
    elif season.season != "unspecified":
        label = season.season.replace("_", "-")
        reasons.append(f"Season inferred as {label} (confidence {season.confidence:.0%})")

    family_label = _FAMILY_LABELS.get(classification.role_family)
    if family_label:
        reasons.append(family_label)

    if classification.is_early_career:
        reasons.append("Early-career/intern signals present")

    if score.matched_skills:
        top = ", ".join(score.matched_skills[:6])
        reasons.append(f"Matches {top}")

    if eligibility.level in ("confirmed_eligible", "likely_eligible"):
        if eligibility.eligibility_sentence:
            reasons.append("Graduation window appears compatible")
        else:
            reasons.append("No eligibility blockers found")

    if freshness_label:
        reasons.append(f"First seen {freshness_label}")

    return reasons


def build_risks(eligibility: EligibilityResult, classification: TitleClassification) -> list[str]:
    risks: list[str] = []
    for flag in eligibility.flags:
        risks.append(_RISK_LABELS.get(flag, flag.replace("_", " ")))
    if eligibility.full_time_required:
        risks.append("Full-time availability required")
    for flag in classification.downrank_flags:
        if flag.startswith("description_exclusion:"):
            risks.append(f"Description mentions '{flag.split(':', 1)[1]}'")
    if not classification.is_early_career:
        risks.append("Not clearly an intern/new-grad role")
    # De-duplicate preserving order.
    seen: set[str] = set()
    unique = []
    for risk in risks:
        if risk not in seen:
            seen.add(risk)
            unique.append(risk)
    return unique
