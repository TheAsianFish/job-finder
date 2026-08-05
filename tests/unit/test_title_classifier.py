from opportunity_radar.matching.title_classifier import classify


def test_swe_intern_classified():
    result = classify("Software Engineer Intern")
    assert result.is_software
    assert result.is_early_career
    assert result.role_family == "general_swe"
    assert not result.hard_excluded


def test_backend_family_detected():
    result = classify("Backend Engineer Intern - Summer 2027")
    assert result.role_family == "backend"
    assert result.is_early_career


def test_ml_family_detected():
    assert classify("Machine Learning Engineer Intern").role_family == "ml_systems"


def test_senior_hard_excluded():
    result = classify("Senior Software Engineer")
    assert result.hard_excluded
    assert result.seniority == "senior_plus"


def test_senior_not_excluded_when_intern_in_title():
    # Vague seniority + explicit intern signal must not hard-exclude.
    result = classify("Software Engineering Intern, Senior Design Team")
    assert not result.hard_excluded


def test_sales_engineer_excluded():
    assert classify("Sales Engineer").hard_excluded


def test_mechanical_only_irrelevant():
    result = classify("Mechanical Engineer Intern")
    assert result.role_family == "irrelevant"
    assert not result.is_software


def test_mixed_hardware_software_kept():
    result = classify("Embedded Software Engineer Intern")
    assert result.is_software
    assert result.role_family == "embedded"


def test_new_grad_signal():
    result = classify("Software Engineer, New Grad 2028")
    assert result.is_early_career
    assert result.is_software


def test_coop_variants():
    assert classify("Software Co-op").is_early_career
    assert classify("Software Coop").is_early_career
    assert classify("Software Co op").is_early_career


def test_sde_abbreviation():
    assert classify("SDE Intern").is_software


def test_description_exclusion_downranks_not_excludes():
    result = classify("Software Engineer", "We require 10+ years of experience.")
    assert not result.hard_excluded
    assert any("10+ years" in flag for flag in result.downrank_flags)


def test_engineering_intern_without_family_keyword():
    result = classify("Engineering Intern")
    assert result.is_software
    assert result.role_family == "general_swe"


def test_quant_developer_family():
    assert classify("Quantitative Developer Intern").role_family == "quant_developer"


def test_marketing_excluded():
    assert classify("Marketing Manager").hard_excluded


def test_sre_family():
    assert classify("Site Reliability Engineer Intern").role_family == "infrastructure"
