"""The portfolio pipeline: projects.yaml in the private career repo.

Lifecycle of a project (AD-32):

    proposed  -> scout (Fable) suggested it; Patrick approves or rejects
    approved  -> the builder picks it up on its next run
    building  -> repo exists; plan PR, then one milestone PR at a time
    finishing -> all milestones merged; resume entry proposed (private PR)
    done      -> resume entry PR opened; nothing left for the builder
    paused / rejected -> ignored by the builder

Patrick changes status by editing the file (GitHub mobile works) or with
`opportunity-radar projects approve|pause|reject <slug>`; the builder only
ever moves approved -> building -> finishing -> done.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import yaml

from opportunity_radar.resume.paths import private_dir

STATUSES = ("proposed", "approved", "building", "finishing", "done", "paused", "rejected")
ACTIVE = ("building", "finishing", "approved")  # builder priority order
OWNER = "TheAsianFish"

HEADER = """\
# Portfolio projects (AD-32). The scout proposes; you approve; the builder ships.
# Change `status` to approve / pause / reject:
#   proposed -> approved   start building it (one project at a time, in file order)
#   any      -> paused     stop working on it;   rejected: never build it
# `autopilot: true` lets the builder merge its own milestone PRs after an
# independent Fable review and green CI, if you haven't commented in 12 hours.
"""


@dataclass
class Project:
    slug: str
    title: str
    status: str = "proposed"
    pitch: str = ""
    why: str = ""  # demand evidence: which roles / skills it targets
    skills: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    release: str = ""  # how real users get it (PyPI, hosted demo, extension, ...)
    repo: str = ""  # owner/name once created
    autopilot: bool = False
    proposed: str = ""
    notes: str = ""

    @property
    def repo_name(self) -> str:
        return self.repo or f"{OWNER}/{self.slug}"


def projects_path() -> Path:
    return private_dir() / "projects.yaml"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "project"


def load_projects(path: Path | None = None) -> list[Project]:
    target = path or projects_path()
    if not target.exists():
        return []
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    rows = raw.get("projects") if isinstance(raw, dict) else None
    known = set(Project.__dataclass_fields__)
    out: list[Project] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("title"):
            continue
        data = {k: v for k, v in row.items() if k in known}
        data["slug"] = slugify(str(data.get("slug") or data["title"]))
        status = str(data.get("status") or "proposed").lower()
        data["status"] = status if status in STATUSES else "proposed"
        for key in ("skills", "stack"):
            data[key] = [str(x) for x in data.get(key) or []]
        for key in ("pitch", "why", "release", "repo", "proposed", "notes", "title"):
            data[key] = str(data.get(key) or "")
        data["autopilot"] = bool(data.get("autopilot"))
        out.append(Project(**data))
    return out


def save_projects(projects: list[Project], path: Path | None = None) -> None:
    target = path or projects_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(p) for p in projects]
    target.write_text(
        HEADER + yaml.safe_dump({"projects": rows}, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )


def find(projects: list[Project], slug: str) -> Project | None:
    wanted = slugify(slug)
    return next((p for p in projects if p.slug == wanted), None)


def set_status(projects: list[Project], slug: str, status: str) -> Project:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; one of {', '.join(STATUSES)}")
    project = find(projects, slug)
    if project is None:
        raise KeyError(f"no project {slug!r} in projects.yaml")
    project.status = status
    return project


def next_project(projects: list[Project]) -> Project | None:
    """One project at a time: finish what's in flight before starting another."""
    for status in ACTIVE:
        for project in projects:
            if project.status == status:
                return project
    return None


def add_proposals(projects: list[Project], new: list[Project]) -> list[Project]:
    """Append scout proposals whose slug or title is not already present."""
    seen = {p.slug for p in projects} | {slugify(p.title) for p in projects}
    added = []
    for project in new:
        if project.slug in seen or slugify(project.title) in seen:
            continue
        project.status = "proposed"
        project.proposed = project.proposed or date.today().isoformat()
        projects.append(project)
        seen.add(project.slug)
        added.append(project)
    return added
