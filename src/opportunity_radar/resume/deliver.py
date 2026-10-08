"""Resume checks for important new roles; speak up only on a real disconnect.

For each fresh immediate alert at a core/strong company (at most a few per
scan): get the full description (fetching it from the ATS when the posting
came from the Simplify list), run the deterministic fit assessment against
the standing resume, and stay silent when it fits. When it doesn't:
- Claude writes a candid review (weak bullets, project/culture fit,
  competitiveness, swaps, a new-project proposal when the bank can't close
  the gap),
- a tailored resume is built with technical STAR rewrites behind the guard,
- Discord gets one message: verdict + flags + the PDF + the full review,
- everything is archived in the private repo; project proposals are also
  appended to reports/project-queue.md for the weekly agent.
Every checked job is marked (jobs.resume_sent_at) so it is never re-checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import structlog
from sqlalchemy import select

from opportunity_radar.config import get_settings
from opportunity_radar.db.engine import session_scope
from opportunity_radar.db.tables import CompanyRow, JobRow
from opportunity_radar.notifications import templates
from opportunity_radar.notifications.discord import DiscordNotifier
from opportunity_radar.resume.assess import MIN_DESCRIPTION, FitAssessment, assess
from opportunity_radar.resume.describe import fetch_description
from opportunity_radar.resume.ledger import commit_and_push
from opportunity_radar.resume.paths import private_dir, resume_source
from opportunity_radar.resume.polish import Runner
from opportunity_radar.resume.review import Review, render_markdown, review
from opportunity_radar.resume.selector import Posting
from opportunity_radar.resume.tailor import load_bank, master_text, slug, tailor
from opportunity_radar.utilities.dates import utcnow

logger = structlog.get_logger(__name__)
LOOKBACK_HOURS = 6
IMPORTANT_TIERS = ("core", "strong")


@dataclass
class DeliveryReport:
    pending: int = 0
    checked: int = 0
    flagged: list[str] = field(default_factory=list)
    quiet: int = 0
    skipped: int = 0
    failed: list[str] = field(default_factory=list)
    skipped_reason: str | None = None
    git: str | None = None


def pending_jobs(db_url: str | None = None, lookback_hours: int = LOOKBACK_HOURS) -> list[int]:
    since = utcnow() - timedelta(hours=lookback_hours)
    with session_scope(db_url) as session:
        return list(
            session.scalars(
                select(JobRow.id)
                .where(
                    JobRow.alerted_at.isnot(None),
                    JobRow.alerted_at >= since,
                    JobRow.resume_sent_at.is_(None),
                    JobRow.status == "active",
                )
                .order_by(JobRow.match_score.desc())
            )
        )


def _mark_checked(db_url: str | None, job_id: int) -> None:
    with session_scope(db_url) as session:
        job = session.get(JobRow, job_id)
        if job is not None:
            job.resume_sent_at = utcnow()


def _queue_project(rev: Review, title: str, company: str) -> None:
    project = rev.new_project
    if not project.get("needed"):
        return
    queue = private_dir() / "reports" / "project-queue.md"
    queue.parent.mkdir(parents=True, exist_ok=True)
    if not queue.exists():
        queue.write_text(
            "# Project queue\n\nProposed by resume checks; the weekly agent "
            "consolidates these into project plans.\n\n",
            encoding="utf-8",
        )
    with queue.open("a", encoding="utf-8") as handle:
        handle.write(
            f"## {date.today().isoformat()}: {project.get('title', 'Untitled')}\n"
            f"- For: {title} ({company})\n- Closes: {', '.join(project.get('skills') or [])}\n"
            f"- Pitch: {project.get('pitch', '')}\n- Why: {project.get('why', '')}\n\n"
        )


@dataclass
class PostingRef:
    """What a resume check needs to know about a posting (DB row or bare URL)."""

    title: str
    company_name: str
    apply_url: str
    description: str
    job_id: int | None = None


async def run_check(
    ref: PostingRef,
    *,
    notifier: DiscordNotifier,
    bank,
    baseline: str,
    runner: Runner | None,
    force: bool = False,
) -> tuple[str, FitAssessment | None]:
    """Assess -> (if flagged or forced) review + tailor + one Discord message."""
    title, company, url = ref.title, ref.company_name, ref.apply_url
    description = ref.description
    if len(description) < MIN_DESCRIPTION:
        description = fetch_description(url) or description
    if len(description) < MIN_DESCRIPTION:
        return "skipped", None  # nothing substantive to judge against
    fit = assess(bank, Posting.from_text(title, description), baseline)
    if not fit.needs_attention and not force:
        return "quiet", fit

    rev = review(
        bank,
        baseline,
        title=title,
        company=company,
        description=description,
        fit=fit,
        runner=runner,
    )
    out_dir = (
        private_dir() / "tailored" / f"{date.today().isoformat()}-{slug(company, 24)}-{slug(title)}"
    )
    result = tailor(
        bank,
        title=title,
        company=company,
        description=description,
        out_dir=out_dir,
        runner=runner,
        baseline_text=baseline,
        meta={
            "job_id": ref.job_id,
            "apply_url": url,
            "severity": fit.severity,
            "reasons": fit.reasons,
        },
        guidance=[f"{w.get('bullet', '')[:90]}: {w.get('fix', '')}" for w in rev.weak_bullets[:6]]
        + [f"Swap in: {s}" for s in rev.swaps[:2]],
        prefer=rev.swaps[:3],
    )
    review_md = render_markdown(rev, fit, title=title, company=company, url=url)
    (out_dir / "review.md").write_text(review_md, encoding="utf-8")
    _queue_project(rev, title, company)

    payload = templates.build_resume_check_message(ref, fit, rev, result.summary)
    files = [("review.md", review_md.encode("utf-8"), "text/markdown")]
    if result.pdf_path is not None:
        files.insert(0, (result.pdf_path.name, result.pdf_path.read_bytes(), "application/pdf"))
    sent = await notifier.send_files(payload, files)
    if not sent and notifier.configured:
        return "failed", fit
    return "flagged", fit


async def check_job(
    job_id: int,
    *,
    notifier: DiscordNotifier,
    bank,
    baseline: str,
    runner: Runner | None,
    db_url: str | None = None,
    force: bool = False,
) -> tuple[str, FitAssessment | None]:
    """Check one stored job; non-priority roles are skipped unless forced."""
    with session_scope(db_url) as session:
        job = session.get(JobRow, job_id)
        if job is None:
            return "skipped", None
        company_row = session.get(CompanyRow, job.company_id)
        tier = company_row.tier if company_row else "broad"
        ref = PostingRef(
            title=job.title,
            company_name=job.company_name,
            apply_url=job.apply_url,
            description=job.description_text or "",
            job_id=job.id,
        )
        family = job.role_family
    targets = set(get_settings().profile.preferences.role_families) | {"general_swe"}
    if not force and (tier not in IMPORTANT_TIERS or family not in targets):
        return "skipped", None
    return await run_check(
        ref, notifier=notifier, bank=bank, baseline=baseline, runner=runner, force=force
    )


async def check_url(
    url: str,
    *,
    notifier: DiscordNotifier,
    runner: Runner | None,
    title: str | None = None,
    company: str | None = None,
    db_url: str | None = None,
) -> tuple[str, FitAssessment | None]:
    """On-demand brutal review of any posting by link (tracked or not)."""
    from opportunity_radar.resume.ledger import find_job

    bank = load_bank()
    baseline = master_text(bank)
    with session_scope(db_url) as session:
        job = find_job(session, url)
        if job is not None:
            ref = PostingRef(
                title=title or job.title,
                company_name=company or job.company_name,
                apply_url=job.apply_url,
                description=job.description_text or "",
                job_id=job.id,
            )
        else:
            host = url.split("//")[-1].split("/")[0]
            ref = PostingRef(
                title=title or "Role",
                company_name=company or host,
                apply_url=url,
                description="",
            )
    return await run_check(
        ref, notifier=notifier, bank=bank, baseline=baseline, runner=runner, force=True
    )


async def deliver_pending(
    notifier: DiscordNotifier,
    *,
    db_url: str | None = None,
    runner: Runner | None = None,
    push: bool = True,
    max_jobs: int = 3,
) -> DeliveryReport:
    report = DeliveryReport()
    job_ids = pending_jobs(db_url)
    report.pending = len(job_ids)
    if not job_ids:
        return report
    if not resume_source().exists():
        report.skipped_reason = f"no resume source at {resume_source()}"
        return report
    bank = load_bank()
    baseline = master_text(bank)
    for job_id in job_ids[:max_jobs]:
        outcome, fit = await check_job(
            job_id, notifier=notifier, bank=bank, baseline=baseline, runner=runner, db_url=db_url
        )
        report.checked += 1
        if outcome == "failed":
            report.failed.append(str(job_id))
            continue  # retry next scan
        _mark_checked(db_url, job_id)
        if outcome == "flagged":
            report.flagged.append(str(job_id))
        elif outcome == "quiet":
            report.quiet += 1
        else:
            report.skipped += 1
        # Public-repo CI logs: ids and numbers only, never resume content.
        logger.info(
            "resume_check",
            job_id=job_id,
            outcome=outcome,
            severity=fit.severity if fit else None,
            coverage=round(fit.master_coverage, 2) if fit else None,
        )
    if report.flagged:
        report.git = commit_and_push(
            private_dir(), f"Resume checks: {len(report.flagged)} flagged role(s)", push=push
        )
    return report
