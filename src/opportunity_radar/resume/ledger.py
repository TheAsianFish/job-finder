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
# Progress order for merges: an import never moves an application backwards.
STATUS_RANK = {"applied": 1, "oa": 2, "interview": 3, "offer": 4, "rejected": 5, "withdrawn": 5}
_HEADER = """# Applications log (source of truth for outcomes). One entry per application.
# Add with:  uv run opportunity-radar apply <job-id-or-apply-url> --resume <version>
# Update:    uv run opportunity-radar jobs status <job-id-or-url> oa|interview|offer|rejected
# Or edit by hand. Fields: url (required), company, title, status
# (applied|oa|interview|offer|rejected|withdrawn), applied (YYYY-MM-DD),
# updated, resume (version used), referral (name or "yes"), notes.
"""


@dataclass
class Application:
    url: str = ""
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
        """Canonical apply URL, or company|title when the source had no link."""
        if self.url:
            return canonicalize_url(self.url)
        return f"{_norm(self.company)}|{_norm(self.title)}"


def _norm(text: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def load(path: Path) -> list[Application]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("applications") or []
    apps = []
    for entry in entries:
        if not isinstance(entry, dict) or not (
            entry.get("url") or (entry.get("company") and entry.get("title"))
        ):
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


def find_tailored(job_id: int | None, url: str | None) -> str | None:
    """Newest tailored resume folder made for this job (by job id or apply URL).

    Logging an application records it as the resume version, so outcomes can
    be traced back to the exact resume, projects and panel verdict used.
    """
    import json

    from opportunity_radar.resume.paths import private_dir

    wanted = canonicalize_url(url) if url else None
    root = private_dir() / "tailored"
    if not root.is_dir():
        return None
    for folder in sorted(root.iterdir(), reverse=True):  # names start with the date
        try:
            meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        same_job = job_id is not None and meta.get("job_id") == job_id
        same_url = wanted is not None and canonicalize_url(meta.get("apply_url") or "") == wanted
        if same_job or same_url:
            return folder.name
    return None


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


def merge(path: Path, incoming: list[Application]) -> tuple[int, int]:
    """Merge applications (e.g. from a Simplify export). Returns (added, updated).

    Matching is by apply URL, else company+title. Existing entries keep any
    field the import doesn't provide, and status only ever moves forward.
    """
    apps = load(path)
    index = {a.key: a for a in apps}
    added = updated = 0
    for new in incoming:
        current = index.get(new.key)
        if current is None and new.url:
            current = index.get(f"{_norm(new.company)}|{_norm(new.title)}")
        if current is None:
            apps.append(new)
            index[new.key] = new
            added += 1
            continue
        changed = False
        if STATUS_RANK.get(new.status, 0) > STATUS_RANK.get(current.status, 0):
            current.status = new.status
            changed = True
        for attr in ("url", "company", "title", "resume", "referral", "notes"):
            if not getattr(current, attr) and getattr(new, attr):
                setattr(current, attr, getattr(new, attr))
                changed = True
        if new.applied and new.applied < current.applied:
            current.applied = new.applied
            changed = True
        if changed:
            current.updated = date.today().isoformat()
            updated += 1
    save(path, apps)
    return added, updated


def find_by_company_title(session: Session, company: str, title: str) -> JobRow | None:
    target = _norm(title)
    for row in session.scalars(
        select(JobRow).where(JobRow.company_name.ilike(f"%{company.strip()}%"))
    ):
        if _norm(row.title) == target:
            return row
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
        job = find_job(session, app.url) if app.url else None
        if job is None and app.company and app.title:
            job = find_by_company_title(session, app.company, app.title)
        if job is None:
            result.unmatched.append(app.url or f"{app.company}: {app.title}")
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
