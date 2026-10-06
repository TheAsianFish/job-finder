import pytest
import respx
from httpx import Response

from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.workday import WorkdayAdapter, extract_workday_config
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

LIST_URL = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeCareers/jobs"
DETAIL_BASE = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeCareers"
ROBOTS = "https://acme.wd5.myworkdayjobs.com/robots.txt"


def company(**overrides):
    defaults = dict(
        id="acme",
        name="Acme",
        adapter="workday",
        adapter_config={"host": "acme.wd5.myworkdayjobs.com", "site": "AcmeCareers"},
    )
    defaults.update(overrides)
    return CompanySource(**defaults)


def _mock_robots(text: str = "User-agent: *\nAllow: /\n"):
    respx.get(ROBOTS).mock(return_value=Response(200, text=text))


def test_extract_config_from_career_url():
    c = company(
        adapter_config={},
        career_urls=["https://acme.wd5.myworkdayjobs.com/en-US/AcmeCareers/job/x"],
    )
    cfg = extract_workday_config(c)
    assert cfg == {"host": "acme.wd5.myworkdayjobs.com", "tenant": "acme", "site": "AcmeCareers"}


def test_extract_config_missing():
    assert extract_workday_config(company(adapter_config={})) is None


@respx.mock
async def test_facet_driven_fetch_keeps_only_early_career_facets(ctx):
    _mock_robots()
    route = respx.post(LIST_URL).mock(
        return_value=Response(200, text=load_fixture("workday_jobs.json"))
    )
    for path in (
        "/job/US-CA-Santa-Clara/2027-Software-Engineering-Intern_JR100001",
        "/job/US-TX-Austin/Software-Engineer--New-College-Grad_JR100002",
        "/job/US-CA-Santa-Clara/Senior-Software-Engineer--Compilers_JR100003",
    ):
        respx.get(DETAIL_BASE + path).mock(
            return_value=Response(200, text=load_fixture("workday_detail.json"))
        )
    jobs = await WorkdayAdapter().fetch_jobs(company(), ctx)

    # First call discovers facets; the second applies the intern + NCG ids only.
    assert route.call_count == 2
    import json

    second_body = json.loads(route.calls[1].request.content)
    assert second_body["appliedFacets"] == {"workerSubType": ["intern-id", "ncg-id"]}
    assert second_body["limit"] == 20

    assert len(jobs) == 3  # fixture returns the same page for the facet pass
    intern = jobs[0]
    assert intern.source_job_id == "JR100001"
    assert intern.title == "2027 Software Engineering Intern"
    assert intern.locations == ["US, CA, Santa Clara", "US, TX, Austin"]
    assert "Summer 2027" in (intern.description_html or "")
    assert intern.apply_url.startswith("https://acme.wd5.myworkdayjobs.com/AcmeCareers/job/")
    assert intern.posted_at is not None and intern.posted_at.year == 2026
    assert intern.remote_hint == "hybrid"
    assert intern.raw["detail_fetched"] is True


@respx.mock
async def test_search_fallback_filters_titles_when_no_facets(ctx):
    _mock_robots()
    route = respx.post(LIST_URL).mock(
        return_value=Response(200, text=load_fixture("workday_jobs_nofacets.json"))
    )
    respx.get(DETAIL_BASE + "/job/San-Jose/2027-Intern---Software-Engineer_R200001").mock(
        return_value=Response(404, text="gone")
    )
    jobs = await WorkdayAdapter().fetch_jobs(
        company(adapter_config={**company().adapter_config, "search_texts": ["intern"]}), ctx
    )
    # One discovery call + one search call ("intern"); senior role filtered out.
    assert route.call_count == 2
    assert [j.title for j in jobs] == ["2027 Intern - Software Engineer"]
    # Detail 404 keeps the listing-only record rather than failing the scan.
    assert jobs[0].description_html is None
    assert jobs[0].raw["detail_fetched"] is False
    assert jobs[0].source_job_id == "R200001"


@respx.mock
async def test_detail_limit_caps_detail_requests(ctx):
    _mock_robots()
    respx.post(LIST_URL).mock(return_value=Response(200, text=load_fixture("workday_jobs.json")))
    detail = respx.get(url__regex=r".*/wday/cxs/acme/AcmeCareers/job/.*").mock(
        return_value=Response(200, text=load_fixture("workday_detail.json"))
    )
    cfg = {**company().adapter_config, "detail_limit": 1}
    jobs = await WorkdayAdapter().fetch_jobs(company(adapter_config=cfg), ctx)
    assert detail.call_count == 1
    assert len(jobs) == 3


@respx.mock
async def test_wrong_site_is_config_error(ctx):
    _mock_robots()
    respx.post(LIST_URL).mock(return_value=Response(422, text="bad site"))
    with pytest.raises(AdapterError) as excinfo:
        await WorkdayAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "config"


@respx.mock
async def test_missing_job_postings_key_is_parse_error(ctx):
    _mock_robots()
    respx.post(LIST_URL).mock(return_value=Response(200, json={"total": 0}))
    with pytest.raises(AdapterError) as excinfo:
        await WorkdayAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "parse"


@respx.mock
async def test_robots_disallow_raises(ctx):
    _mock_robots("User-agent: *\nDisallow: /wday/\n")
    with pytest.raises(AdapterError) as excinfo:
        await WorkdayAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "robots"


async def test_missing_config_raises(ctx):
    with pytest.raises(AdapterError) as excinfo:
        await WorkdayAdapter().fetch_jobs(company(adapter_config={}), ctx)
    assert excinfo.value.category == "config"
