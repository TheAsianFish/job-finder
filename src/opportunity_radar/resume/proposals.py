"""Bullet proposals -> one pull request in the private career repo.

The writer (polish.py) proposes a bullet when it believes a stronger story
exists but needs a fact Patrick has not written down. Nothing is ever put
on a resume on the model's word. Instead, per tailored role:

1. drop proposals already made before (proposals/log.yaml) or already verified,
2. Claude writes an interview prep sheet for them (how it works, trade-offs,
   likely follow-ups), so an approved bullet can be defended in an interview,
3. a branch adds them to verified.yaml plus the prep sheet, and a pull request
   is opened. Merge = "these are true" (edit lines first to correct them,
   delete a block to reject just that one); close = reject all.

Without a GitHub token or the gh CLI the same content is saved to
proposals/pending/ in the private repo so nothing is lost.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from opportunity_radar.resume.bank import Bank
from opportunity_radar.resume.polish import Proposal, Runner
from opportunity_radar.resume.private_pr import gh_token, open_private_pr
from opportunity_radar.resume.verified import (
    VerifiedBullet,
    dump_verified,
    load_verified,
)

LOG_NAME = "proposals/log.yaml"


@dataclass
class SubmitResult:
    proposals: list[Proposal]
    pr_url: str | None = None
    saved: Path | None = None
    error: str | None = None


def proposal_key(text: str) -> str:
    norm = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return hashlib.sha1(norm.encode()).hexdigest()[:12]


def _load_log(repo: Path) -> list[dict]:
    path = repo / LOG_NAME
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = raw.get("proposed") if isinstance(raw, dict) else None
    return [r for r in rows or [] if isinstance(r, dict)]


def fresh(proposals: list[Proposal], repo: Path) -> list[Proposal]:
    """Proposals never made before and not already verified."""
    known = {str(r.get("key")) for r in _load_log(repo)}
    known |= {proposal_key(v.text) for v in load_verified(repo / "verified.yaml")}
    out, seen = [], set()
    for proposal in proposals:
        key = proposal_key(proposal.text)
        if key in known or key in seen:
            continue
        seen.add(key)
        out.append(proposal)
    return out


def record(repo: Path, proposals: list[Proposal], *, role: str, link: str | None) -> None:
    """Remember what was proposed (so a denial is never asked again)."""
    rows = _load_log(repo)
    today = date.today().isoformat()
    rows += [
        {
            "key": proposal_key(p.text),
            "entry": p.entry_id,
            "text": p.text,
            "for": role,
            "date": today,
            "review": link or "saved locally",
        }
        for p in proposals
    ]
    path = repo / LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Every bullet ever proposed (so none is asked twice). Status lives on its PR.\n"
        + yaml.safe_dump({"proposed": rows}, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )


def prep_prompt(proposals: list[Proposal], bank: Bank, *, title: str, company: str) -> str:
    facts = {
        e.id: [b.text for b in e.bullets]
        for e in bank.entries
        if e.id in {p.entry_id for p in proposals}
    }
    items = "\n".join(
        f"{i}. [{p.entry_name}] {p.text}\n   Confirming: {'; '.join(p.confirm) or 'accuracy'}"
        for i, p in enumerate(proposals, 1)
    )
    return f"""You are a senior engineer coaching a candidate for a "{title}" interview at {company}.
The candidate is about to confirm that each resume bullet below is true. Write a concise
interview prep sheet in Markdown so they can explain each one under deep follow-up questions.

For each bullet, a "### " heading with the bullet, then:
- **How it works**: the system and the candidate's part in it, in 3-5 sentences, using only
  what the bullet and the entry's facts say; mark anything they must fill in from memory
  as "(you: ...)" instead of inventing it.
- **Trade-offs to explain**: 2-3 design decisions an interviewer will probe, with the
  alternatives they should be able to compare.
- **Likely follow-ups**: 5-6 questions, each with a one-line outline of a strong answer.
- **Numbers to know cold**: every number in the bullet and how it was measured.

Never invent details about the candidate's work beyond the bullet and facts given.
Reply with only the Markdown.

Bullets:
{items}

