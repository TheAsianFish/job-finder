import respx
from httpx import Response

from opportunity_radar.adapters.ashby import AshbyAdapter, extract_board_name
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

API_URL = "https://api.ashbyhq.com/posting-api/job-board/acmeai?includeCompensation=true"


def company(**overrides):
    defaults = dict(
        id="acmeai",
        name="Acme AI",
        adapter="ashby",
        adapter_config={"job_board_name": "acmeai"},
    )
    defaults.update(overrides)
    return CompanySource(**defaults)


def test_extract_board_name_from_url():
    c = company(adapter_config={}, career_urls=["https://jobs.ashbyhq.com/acmeai"])
    assert extract_board_name(c) == "acmeai"


@respx.mock
async def test_fetch_jobs_parses_fixture(ctx):
    respx.get(API_URL).mock(return_value=Response(200, text=load_fixture("ashby_board.json")))
    jobs = await AshbyAdapter().fetch_jobs(company(), ctx)
    # Unlisted job is skipped.
    assert len(jobs) == 2
    ml = jobs[0]
    assert ml.title == "Machine Learning Engineer Intern - Fall 2027"
    assert "San Francisco" in ml.locations
    assert "Remote (US)" in ml.locations
    assert ml.compensation_min == 55
    assert ml.compensation_max == 65
    assert ml.compensation_period == "hour"
    assert ml.compensation_currency == "USD"
    assert ml.team == "ML Platform"
    assert ml.apply_url.endswith("/application")
