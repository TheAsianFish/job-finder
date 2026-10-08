"""Shared hub memory, Discord channel routing and bot setup (AD-33)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx
from typer.testing import CliRunner

from opportunity_radar.hub import (
    about_path,
    append_journal,
    bundle,
    journal_path,
    recent_journal,
    write_project_summary,
)
from opportunity_radar.notifications.discord import CHANNELS, webhook_env, webhook_for
from opportunity_radar.notifications.discord_bot import (
    API,
    DiscordBotError,
    setup_hub,
    upsert_env,
)

# ---------------------------------------------------------------- hub


def test_journal_appends_and_bundle_includes_everything():
    about_path().parent.mkdir(parents=True, exist_ok=True)
    about_path().write_text("# About Patrick\nPrefers depth.\n", encoding="utf-8")
    for i in range(5):
        append_journal(f"agent-{i}", f"did thing {i}", when=datetime(2026, 10, 9, i, tzinfo=UTC))
    text = journal_path().read_text()
    assert text.startswith("# Journal") and text.count("\n## 2026-10-09") == 5
    assert "## 2026-10-09 04:00 UTC · agent-4" in text
    assert recent_journal(2).startswith("## 2026-10-09 03:00 UTC · agent-3")
    write_project_summary("replay", "# Replay\nM1 merged.")
    context = bundle(journal_entries=3)
    assert "Prefers depth." in context and "# Replay" in context
    assert "agent-4" in context and "agent-1" not in context  # only recent entries


def test_bundle_is_empty_but_valid_without_a_hub():
    assert bundle().startswith("# Shared context")


def test_hub_cli_log_and_context(tmp_path):
    from opportunity_radar.cli import app

    runner = CliRunner()
    note = tmp_path / "note.md"
    note.write_text("Plan PR opened.\nNext: M1.")
    assert runner.invoke(app, ["hub", "log", "builder/replay", "--file", str(note)]).exit_code == 0
    assert runner.invoke(app, ["hub", "log", "session", "short note"]).exit_code == 0
    out = tmp_path / "ctx.md"
    result = runner.invoke(app, ["hub", "context", "--out", str(out)])
    assert result.exit_code == 0
    assert "Plan PR opened." in out.read_text() and "short note" in out.read_text()
    summary = tmp_path / "s.md"
    summary.write_text("# Replay summary")
    assert runner.invoke(app, ["hub", "project-summary", "replay", str(summary)]).exit_code == 0
    assert "# Replay summary" in out.read_text() or "# Replay summary" in bundle()


# ---------------------------------------------------------------- routing


def test_channel_webhooks_fall_back_to_the_default(monkeypatch):
    from opportunity_radar.config import get_settings

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/default")
    monkeypatch.setenv("DISCORD_WEBHOOK_PROJECTS", "https://discord.test/projects")
    monkeypatch.delenv("DISCORD_WEBHOOK_STUDY", raising=False)
    get_settings.cache_clear()
    try:
        assert webhook_env("agent-log") == "DISCORD_WEBHOOK_AGENT_LOG"
        assert webhook_for("projects") == "https://discord.test/projects"
        assert webhook_for("study") == "https://discord.test/default"
    finally:
        get_settings.cache_clear()


# ---------------------------------------------------------------- bot setup


GUILD = "111"


def _mock_guild(existing: list[dict], hooks: dict[str, list[dict]]):
    created: list[dict] = []
    respx.get(f"{API}/guilds/{GUILD}/channels").mock(
        return_value=httpx.Response(200, json=existing)
    )

    def create_channel(request):
        body = __import__("json").loads(request.content)
        channel = {"id": f"c{len(created) + 10}", **body}
        created.append(channel)
        return httpx.Response(201, json=channel)

    respx.post(f"{API}/guilds/{GUILD}/channels").mock(side_effect=create_channel)
    respx.get(url__regex=rf"{API}/channels/(?P<cid>[^/]+)/webhooks").mock(
        side_effect=lambda request, cid: httpx.Response(200, json=hooks.get(cid, []))
    )
    respx.post(url__regex=rf"{API}/channels/(?P<cid>[^/]+)/webhooks").mock(
        side_effect=lambda request, cid: httpx.Response(
            200, json={"id": f"w{cid}", "token": "tok", "name": "Opportunity Radar"}
        )
    )
    respx.post(url__regex=rf"{API}/channels/[^/]+/messages").mock(
        return_value=httpx.Response(200, json={})
    )
    return created


@respx.mock
def test_setup_creates_category_channels_and_webhooks():
    created = _mock_guild(existing=[{"id": "9", "type": 0, "name": "job"}], hooks={})
    result = setup_hub("bot-token", GUILD)
    assert created[0]["type"] == 4 and created[0]["name"] == "Opportunity Radar"
    assert result.created_channels == list(CHANNELS)
    assert all(c.get("parent_id") == created[0]["id"] for c in created[1:])
    assert set(result.env) == {webhook_env(c) for c in CHANNELS}
    assert all(
        url.startswith("https://discord.com/api/webhooks/") for url in result.webhooks.values()
    )
    sent = respx.calls[0].request
    assert sent.headers["Authorization"] == "Bot bot-token"


@respx.mock
def test_setup_is_idempotent():
    existing = [{"id": "cat", "type": 4, "name": "Opportunity Radar"}] + [
        {"id": f"id-{name}", "type": 0, "name": name} for name in CHANNELS
    ]
    hooks = {
        f"id-{name}": [{"id": f"h-{name}", "token": "t", "name": "Opportunity Radar"}]
        for name in CHANNELS
    }
    created = _mock_guild(existing, hooks)
    result = setup_hub("bot-token", GUILD)
    assert created == [] and result.created_channels == [] and result.created_webhooks == []
    assert result.webhooks["resume"] == "https://discord.com/api/webhooks/h-resume/t"


@respx.mock
def test_setup_explains_permission_errors():
    respx.get(f"{API}/guilds/{GUILD}/channels").mock(return_value=httpx.Response(403))
    with pytest.raises(DiscordBotError, match="Manage Channels"):
        setup_hub("bad", GUILD)


def test_upsert_env_replaces_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DISCORD_WEBHOOK_URL=x\nDISCORD_WEBHOOK_RESUME=old\n# comment\n")
    upsert_env(env, {"DISCORD_WEBHOOK_RESUME": "new", "DISCORD_WEBHOOK_STUDY": "s"})
    assert env.read_text() == (
        "DISCORD_WEBHOOK_URL=x\nDISCORD_WEBHOOK_RESUME=new\n# comment\nDISCORD_WEBHOOK_STUDY=s\n"
    )
