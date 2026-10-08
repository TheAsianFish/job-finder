"""Verified bullets, writer proposals, and the approval pull request (AD-31)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from opportunity_radar.notifications.templates import build_proposals_message
from opportunity_radar.resume.bank import build_bank
from opportunity_radar.resume.polish import MAX_PROPOSALS, Proposal, rewrite_entries
from opportunity_radar.resume.proposals import fresh, pr_body, proposal_key, record, submit
from opportunity_radar.resume.selector import Posting, select
from opportunity_radar.resume.verified import (
    VerifiedBullet,
    apply_verified,
    dump_verified,
    load_verified,
)
from tests.conftest import load_fixture

SOURCE = load_fixture("resume_sample.tex")
ACME = "software-engineering-intern-acme-cloud"
VERIFIED_TEXT = (
    "Designed idempotent invoice retries with request keys in PostgreSQL, "
    "eliminating duplicate charges across 3 payment providers."
)


@pytest.fixture
def bank():
    return build_bank(SOURCE)


def _acme(bank):
    selection = select(bank, Posting.from_text("Backend Intern", "Python PostgreSQL REST APIs"))
    return [pair for pair in selection.experiences if pair[0].id == ACME]


# ---------------------------------------------------------------- verified.yaml


def test_verified_bullets_round_trip_and_attach_as_reserve_facts(bank, tmp_path):
    path = tmp_path / "verified.yaml"
    rows = [
        VerifiedBullet(entry=ACME, text=VERIFIED_TEXT, confirmed=["3 providers?"]),
        VerifiedBullet(entry="gone-entry", text="Something from a deleted entry, long enough."),
    ]
    path.write_text(dump_verified(rows), encoding="utf-8")
    loaded = load_verified(path)
    assert [r.text for r in loaded] == [r.text for r in rows]

    orphans = apply_verified(bank, loaded)
    assert orphans == ["Something from a deleted entry, long enough."]
    acme = next(e for e in bank.entries if e.id == ACME)
    assert len(acme.bullets) == 4 and len(acme.live_bullets) == 3
    assert acme.bullets[-1].verified and "3" in acme.bullets[-1].text
    apply_verified(bank, loaded)  # idempotent
    assert len(acme.bullets) == 4
    # The guard's corpus now accepts the verified facts.
    assert "payment providers" in bank.plain_corpus()


def test_selector_may_show_a_verified_bullet_but_keeps_the_page_budget(bank):
    apply_verified(bank, [VerifiedBullet(entry=ACME, text=VERIFIED_TEXT)])
    posting = Posting.from_text(
        "Payments Backend Intern", "Idempotent PostgreSQL payment retries, duplicate charges"
    )
    selection = select(bank, posting)
    _, shown = next(pair for pair in selection.experiences if pair[0].id == ACME)
    assert any(b.verified for b in shown)
    assert len(shown) == 3  # replaced a weaker bullet, did not grow the entry
    master = sum(len(e.live_bullets) for e in bank.entries if e.active)
    assert len(selection.bullets) <= master


# ---------------------------------------------------------------- writer


def test_writer_may_drop_one_weak_bullet_but_not_two(bank):
    entries = _acme(bank)
    entry, shown = entries[0]
    assert len(shown) == 3
    two = [
        "Architected a Python/PostgreSQL billing service with REST APIs for 40 internal teams.",
        "Cut release time 60% by containerizing deploys with Docker and Kubernetes rollouts.",
    ]
    reply = json.dumps({"entries": [{"id": entry.id, "bullets": two}]})
    outcome = rewrite_entries(
        bank, entries, title="x", company="y", description="", runner=lambda p: reply
    )
    assert len(outcome.accepted[entry.id]) == 2
    one = json.dumps({"entries": [{"id": entry.id, "bullets": two[:1]}]})
    outcome = rewrite_entries(
        bank, entries, title="x", company="y", description="", runner=lambda p: one
    )
    assert "expected" in outcome.rejected[entry.id]


def test_prompt_asks_for_ats_terms_and_proposals(bank):
    from opportunity_radar.resume.polish import build_prompt

    prompt = build_prompt(
        _acme(bank), title="AI Engineer Intern", company="Acme", description="LLM", skills_line=""
    )
    assert "ATS" in prompt and "exact terms" in prompt
    assert '"proposals"' in prompt and "min_bullets" in prompt


def test_model_proposals_and_guard_failures_become_proposals(bank):
    entries = _acme(bank)
    entry, _ = entries[0]
    bullets = [
        "Architected a Python/PostgreSQL billing service with REST APIs for 40 internal teams.",
        "Cut release time 60% by containerizing deploys with Docker and Kubernetes rollouts.",
        "Diagnosed an invoice-queue race condition affecting 900 invoices and fixed it with tests.",
    ]
    reply = json.dumps(
        {
            "entries": [{"id": entry.id, "bullets": bullets}],
            "proposals": [
                {
                    "id": entry.id,
                    "bullet": "Scaled the billing service to 2,000 requests per second with "
                    "connection pooling and PostgreSQL query tuning.",
                    "confirm": ["Did it reach ~2,000 requests per second?"],
                    "why": "the role is about scale",
                },
                {"id": "not-an-entry", "bullet": "x" * 100, "confirm": []},
            ],
        }
    )
    outcome = rewrite_entries(
        bank, entries, title="x", company="y", description="", runner=lambda p: reply
    )
    assert entry.id in outcome.rejected  # 900 is not a fact: the entry keeps its wording
    texts = [p.text for p in outcome.proposals]
    assert texts[0].startswith("Scaled the billing service")  # deliberate proposal first
    assert any("900 invoices" in t for t in texts)  # the guard's catch is asked, not lost
    assert all(p.entry_name == entry.name for p in outcome.proposals)
    assert len(outcome.proposals) <= MAX_PROPOSALS


# ---------------------------------------------------------------- dedupe log


def _proposal(text: str = VERIFIED_TEXT) -> Proposal:
    return Proposal(
        entry_id=ACME,
        entry_name="Software Engineering Intern @ Acme Cloud",
        text=text,
        confirm=["Was it 3 providers?"],
        why="payments role",
    )


def test_fresh_skips_logged_and_verified_proposals(tmp_path):
    first, second = _proposal(), _proposal("Another true-sounding bullet about the queue work.")
    assert fresh([first, second, first], tmp_path) == [first, second]
    record(tmp_path, [first], role="Intern @ Acme", link="https://example/pr/1")
    assert fresh([first, second], tmp_path) == [second]
    (tmp_path / "verified.yaml").write_text(
        dump_verified([VerifiedBullet(entry=ACME, text=second.text)]), encoding="utf-8"
    )
    assert fresh([first, second], tmp_path) == []
    log = yaml.safe_load((tmp_path / "proposals" / "log.yaml").read_text())
    assert log["proposed"][0]["key"] == proposal_key(first.text)


def test_pr_body_explains_merge_edit_close():
    body = pr_body([_proposal()], title="Intern", company="Acme", url="https://jobs/1")
    assert "Merge = these are true" in body and "Close the PR" in body
    assert "- [ ] Was it 3 providers?" in body and VERIFIED_TEXT in body


def test_proposals_message_links_the_pr():
    payload = build_proposals_message("Intern", "Acme", [_proposal()], "https://gh/pr/7", None)
    assert payload["embeds"][0]["url"] == "https://gh/pr/7"
    assert "need your OK" in payload["content"]
    saved = build_proposals_message("Intern", "Acme", [_proposal()], None, "proposals/pending/x")
    assert "proposals/pending/x" in saved["embeds"][0]["description"]


# ---------------------------------------------------------------- pull request


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def career_repo(tmp_path):
    """A private-repo clone whose origin is a local bare repo named like GitHub's."""
    remote = tmp_path / "github.com" / "TheAsianFish" / "career-private.git"
    remote.mkdir(parents=True)
    _git(remote, "init", "-q", "--bare", "-b", "main")
    clone = tmp_path / "private"
    _git(tmp_path, "clone", "-q", str(remote), str(clone))
    _git(clone, "symbolic-ref", "HEAD", "refs/heads/main")
    (clone / "resume.tex").write_text(SOURCE, encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    _git(clone, "push", "-q", "origin", "main")
    return clone, remote


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "gh-calls.txt"
    script = bindir / "gh"
    script.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$GH_TOKEN" "$@" > "{calls}"\n'
        'echo "https://github.com/TheAsianFish/career-private/pull/12"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return calls


def test_submit_opens_a_pr_branch_without_touching_main(career_repo, fake_gh, bank):
    clone, remote = career_repo  # origin path ends in github.com/TheAsianFish/career-private

    result = submit(
        [_proposal()],
        repo=clone,
        bank=bank,
        title="Payments Intern",
        company="Acme Pay",
        url="https://jobs/1",
        runner=lambda prompt: "### bullet\n- **How it works**: ...",
        token="tok-123",
    )
    assert result.error is None
    assert result.pr_url == "https://github.com/TheAsianFish/career-private/pull/12"
    gh_args = fake_gh.read_text().splitlines()
    assert gh_args[0] == "tok-123"
    assert "TheAsianFish/career-private" in gh_args and "--base" in gh_args

    branches = _git(remote, "branch", "--list", "proposals/*")
    assert "acme-pay" in branches
    branch = branches.strip("* ").strip()
    verified = yaml.safe_load(_git(remote, "show", f"{branch}:verified.yaml"))
    assert verified["bullets"][0]["text"] == VERIFIED_TEXT
    assert verified["bullets"][0]["proposed_for"] == "Payments Intern @ Acme Pay"
    files = _git(remote, "ls-tree", "-r", "--name-only", branch)
    assert "prep/" in files
    assert "verified.yaml" not in _git(remote, "ls-tree", "-r", "--name-only", "main")
    assert not (clone / "verified.yaml").exists()  # main's working tree untouched
    assert "proposals/" not in _git(clone, "branch", "--list")
    # Logged on main so it is never asked again.
    assert fresh([_proposal()], clone) == []
    author = _git(remote, "log", "-1", "--format=%an <%ae>", branch)
    assert author == "TheAsianFish <jmchung2006@gmail.com>"


def test_submit_without_github_saves_for_review(tmp_path, bank, monkeypatch):
    monkeypatch.setattr("opportunity_radar.resume.proposals.shutil.which", lambda name: None)
    result = submit(
        [_proposal()],
        repo=tmp_path,
        bank=bank,
        title="Intern",
        company="Acme",
        url=None,
        runner=None,
    )
    assert result.pr_url is None and result.saved is not None
    text = result.saved.read_text()
    assert VERIFIED_TEXT in text and "Interview prep" in text
    assert (
        submit(
            [_proposal()], repo=tmp_path, bank=bank, title="I", company="A", url=None, runner=None
        ).proposals
        == []
    )
