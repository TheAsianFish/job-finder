"""What works: application outcomes broken down by the choices you control.

Funnel per application: applied -> responded (OA / interview / offer) ->
interview -> offer. Broken down by company tier, role family, season,
resume version, referral, source (employer board vs Simplify list) and how
fast you applied after the posting was first seen. Groups with fewer than
MIN_SAMPLE applications are marked as too small to conclude anything.
"""

from __future__ import annotations

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
    return dims


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
