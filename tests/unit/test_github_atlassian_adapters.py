import pytest
import respx
from httpx import Response

from opportunity_radar.adapters.atlassian_careers import AtlassianCareersAdapter
from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.github_careers import GitHubCareersAdapter
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

GH_LIST = "https://www.github.careers/api/jobs?page=1&limit=100"
AT_LIST = "https://www.atlassian.com/endpoint/careers/listings"


@respx.mock
async def test_github_careers_parses_fixture(ctx):
    respx.get("https://www.github.careers/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nAllow: /\n")
    )
    respx.get(GH_LIST).mock(return_value=Response(200, text=load_fixture("github_careers.json")))
    jobs = await GitHubCareersAdapter().fetch_jobs(
        CompanySource(id="github", name="GitHub", adapter="github_careers"), ctx
    )
    assert len(jobs) == 2
    intern = jobs[0]
    assert intern.source_job_id == "5901"
    assert intern.title == "Software Engineer Intern - Summer 2027"
    assert intern.url == "https://www.github.careers/careers-home/jobs/5901"
    assert intern.apply_url == "https://careers-acme.icims.com/jobs/5901/login"
    assert intern.locations == ["US Remote", "United States"]
    assert intern.remote_hint == "remote"
    assert intern.department == "Engineering"
    assert intern.employment_type == "INTERN"
    assert intern.posted_at is not None and intern.updated_at is not None


@respx.mock
async def test_github_careers_missing_jobs_is_parse_error(ctx):
    respx.get("https://www.github.careers/robots.txt").mock(return_value=Response(404))
    respx.get(GH_LIST).mock(return_value=Response(200, json={"totalCount": 0}))
    with pytest.raises(AdapterError) as excinfo:
        await GitHubCareersAdapter().fetch_jobs(
            CompanySource(id="github", name="GitHub", adapter="github_careers"), ctx
        )
    assert excinfo.value.category == "parse"


@respx.mock
async def test_atlassian_listing_parses_fixture(ctx):
    respx.get("https://www.atlassian.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nDisallow: /blog/\n")
    )
    respx.get(AT_LIST).mock(
        return_value=Response(200, text=load_fixture("atlassian_listings.json"))
    )
    jobs = await AtlassianCareersAdapter().fetch_jobs(
        CompanySource(id="atlassian", name="Atlassian", adapter="atlassian_careers"), ctx
    )
    assert len(jobs) == 2
    intern = jobs[0]
    assert intern.source_job_id == "25500"
    assert intern.url == "https://www.atlassian.com/company/careers/details/25500"
    assert intern.apply_url.endswith("mode=apply")
    assert intern.locations == ["Mountain View, United States", "San Francisco, United States"]
    assert intern.department == "Graduates and Interns"
    assert intern.employment_type == "Intern"
    assert "Bachelor" in (intern.description_html or "")


@respx.mock
async def test_atlassian_non_list_is_parse_error(ctx):
    respx.get("https://www.atlassian.com/robots.txt").mock(return_value=Response(404))
    respx.get(AT_LIST).mock(return_value=Response(200, json={"jobs": []}))
    with pytest.raises(AdapterError) as excinfo:
        await AtlassianCareersAdapter().fetch_jobs(
            CompanySource(id="atlassian", name="Atlassian", adapter="atlassian_careers"), ctx
        )
    assert excinfo.value.category == "parse"
