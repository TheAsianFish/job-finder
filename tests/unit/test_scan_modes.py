"""`scan --mode hot|auto`: hot set selection and full-scan cadence."""

from __future__ import annotations

from datetime import timedelta

import pytest

from opportunity_radar.cli import LAST_FULL_SCAN_KEY, _hot_companies, _resolve_scan_mode
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base
from opportunity_radar.models.company import CompanySource
from opportunity_radar.utilities.dates import utcnow


@pytest.fixture()
def db(tmp_path):
    reset_engine()
    engine = get_engine(f"sqlite:///{tmp_path}/modes.db")  # becomes the default engine
    Base.metadata.create_all(engine)
    yield
    reset_engine()


def _set_last_full(minutes_ago: int) -> None:
    with session_scope() as session:
        repo.meta_set(
            session, LAST_FULL_SCAN_KEY, (utcnow() - timedelta(minutes=minutes_ago)).isoformat()
        )


def test_hot_set_is_core_and_strong_plus_secondary_feeds():
    companies = [
        CompanySource(id="google-ish", name="Core", tier="core", adapter="greenhouse"),
        CompanySource(id="strongco", name="Strong", tier="strong", adapter="greenhouse"),
        CompanySource(id="broadco", name="Broad", tier="broad", adapter="greenhouse"),
        CompanySource(id="simplify-internships", name="S", tier="broad", adapter="simplify"),
    ]
    assert [c.id for c in _hot_companies(companies)] == [
        "google-ish",
        "strongco",
        "simplify-internships",
    ]


def test_explicit_modes_pass_through(db):
    assert _resolve_scan_mode("full", 60) == "full"
    assert _resolve_scan_mode("hot", 60) == "hot"


def test_auto_runs_full_first_then_hot_until_due(db):
    assert _resolve_scan_mode("auto", 60) == "full"  # never ran a full scan
    _set_last_full(10)
    assert _resolve_scan_mode("auto", 60) == "hot"
    _set_last_full(56)  # within the 5-minute grace of the hour
    assert _resolve_scan_mode("auto", 60) == "full"


def test_auto_treats_garbage_timestamp_as_due(db):
    with session_scope() as session:
        repo.meta_set(session, LAST_FULL_SCAN_KEY, "not-a-date")
    assert _resolve_scan_mode("auto", 60) == "full"
