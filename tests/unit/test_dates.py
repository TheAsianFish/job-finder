from datetime import UTC, datetime

from opportunity_radar.utilities.dates import humanize_age, parse_date, parse_datetime


def test_parse_datetime_iso():
    parsed = parse_datetime("2026-08-05T12:00:00Z")
    assert parsed == datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def test_parse_datetime_epoch_millis():
    parsed = parse_datetime(1754400000000)
    assert parsed is not None and parsed.year == 2025


def test_parse_datetime_garbage_returns_none():
    assert parse_datetime("not a date at all zzz") is None
    assert parse_datetime(None) is None


def test_parse_date():
    assert parse_date("2027-06-15") is not None
    assert parse_date(None) is None


def test_humanize_age():
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    assert humanize_age(datetime(2026, 8, 5, 11, 52, tzinfo=UTC), now) == "8 minutes ago"
    assert humanize_age(datetime(2026, 8, 5, 9, 0, tzinfo=UTC), now) == "3 hours ago"
    assert humanize_age(None, now) == "unknown"
