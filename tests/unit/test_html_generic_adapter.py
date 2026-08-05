import pytest
import respx
from httpx import Response

from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.html_generic import HtmlGenericAdapter
from opportunity_radar.models.company import CompanySource
from tests.conftest import load_fixture

LIST_URL = "https://example.com/careers"

SELECTORS = {
    "card": ".job-card",
    "title": ".job-card__title",
    "location": ".job-card__location",
    "url": "a@href",
}


def company(**overrides):
    defaults = dict(
        id="htmlco",
        name="HtmlCo",
        adapter="html_generic",
        adapter_config={"list_url": LIST_URL, "selectors": dict(SELECTORS)},
    )
    defaults.update(overrides)
    return CompanySource(**defaults)


def _mock_robots_ok():
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nAllow: /\n")
    )


@respx.mock
async def test_parses_cards_with_relative_urls(ctx):
    _mock_robots_ok()
    respx.get(LIST_URL).mock(return_value=Response(200, text=load_fixture("html_cards.html")))
    jobs = await HtmlGenericAdapter().fetch_jobs(company(), ctx)
    assert len(jobs) == 3
    assert jobs[0].title == "Software Engineer Intern — Summer 2027"
    assert jobs[0].url == "https://example.com/careers/swe-intern-summer-2027"
    assert jobs[0].locations == ["Denver, CO"]
    assert jobs[1].url == "https://example.com/careers/devtools-coop"


@respx.mock
async def test_broken_selector_raises_degraded(ctx):
    _mock_robots_ok()
    respx.get(LIST_URL).mock(
        return_value=Response(200, text="<html><body>redesigned</body></html>")
    )
    with pytest.raises(AdapterError) as excinfo:
        await HtmlGenericAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "parse"


@respx.mock
async def test_robots_disallow_raises(ctx):
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nDisallow: /\n")
    )
    with pytest.raises(AdapterError) as excinfo:
        await HtmlGenericAdapter().fetch_jobs(company(), ctx)
    assert excinfo.value.category == "robots"


async def test_missing_config_raises(ctx):
    with pytest.raises(AdapterError) as excinfo:
        await HtmlGenericAdapter().fetch_jobs(company(adapter_config={"list_url": LIST_URL}), ctx)
    assert excinfo.value.category == "config"
