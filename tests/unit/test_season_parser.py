from datetime import date

from opportunity_radar.matching.season_parser import parse_season


def test_explicit_title_season_year():
    result = parse_season("Spring 2027 Software Engineering Intern")
    assert result.season == "spring"
    assert result.year == 2027
    assert result.confidence == 1.0
    assert result.start_min is not None and result.start_min.year == 2027


def test_year_before_season():
    result = parse_season("2027 Summer Intern - Backend")
    assert result.season == "summer"
    assert result.year == 2027
    assert result.confidence == 1.0


def test_description_season():
    result = parse_season("Software Intern", "This role is part of our Summer 2027 program.")
    assert result.season == "summer"
    assert result.year == 2027
    assert result.confidence == 0.9


def test_start_month_phrase():
    result = parse_season("Software Intern", "Starts January or February 2027.")
    assert result.season == "winter"
    assert result.year == 2027
    assert result.confidence == 0.9


def test_duration_and_start_months():
    result = parse_season(
        "Software Intern", "This is a 12-week internship with start dates in Aug/Sept."
    )
    assert result.duration_weeks == 12
    assert result.season == "fall"
    # No year given: not a confirmed window.
    assert result.year is None
    assert result.confidence < 0.9


def test_generic_intern_stays_unspecified():
    result = parse_season("Software Intern", "Join our team and build great things.")
    assert result.season == "unspecified"
    assert result.confidence == 0.0


def test_off_cycle_title():
    result = parse_season("Software Engineer Intern (Off-Cycle)")
    assert result.season == "off_cycle"
    assert result.confidence == 1.0


def test_year_round_description():
    result = parse_season("Software Intern", "We hire year-round interns on a rolling basis.")
    assert result.season == "year_round"


def test_explicit_start_date_field():
    result = parse_season("Software Intern", "", explicit_start=date(2027, 1, 15))
    assert result.season == "winter"
    assert result.year == 2027
    assert result.confidence == 0.95


def test_quarter_notation():
    result = parse_season("Software Intern", "The program runs in Q2 2027.")
    assert result.season == "spring"
    assert result.year == 2027


def test_season_without_year_lower_confidence():
    result = parse_season("Fall Software Engineering Intern")
    assert result.season == "fall"
    assert result.year is None
    assert result.confidence == 0.7


def test_autumn_maps_to_fall():
    result = parse_season("Autumn 2027 Software Intern")
    assert result.season == "fall"
    assert result.year == 2027
