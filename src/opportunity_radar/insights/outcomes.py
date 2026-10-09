"""What works: application outcomes broken down by the choices you control.

Funnel per application: applied -> responded (OA / interview / offer) ->
interview -> offer. Broken down by company tier, role family, season,
resume version, referral, source (employer board vs Simplify list) and how
fast you applied after the posting was first seen. Groups with fewer than
MIN_SAMPLE applications are marked as too small to conclude anything.

When an application's resume version is a tailored resume (a folder under
the private repo's tailored/), its meta.json adds two breakdowns: which
projects were shown, and what the hiring panel predicted (recruiter
"advance", hiring manager "interview"). `lessons()` turns all of this into a
few lines the panel lead reads before reviewing the next resume: the only
"learning" the system does, and the honest kind (no fine-tuning; evidence in
the prompt, labelled weak until samples are big enough).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from opportunity_radar.db.tables import ApplicationRow, CompanyRow, JobRow
from opportunity_radar.utilities.dates import ensure_utc

MIN_SAMPLE = 10
APPLIED_STATES = {"applied", "oa", "interview", "offer", "rejected"}
RESPONDED = {"oa", "interview", "offer"}
INTERVIEWED = {"interview", "offer"}


@dataclass
class Funnel:
    applied: int = 0
    responded: int = 0
    interviewed: int = 0
    offers: int = 0

    def add(self, status: str) -> None:
        self.applied += 1
        self.responded += status in RESPONDED
        self.interviewed += status in INTERVIEWED
        self.offers += status == "offer"

    @property
    def response_rate(self) -> float:
        return self.responded / self.applied if self.applied else 0.0


def _speed_bucket(job: JobRow, app: ApplicationRow) -> str:
    applied, seen = ensure_utc(app.applied_at), ensure_utc(job.first_seen_at)
    if applied is None or seen is None:
        return "unknown"
    days = (applied - seen).total_seconds() / 86400
    if days < 1:
        return "within 1 day"
    if days < 3:
        return "1-3 days"
    if days < 7:
        return "3-7 days"
    return "7+ days"


def tailored_meta(variant: str) -> dict:
    """meta.json of a tailored resume folder, or {} for other resume versions."""
    from opportunity_radar.resume.paths import private_dir

    if not variant or "/" in variant or variant.startswith("."):
        return {}
    path = private_dir() / "tailored" / variant / "meta.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def collect(session: Session) -> dict[str, dict[str, Funnel]]:
    tiers = {c.id: c.tier for c in session.scalars(select(CompanyRow))}
    rows = session.execute(
        select(ApplicationRow, JobRow).join(JobRow, JobRow.id == ApplicationRow.job_id)
    ).all()
    dims: dict[str, dict[str, Funnel]] = defaultdict(lambda: defaultdict(Funnel))
    for app, job in rows:
        if app.status not in APPLIED_STATES:
            continue
        season = f"{job.season} {job.season_year or ''}".strip()
        keys = {
            "Overall": "all",
            "Company tier": tiers.get(job.company_id, "unknown"),
            "Role family": job.role_family or "unknown",
            "Season": season,
            "Resume version": app.resume_variant or "unspecified",
            "Referral": "yes" if app.referral_status else "no",
            "Source": "Simplify list" if job.source_adapter == "simplify" else "employer board",
            "Applied after first seen": _speed_bucket(job, app),
        }
        for dim, key in keys.items():
            dims[dim][key].add(app.status)
        meta = tailored_meta(app.resume_variant or "")
        for project in meta.get("projects") or []:
            dims["Project shown"][str(project)].add(app.status)
        panel = meta.get("panel") or {}
        for seat, dim in (("recruiter", "Panel: recruiter advance"),
                          ("hiring_manager", "Panel: manager interview"),
                          ("editor", "Panel: page coherent")):  # fmt: skip
            if panel.get(seat):
                dims[dim][str(panel[seat])].add(app.status)
    return dims


LESSON_DIMS = (
    "Resume version",
    "Project shown",
    "Panel: recruiter advance",
    "Panel: manager interview",
    "Panel: page coherent",
    "Role family",
    "Company tier",
    "Applied after first seen",
)


def lessons(dims: dict[str, dict[str, Funnel]]) -> str:
    """A few lines of evidence for the resume panel lead (empty-safe)."""
    overall = dims.get("Overall", {}).get("all")
    if not overall or not overall.applied:
        return "No applications logged yet, so there is no outcome evidence to use."
    lines = [
        f"{overall.applied} applications logged, {overall.responded} responses "
        f"({overall.response_rate:.0%}), {overall.interviewed} interviews."
    ]
    if overall.applied < MIN_SAMPLE:
        lines.append(
            f"Fewer than {MIN_SAMPLE} applications: treat every pattern below as anecdote."
        )
    for dim in LESSON_DIMS:
        groups = [(k, f) for k, f in dims.get(dim, {}).items() if f.applied >= 2]
        if len(groups) < 2:
            continue
        groups.sort(key=lambda kv: -kv[1].response_rate)
        parts = [
            f"{k}: {f.responded}/{f.applied}" + ("" if f.applied >= MIN_SAMPLE else " (small)")
            for k, f in groups[:5]
        ]
        lines.append(f"- {dim}: " + "; ".join(parts))
    return "\n".join(lines)


def render(dims: dict[str, dict[str, Funnel]], today: date | None = None) -> str:
    today = today or date.today()
    lines = [
        "# What works: application outcomes",
        "",
        f"Generated {today.isoformat()} by `opportunity-radar insights outcomes`. "
        f"Groups under {MIN_SAMPLE} applications are marked *too early*.",
        "",
    ]
    if not dims:
        lines += [
            "No applications logged yet. Log them with "
            "`uv run opportunity-radar jobs applied <id> --resume <version>` and update "
            "outcomes with `uv run opportunity-radar jobs status <id> oa|interview|offer|rejected`.",
            "",
        ]
        return "\n".join(lines)
    for dim, groups in dims.items():
        lines += [
            f"## {dim}",
            "",
            "| Group | Applied | Responded | Response rate | Interviews | Offers |",
            "|---|---|---|---|---|---|",
        ]
        for key, f in sorted(groups.items(), key=lambda kv: -kv[1].applied):
            rate = f"{f.response_rate:.0%}" + ("" if f.applied >= MIN_SAMPLE else " *too early*")
            lines.append(
                f"| {key} | {f.applied} | {f.responded} | {rate} | {f.interviewed} | {f.offers} |"
            )
        lines.append("")
    return "\n".join(lines)
