from datetime import UTC, datetime

import respx
from httpx import Response

from opportunity_radar.db.tables import JobRow
from opportunity_radar.notifications import templates
from opportunity_radar.notifications.discord import DiscordNotifier

WEBHOOK = "https://discord.com/api/webhooks/123/abc"


def make_job_row(**overrides) -> JobRow:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    defaults = dict(
        id=1,
        identity_hash="x" * 64,
        content_hash="y" * 64,
        source_name="palantir",
        source_adapter="lever",
        source_job_id="123",
        company_id="palantir",
        company_name="Palantir",
        title="Software Engineer Intern - Spring 2027",
        normalized_title="Software Engineer Intern - Spring 2027",
        description_text="Build things.",
        primary_location="New York, NY",
        all_locations=["New York, NY"],
        remote_type="onsite",
        season="spring",
        season_year=2027,
        season_confidence=1.0,
        first_seen_at=now,
        last_seen_at=now,
        posted_at=now,
        apply_url="https://jobs.lever.co/palantir/123",
        canonical_url="https://jobs.lever.co/palantir/123",
        source_url="https://jobs.lever.co/palantir/123",
        status="active",
        match_score=93.0,
        match_reasons=["Core target company", "Explicit Spring 2027 timing"],
        risk_flags=["Full-time availability required"],
        eligibility_level="likely_eligible",
    )
    defaults.update(overrides)
    return JobRow(**defaults)


def test_embed_contains_required_fields():
    payload = templates.build_job_embed(make_job_row())
    embed = payload["embeds"][0]
    assert embed["url"] == "https://jobs.lever.co/palantir/123"
    assert embed["color"] == templates.COLOR_HIGH
    names = {f["name"] for f in embed["fields"]}
    assert {"Company", "Score", "Season", "Location", "First seen", "Links"} <= names
    links = next(f for f in embed["fields"] if f["name"] == "Links")
    assert "Apply directly" in links["value"]
    assert "127.0.0.1:8765" in links["value"]
    assert payload["allowed_mentions"] == {"parse": []}


def test_embed_sanitizes_mentions():
    job = make_job_row(title="@everyone Apply now!!", company_name="Evil @here Co")
    payload = templates.build_job_embed(job)
    assert "@everyone" not in payload["embeds"][0]["title"]
    fields = payload["embeds"][0]["fields"]
    company = next(f for f in fields if f["name"] == "Company")
    assert "@here" not in company["value"]


def test_inferred_season_is_labeled():
    job = make_job_row(season="fall", season_year=None, season_confidence=0.7)
    payload = templates.build_job_embed(job)
    season_field = next(f for f in payload["embeds"][0]["fields"] if f["name"] == "Season")
    assert "inferred" in season_field["value"]


def test_digest_payload_skips_empty_sections():
    payload = templates.build_digest_payload(
        "Digest", {"New high-priority": ["line1"], "Empty": []}
    )
    assert payload is not None
    assert len(payload["embeds"][0]["fields"]) == 1
    assert templates.build_digest_payload("Digest", {"A": [], "B": []}) is None


@respx.mock
async def test_notifier_sends_and_handles_rate_limit():
    route = respx.post(WEBHOOK)
    route.side_effect = [
        Response(429, json={"retry_after": 0.01}),
        Response(204),
    ]
    notifier = DiscordNotifier(WEBHOOK)
    assert await notifier.send({"content": "hi"}) is True
    assert route.call_count == 2


async def test_notifier_unconfigured_returns_false():
    notifier = DiscordNotifier(None)
    assert await notifier.send({"content": "hi"}) is False
    assert notifier.configured is False


@respx.mock
async def test_notifier_gives_up_on_400():
    respx.post(WEBHOOK).mock(return_value=Response(400, text="bad payload"))
    notifier = DiscordNotifier(WEBHOOK)
    assert await notifier.send({"content": "hi"}) is False
