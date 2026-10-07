from datetime import date

import pytest
import respx
from httpx import Response

from opportunity_radar.adapters.base import AdapterError
from opportunity_radar.adapters.simplify import SimplifyAdapter, term_is_live
from opportunity_radar.models.company import CompanySource
from opportunity_radar.pipeline.company_resolver import CompanyResolver, normalize_name, slugify
from tests.conftest import load_fixture

URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"


def source(**config):
    return CompanySource(
        id="simplify-internships",
        name="Simplify internships list",
        tier="broad",
        adapter="simplify",
        adapter_config={"url": URL, **config},
    )


def test_term_is_live():
    today = date(2026, 10, 7)
    assert term_is_live("Summer 2027", today)
    assert term_is_live("Fall 2026", today)
    assert not term_is_live("Summer 2026", today)
    assert not term_is_live("Winter 2026", today)
    assert term_is_live("N/A", today)


@respx.mock
async def test_fetch_filters_and_builds_factual_descriptions(ctx):
    respx.get(URL).mock(return_value=Response(200, text=load_fixture("simplify_listings.json")))
    jobs = await SimplifyAdapter().fetch_jobs(source(), ctx)
    # Hardware category, inactive, past-only term and hidden rows are dropped.
    assert [j.raw["company_name"] for j in jobs] == [
        "Google",
        "Stripe",
        "Acme Robotics, Inc.",
        "Susquehanna International Group (SIG)",
    ]
    google = jobs[0]
    assert google.source_job_id == "aaaa0001-0000-0000-0000-000000000001"
    assert google.apply_url.startswith("https://www.google.com/")
    assert google.locations == ["Mountain View, CA", "New York, NY"]
    assert "Terms: Summer 2027." in (google.description_text or "")
    assert "Sponsorship" not in (google.description_text or "")  # "Other" says nothing
    assert google.posted_at is not None and google.posted_at.year == 2026
    acme = jobs[2]
    assert acme.locations == ["Remote (US)"]
    assert "Sponsorship: U.S. Citizenship is Required." in (acme.description_text or "")
    assert "N/A" not in (jobs[3].description_text or "")


@respx.mock
async def test_new_grad_list_says_new_grad(ctx):
    respx.get(URL).mock(return_value=Response(200, text=load_fixture("simplify_listings.json")))
    jobs = await SimplifyAdapter().fetch_jobs(source(list_kind="new_grad"), ctx)
    assert all("New grad position" in (j.description_text or "") for j in jobs)


@respx.mock
async def test_non_list_payload_is_parse_error(ctx):
    respx.get(URL).mock(return_value=Response(200, json={"listings": []}))
    with pytest.raises(AdapterError) as excinfo:
        await SimplifyAdapter().fetch_jobs(source(), ctx)
    assert excinfo.value.category == "parse"


@respx.mock
async def test_404_is_config_error(ctx):
    respx.get(URL).mock(return_value=Response(404))
    with pytest.raises(AdapterError) as excinfo:
        await SimplifyAdapter().fetch_jobs(source(), ctx)
    assert excinfo.value.category == "config"


def test_resolver_matches_registry_aliases_and_synthesizes():
    registry = [
        CompanySource(id="google", name="Google", tier="core", enabled=False),
        CompanySource(id="stripe", name="Stripe", tier="core"),
        CompanySource(
            id="sig", name="Susquehanna International Group", tier="strong", enabled=False
        ),
        CompanySource(id="cockroach-labs", name="Cockroach Labs", tier="strong"),
    ]
    resolver = CompanyResolver(registry, default_tier="broad", source_id="simplify-internships")
    assert resolver.resolve("Google").id == "google"
    assert resolver.resolve("Susquehanna International Group (SIG)").id == "sig"
    assert resolver.resolve("Cockroach Labs").id == "cockroach-labs"
    stripe = resolver.resolve("Stripe, Inc.")
    assert stripe.id == "stripe" and not resolver.should_ingest(stripe)
    acme = resolver.resolve("Acme Robotics, Inc.")
    assert acme.id == "acme-robotics" and acme.tier == "broad" and not acme.enabled
    assert resolver.should_ingest(acme)
    assert resolver.resolve("Acme Robotics") is acme  # cached synthetic


def test_name_normalisation_keeps_real_words():
    assert normalize_name("Cisco") == "cisco"  # trailing 'co' only dropped as a word
    assert normalize_name("Box Co.") == "box"
    assert slugify("S&C Electric Company") == "s-c-electric"


def test_resolver_matches_by_board_token_and_name_prefix():
    registry = [
        CompanySource(
            id="anduril",
            name="Anduril Industries",
            tier="core",
            adapter="greenhouse",
            adapter_config={"board_token": "andurilindustries"},
        ),
        CompanySource(
            id="nvidia",
            name="NVIDIA",
            tier="core",
            adapter="workday",
            adapter_config={"host": "nvidia.wd5.myworkdayjobs.com", "site": "Ext"},
        ),
        CompanySource(id="aqr", name="AQR Capital", tier="broad"),
        CompanySource(id="meta", name="Meta", tier="core", enabled=False),
    ]
    resolver = CompanyResolver(registry, default_tier="broad", source_id="s")
    by_board = resolver.resolve(
        "Anduril", "https://boards.greenhouse.io/andurilindustries/jobs/5255902007"
    )
    assert by_board.id == "anduril"
    assert (
        resolver.resolve("Nvidia Corp", "https://nvidia.wd5.myworkdayjobs.com/Ext/job/x").id
        == "nvidia"
    )
    assert resolver.resolve("AQR Capital Management").id == "aqr"
    # Single-word names never prefix-match: "Metaview" is not Meta.
    assert resolver.resolve("Metaview").id == "metaview"


@respx.mock
async def test_graduate_only_degree_listings_are_dropped(ctx):
    import json

    listings = json.loads(load_fixture("simplify_listings.json"))
    listings[0]["degrees"] = ["Master's", "PhD"]
    respx.get(URL).mock(return_value=Response(200, json=listings))
    jobs = await SimplifyAdapter().fetch_jobs(source(), ctx)
    assert "Google" not in [j.raw["company_name"] for j in jobs]
