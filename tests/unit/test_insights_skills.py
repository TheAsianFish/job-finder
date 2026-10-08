from datetime import date

from opportunity_radar.config import ProfileConfig
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import get_engine, reset_engine, session_scope
from opportunity_radar.db.tables import Base
from opportunity_radar.insights.skills import (
    build_report,
    load_vocabulary,
    on_profile,
    render_markdown,
    select_postings,
)
from opportunity_radar.models.company import CompanySource
from tests.unit.test_db import alias_hashes, make_record

LONG = " Our team builds things. " * 30


def _vocab():
    return {s.name: s for s in load_vocabulary()}


def test_vocabulary_avoids_known_false_positives():
    v = _vocab()
    assert not v["Spring"].found_in("Software Engineer Intern - Spring 2027")
    assert v["Spring"].found_in("Experience with Spring Boot microservices")
    assert not v["Java"].found_in("Strong JavaScript skills")
    assert v["Java"].found_in("Java, Python")
    assert not v["Security"].found_in("Must be able to obtain a security clearance")
    assert v["Security"].found_in("Interest in application security and threat modeling")
    assert not v["Networking"].found_in("Intern networking events every week")
    assert not v["Embedded systems"].found_in("You will be embedded in the payments team")
    assert v["Embedded systems"].found_in("Write embedded C for microcontrollers")
    assert v["C++"].found_in("Proficiency in C++17")


def test_profile_coverage_uses_profile_terms():
    v = _vocab()
    terms = [t.lower() for t in ["Python", "Kubernetes", "distributed systems"]]
    assert on_profile(v["Python"], terms)
    assert on_profile(v["Kubernetes"], terms)
    assert on_profile(v["Distributed systems"], terms)
    assert not on_profile(v["Rust"], terms)


def test_report_shares_and_selection(tmp_path):
    reset_engine()
    url = f"sqlite:///{tmp_path}/insights.db"
    Base.metadata.create_all(get_engine(url))
    rows = [
        ("1", "Software Engineer Intern", "Python and Rust services." + LONG, "likely_eligible"),
        ("2", "Backend Intern", "Python, Kubernetes, Rust." + LONG, "likely_eligible"),
        ("3", "Software Engineer", "Rust everywhere." + LONG, "likely_eligible"),  # not intern
        ("4", "SWE Intern", "Python only.", "likely_eligible"),  # description too short
        ("5", "Research Intern", "Rust and Python." + LONG, "likely_ineligible"),  # PhD-only etc.
    ]
    with session_scope(url) as session:
        repo.sync_companies(session, [CompanySource(id="stripe", name="Stripe", tier="core")])
        for job_id, title, desc, level in rows:
            record = make_record(job_id, title).model_copy(
                update={
                    "description_text": desc,
                    "is_early_career": True,
                    "match_score": 70.0,
                    "eligibility_level": level,
                }
            )
            repo.insert_job(session, record, alias_hashes(record))
        postings = select_postings(session)
        assert sorted(p.source_job_id for p in postings) == ["1", "2"]
        profile = ProfileConfig()
        report = build_report(postings, load_vocabulary(), profile, today=date(2026, 10, 7))
    reset_engine()
    stats = {s.name: s for s in report.stats}
    assert report.postings == 2
    assert stats["Python"].share == 1.0 and stats["Python"].on_profile
    assert stats["Rust"].share == 1.0 and not stats["Rust"].on_profile
    assert stats["Kubernetes"].share == 0.5
    assert report.gaps[0].name == "Rust"
    text = render_markdown(report)
    assert "| Rust | language | 100% |" in text
    assert "2026-10-07" in text
