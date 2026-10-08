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


def test_is_us_accessible():
    from opportunity_radar.matching.scorer import is_us_accessible

    assert is_us_accessible(["San Francisco, CA"])
    assert is_us_accessible(["Portland, OR"])
    assert is_us_accessible(["Remote"])
    assert is_us_accessible([])  # unknown location never gates
    assert is_us_accessible(["Austin, TX; Lisbon, Portugal"])  # US option exists
    assert not is_us_accessible(["Lisbon, Portugal"])
    assert not is_us_accessible(["Remote - Portugal"])
    assert not is_us_accessible(["London or Dublin"])  # 'or' is not Oregon
    assert not is_us_accessible(["London, UK"])
    assert not is_us_accessible(["Bangalore, India"])
    # Non-USD pay marks a non-US payroll even when the location is vague.
    assert not is_us_accessible(["Remote"], compensation_currency="EUR")
    assert is_us_accessible(["Remote"], compensation_currency="USD")


def test_non_us_role_capped_at_dashboard():
    """A Lisbon-based role must never notify a US-only candidate, whatever
    its score (regression: Cloudflare Portugal intern alerted at high score)."""
    level = decide_alert_level(
        score=80,
        season=parse_season("Software Engineer Intern - Summer 2027"),
        classification=classify("Software Engineer Intern - Summer 2027"),
        company_tier="core",
        posted_at=None,
        deadline=None,
        thresholds_immediate=82,
        thresholds_digest=60,
        thresholds_dashboard=35,
        thresholds_suppress=20,
        now=NOW,
        us_accessible=False,
    )
    assert level == "dashboard"


def test_non_us_remote_gets_no_remote_bonus():
    result = _score(
        "Software Engineer Intern", "Python.", locations=["Remote - Portugal"], remote="remote"
    )
    assert result.components["location"] == 0.0


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


def _decide(title, description, tier="strong", score=70.0, now=NOW):
    classification = classify(title, description)
    season = parse_season(title, description)
    return decide_alert_level(
        score=score,
        season=season,
        classification=classification,
        company_tier=tier,
        posted_at=None,
        deadline=None,
        thresholds_immediate=78,
        thresholds_digest=50,
        thresholds_dashboard=35,
        thresholds_suppress=20,
        now=now,
    )


def test_explicit_summer_swe_intern_at_strong_company_is_immediate():
    level = _decide("Software Engineer Intern (Summer 2027)", "Join us for 12 weeks.", score=65)
    assert level == "immediate"


def test_summer_override_needs_core_or_strong_tier():
    level = _decide("Software Engineer Intern (Summer 2027)", "Join us.", tier="broad", score=65)
    assert level == "digest"


def test_summer_override_ignores_past_seasons():
    # Summer 2026 has already started relative to NOW (Aug 2026): no override.
    level = _decide("Software Engineer Intern (Summer 2026)", "Join us.", score=65)
    assert level == "digest"


def test_summer_override_still_requires_software_role():
    level = _decide("Marketing Intern (Summer 2027)", "Campaigns.", score=65)
    assert level == "dashboard"


def test_off_season_windows_reward_winter_and_fall_roles():
    # Winter 2027 overlaps the winter_2027 / spring_2027 windows.
    winter = _score("Software Engineer Intern - Winter 2027", "Build backend services.")
    fall = _score("Software Engineer Intern - Fall 2026", "Build backend services.")
    off = _score("Software Engineer Intern - Fall 2025", "Build backend services.")
    assert winter.components["timing"] >= 18.0
    assert fall.components["timing"] >= 14.0
    assert off.components["timing"] == 2.0


def test_expired_target_windows_are_ignored():
    from datetime import date

    from opportunity_radar.config import TargetWindow

    expired = ScoringConfig(
        target_windows=[
            TargetWindow(name="old", start=date(2025, 5, 15), end=date(2025, 9, 15), priority=100)
        ]
    )
    classification = classify("Software Engineer Intern - Summer 2025", "")
    season = parse_season("Software Engineer Intern - Summer 2025", "")
    eligibility = evaluate("", PROFILE.candidate, season.season, season.year)
    result = score_job(
        title="Software Engineer Intern - Summer 2025",
        description_text="",
        locations=["Austin, TX"],
        remote_type="onsite",
        company_tier="core",
        classification=classification,
        season=season,
        eligibility=eligibility,
        first_seen_at=NOW,
        profile=PROFILE,
        scoring=expired,
        now=NOW,
    )
    # No live window left -> treated like "season known, no overlap" (7 pts
    # for an early-career role), never a stale 20.
    assert result.components["timing"] <= 7.0


def test_internship_detection():
    from opportunity_radar.matching.scorer import is_internship

    assert is_internship("Software Engineer Intern")
    assert is_internship("Backend Co-op (Spring)")
    assert is_internship("Software Engineer - Summer 2027")
    assert is_internship("Software Engineer", "Internship listed on the Simplify internships list.")
    assert not is_internship("Graduate Software Engineer (DV Commodities)")
    assert not is_internship("Mission Software Engineer, Mission Systems")
    assert not is_internship("Internal Tools Engineer")


def test_full_time_roles_never_notify_when_internships_only():
    title = "AI Engineer"
    classification = classify(title, "")
    season = parse_season(title, "")
    kwargs = dict(
        score=90.0,
        season=season,
        classification=classification,
        company_tier="core",
        posted_at=None,
        deadline=None,
        thresholds_immediate=78,
        thresholds_digest=50,
        thresholds_dashboard=35,
        thresholds_suppress=20,
        now=NOW,
        internship=False,
    )
    assert decide_alert_level(**kwargs, require_internship=True) == "dashboard"
    assert decide_alert_level(**kwargs, require_internship=False) == "immediate"


def test_posted_pay_adjusts_score():
    from opportunity_radar.config import CompensationScoring
    from opportunity_radar.matching.scorer import _score_compensation

    cfg = CompensationScoring()
    assert _score_compensation(None, "onsite", "broad", cfg) == 0.0
    assert _score_compensation(55.0, "onsite", "broad", cfg) == cfg.strong_bonus
    assert _score_compensation(42.0, "onsite", "broad", cfg) == cfg.good_bonus
    assert _score_compensation(30.0, "onsite", "broad", cfg) == 0.0
    assert _score_compensation(20.0, "onsite", "broad", cfg) == -cfg.low_penalty
    # Low pay is softened by remote work or a brand-name employer.
    assert _score_compensation(20.0, "remote", "broad", cfg) == -cfg.softened_low_penalty
    assert _score_compensation(20.0, "onsite", "core", cfg) == -cfg.softened_low_penalty


def test_no_location_preference_makes_any_us_location_ideal():
    from opportunity_radar.matching.scorer import _score_location

    open_profile = ProfileConfig()
    open_profile.preferences.preferred_locations = []
    assert _score_location(["Omaha, NE"], "onsite", open_profile) == 5.0
    assert _score_location(["Omaha, NE"], "onsite", ProfileConfig()) == 4.0
