"""Extract explicitly posted pay from job description text.

Pay-transparency laws mean most US postings state a range ("$40 - $55 per
hour", "$120,000 - $150,000 annually"). Only an explicit dollar figure with
a clear period is extracted; nothing is estimated (spec: never invent
compensation). Annual figures convert to hourly at 2,080 hours for scoring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

_AMOUNT = r"\$\s?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d{1,2})?)\s?(k|K)?"
_RANGE_RE = re.compile(
    rf"{_AMOUNT}(?:\s?(?:-|–|—|to)\s?{_AMOUNT})?"  # noqa: RUF001
    r"(?:\s?(?:USD|usd))?\s?"
    r"(?P<period>/\s?(?:hr|hour)|per\s+hour|an\s+hour|hourly"
    r"|/\s?(?:yr|year)|per\s+(?:year|annum)|annual(?:ly)?|a\s+year|/\s?month|per\s+month|monthly)?",
)
HOURS_PER_YEAR = 2080


@dataclass(frozen=True)
class Pay:
    minimum: Decimal
    maximum: Decimal
    period: str  # "hour" | "year" | "month"

    @property
    def hourly_max(self) -> float:
        return _to_hourly(float(self.maximum), self.period)

    @property
    def hourly_min(self) -> float:
        return _to_hourly(float(self.minimum), self.period)


def _to_hourly(value: float, period: str) -> float:
    if period == "year":
        return value / HOURS_PER_YEAR
    if period == "month":
        return value * 12 / HOURS_PER_YEAR
    return value


def _number(text: str, k: str | None) -> Decimal:
    value = Decimal(text.replace(",", ""))
    return value * 1000 if k else value


def _period(raw: str | None, amount: Decimal) -> str | None:
    if raw:
        lowered = raw.lower()
        if "h" in lowered and ("hr" in lowered or "hour" in lowered):
            return "hour"
        if "month" in lowered:
            return "month"
        return "year"
    # No explicit period: only magnitudes that cannot be ambiguous.
    if amount >= 20000:
        return "year"
    return None


def extract_pay(text: str) -> Pay | None:
    """Return the first plausible explicit USD pay statement, if any."""
    for match in _RANGE_RE.finditer(text or ""):
        low = _number(match.group(1), match.group(2))
        high = _number(match.group(3), match.group(4)) if match.group(3) else low
        if high < low:
            low, high = high, low
        period = _period(match.group("period"), high)
        if period is None:
            continue
        hourly = _to_hourly(float(high), period)
        if not 12 <= hourly <= 400:  # signing bonuses, revenue figures, typos
            continue
        return Pay(minimum=low, maximum=high, period=period)
    return None
