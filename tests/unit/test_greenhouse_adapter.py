import pytest
import respx
from httpx import Response

from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.greenhouse import GreenhouseAdapter, extract_board_token
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

API_URL = "https://boards-api.greenhouse.io/v1/boards/acmecorp/jobs?content=true"


def company(**overrides):
    defaults = dict(
        id="acmecorp",
        name="AcmeCorp",
        adapter="greenhouse",
        adapter_config={"board_token": "acmecorp"},
    )
    defaults.update(overrides)
    return CompanySource(**defaults)


def test_extract_board_token_from_config():
    assert extract_board_token(company()) == "acmecorp"


def test_extract_board_token_from_urls():
    c = company(
        adapter_config={},
        career_urls=["https://boards.greenhouse.io/acmecorp"],
    )
    assert extract_board_token(c) == "acmecorp"
    c2 = company(
        adapter_config={},
        career_urls=["https://job-boards.greenhouse.io/acmecorp?departments=eng"],
    )
    assert extract_board_token(c2) == "acmecorp"


@respx.mock
async def test_fetch_jobs_parses_fixture(ctx):
    respx.get(API_URL).mock(return_value=Response(200, text=load_fixture("greenhouse_jobs.json")))
    jobs = await GreenhouseAdapter().fetch_jobs(company(), ctx)
    assert len(jobs) == 3
    intern = jobs[0]
    assert intern.source_job_id == "4011001"
    assert intern.title == "Software Engineer Intern - Summer 2027"
    assert intern.locations[0] == "San Francisco, CA"
    assert intern.apply_url == "https://boards.greenhouse.io/acmecorp/jobs/4011001"
    # HTML content is unescaped.
    assert "<strong>Python</strong>" in (intern.description_html or "")
    assert intern.posted_at is not None
    assert intern.updated_at is not None


@respx.mock
async def test_404_raises_config_error(ctx):
    respx.get(API_URL).mock(return_value=Response(404, text="Not found"))
    with pytest.raises(AdapterError) as excinfo:
        await GreenhouseAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "config"
    assert not excinfo.value.retryable


@respx.mock
async def test_malformed_json_raises_parse_error(ctx):
    respx.get(API_URL).mock(return_value=Response(200, text=load_fixture("malformed.json")))
    with pytest.raises(AdapterError) as excinfo:
        await GreenhouseAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "parse"


@respx.mock
async def test_rate_limit_categorized_retryable(ctx):
    respx.get(API_URL).mock(return_value=Response(429, text="slow down"))
    with pytest.raises(AdapterError) as excinfo:
        await GreenhouseAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.retryable


async def test_missing_token_raises_config_error(ctx):
    with pytest.raises(AdapterError) as excinfo:
        await GreenhouseAdapter().fetch_jobs(company(adapter_config={}), ctx)
    assert excinfo.value.category == "config"
