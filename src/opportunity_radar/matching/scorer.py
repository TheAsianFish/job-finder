"""Deterministic weighted scoring (spec §13).

Every component is stored separately so each score is fully explainable.
Clamped to 0-100.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from opportunity_radar.config import CompensationScoring, ProfileConfig, ScoringConfig, TargetWindow
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
    # State abbreviations only count after a comma ("Portland, OR") — bare
    # two-letter words collide with English ("London or Dublin" is not Oregon).
    r"\b(united states|usa|u\.s\.|remote[\s\-]?\(?us)\b"
    r"|,\s*(al|ak|az|ar|ca|co|ct|de|dc|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms"
    r"|mo|mt|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy)\b"
    r"|california|new york|seattle|austin|boston|chicago|denver|atlanta|san francisco"
    r"|mountain view|palo alto|sunnyvale|san jose|los angeles|san diego|bellevue|redmond"
    r"|portland|salt lake|raleigh|arlington|washington",
    re.IGNORECASE,
)
_NON_US_HINTS = re.compile(
    r"london|dublin|toronto|vancouver|bangalore|bengaluru|hyderabad|singapore|sydney"
    r"|amsterdam|berlin|munich|paris|zurich|tokyo|tel aviv|warsaw|krakow|mexico city"
    r"|s[aã]o paulo|shanghai|beijing|seoul|taipei"
    r"|lisbon|portugal|madrid|barcelona|spain|france|germany|netherlands|belgium"
    r"|austria|vienna|switzerland|italy|milan|poland|romania|bucharest|czech|prague"
    r"|hungary|budapest|bulgaria|sofia|croatia|serbia|ukraine|estonia|tallinn"
    r"|lithuania|vilnius|sweden|stockholm|denmark|copenhagen|norway|oslo|finland"
    r"|helsinki|ireland|scotland|edinburgh|glasgow|belfast|united kingdom|\buk\b"
    r"|england|manchester|hamburg|frankfurt|stuttgart|cologne|eindhoven|rotterdam"
    r"|india|mumbai|pune|chennai|delhi|noida|gurgaon|gurugram|kolkata|israel"
    r"|japan|osaka|china|hong kong|taiwan|korea|philippines|manila|vietnam"
    r"|indonesia|jakarta|thailand|bangkok|malaysia|kuala lumpur|australia"
    r"|melbourne|brisbane|new zealand|auckland|wellington|canada|montreal|ottawa"
    r"|calgary|waterloo|quebec|mexico|guadalajara|monterrey|brazil|argentina"
    r"|buenos aires|chile|santiago|colombia|bogot[aá]|peru|lima|costa rica"
    r"|uruguay|montevideo|turkey|istanbul|dubai|\buae\b|egypt|cairo|nigeria"
    r"|lagos|kenya|nairobi|south africa|cape town|johannesburg",
    re.IGNORECASE,
)


def is_us_accessible(
    locations: list[str],
    compensation_currency: str | None = None,
) -> bool:
    """False when a role is clearly workable only outside the US.

    Conservative on missing data: unknown locations stay accessible and are
    handled by the location score, never by this gate. Non-USD pay is treated
    as a non-US signal — US-payroll roles are quoted in dollars.
    """
    if compensation_currency and compensation_currency.upper() not in ("USD", "US$", "$"):
        return False
    joined = " | ".join(locations or [])
    if not joined:
        return True
    if _US_LOCATION_HINTS.search(joined):
        return True
    return not _NON_US_HINTS.search(joined)


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
    season: SeasonResult,
    windows: list[TargetWindow],
    is_early_career: bool,
    today: date | None = None,
) -> float:
    """0-20 based on overlap between the inferred start window and target windows.

    Windows that have already closed (end before today) are ignored, so a
    static config never keeps rewarding a season that has passed.
    """
    today = today or utcnow().date()
    windows = [w for w in windows if w.end >= today]
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
    joined = " | ".join(locations)
    # Clearly non-US scores zero even when remote: "Remote - Portugal" is not
    # workable from the US, so it earns no remote bonus.
    if joined and _NON_US_HINTS.search(joined) and not _US_LOCATION_HINTS.search(joined):
        return 0.0
    if remote_type == "remote" and profile.preferences.allow_remote:
        return 5.0
    if not joined:
        return 2.0
    if _US_LOCATION_HINTS.search(joined):
        preferred_list = profile.preferences.preferred_locations
        if not preferred_list:
            return 5.0  # no preference: any US location is ideal
        for preferred in preferred_list:
            if preferred.lower() in joined.lower():
                return 5.0
        return 4.0
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


_INTERN_TITLE_RE = re.compile(
    r"(?<![a-z])(?:intern|internship|interns|co-?op|apprentice(?:ship)?)(?![a-z])", re.IGNORECASE
)
_SEASON_YEAR_TITLE_RE = re.compile(r"(?:winter|spring|summer|fall|autumn)\s*'?(?:20)?\d{2}", re.I)
_LIST_INTERNSHIP_MARKER = "Internship listed on the Simplify internships list."


def is_internship(title: str, description: str = "") -> bool:
    """Internship/co-op by title, by an explicit season+year in the title
    ("Software Engineer - Summer 2027"), or by coming from an internship list."""
    return bool(
        _INTERN_TITLE_RE.search(title or "")
        or _SEASON_YEAR_TITLE_RE.search(title or "")
        or _LIST_INTERNSHIP_MARKER in (description or "")
    )


_STRONG_EARLY_DESC_RE = re.compile(
    r"new[\s\-]?grad(?:uate)?s?\b|recent (?:college |university )?graduates?|entry[\s\-]level"
    r"|early[\s\-]career (?:program|role|position|talent)|university (?:grad|hire|program)"
    r"|graduating (?:in|by|between)|class of 20\d\d|0\s*[-–]\s*[12] years",  # noqa: RUF001
    re.IGNORECASE,
)
_EXPERIENCE_RE = re.compile(
    r"(?<![\d\-–])(\d{1,2})\s*(?:\+|\s*or more)?\s*years?(?:\s+of)?"  # noqa: RUF001
    r"(?:\s+(?:professional|industry|relevant|work|hands-on|software|engineering|full-time))*"
    r"\s+experience",
    re.IGNORECASE,
)
_CLASS_YEAR_RE = re.compile(
    r"(20\d\d)\s+(?:new\s+(?:college\s+)?grad|graduates?|university\s+grad|grad\b)"
    r"|new[\s\-](?:college[\s\-])?grad(?:uate)?s?[\s,(\-]+(20\d\d)"
    r"|class of (20\d\d)|(20\d\d)\s+(?:start|graduating)",
    re.IGNORECASE,
)


def full_time_aligned(
    *,
    title: str,
    description: str,
    early_career_title: bool,
    eligibility_level: str,
    start_min: date | None,
    earliest_start: date,
    earliest_class_year: int,
) -> bool:
    """Would a full-time role fit a candidate graduating in the given range?

    Needs an explicit entry-level signal (title, or a strong description
    phrase - a stray "university" in boilerplate is not enough), no 2+ years
    of required experience, no graduation-window mismatch, a target class
    year no earlier than the candidate's, and no start date before
    earliest_start. Unknown start/class year is allowed: most postings omit it.
    """
    text = f"{title}\n{description or ''}"
    if not (early_career_title or _STRONG_EARLY_DESC_RE.search(text)):
        return False
    if eligibility_level in ("likely_ineligible", "confirmed_ineligible"):
        return False
    if any(int(m.group(1)) >= 2 for m in _EXPERIENCE_RE.finditer(text)):
        return False
    years = [int(y) for m in _CLASS_YEAR_RE.finditer(text) for y in m.groups() if y]
    if years and max(years) < earliest_class_year:
        return False
    return start_min is None or start_min >= earliest_start


def notify_eligible(
    *,
    title: str,
    description: str,
    early_career_title: bool,
    eligibility_level: str,
    start_min: date | None,
    preferences,  # config.Preferences
    earliest_class_year: int,
) -> bool:
    """Internships always qualify; full-time roles per preferences.full_time_policy."""
    if is_internship(title, description):
        return True
    policy = preferences.full_time_policy
    if policy == "always":
        return True
    if policy == "never":
        return False
    return full_time_aligned(
        title=title,
        description=description,
        early_career_title=early_career_title,
        eligibility_level=eligibility_level,
        start_min=start_min,
        earliest_start=preferences.full_time_earliest_start,
        earliest_class_year=earliest_class_year,
    )


def _score_compensation(
    pay_hourly_max: float | None,
    remote_type: str,
    company_tier: str,
    cfg: CompensationScoring,
) -> float:
    """Posted pay: bonus when strong, penalty when low. Low pay is softened
    for remote roles or brand-name (core/strong) employers."""
    if pay_hourly_max is None:
        return 0.0
    if pay_hourly_max >= cfg.strong_hourly:
        return cfg.strong_bonus
    if pay_hourly_max >= cfg.good_hourly:
        return cfg.good_bonus
    if pay_hourly_max < cfg.low_hourly:
        softened = remote_type == "remote" or company_tier in ("core", "strong")
        return -(cfg.softened_low_penalty if softened else cfg.low_penalty)
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
    pay_hourly_max: float | None = None,
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
        _score_timing(
            season,
            scoring.target_windows,
            classification.is_early_career,
            today=(now or utcnow()).date(),
        ),
        2,
    )
    skill_points, matched_skills = _score_skills(text, profile)
    components["skills"] = round(skill_points, 2)
    result.matched_skills = matched_skills
    components["production_relevance"] = _score_production(text)
    components["location"] = _score_location(locations, remote_type, profile)
    components["freshness"] = _score_freshness(first_seen_at, now)
    components["compensation"] = _score_compensation(
        pay_hourly_max, remote_type, company_tier, scoring.compensation
    )
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
    us_accessible: bool = True,
    role_notifiable: bool = True,
) -> str:
    """Return one of: immediate, digest, dashboard, suppress (spec §13.5)."""
    now = now or utcnow()
    if score < thresholds_suppress:
        return "suppress"

    # Non-software roles never notify: company tier + timing + freshness can
    # push a civil/hardware intern past the digest bar on points alone, but
    # score is a ranking signal, not a role-fit override.
    if not classification.is_software:
        return "dashboard" if score >= thresholds_dashboard else "suppress"

    # Roles clearly workable only outside the US never notify either — a US
    # citizen can't take them without foreign work authorization.
    if not us_accessible:
        return "dashboard" if score >= thresholds_dashboard else "suppress"

    # Full-time roles outside the candidate's start/graduation fit (or any
    # full-time role, under an internships-only policy) never notify.
    if not role_notifiable:
        return "dashboard" if score >= thresholds_dashboard else "suppress"

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

    # Override: explicit Summer internship/new-grad SWE role at a core/strong
    # company whose start window is still ahead. Summer is the main season
    # and these postings close fast, so they are worth an immediate ping even
    # when a thin description keeps the score under the immediate bar.
    if (
        classification.is_software
        and classification.is_early_career
        and season.season == "summer"
        and season.confidence >= 0.9
        and season.start_min is not None
        and season.start_min >= now.date() - timedelta(days=30)
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
