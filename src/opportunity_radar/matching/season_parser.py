"""Season and start-window inference (spec §11).

Priority: explicit title > explicit description > start-date fields >
date ranges > program names > posting-month heuristic (low confidence only).
A low-confidence inference is never presented as confirmed: confidence is
carried on every result and callers must respect it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_SEASON_WORDS = {
    "winter": "winter",
    "spring": "spring",
    "summer": "summer",
    "fall": "fall",
    "autumn": "fall",
}

_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_MONTH_TO_SEASON = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "fall",
    10: "fall",
    11: "fall",
}

# Canonical start windows per season (inference aids, never "confirmed" dates).
_SEASON_START_WINDOWS = {
    "winter": ((1, 1), (3, 31)),
    "spring": ((1, 1), (6, 15)),
    "summer": ((5, 15), (9, 15)),
    "fall": ((8, 1), (12, 31)),
}

_SEASON_YEAR_RE = re.compile(
    r"(winter|spring|summer|fall|autumn)\s*(?:of\s+|['’]?)?(20\d{2})",  # noqa: RUF001
    re.IGNORECASE,
)
_YEAR_SEASON_RE = re.compile(r"(20\d{2})\s*(winter|spring|summer|fall|autumn)", re.IGNORECASE)
_SEASON_ONLY_RE = re.compile(
    r"(?<![a-z])(winter|spring|summer|fall|autumn)(?![a-z])", re.IGNORECASE
)
_OFF_CYCLE_RE = re.compile(r"off[\s\-]?cycle", re.IGNORECASE)
_YEAR_ROUND_RE = re.compile(r"year[\s\-]?round", re.IGNORECASE)
_DURATION_RE = re.compile(r"(\d{1,2})\s*[-–]?\s*(?:week|wk)s?", re.IGNORECASE)  # noqa: RUF001
_QUARTER_RE = re.compile(r"(?<![a-z])q([1-4])\s*(20\d{2})", re.IGNORECASE)


@dataclass
class SeasonResult:
    season: str = "unspecified"
    year: int | None = None
    confidence: float = 0.0
    start_min: date | None = None
    start_max: date | None = None
    duration_weeks: int | None = None
    evidence: str | None = None


def _window_for(season: str, year: int | None) -> tuple[date | None, date | None]:
    if year is None or season not in _SEASON_START_WINDOWS:
        return None, None
    (m1, d1), (m2, d2) = _SEASON_START_WINDOWS[season]
    return date(year, m1, d1), date(year, m2, d2)


def _explicit_season(text: str) -> tuple[str, int | None, str] | None:
    match = _SEASON_YEAR_RE.search(text)
    if match:
        return _SEASON_WORDS[match.group(1).lower()], int(match.group(2)), match.group(0)
    match = _YEAR_SEASON_RE.search(text)
    if match:
        return _SEASON_WORDS[match.group(2).lower()], int(match.group(1)), match.group(0)
    return None


def _quarter_season(text: str) -> tuple[str, int, str] | None:
    match = _QUARTER_RE.search(text)
    if not match:
        return None
    quarter = int(match.group(1))
    year = int(match.group(2))
    season = {1: "winter", 2: "spring", 3: "summer", 4: "fall"}[quarter]
    return season, year, match.group(0)


_MONTH_ALTS = (
    r"january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|"
    r"august|aug|september|sept|sep|october|oct|november|nov|december|dec"
)


def _start_month_season(text: str) -> tuple[str, int | None, str] | None:
    """'starts in January 2027' / 'start dates in Aug/Sept' style phrases.

    When two months are named and they straddle a season boundary (Aug/Sept),
    the later month wins: an August/September start is a fall program.
    """
    pattern = re.compile(
        rf"start(?:s|ing|\s+dates?)?\b[^.\n]{{0,80}}?"
        rf"\b({_MONTH_ALTS})\b"
        rf"(?:\s*(?:or|and|/|,|-|–)\s*\b({_MONTH_ALTS})\b)?"  # noqa: RUF001
        rf"[^.\n]{{0,40}}?\b(20\d{{2}})\b|"
        rf"start(?:s|ing|\s+dates?)?\b[^.\n]{{0,80}}?"
        rf"\b({_MONTH_ALTS})\b"
        rf"(?:\s*(?:or|and|/|,|-|–)\s*\b({_MONTH_ALTS})\b)?",  # noqa: RUF001
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    if match.group(1):
        first, second, year_text = match.group(1), match.group(2), match.group(3)
    else:
        first, second, year_text = match.group(4), match.group(5), None
    months = [_MONTHS[first.lower()]]
    if second:
        months.append(_MONTHS[second.lower()])
    seasons = [_MONTH_TO_SEASON[m] for m in months]
    season = seasons[-1] if len(set(seasons)) > 1 else seasons[0]
    year = int(year_text) if year_text else None
    return season, year, match.group(0)


def parse_season(
    title: str,
    description: str = "",
    explicit_start: date | None = None,
) -> SeasonResult:
    result = SeasonResult()
    title_text = title or ""
    desc_text = description or ""

    match = _DURATION_RE.search(f"{title_text}\n{desc_text}")
    if match:
        weeks = int(match.group(1))
        if 4 <= weeks <= 52:
            result.duration_weeks = weeks

    # 1. Explicit season+year in the title — authoritative.
    found = _explicit_season(title_text)
    if found:
        result.season, result.year, result.evidence = found
        result.confidence = 1.0
        result.start_min, result.start_max = _window_for(result.season, result.year)
        return result

    if _OFF_CYCLE_RE.search(title_text):
        result.season = "off_cycle"
        result.confidence = 1.0
        result.evidence = _OFF_CYCLE_RE.search(title_text).group(0)  # type: ignore[union-attr]
        year_match = re.search(r"20\d{2}", title_text)
        if year_match:
            result.year = int(year_match.group(0))
        return result

    if _YEAR_ROUND_RE.search(title_text) or _YEAR_ROUND_RE.search(desc_text):
        result.season = "year_round"
        result.confidence = 0.9 if _YEAR_ROUND_RE.search(title_text) else 0.8
        result.evidence = "year-round"
        return result

    # 2. Explicit season+year in the description.
    found = _explicit_season(desc_text)
    if found:
        result.season, result.year, result.evidence = found
        result.confidence = 0.9
        result.start_min, result.start_max = _window_for(result.season, result.year)
        return result

    # 3. Explicit start-date field from the source.
    if explicit_start is not None:
        result.season = _MONTH_TO_SEASON[explicit_start.month]
        result.year = explicit_start.year
        result.confidence = 0.95
        result.start_min = result.start_max = explicit_start
        result.evidence = f"start date {explicit_start.isoformat()}"
        return result

    # 4. Start-month phrases in the description.
    found = _start_month_season(desc_text)
    if found:
        result.season, result.year, result.evidence = found
        result.confidence = 0.9 if result.year else 0.85
        result.start_min, result.start_max = _window_for(result.season, result.year)
        return result

    # Quarter naming (Q1 2027).
    quarter = _quarter_season(f"{title_text}\n{desc_text}")
    if quarter:
        result.season, result.year, result.evidence = quarter
        result.confidence = 0.8
        result.start_min, result.start_max = _window_for(result.season, result.year)
        return result

    if _OFF_CYCLE_RE.search(desc_text):
        result.season = "off_cycle"
        result.confidence = 0.7
        result.evidence = "off-cycle (description)"
        return result

    # 5. Season word without a year (title only — descriptions are too noisy).
    season_only = _SEASON_ONLY_RE.search(title_text)
    if season_only:
        result.season = _SEASON_WORDS[season_only.group(1).lower()]
        result.confidence = 0.7
        result.evidence = season_only.group(0)
        year_match = re.search(r"20\d{2}", title_text)
        if year_match:
            result.year = int(year_match.group(0))
            result.confidence = 0.9
            result.start_min, result.start_max = _window_for(result.season, result.year)
        return result

    # 6. No posting-month heuristic promotion: a generic "Software Intern"
    #    posted in November stays "unspecified" (spec §11.2).
    return result