Facts already on the resume for these entries:
{yaml.safe_dump(facts, allow_unicode=True, width=100)}
"""


def build_prep(
    proposals: list[Proposal], bank: Bank, *, title: str, company: str, runner: Runner | None
) -> str:
    header = f"# Interview prep: {title} @ {company}\n\n"
    if runner is not None:
        try:
            text = runner(prep_prompt(proposals, bank, title=title, company=company)).strip()
            if text:
                return header + text + "\n"
        except Exception:  # never block a proposal on the prep sheet
            pass
    lines = [header, "_Prep sheet unavailable (Claude not reachable); outline:_\n"]
    for p in proposals:
        lines.append(f"### {p.text}\n- How it works: (you: ...)\n- Likely follow-ups: ...\n")
    return "\n".join(lines)


def pr_body(proposals: list[Proposal], *, title: str, company: str, url: str | None) -> str:
    lines = [
        f"Bullet proposals from tailoring **{title}** at **{company}**"
        + (f" ([posting]({url}))" if url else "")
        + ".",
        "",
        "Each needs a fact only you know. **Merge = these are true** (they join "
        "`verified.yaml` and the tailor may use them from then on).",
        "- Wrong detail? Edit the line in `verified.yaml` on this branch, then merge.",
        "- Only some true? Delete the other blocks on this branch, then merge.",
        "- None true? Close the PR. It will not be proposed again.",
        "",
        "Interview prep for each bullet is in the `prep/` file of this PR.",
        "",
    ]
    for i, p in enumerate(proposals, 1):
        lines.append(f"### {i}. {p.entry_name}")
        lines.append(f"> {p.text}")
        for question in p.confirm or ["Is every detail accurate?"]:
            lines.append(f"- [ ] {question}")
        if p.why:
            lines.append(f"_Why: {p.why}_")
        lines.append("")
    return "\n".join(lines)


def _write_branch_files(
    root: Path, proposals: list[Proposal], prep: str, *, role: str, prep_name: str
) -> None:
    rows = load_verified(root / "verified.yaml")
    today = date.today().isoformat()
    rows += [
        VerifiedBullet(
            entry=p.entry_id,
            entry_name=p.entry_name,
            text=p.text,
            confirmed=p.confirm,
            proposed_for=role,
            date=today,
        )
        for p in proposals
    ]
    (root / "verified.yaml").write_text(dump_verified(rows), encoding="utf-8")
    prep_path = root / "prep" / prep_name
    prep_path.parent.mkdir(parents=True, exist_ok=True)
    prep_path.write_text(prep, encoding="utf-8")


def open_pull_request(
    repo: Path,
    proposals: list[Proposal],
    prep: str,
    *,
    title: str,
    company: str,
    url: str | None,
    token: str | None,
) -> str:
    """One PR adding the proposals to verified.yaml plus the prep sheet."""
    company_slug = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")[:24] or "role"
    stamp = date.today().isoformat()
    role = f"{title} @ {company}"
    return open_private_pr(
        repo,
        branch=f"proposals/{stamp}-{company_slug}-{proposal_key(proposals[0].text)[:6]}",
        title=f"Review {len(proposals)} bullet(s): {role}",
        body=pr_body(proposals, title=title, company=company, url=url),
        message=f"Propose {len(proposals)} bullet(s) for {role}",
        write=lambda work: _write_branch_files(
            work, proposals, prep, role=role, prep_name=f"{stamp}-{company_slug}.md"
        ),
        token=token,
    )


def submit(
    proposals: list[Proposal],
    *,
    repo: Path,
    bank: Bank,
    title: str,
    company: str,
    url: str | None,
    runner: Runner | None,
    token: str | None = None,
) -> SubmitResult:
    """Fresh proposals -> PR (or a pending file). Records them in the log."""
    todo = fresh(proposals, repo)
    result = SubmitResult(proposals=todo)
    if not todo:
        return result
    prep = build_prep(todo, bank, title=title, company=company, runner=runner)
    token = gh_token(token)
    try:
        result.pr_url = open_pull_request(
            repo, todo, prep, title=title, company=company, url=url, token=token
        )
    except RuntimeError as exc:
        result.error = str(exc)
        pending = repo / "proposals" / "pending"
        pending.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^a-z0-9]+", "-", f"{date.today()}-{company}".lower()).strip("-")
        result.saved = pending / f"{name}.md"
        result.saved.write_text(
            pr_body(todo, title=title, company=company, url=url) + "\n\n" + prep,
            encoding="utf-8",
        )
    record(repo, todo, role=f"{title} @ {company}", link=result.pr_url)
    return result
