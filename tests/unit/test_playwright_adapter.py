import importlib.util

import pytest

from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.playwright_generic import PlaywrightAdapter
from opportunity_radar.models.company import CompanySource

playwright_installed = importlib.util.find_spec("playwright") is not None


@pytest.mark.skipif(playwright_installed, reason="playwright installed in this env")
async def test_missing_playwright_gives_clear_config_error(ctx):
    company = CompanySource(
        id="jsco",
        name="JSCo",
        adapter="playwright",
        adapter_config={"list_url": "https://jsco.example/careers"},
    )
    with pytest.raises(AdapterError) as excinfo:
        await PlaywrightAdapter().fetch_jobs(company, ctx)
    assert excinfo.value.category == "config"
    assert "uv sync --extra browser" in str(excinfo.value)
