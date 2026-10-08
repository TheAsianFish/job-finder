"""Applications log: the durable, private record of what you applied to.

Lives in the private career repo (applications.yaml) so it survives cloud
cache evictions, is editable by hand (even from GitHub mobile), and is the
one place both your Mac and the cloud scanner read. Every scan syncs it into
the job database, which powers the outcomes report and keeps applied roles
out of future digests.
"""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.tables import JobRow
from opportunity_radar.utilities.urls import canonicalize_url

STATUSES = ("applied", "oa", "interview", "offer", "rejected", "withdrawn")
_HEADER = """# Applications log (source of truth for outcomes). One entry per application.
# Add with:  uv run opportunity-radar apply <job-id-or-apply-url> --resume <version>
# Update:    uv run opportunity-radar jobs status <job-id-or-url> oa|interview|offer|rejected
# Or edit by hand. Fields: url (required), company, title, status
# (applied|oa|interview|offer|rejected|withdrawn), applied (YYYY-MM-DD),
# updated, resume (version used), referral (name or "yes"), notes.
"""


@dataclass
class Application:
    url: str
    company: str = ""
    title: str = ""
    status: str = "applied"
    applied: str = field(default_factory=lambda: date.today().isoformat())
    updated: str = field(default_factory=lambda: date.today().isoformat())
    resume: str | None = None
    referral: str | None = None
    notes: str | None = None

    @property
    def key(self) -> str:
        return canonicalize_url(self.url)


def load(path: Path) -> list[Application]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("applications") or []
    apps = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        known = {k: entry[k] for k in Application.__dataclass_fields__ if k in entry}
        for key in ("applied", "updated"):
            if key in known and not isinstance(known[key], str):
                known[key] = str(known[key])
        apps.append(Application(**known))
    return apps


def save(path: Path, apps: list[Application]) -> None:
    rows = [{k: v for k, v in asdict(a).items() if v not in (None, "")} for a in apps]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _HEADER + yaml.safe_dump({"applications": rows}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def upsert(
    path: Path,
    url: str,
    *,
    status: str | None = None,
    company: str | None = None,
    title: str | None = None,
    resume: str | None = None,
    referral: str | None = None,
    notes: str | None = None,
) -> Application:
    if status is not None and status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    apps = load(path)
    key = canonicalize_url(url)
    today = date.today().isoformat()
    found = next((a for a in apps if a.key == key), None)
    if found is None:
        found = Application(url=url)
        apps.append(found)
    for attr, value in (
        ("status", status),
        ("company", company),
        ("title", title),
        ("resume", resume),
        ("referral", referral),
        ("notes", notes),
    ):
        if value:
            setattr(found, attr, value)
    found.updated = today
    save(path, apps)
    return found


def find_job(session: Session, url: str) -> JobRow | None:
    key = canonicalize_url(url)
    for column in (JobRow.canonical_url, JobRow.apply_url, JobRow.source_url):
        row = session.scalars(select(JobRow).where(column == url)).first()
        if row is not None:
            return row
    row = session.scalars(select(JobRow).where(JobRow.canonical_url == key)).first()
    if row is not None:
        return row
    for candidate in session.scalars(
        select(JobRow).where(JobRow.apply_url.like(f"%{key.split('//')[-1][:60]}%"))
    ):
        if (
            canonicalize_url(candidate.apply_url) == key
            or canonicalize_url(candidate.source_url) == key
        ):
            return candidate
    return None


@dataclass
class SyncResult:
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)


def sync_to_db(session: Session, apps: list[Application]) -> SyncResult:
    """Mirror the log into the applications table (idempotent)."""
    from datetime import datetime, time

    from opportunity_radar.utilities.dates import ensure_utc

    result = SyncResult()
    for app in apps:
        job = find_job(session, app.url)
        if job is None:
            result.unmatched.append(app.url)
            continue
        row = repo.set_application_status(session, job.id, app.status)
        try:
            applied_day = date.fromisoformat(app.applied)
            row.applied_at = ensure_utc(datetime.combine(applied_day, time(12)))
        except ValueError:
            pass
        row.resume_variant = app.resume or row.resume_variant
        row.referral_status = app.referral or row.referral_status
        row.notes = app.notes or row.notes
        result.matched += 1
    return result


def commit_and_push(directory: Path, message: str, push: bool = True) -> str:
    """Commit the private repo (if it is one) and push. Returns a status line."""
    if not (directory / ".git").exists():
        return "private dir is not a git repo; saved locally only"

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(directory), *args], capture_output=True, text=True, check=False
        )

    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode == 0:
        return "nothing to commit"
    commit = git(
        "-c",
        "user.name=TheAsianFish",
        "-c",
        "user.email=jmchung2006@gmail.com",
        "commit",
        "-q",
        "-m",
        message,
    )
    if commit.returncode != 0:
        return f"commit failed: {commit.stderr.strip()[:200]}"
    if not push:
        return "committed"
    pushed = git("push", "-q")
    if pushed.returncode != 0:
        git("pull", "-q", "--rebase")
        pushed = git("push", "-q")
    return (
        "committed and pushed"
        if pushed.returncode == 0
        else f"push failed: {pushed.stderr.strip()[:200]}"
    )
