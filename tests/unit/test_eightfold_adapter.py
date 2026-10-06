import pytest
import respx
from httpx import Response

from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.eightfold import EightfoldAdapter
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

BASE = "https://explore.jobs.acme.net"
ROBOTS = f"{BASE}/robots.txt"


def company(**overrides):
    defaults = dict(
        id="acme",
        name="Acme",
        adapter="eightfold",
        adapter_config={"base_url": BASE, "domain": "acme.com", "queries": ["intern"]},
    )
    defaults.update(overrides)
    return CompanySource(**defaults)


def _mock_robots():
    respx.get(ROBOTS).mock(
        return_value=Response(200, text="User-agent: *\nDisallow: /\nAllow: /api/apply\n")
    )


@respx.mock
async def test_fetch_keeps_early_career_titles_and_fetches_detail(ctx):
    _mock_robots()
    search = respx.get(url__regex=rf"{BASE}/api/apply/v2/jobs\?.*query=intern.*").mock(
        return_value=Response(200, text=load_fixture("eightfold_positions.json"))
    )
    respx.get(f"{BASE}/api/apply/v2/jobs/790300000001?domain=acme.com").mock(
        return_value=Response(200, text=load_fixture("eightfold_detail.json"))
    )
    respx.get(f"{BASE}/api/apply/v2/jobs/790300000003?domain=acme.com").mock(
        return_value=Response(503)
    )
    jobs = await EightfoldAdapter().fetch_jobs(company(), ctx)
    assert search.call_count == 1  # count=3 < page size -> no second page
    assert [j.source_job_id for j in jobs] == ["790300000001", "790300000003"]
    intern = jobs[0]
    assert "Summer 2027" in (intern.description_html or "")
    assert intern.locations == ["Los Gatos, California, United States of America"]
    assert intern.posted_at is not None and intern.posted_at.year == 2026
    assert intern.apply_url.startswith(f"{BASE}/careers/job/790300000001")
    assert intern.department == "Engineering"
    remote = jobs[1]
    assert remote.remote_hint == "remote"
    assert remote.description_html is None
    assert remote.raw["detail_fetched"] is False


@respx.mock
async def test_missing_positions_is_parse_error(ctx):
    _mock_robots()
    respx.get(url__regex=rf"{BASE}/api/apply/v2/jobs\?.*").mock(
        return_value=Response(200, json={"count": 0})
    )
    with pytest.raises(AdapterError) as excinfo:
        await EightfoldAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "parse"


@respx.mock
async def test_robots_disallow_without_api_allow_raises(ctx):
    respx.get(ROBOTS).mock(return_value=Response(200, text="User-agent: *\nDisallow: /\n"))
    with pytest.raises(AdapterError) as excinfo:
        await EightfoldAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "robots"


async def test_missing_config_raises(ctx):
    with pytest.raises(AdapterError) as excinfo:
        await EightfoldAdapter().fetch_jobs(company(adapter_config={}, domain=None), ctx)
    assert excinfo.value.category == "config"


@respx.mock
async def test_known_positions_skip_detail_requests(ctx):
    import dataclasses

    _mock_robots()
    respx.get(url__regex=rf"{BASE}/api/apply/v2/jobs\?.*").mock(
        return_value=Response(200, text=load_fixture("eightfold_positions.json"))
    )
    detail = respx.get(url__regex=rf"{BASE}/api/apply/v2/jobs/\d+\?.*").mock(
        return_value=Response(200, text=load_fixture("eightfold_detail.json"))
    )
    known_ctx = dataclasses.replace(ctx, known_job_ids=frozenset({"790300000001"}))
    jobs = await EightfoldAdapter().fetch_jobs(company(), known_ctx)
    assert detail.call_count == 1
    assert jobs[0].raw["detail_fetched"] is False
