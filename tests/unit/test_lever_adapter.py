import respx
from httpx import Response

from opportunity_radar.adapters.lever import LeverAdapter, extract_site
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

API_URL = "https://api.lever.co/v0/postings/acmetrading?mode=json&skip=0&limit=100"


def company(**overrides):
    defaults = dict(
        id="acmetrading",
        name="Acme Trading",
        adapter="lever",
        adapter_config={"site": "acmetrading"},
    )
    defaults.update(overrides)
    return CompanySource(**defaults)


def test_extract_site_from_urls():
    c = company(adapter_config={}, career_urls=["https://jobs.lever.co/acmetrading"])
    assert extract_site(c) == ("acmetrading", "")


def test_extract_site_eu():
    c = company(adapter_config={}, career_urls=["https://jobs.eu.lever.co/acmetrading"])
    assert extract_site(c) == ("acmetrading", "eu.")


@respx.mock
async def test_fetch_jobs_parses_fixture(ctx):
    respx.get(API_URL).mock(return_value=Response(200, text=load_fixture("lever_postings.json")))
    jobs = await LeverAdapter().fetch_jobs(company(), ctx)
    assert len(jobs) == 2
    winter = jobs[0]
    assert winter.title == "Software Engineering Intern (Winter 2027)"
    assert "New York, NY" in winter.locations
    assert "Chicago, IL" in winter.locations
    assert winter.remote_hint == "hybrid"
    assert winter.employment_type == "Intern"
    assert winter.apply_url.endswith("/apply")
    assert winter.posted_at is not None

    remote = jobs[1]
    assert remote.remote_hint == "remote"


@respx.mock
async def test_pagination(ctx):
    page1 = load_fixture("lever_postings.json")
    import json

    postings = json.loads(page1)
    full_page = postings * 50  # 100 items triggers a second fetch
    respx.get(API_URL).mock(return_value=Response(200, json=full_page))
    respx.get("https://api.lever.co/v0/postings/acmetrading?mode=json&skip=100&limit=100").mock(
        return_value=Response(200, json=[])
    )
    jobs = await LeverAdapter().fetch_jobs(company(), ctx)
    assert len(jobs) == 100
