"""Eligibility engine (spec §12).

Distinguishes confirmed/likely eligible, uncertain, likely/confirmed
ineligible. Conservative by design: unknown personal fields (citizenship,
sponsorship) stay unknown and produce flags rather than assumptions, and the
exact sentence that drove a decision is surfaced for the job detail page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from opportunity_radar.config import CandidateProfile

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_YEAR_RE = re.compile(r"20\d{2}")

_GRADUATION_RE = re.compile(r"graduat|degree completion|expected completion", re.IGNORECASE)
_RETURN_TO_SCHOOL_RE = re.compile(
    r"return(?:ing)? to (?:school|university|college|a degree|your degree|their degree)"
    r"|at least one (?:semester|quarter|term|academic year) (?:remaining|left)"
    r"|enrolled (?:in|at) (?:a|an|your) (?:degree|university|college|academic)"
    r"|currently enrolled",
    re.IGNORECASE,
)
_CITIZENSHIP_RE = re.compile(
    r"(?:must be|requires?|required to be)[^.\n]{0,40}u\.?s\.? citizen"
    r"|u\.?s\.? citizenship (?:is )?required"
    r"|citizenship:?\s*u\.?s\.?"
    r"|only u\.?s\.? citizens",
    re.IGNORECASE,
)
_CLEARANCE_RE = re.compile(
    r"(?:active|current|able to obtain|obtain and maintain|must (?:hold|obtain)|requires?)"
    r"[^.\n]{0,60}security clearance"
    r"|security clearance (?:is )?required"
    r"|ts/sci",
    re.IGNORECASE,
)
_NO_SPONSORSHIP_RE = re.compile(
    r"(?:unable|not able|will not|won't|cannot|can not|do(?:es)? not)"
    r"[^.\n]{0,50}sponsor"
    r"|without (?:the need for )?(?:visa )?sponsorship"
    r"|sponsorship (?:is )?not (?:available|offered|provided)",
    re.IGNORECASE,
)
_SPONSORSHIP_OK_RE = re.compile(
    r"(?:will|can|do(?:es)?)\s+sponsor|sponsorship (?:is )?available", re.IGNORECASE
)
_FULL_TIME_RE = re.compile(
    r"full[\s\-]?time availability|available (?:to work )?full[\s\-]?time"
    r"|40 hours (?:per|a) week|commit(?:ment)? (?:of|to) 40 hours",
    re.IGNORECASE,
)
_PHD_ONLY_RE = re.compile(
    r"phd (?:students? )?(?:required|only)|pursuing a phd|enrolled in a phd", re.IGNORECASE
)
_GRAD_ONLY_RE = re.compile(
    r"(?:master'?s?|graduate|ms/phd) students? only"
    r"|currently pursuing (?:a|an) (?:master|graduate|phd)"
    r"|must be (?:a )?graduate student",
    re.IGNORECASE,
)
_BACHELORS_RE = re.compile(r"bachelor|\bb\.?s\.?\b|\bba\b|undergraduate", re.IGNORECASE)
_MASTERS_RE = re.compile(r"master|\bm\.?s\.?\b|graduate degree", re.IGNORECASE)
_PHD_RE = re.compile(r"\bph\.?d\.?\b|doctora(?:te|l)", re.IGNORECASE)

_MONTHS_RE = (
    r"(january|february|march|april|may|june|july|august|september|october|november|december)"
)
_MONTH_NUM = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_YEAR_RE = re.compile(_MONTHS_RE + r"\s+(20\d{2})", re.IGNORECASE)


@dataclass
class EligibilityResult:
    level: str = "uncertain"
    confidence: float = 0.3
    flags: list[str] = field(default_factory=list)
    eligibility_sentence: str | None = None
    graduation_min: date | None = None
    graduation_max: date | None = None
    requires_return_to_school: bool | None = None
    citizenship_required: bool | None = None
    clearance_required: bool | None = None
    full_time_required: bool | None = None
    work_authorization_text: str | None = None
    degree_levels: list[str] = field(default_factory=list)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text or "") if s.strip()]


def _graduation_window(sentence: str) -> tuple[date | None, date | None]:
    """Extract a graduation window from one sentence, conservatively."""
    month_years = [
        (int(m.group(2)), _MONTH_NUM[m.group(1).lower()]) for m in _MONTH_YEAR_RE.finditer(sentence)
    ]
    if month_years:
        dates = sorted(date(y, m, 1) for y, m in month_years)
        lowered = sentence.lower()
        if len(dates) == 1:
            if re.search(r"or (?:later|after)", lowered):
                return dates[0], None
            if re.search(r"or (?:earlier|before)|by " + _MONTHS_RE, lowered):
                return None, dates[0]
            return dates[0], dates[0]
        return dates[0], dates[-1]
    years = sorted({int(y) for y in _YEAR_RE.findall(sentence)})
    if not years:
        return None, None
    if len(years) == 1:
        year = years[0]
        lowered = sentence.lower()
        if re.search(r"or (?:later|after)", lowered):
            return date(year, 1, 1), None
        if re.search(r"or (?:earlier|before)", lowered):
            return None, date(year, 12, 31)
        return date(year, 1, 1), date(year, 12, 31)
    return date(years[0], 1, 1), date(years[-1], 12, 31)


def evaluate(
    description_text: str,
    profile: CandidateProfile,
    season: str = "unspecified",
    season_year: int | None = None,
) -> EligibilityResult:
    result = EligibilityResult()
    text = description_text or ""
    sentences = _sentences(text)
    expected_grad = profile.expected_graduation
    positives = 0
    negatives = 0

    # --- Graduation window -------------------------------------------------
    grad_sentence = next((s for s in sentences if _GRADUATION_RE.search(s)), None)
    if grad_sentence:
        result.eligibility_sentence = grad_sentence
        grad_min, grad_max = _graduation_window(grad_sentence)
        result.graduation_min = grad_min
        result.graduation_max = grad_max
        if grad_min or grad_max:
            in_window = (grad_min is None or expected_grad >= grad_min) and (
                grad_max is None or expected_grad <= grad_max
            )
            if in_window:
                positives += 2
            else:
                negatives += 2
                result.flags.append("graduation_window_mismatch")
        else:
            result.flags.append("graduation_window_uncertain")

    # --- Return-to-school requirement ---------------------------------------
    if _RETURN_TO_SCHOOL_RE.search(text):
        result.requires_return_to_school = True
        result.flags.append("requires_full_academic_term_after_internship")
        if result.eligibility_sentence is None:
            result.eligibility_sentence = next(
                (s for s in sentences if _RETURN_TO_SCHOOL_RE.search(s)), None
            )
        # Graduating Dec 2027: a Fall 2027 internship leaves no term to return to.
        if season == "fall" and season_year == expected_grad.year:
            result.flags.append("fall_2027_conflicts_with_expected_graduation")
            negatives += 1

    # --- Citizenship / clearance --------------------------------------------
    if _CITIZENSHIP_RE.search(text):
        result.citizenship_required = True
        result.flags.append("us_citizenship_required")
        if profile.us_citizen is False:
            negatives += 3
        elif profile.us_citizen is None:
            result.flags.append("citizenship_status_unconfigured")

    if _CLEARANCE_RE.search(text):
        result.clearance_required = True
        result.flags.append("security_clearance_required")
        if profile.clearance_eligible is False:
            negatives += 2

    # --- Sponsorship ----------------------------------------------------------
    sponsorship_match = _NO_SPONSORSHIP_RE.search(text)
    if sponsorship_match:
        sentence = next((s for s in sentences if _NO_SPONSORSHIP_RE.search(s)), None)
        result.work_authorization_text = sentence or sponsorship_match.group(0)
        result.flags.append("sponsorship_not_available")
        if profile.requires_sponsorship is True:
            negatives += 3
        elif profile.requires_sponsorship is None:
            result.flags.append("international_work_authorization_unknown")
    elif _SPONSORSHIP_OK_RE.search(text):
        sentence = next((s for s in sentences if _SPONSORSHIP_OK_RE.search(s)), None)
        result.work_authorization_text = sentence

    # --- Degree levels ---------------------------------------------------------
    if _BACHELORS_RE.search(text):
        result.degree_levels.append("bachelors")
    if _MASTERS_RE.search(text):
        result.degree_levels.append("masters")
    if _PHD_RE.search(text):
        result.degree_levels.append("phd")

    if _PHD_ONLY_RE.search(text) and profile.degree_level != "phd":
        result.flags.append("phd_only")
        negatives += 3
    elif _GRAD_ONLY_RE.search(text) and profile.degree_level == "bachelors":
        # Considering a master's does NOT satisfy a grad-students-only rule.
        result.flags.append("graduate_students_only")
        negatives += 2

    # --- Full-time availability ---------------------------------------------
    if _FULL_TIME_RE.search(text):
        result.full_time_required = True

    # --- Level determination ---------------------------------------------------
    hard_negative = (
        (result.citizenship_required and profile.us_citizen is False)
        or "phd_only" in result.flags
        or "graduation_window_mismatch" in result.flags
    )
    if hard_negative and negatives >= 3:
        result.level = "confirmed_ineligible"
        result.confidence = 0.9
    elif negatives >= 2:
        result.level = "likely_ineligible"
        result.confidence = 0.7
    elif positives >= 2 and negatives == 0:
        blocking_unknowns = {
            "citizenship_status_unconfigured",
            "international_work_authorization_unknown",
        } & set(result.flags)
        if blocking_unknowns:
            result.level = "likely_eligible"
            result.confidence = 0.7
        else:
            result.level = "confirmed_eligible" if grad_sentence else "likely_eligible"
            result.confidence = 0.85
    elif positives > 0 and negatives == 0:
        result.level = "likely_eligible"
        result.confidence = 0.6
    else:
        result.level = "uncertain"
        result.confidence = 0.3
    return result
