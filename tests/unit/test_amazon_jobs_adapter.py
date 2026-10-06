import pytest
import respx
from httpx import Response

from opportunity_radar.adapters.amazon_jobs import AmazonJobsAdapter
from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

ROBOTS = "https://www.amazon.jobs/robots.txt"
SEARCH = r"https://www\.amazon\.jobs/en/search\.json\?.*"


def company(**overrides):
    defaults = dict(
        id="amazon", name="Amazon", adapter="amazon_jobs", adapter_config={"queries": ["intern"]}
    )
    defaults.update(overrides)
    return CompanySource(**defaults)


def _mock_robots():
    respx.get(ROBOTS).mock(return_value=Response(200, text="User-agent: *\nDisallow: /internal\n"))


@respx.mock
async def test_fetch_keeps_flagged_and_titled_early_career_jobs(ctx):
    _mock_robots()
    route = respx.get(url__regex=SEARCH).mock(
        return_value=Response(200, text=load_fixture("amazon_search.json"))
    )
    jobs = await AmazonJobsAdapter().fetch_jobs(company(), ctx)
    assert route.call_count == 1
    request_url = str(route.calls[0].request.url)
    assert "category[]=software-development" in request_url
    assert "base_query=intern" in request_url
    # The Dublin new-grad role is dropped by the default USA country filter.
    assert [j.source_job_id for j in jobs] == ["10400001"]
    intern = jobs[0]
    assert intern.title == "2027 Software Dev Engineer Intern"
    assert (
        intern.url == "https://www.amazon.jobs/en/jobs/10400001/2027-software-dev-engineer-intern"
    )
    assert intern.apply_url == "https://account.amazon.jobs/jobs/10400001/apply"
    assert intern.locations[0] == "Seattle, Washington, USA"
    assert "<h3>Basic qualifications</h3>" in (intern.description_html or "")
    assert intern.posted_at is not None and intern.posted_at.month == 10
    assert intern.raw["is_intern"] is True
    assert intern.department == "Software Development"


@respx.mock
async def test_api_error_field_raises(ctx):
    _mock_robots()
    respx.get(url__regex=SEARCH).mock(
        return_value=Response(200, json={"error": "bad request", "hits": 0, "jobs": []})
    )
    with pytest.raises(AdapterError) as excinfo:
        await AmazonJobsAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "http"


@respx.mock
async def test_missing_jobs_key_is_parse_error(ctx):
    _mock_robots()
    respx.get(url__regex=SEARCH).mock(return_value=Response(200, json={"hits": 1}))
    with pytest.raises(AdapterError) as excinfo:
        await AmazonJobsAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "parse"


@respx.mock
async def test_robots_disallow_raises(ctx):
    respx.get(ROBOTS).mock(return_value=Response(200, text="User-agent: *\nDisallow: /en/search\n"))
    with pytest.raises(AdapterError) as excinfo:
        await AmazonJobsAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "robots"


@respx.mock
async def test_country_filter_can_be_widened(ctx):
    _mock_robots()
    respx.get(url__regex=SEARCH).mock(
        return_value=Response(200, text=load_fixture("amazon_search.json"))
    )
    cfg = {"queries": ["intern"], "country_codes": ["USA", "IRL"]}
    jobs = await AmazonJobsAdapter().fetch_jobs(company(adapter_config=cfg), ctx)
    assert [j.source_job_id for j in jobs] == ["10400001", "10400003"]
