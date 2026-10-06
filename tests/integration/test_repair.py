"""Self-repair: silent (0-job) and failing sources get re-pointed in companies.yaml."""

from __future__ import annotations

import pytest
import respx
import yaml
from httpx import Response

from opportunity_radar.config import load_settings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base
from opportunity_radar.discovery.repair import repair_failing_sources
from opportunity_radar.models.company import CompanySource

REGISTRY = """
companies:
- id: xai
  name: xAI
  domain: x.ai
  tier: strong
  adapter: auto
  career_urls:
  - https://x.ai/careers
- id: fineco
  name: FineCo
  domain: fineco.com
  tier: broad
  adapter: greenhouse
  adapter_config:
    board_token: fineco
"""


@pytest.fixture()
def home(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "companies.yaml").write_text(REGISTRY, encoding="utf-8")
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("OPPORTUNITY_RADAR_HOME", str(tmp_path))
    load_settings(reload=True)
    reset_engine()
    url = f"sqlite:///{tmp_path}/data/repair.db"
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    yield tmp_path, url
    reset_engine()
    load_settings(reload=True)


@respx.mock
async def test_silent_source_is_repointed_via_token_guess(home, ctx):
    root, db_url = home
    with session_scope(db_url) as session:
        repo.sync_companies(
            session,
            [
                CompanySource(id="xai", name="xAI", domain="x.ai", adapter="auto"),
                CompanySource(id="fineco", name="FineCo", adapter="greenhouse"),
            ],
        )
        repo.update_source_state_success(session, "xai", 0)  # silent
        repo.update_source_state_success(session, "fineco", 40)  # healthy

    # Homepage / career pages yield nothing fingerprintable.
    respx.get(url__regex=r"https://x\.ai/.*").mock(return_value=Response(200, text="<html></html>"))
    respx.get("https://x.ai/robots.txt").mock(return_value=Response(404))
    greenhouse = respx.get(
        url__regex=r"https://boards-api\.greenhouse\.io/v1/boards/xai/jobs.*"
    ).mock(
        return_value=Response(
            200,
            json={"jobs": [{"id": 1, "title": "Software Engineering Internship", "content": ""}]},
        )
    )
    respx.get(url__regex=r"https://api\.ashbyhq\.com/.*").mock(return_value=Response(404))
    respx.get(url__regex=r"https://api\.lever\.co/.*").mock(return_value=Response(404))

    result = await repair_failing_sources(ctx, db_url=db_url)
    assert result.repaired == ["xai"]
    assert result.unrepairable == []
    assert greenhouse.called

    registry = yaml.safe_load((root / "config" / "companies.yaml").read_text())
    entry = next(c for c in registry["companies"] if c["id"] == "xai")
    assert entry["adapter"] == "greenhouse"
    assert entry["adapter_config"] == {"board_token": "xai"}
    assert "Auto-repaired" in entry["notes"]
    untouched = next(c for c in registry["companies"] if c["id"] == "fineco")
    assert untouched["adapter_config"] == {"board_token": "fineco"}


@respx.mock
async def test_genuinely_empty_board_is_reported_not_rewritten(home, ctx):
    root, db_url = home
    with session_scope(db_url) as session:
        repo.sync_companies(
            session, [CompanySource(id="fineco", name="FineCo", adapter="greenhouse")]
        )
        repo.update_source_state_success(session, "fineco", 0)
    respx.get(url__regex=r"https://fineco\.com/.*").mock(
        return_value=Response(200, text='<a href="https://boards.greenhouse.io/fineco">Jobs</a>')
    )
    result = await repair_failing_sources(ctx, db_url=db_url)
    assert result.repaired == []
    assert result.unrepairable == ["fineco"]
    assert any("genuinely empty" in d for d in result.details)
    registry = yaml.safe_load((root / "config" / "companies.yaml").read_text())
    assert "notes" not in next(c for c in registry["companies"] if c["id"] == "fineco")
