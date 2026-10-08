"""Bullets Patrick confirmed true: verified.yaml in the private career repo.

A bullet lands here only by merging a proposal pull request (see
proposals.py): Claude drafted it, could not back it with facts already in
resume.tex, and Patrick approved (or corrected) it. From then on it is a
fact like any other: the selector and the guarded writer may use it for the
entry it belongs to, and the guard accepts its numbers and names. It is
never shown on the master resume unless resume.tex itself is edited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from opportunity_radar.insights.skills import default_vocabulary
from opportunity_radar.resume.bank import Bank, Bullet, Entry
from opportunity_radar.resume.latex import escape
from opportunity_radar.resume.paths import private_dir

HEADER = """\
# Verified bullets: each one was proposed by the resume writer, then reviewed
# and approved by Patrick (merging its proposal PR = "this is true").
# The tailor may use them for their entry like any line in resume.tex.
# Edit or delete freely; `entry` is the entry id from `opportunity-radar resume bank`.
"""


@dataclass
class VerifiedBullet:
    entry: str  # entry id (slug of the entry name)
    text: str  # plain text, exactly as it may appear on a resume
    entry_name: str = ""
    confirmed: list[str] = field(default_factory=list)  # what Patrick was asked to confirm
    proposed_for: str = ""  # "Title @ Company" that prompted it
    date: str = ""


def verified_path() -> Path:
    return private_dir() / "verified.yaml"


def load_verified(path: Path | None = None) -> list[VerifiedBullet]:
    target = path or verified_path()
    if not target.exists():
        return []
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    rows = raw.get("bullets") if isinstance(raw, dict) else None
    out: list[VerifiedBullet] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("entry") or not row.get("text"):
            continue
        out.append(
            VerifiedBullet(
                entry=str(row["entry"]),
                text=" ".join(str(row["text"]).split()),
                entry_name=str(row.get("entry_name") or ""),
                confirmed=[str(c) for c in row.get("confirmed") or []],
                proposed_for=str(row.get("proposed_for") or ""),
                date=str(row.get("date") or ""),
            )
        )
    return out


def dump_verified(rows: list[VerifiedBullet]) -> str:
    data = [
        {
            "entry": r.entry,
            "entry_name": r.entry_name,
            "text": r.text,
            "confirmed": r.confirmed,
            "proposed_for": r.proposed_for,
            "date": r.date,
        }
        for r in rows
    ]
    return HEADER + yaml.safe_dump(
        {"bullets": data}, sort_keys=False, allow_unicode=True, width=100
    )


def _find_entry(bank: Bank, row: VerifiedBullet) -> Entry | None:
    by_id = {e.id: e for e in bank.entries}
    if row.entry in by_id:
        return by_id[row.entry]
    wanted = row.entry_name.strip().lower()
    return next((e for e in bank.entries if wanted and e.name.lower() == wanted), None)


def apply_verified(bank: Bank, rows: list[VerifiedBullet]) -> list[str]:
    """Attach verified bullets to their entries (in place). Returns texts whose
    entry no longer exists (renamed or deleted in resume.tex)."""
    orphans: list[str] = []
    vocab = default_vocabulary()
    for row in rows:
        entry = _find_entry(bank, row)
        if entry is None:
            orphans.append(row.text)
            continue
        if any(_norm(b.text) == _norm(row.text) for b in entry.bullets):
            continue
        evidence = f"{row.text}\n{entry.name}"
        entry.bullets.append(
            Bullet(
                id=f"{entry.id}-v{len(entry.bullets)}",
                tex=escape(row.text),
                text=row.text,
                skills=frozenset(s.name for s in vocab if s.found_in(evidence)),
                bold=(),
                has_metric=bool(re.search(r"\d", row.text)),
                verified=True,
            )
        )
    return orphans


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
