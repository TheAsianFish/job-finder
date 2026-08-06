"""Feedback tuning: deterministic, bounded, explainable."""

from __future__ import annotations

import pytest

from opportunity_radar.config import ScoringConfig
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base
from opportunity_radar.models.company import CompanySource
from opportunity_radar.tuning import FeedbackStats, compute_adjustments, run_tune
from opportunity_radar.utilities.dates import utcnow
from tests.unit.test_db import alias_hashes, make_record


def test_family_weight_boost_on_positive_signals():
    stats = FeedbackStats(family_pos={"robotics": 4}, family_neg={"robotics": 1}, total_events=5)
    report = compute_adjustments(stats, ScoringConfig())
    changes = {a.key: a for a in report.adjustments}
    assert "role_family_weights.robotics" in changes
    assert changes["role_family_weights.robotics"].new == 15.0  # 14 + 1


def test_family_weight_drop_on_dismissals():
    stats = FeedbackStats(family_neg={"frontend": 4}, family_pos={"frontend": 1}, total_events=5)
    report = compute_adjustments(stats, ScoringConfig())
    changes = {a.key: a for a in report.adjustments}
    assert changes["role_family_weights.frontend"].new == 11.0  # 12 - 1


def test_minimum_sample_size_respected():
    stats = FeedbackStats(family_pos={"backend": 2}, total_events=2)
    report = compute_adjustments(stats, ScoringConfig())
    assert not report.adjustments


def test_weight_never_exceeds_cap():
    stats = FeedbackStats(family_pos={"backend": 10}, total_events=10)
    report = compute_adjustments(stats, ScoringConfig())
    # backend already at cap 20 -> no adjustment offered
    assert all(a.key != "role_family_weights.backend" for a in report.adjustments)


def test_threshold_raises_when_alerts_dismissed():
    stats = FeedbackStats(alerted_neg=5, alerted_pos=0, total_events=5)
    report = compute_adjustments(stats, ScoringConfig())
    changes = {a.key: a for a in report.adjustments}
    assert changes["alerts.immediate_min_score"].new == 84


def test_threshold_lowers_when_digest_jobs_saved():
    stats = FeedbackStats(digest_band_pos=6, total_events=6)
    report = compute_adjustments(stats, ScoringConfig())
    changes = {a.key: a for a in report.adjustments}
    assert changes["alerts.immediate_min_score"].new == 80


def test_company_suggestions_never_auto_applied():
    stats = FeedbackStats(company_neg={"boringco": 4}, total_events=4)
    report = compute_adjustments(stats, ScoringConfig())
    assert not report.adjustments
    assert any("boringco" in s for s in report.suggestions)


@pytest.fixture()
def db(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/tune.db"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    yield url
    reset_engine()


def test_run_tune_end_to_end_no_apply(db):
    with session_scope(db) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe")])
        for index in range(4):
            record = make_record(str(index), f"Robotics Software Intern {index}")
            record = record.model_copy(update={"role_family": "robotics"})
            row = repo.insert_job(session, record, alias_hashes(record))
            row.role_family = "robotics"
            row.alerted_at = utcnow()
            repo.set_application_status(session, row.id, "saved")
    report = run_tune(apply=False, db_url=db)
    assert report.feedback_events == 4
    assert any(a.key == "role_family_weights.robotics" for a in report.adjustments)
