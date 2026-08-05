from opportunity_radar.config import CandidateProfile
from opportunity_radar.matching.eligibility import evaluate

PROFILE = CandidateProfile()  # expected graduation 2027-12-01, unknowns null


def test_graduation_window_compatible():
    text = "Must be graduating between December 2026 and June 2028."
    result = evaluate(text, PROFILE)
    assert result.level in ("likely_eligible", "confirmed_eligible")
    assert result.graduation_min is not None
    assert result.eligibility_sentence is not None


def test_graduation_window_mismatch():
    text = "Only students graduating in December 2025 or earlier are eligible."
    result = evaluate(text, PROFILE)
    assert "graduation_window_mismatch" in result.flags
    assert result.level in ("likely_ineligible", "confirmed_ineligible")


def test_citizenship_required_unknown_status():
    text = "Applicants must be a U.S. citizen due to contract requirements."
    result = evaluate(text, PROFILE)
    assert result.citizenship_required is True
    assert "us_citizenship_required" in result.flags
    assert "citizenship_status_unconfigured" in result.flags


def test_citizenship_required_noncitizen_ineligible():
    profile = CandidateProfile(us_citizen=False)
    text = "U.S. citizenship is required for this role."
    result = evaluate(text, profile)
    assert result.level == "confirmed_ineligible"


def test_clearance_detection():
    text = "Must be able to obtain and maintain a security clearance."
    result = evaluate(text, PROFILE)
    assert result.clearance_required is True
    assert "security_clearance_required" in result.flags


def test_sponsorship_unavailable():
    text = "We are unable to sponsor visas for this position."
    result = evaluate(text, PROFILE)
    assert "sponsorship_not_available" in result.flags
    assert result.work_authorization_text is not None


def test_sponsorship_unavailable_needs_sponsorship():
    profile = CandidateProfile(requires_sponsorship=True)
    text = "We will not sponsor employment visas."
    result = evaluate(text, profile)
    assert result.level in ("likely_ineligible", "confirmed_ineligible")


def test_return_to_school_flag():
    text = "You must be returning to school for at least one quarter after the internship."
    result = evaluate(text, PROFILE)
    assert result.requires_return_to_school is True
    assert "requires_full_academic_term_after_internship" in result.flags


def test_fall_2027_conflict():
    text = "Interns must be returning to school after the program ends."
    result = evaluate(text, PROFILE, season="fall", season_year=2027)
    assert "fall_2027_conflicts_with_expected_graduation" in result.flags


def test_phd_only():
    text = "Candidates must be enrolled in a PhD program."
    result = evaluate(text, PROFILE)
    assert "phd_only" in result.flags
    assert result.level in ("likely_ineligible", "confirmed_ineligible")


def test_graduate_students_only():
    text = "This internship is for master's students only."
    result = evaluate(text, PROFILE)
    assert "graduate_students_only" in result.flags


def test_full_time_required():
    text = "Requires full-time availability of 40 hours per week during the program."
    result = evaluate(text, PROFILE)
    assert result.full_time_required is True


def test_no_signals_uncertain():
    result = evaluate("Write code. Ship products.", PROFILE)
    assert result.level == "uncertain"


def test_or_later_graduation():
    text = "Expected graduation date of December 2026 or later."
    result = evaluate(text, PROFILE)
    assert result.level in ("likely_eligible", "confirmed_eligible")
