from datetime import UTC, datetime, timedelta

from opportunity_radar.config import ProfileConfig, ScoringConfig
from opportunity_radar.matching.eligibility import evaluate
from opportunity_radar.matching.scorer import decide_alert_level, score_job
from opportunity_radar.matching.season_parser import parse_season
from opportunity_radar.matching.title_classifier import classify

PROFILE = ProfileConfig()
SCORING = ScoringConfig()
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def _score(title, description, tier="core", first_seen=None, locations=None, remote="unknown"):
    classification = classify(title, description)
    season = parse_season(title, description)
    eligibility = evaluate(description, PROFILE.candidate, season.season, season.year)
    return score_job(
        title=title,
        description_text=description,
        locations=locations or ["San Francisco, CA"],
        remote_type=remote,
        company_tier=tier,
        classification=classification,
        season=season,
        eligibility=eligibility,
        first_seen_at=first_seen or NOW,
        profile=PROFILE,
        scoring=SCORING,
        now=NOW,
    )


def test_ideal_role_scores_high():
    result = _score(
        "Software Engineer Intern - Summer 2027",
        "Work on distributed systems in Python and Java with Docker and Kubernetes. "
        "Build production cloud infrastructure with PostgreSQL databases. "
        "Must be graduating between December 2026 and June 2028.",
        first_seen=NOW - timedelta(hours=2),
    )
    assert result.total >= 82
    assert not result.suppressed
    assert "Python" in result.matched_skills


def test_senior_role_suppressed():
    result = _score("Senior Software Engineer", "10 years of experience required.")
    assert result.suppressed


def test_irrelevant_role_scores_low():
    result = _score(
        "Marketing Coordinator Intern",
        "Support our social media campaigns.",
        tier="exploratory",
    )
    assert result.total < 35


def test_off_season_role_gets_timing_boost():
    spring = _score(
        "Spring 2027 Software Engineering Intern",
        "Backend Python development on production systems.",
    )
    unspecified = _score(
        "Software Engineering Intern",
        "Backend Python development on production systems.",
    )
    assert spring.components["timing"] > unspecified.components["timing"]


def test_wrong_year_gets_low_timing():
    result = _score("Summer 2026 Software Engineering Intern", "Python development.")
    assert result.components["timing"] <= 4.0


def test_score_components_recorded():
    result = _score("Software Engineer Intern", "Python and React development.")
    for key in (
        "company_quality",
        "role_fit",
        "timing",
        "skills",
        "production_relevance",
        "location",
        "freshness",
        "eligibility_adjustment",
        "risk_adjustment",
    ):
        assert key in result.components


def test_company_tier_does_not_overwhelm_relevance():
    core_irrelevant = _score("Accountant Intern", "Prepare financial statements.", tier="core")
    broad_relevant = _score(
        "Backend Software Engineer Intern - Summer 2027",
        "Python, distributed systems, production infrastructure. Graduating between 2026 and 2028.",
        tier="broad",
    )
    assert broad_relevant.total > core_irrelevant.total


def test_immediate_alert_for_high_score():
    level = decide_alert_level(
        score=90,
        season=parse_season("Summer 2027 SWE Intern"),
        classification=classify("Summer 2027 SWE Intern"),
        company_tier="core",
        posted_at=None,
        deadline=None,
        thresholds_immediate=82,
        thresholds_digest=60,
        thresholds_dashboard=35,
        thresholds_suppress=20,
        now=NOW,
    )
    assert level == "immediate"


def test_immediate_override_for_explicit_offseason_at_core():
    level = decide_alert_level(
        score=70,  # below immediate threshold
        season=parse_season("Spring 2027 Software Engineer Intern"),
        classification=classify("Spring 2027 Software Engineer Intern"),
        company_tier="core",
        posted_at=None,
        deadline=None,
        thresholds_immediate=82,
        thresholds_digest=60,
        thresholds_dashboard=35,
        thresholds_suppress=20,
        now=NOW,
    )
    assert level == "immediate"


def test_fresh_posting_override():
    level = decide_alert_level(
        score=76,
        season=parse_season("Software Engineer Intern"),
        classification=classify("Software Engineer Intern"),
        company_tier="broad",
        posted_at=NOW - timedelta(hours=3),
        deadline=None,
        thresholds_immediate=82,
        thresholds_digest=60,
        thresholds_dashboard=35,
        thresholds_suppress=20,
        now=NOW,
    )
    assert level == "immediate"


def test_non_software_role_capped_at_dashboard():
    """A civil/hardware intern can out-score the digest bar on company tier +
    timing alone; role fit must gate notifications regardless of score."""
    level = decide_alert_level(
        score=74,
        season=parse_season("2027 Electrical Engineer Intern"),
        classification=classify("2027 Electrical Engineer Intern"),
        company_tier="core",
        posted_at=None,
        deadline=None,
        thresholds_immediate=82,
        thresholds_digest=60,
        thresholds_dashboard=35,
        thresholds_suppress=20,
        now=NOW,
    )
    assert level == "dashboard"


def test_low_score_suppressed():
    level = decide_alert_level(
        score=10,
        season=parse_season("Something"),
        classification=classify("Something"),
        company_tier="broad",
        posted_at=None,
        deadline=None,
        thresholds_immediate=82,
        thresholds_digest=60,
        thresholds_dashboard=35,
        thresholds_suppress=20,
        now=NOW,
    )
    assert level == "suppress"
