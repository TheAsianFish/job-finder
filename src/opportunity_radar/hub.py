"""The shared memory every agent reads first and writes last (AD-33).

Lives in the private career repo under hub/ (personal, so never public):

    hub/ABOUT.md          who Patrick is, goals, preferences, standing decisions
                          (curated; agents propose edits, they don't rewrite it)
    hub/JOURNAL.md        append-only log: one dated entry per agent run or
                          working session (what happened, what's next)
    hub/projects/<slug>.md  living summary of each portfolio project
                          (architecture, status, decisions, lessons), so each
                          new project builds on the previous ones

The whole hub is small (tens of KB), so agents read all of it every run
instead of retrieving pieces; a retrieval index would only add failure modes
at this size. `bundle()` is what agents get as context.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from opportunity_radar.resume.paths import private_dir

JOURNAL_HEADER = """\
# Journal

Append-only. Every agent run and working session adds one entry at the end:
`## YYYY-MM-DD HH:MM UTC · source`, then what happened and what's next.
"""
_ENTRY_RE = re.compile(r"^## \d{4}-\d{2}-\d{2} ", re.MULTILINE)
MAX_JOURNAL_ENTRIES = 40


def hub_dir() -> Path:
    return private_dir() / "hub"


def about_path() -> Path:
    return hub_dir() / "ABOUT.md"


def journal_path() -> Path:
    return hub_dir() / "JOURNAL.md"


def project_summary_path(slug: str) -> Path:
    return hub_dir() / "projects" / f"{slug}.md"


def append_journal(source: str, text: str, when: datetime | None = None) -> Path:
    path = journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(JOURNAL_HEADER, encoding="utf-8")
    stamp = (when or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    body = text.strip() or "(no details)"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {stamp} · {source.strip()}\n\n{body}\n")
    return path


def recent_journal(limit: int = MAX_JOURNAL_ENTRIES) -> str:
    path = journal_path()
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    starts = [m.start() for m in _ENTRY_RE.finditer(text)]
    if len(starts) <= limit:
        return text[starts[0] :].strip() if starts else ""
    return text[starts[-limit] :].strip()


def write_project_summary(slug: str, text: str) -> Path:
    path = project_summary_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def bundle(journal_entries: int = MAX_JOURNAL_ENTRIES) -> str:
    """Everything an agent should know, as one Markdown document."""
    parts = ["# Shared context (private hub; never copy into public files)"]
    if about_path().exists():
        parts.append(about_path().read_text(encoding="utf-8").strip())
    summaries = sorted((hub_dir() / "projects").glob("*.md"))
    if summaries:
        parts.append("# Portfolio projects so far")
        parts += [s.read_text(encoding="utf-8").strip() for s in summaries]
    journal = recent_journal(journal_entries)
    if journal:
        parts.append(f"# Recent journal (last {journal_entries} entries)\n\n{journal}")
    return "\n\n".join(parts) + "\n"
