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
    assert {"Company", "Score", "Season", "Location", "Detected", "Links"} <= names
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


def test_new_sources_summary_lists_best_matches_once():
    jobs = [make_job_row(id=i, title=f"SWE Intern {i} - Summer 2027") for i in range(20)]
    payload = templates.build_new_sources_summary(["Waymo", "xAI"], jobs, hidden_count=5)
    embed = payload["embeds"][0]
    assert "2 new source(s)" in embed["title"]
    assert "Waymo" in embed["description"]
    value = "\n".join(f["value"] for f in embed["fields"])
    assert value.count("SWE Intern") == templates.SUMMARY_LINE_LIMIT
    assert "+ 5 more on the dashboard" in value
    assert payload["allowed_mentions"] == {"parse": []}


def test_new_sources_summary_with_no_matches_says_so():
    payload = templates.build_new_sources_summary(["QuietCo"], [], hidden_count=0)
    assert "No early-career software roles" in payload["embeds"][0]["fields"][0]["value"]


def test_digest_payload_chunks_long_sections_without_cutting_lines():
    long_url = "https://example.wd5.myworkdayjobs.com/en-US/Site/job/US-CA-Santa-Clara/" + "x" * 90
    lines = [
        f"**80** · [Software Engineer Intern {i} - Summer 2027]({long_url}) — Co" for i in range(12)
    ]
    payload = templates.build_digest_payload("t", {"New review-worthy": lines})
    fields = payload["embeds"][0]["fields"]
    assert len(fields) >= 2
    assert fields[0]["name"] == "New review-worthy"
    assert fields[1]["name"] == "(cont.)"
    joined = "\n".join(f["value"] for f in fields)
    assert joined.count("Software Engineer Intern") == 12
    assert "…" not in joined
    assert all(len(f["value"]) <= 1024 for f in fields)


def test_markdown_chunks_respect_discord_limits():
    md = "# Weekly review\n\n| a | b |\n|---|---|\n| 1 | 2 |\n" + ("- line of text\n" * 600)
    chunks = templates.markdown_chunks(md)
    assert chunks[0].startswith("**Weekly review**")
    assert all(len(c) <= 4000 for c in chunks)
    assert "|---|" not in "".join(chunks)
    assert len(chunks) >= 2


@respx.mock
async def test_send_files_posts_multipart_attachment():
    route = respx.post(WEBHOOK).mock(return_value=Response(200))
    ok = await DiscordNotifier(WEBHOOK).send_files(
        {"content": "resume"}, [("resume.pdf", b"%PDF-1.4 test", "application/pdf")]
    )
    assert ok
    request = route.calls[0].request
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'filename="resume.pdf"' in request.content
    assert b"payload_json" in request.content


def test_alert_carries_resume_verdict_when_a_resume_exists(tmp_path, monkeypatch):
    from tests.conftest import load_fixture

    private = tmp_path / "private"
    private.mkdir()
    (private / "resume.tex").write_text(load_fixture("resume_sample.tex"), encoding="utf-8")
    monkeypatch.setenv("OPPORTUNITY_RADAR_PRIVATE_DIR", str(private))
    fits = make_job_row(
        title="Backend Engineer Intern",
        description_text="Build Python services on PostgreSQL with REST APIs, Docker and Kubernetes. "
        * 8,
    )
    field = next(
        f for f in templates.build_job_embed(fits)["embeds"][0]["fields"] if f["name"] == "Resume"
    )
    assert field["value"].startswith("✅") and "apply as-is" in field["value"]
    gap = make_job_row(
        title="Rust Systems Intern", description_text="Rust Kafka Terraform Go tooling. " * 20
    )
    field = next(
        f for f in templates.build_job_embed(gap)["embeds"][0]["fields"] if f["name"] == "Resume"
    )
    assert field["value"].startswith("🛠️") and "Rust" in field["value"]
    short = make_job_row(description_text="Internship listed on the Simplify internships list.")
    field = next(
        f for f in templates.build_job_embed(short)["embeds"][0]["fields"] if f["name"] == "Resume"
    )
    assert field["value"].startswith("❔")


def test_alert_has_no_resume_field_without_a_resume():
    names = {f["name"] for f in templates.build_job_embed(make_job_row())["embeds"][0]["fields"]}
    assert "Resume" not in names
