"""Date parsing helpers. Conservative: return None rather than guess."""

from __future__ import annotations

from datetime import UTC, date, datetime

from dateutil import parser as dateutil_parser


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Coerce naive datetimes (e.g. read back from SQLite) to UTC-aware."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def parse_datetime(value: str | int | float | datetime | None) -> datetime | None:
    """Parse an ISO timestamp, epoch millis/seconds, or common date string.

    Returns timezone-aware UTC datetimes; naive inputs are assumed UTC.
    Returns None on anything ambiguous or unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float):
        # Heuristic: values above 10^11 are epoch milliseconds.
        seconds = value / 1000.0 if value > 100_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = dateutil_parser.parse(text)
    except (ValueError, OverflowError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_date(value: str | datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = parse_datetime(value)
    return parsed.date() if parsed else None


def humanize_age(moment: datetime | None, now: datetime | None = None) -> str:
    """'8 minutes ago' style rendering for alerts and dashboard."""
    if moment is None:
        return "unknown"
    now = now or utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    delta = now - moment
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    months = days // 30
    return f"{months} month{'s' if months != 1 else ''} ago"
