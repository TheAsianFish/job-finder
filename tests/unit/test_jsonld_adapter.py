import respx
from httpx import Response

from opportunity_radar.adapters.jsonld import JsonLdAdapter, parse_jsonld_scripts
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

PAGE_URL = "https://example.com/careers"


def company(**overrides):
    defaults = dict(
        id="exampleco",
        name="ExampleCo",
        adapter="jsonld",
        career_urls=[PAGE_URL],
    )
    defaults.update(overrides)
    return CompanySource(**defaults)


def _mock_robots_ok():
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nAllow: /\n")
    )


def test_parse_single_object():
    postings = parse_jsonld_scripts(load_fixture("jsonld_single.html"))
    assert len(postings) == 1
    assert postings[0]["title"].startswith("Software Engineer Intern")


def test_parse_graph_with_malformed_sibling():
    postings = parse_jsonld_scripts(load_fixture("jsonld_graph.html"))
    assert len(postings) == 2


@respx.mock
async def test_fetch_single(ctx):
    _mock_robots_ok()
    respx.get(PAGE_URL).mock(return_value=Response(200, text=load_fixture("jsonld_single.html")))
    jobs = await JsonLdAdapter().fetch_jobs(company(), ctx)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_job_id == "EX-2027-001"
    assert job.locations == ["Seattle, WA, US"]
    assert job.compensation_min == 50
    assert job.compensation_period == "hour"
    assert job.valid_through is not None
    assert job.apply_url == "https://example.com/careers/ex-2027-001"
    assert "Kubernetes" in (job.description_text or "")


@respx.mock
async def test_fetch_graph_relative_urls_and_remote(ctx):
    _mock_robots_ok()
    respx.get(PAGE_URL).mock(return_value=Response(200, text=load_fixture("jsonld_graph.html")))
    jobs = await JsonLdAdapter().fetch_jobs(company(), ctx)
    assert len(jobs) == 2
    backend = next(j for j in jobs if "Backend" in j.title)
    assert backend.apply_url == "https://example.com/careers/backend-intern-winter-2027"
    assert backend.remote_hint == "remote"
    data = next(j for j in jobs if "Data" in j.title)
    assert data.locations == ["Austin, TX"]


@respx.mock
async def test_robots_disallow_skips_page(ctx):
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nDisallow: /careers\n")
    )
    import pytest

    from opportunity_radar.adapters.base import AdapterError

    with pytest.raises(AdapterError) as excinfo:
        await JsonLdAdapter().fetch_jobs(company(), ctx)
    assert "robots" in str(excinfo.value)
