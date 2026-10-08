import pytest

from opportunity_radar.utilities.pay import extract_pay


@pytest.mark.parametrize(
    ("text", "period", "low", "high"),
    [
        ("The hourly rate for this role is $45 - $55 per hour.", "hour", 45, 55),
        ("Pay: $42/hr", "hour", 42, 42),
        ("Base salary range: $120,000 - $150,000 annually", "year", 120000, 150000),
        ("Compensation $130k–$160k USD", "year", 130000, 160000),  # noqa: RUF001
        ("Interns earn $8,000/month", "month", 8000, 8000),
        ("Expected range $38.50 to $52.00 hourly", "hour", 38.5, 52),
    ],
)
def test_extracts_explicit_pay(text, period, low, high):
    pay = extract_pay(text)
    assert pay is not None
    assert pay.period == period
    assert float(pay.minimum) == low and float(pay.maximum) == high


def test_hourly_conversion():
    assert extract_pay("$104,000 per year").hourly_max == 50.0


@pytest.mark.parametrize(
    "text",
    [
        "We raised $250 million in Series C funding.",  # no period, out of band
        "A $5 lunch stipend daily",
        "No compensation details listed.",
        "Join a $2,000,000,000 company",
    ],
)
def test_ignores_non_pay_numbers(text):
    assert extract_pay(text) is None


def test_normalizer_fills_pay_from_description_and_scores_it():
    from opportunity_radar.config import AppSettings
    from opportunity_radar.models.company import CompanySource
    from opportunity_radar.models.job import RawJob
    from opportunity_radar.pipeline.normalizer import normalize

    raw = RawJob(
        source_adapter="greenhouse",
        source_job_id="1",
        title="Software Engineer Intern - Summer 2027",
        url="https://example.com/1",
        locations=["Austin, TX"],
        description_text="Build backend services in Python. Pay: $55 - $60 per hour.",
    )
    record = normalize(raw, CompanySource(id="x", name="X", tier="broad"), AppSettings())
    assert record.compensation_period == "hour"
    assert float(record.compensation_max) == 60
    assert record.score_components["compensation"] > 0
    assert any(r.startswith("Posted pay $55-$60/hr") for r in record.match_reasons)
