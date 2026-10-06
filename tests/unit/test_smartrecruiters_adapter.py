import pytest
import respx
from httpx import Response

from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.smartrecruiters import SmartRecruitersAdapter, extract_company
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

LIST_URL = "https://api.smartrecruiters.com/v1/companies/AcmeCo/postings?limit=100&offset=0"
DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/AcmeCo/postings/{id}"


def company(**overrides):
    defaults = dict(
        id="acmeco", name="AcmeCo", adapter="smartrecruiters", adapter_config={"company": "AcmeCo"}
    )
    defaults.update(overrides)
    return CompanySource(**defaults)


def test_extract_company_from_url():
    c = company(adapter_config={}, career_urls=["https://jobs.smartrecruiters.com/AcmeCo/"])
    assert extract_company(c) == "AcmeCo"
    assert extract_company(company(adapter_config={})) is None


@respx.mock
async def test_fetch_filters_early_career_and_fetches_detail(ctx):
    respx.get(LIST_URL).mock(
        return_value=Response(200, text=load_fixture("smartrecruiters_postings.json"))
    )
    respx.get(DETAIL_URL.format(id="744000100000001")).mock(
        return_value=Response(200, text=load_fixture("smartrecruiters_detail.json"))
    )
    respx.get(DETAIL_URL.format(id="744000100000003")).mock(return_value=Response(500))
    jobs = await SmartRecruitersAdapter().fetch_jobs(company(), ctx)
    assert [j.title for j in jobs] == [
        "Software Engineer Intern - Summer 2027",
        "New Grad Software Engineer (2027)",
    ]
    intern = jobs[0]
    assert intern.source_job_id == "744000100000001"
    assert intern.locations == ["Santa Clara, California, us"]
    assert "Kubernetes" in (intern.description_html or "")
    assert "<h3>Qualifications</h3>" in (intern.description_html or "")
    assert intern.apply_url.endswith("?oga=true")
    assert intern.url.startswith("https://jobs.smartrecruiters.com/AcmeCo/")
    assert intern.employment_type == "Intern"
    assert intern.posted_at is not None
    # Detail failure degrades to a listing-only record.
    assert jobs[1].description_html is None
    assert jobs[1].url == "https://jobs.smartrecruiters.com/AcmeCo/744000100000003"


@respx.mock
async def test_zero_postings_is_config_error(ctx):
    respx.get(LIST_URL).mock(
        return_value=Response(200, json={"offset": 0, "limit": 100, "totalFound": 0, "content": []})
    )
    with pytest.raises(AdapterError) as excinfo:
        await SmartRecruitersAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "config"


@respx.mock
async def test_missing_content_is_parse_error(ctx):
    respx.get(LIST_URL).mock(return_value=Response(200, json={"totalFound": 3}))
    with pytest.raises(AdapterError) as excinfo:
        await SmartRecruitersAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "parse"


@respx.mock
async def test_whole_board_when_filter_disabled(ctx):
    respx.get(LIST_URL).mock(
        return_value=Response(200, text=load_fixture("smartrecruiters_postings.json"))
    )
    respx.get(url__regex=r".*/postings/\d+$").mock(
        return_value=Response(200, text=load_fixture("smartrecruiters_detail.json"))
    )
    cfg = {"company": "AcmeCo", "early_career_only": False}
    jobs = await SmartRecruitersAdapter().fetch_jobs(company(adapter_config=cfg), ctx)
    assert len(jobs) == 3
