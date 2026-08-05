import pytest

from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.registry import available_adapters, get_adapter, resolve_adapter
from opportunity_radar.discovery.ats_fingerprint import detect_from_html, detect_from_url
from opportunity_radar.models.company import CompanySource


def test_detect_greenhouse_variants():
    assert detect_from_url("https://boards.greenhouse.io/stripe").adapter == "greenhouse"
    result = detect_from_url("https://job-boards.greenhouse.io/datadog/jobs/123")
    assert result.adapter == "greenhouse"
    assert result.config["board_token"] == "datadog"


def test_detect_lever_and_eu():
    result = detect_from_url("https://jobs.lever.co/palantir/abc")
    assert result.adapter == "lever"
    assert result.config["site"] == "palantir"
    eu = detect_from_url("https://jobs.eu.lever.co/someco")
    assert eu.config.get("region") == "eu"


def test_detect_ashby():
    result = detect_from_url("https://jobs.ashbyhq.com/openai")
    assert result.adapter == "ashby"
    assert result.config["job_board_name"] == "openai"


def test_detect_workday():
    result = detect_from_url("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite")
    assert result.adapter == "workday"


def test_detect_from_html_embedded_link():
    html = '<html><a href="https://boards.greenhouse.io/figma/jobs/1">Jobs</a></html>'
    result = detect_from_html(html)
    assert result.adapter == "greenhouse"
    assert result.config["board_token"] == "figma"


def test_detect_none():
    assert detect_from_url("https://example.com/careers") is None


def test_registry_contains_all():
    names = available_adapters()
    for expected in (
        "greenhouse",
        "lever",
        "ashby",
        "jsonld",
        "sitemap",
        "html_generic",
        "playwright",
        "workday",
        "smartrecruiters",
        "icims",
        "eightfold",
        "successfactors",
        "taleo",
    ):
        assert expected in names


def test_get_adapter_unknown_raises():
    with pytest.raises(AdapterError):
        get_adapter("nope")


def test_resolve_explicit():
    company = CompanySource(id="x", name="X", adapter="greenhouse")
    assert resolve_adapter(company).name == "greenhouse"


def test_resolve_auto_via_url():
    company = CompanySource(
        id="x",
        name="X",
        adapter="auto",
        career_urls=["https://jobs.lever.co/xco"],
    )
    adapter = resolve_adapter(company)
    assert adapter.name == "lever"
    # The adapter re-derives the site token from career_urls at fetch time.
    from opportunity_radar.adapters.lever import extract_site

    assert extract_site(company)[0] == "xco"


def test_resolve_auto_selectors():
    company = CompanySource(
        id="x",
        name="X",
        adapter="auto",
        adapter_config={"selectors": {"card": ".job"}, "list_url": "https://x.com/jobs"},
    )
    assert resolve_adapter(company).name == "html_generic"


def test_resolve_auto_career_urls_falls_to_jsonld():
    company = CompanySource(id="x", name="X", adapter="auto", career_urls=["https://x.com/careers"])
    assert resolve_adapter(company).name == "jsonld"


def test_resolve_nothing_raises():
    company = CompanySource(id="x", name="X", adapter="auto")
    with pytest.raises(AdapterError):
        resolve_adapter(company)


async def test_unsupported_adapter_message(ctx):
    company = CompanySource(id="x", name="X", adapter="workday")
    adapter = resolve_adapter(company)
    with pytest.raises(AdapterError) as excinfo:
        await adapter.fetch_jobs(company, ctx)
    assert excinfo.value.category == "unsupported"
    assert "jsonld" in str(excinfo.value)
