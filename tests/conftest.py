from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from opportunity_radar.adapters.base import AdapterContext
from opportunity_radar.utilities import robots
from opportunity_radar.utilities.rate_limit import RateLimiter

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_robots_cache():
    robots.clear_cache()
    yield
    robots.clear_cache()


@pytest.fixture()
async def ctx():
    async with httpx.AsyncClient() as client:
        yield AdapterContext(
            client=client,
            limiter=RateLimiter(max_global=4, min_domain_interval=0.0),
            user_agent="OpportunityRadar-Test/1.0",
            timeout=10.0,
            retries=0,
            backoff_seconds=(0.01,),
        )
