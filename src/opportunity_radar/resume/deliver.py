"""Tailored resumes for fresh high-priority alerts, delivered to Discord.

After a scan sends immediate alerts, each alerted job (not yet served)
gets a tailored resume: compiled PDF attached to a Discord message next to
the alert, and the .tex / PDF / ATS report archived in the private career
repo. Bounded per run so a burst of alerts can't stall the scanner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import structlog
from sqlalchemy import select

from opportunity_radar.db.engine import session_scope
from opportunity_radar.db.tables import JobRow
from opportunity_radar.notifications import templates
from opportunity_radar.notifications.discord import DiscordNotifier
from opportunity_radar.resume.ledger import commit_and_push
from opportunity_radar.resume.paths import private_dir, resume_source
from opportunity_radar.resume.polish import Runner
from opportunity_radar.resume.tailor import load_bank, master_text, slug, tailor
from opportunity_radar.utilities.dates import utcnow

logger = structlog.get_logger(__name__)
LOOKBACK_HOURS = 6


@dataclass
class DeliveryReport:
    pending: int = 0
    delivered: list[str] = field(default_factory=list)
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


async def deliver_pending(
    notifier: DiscordNotifier,
    *,
    db_url: str | None = None,
    runner: Runner | None = None,
    push: bool = True,
    max_jobs: int = 5,
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
        with session_scope(db_url) as session:
            job = session.get(JobRow, job_id)
            if job is None:
                continue
            title, company = job.title, job.company_name
            description, url, score = job.description_text or "", job.apply_url, job.match_score
        out_dir = (
            private_dir()
            / "tailored"
            / f"{date.today().isoformat()}-{slug(company, 24)}-{slug(title)}"
        )
        result = tailor(
            bank,
            title=title,
            company=company,
            description=description,
            out_dir=out_dir,
            runner=runner,
            baseline_text=baseline,
            meta={"job_id": job_id, "apply_url": url, "match_score": score},
        )
        gaps = result.report.true_gaps[:4]
        ats_line = f"ATS keywords {result.report.coverage:.0%}" + (
            f" · gaps you can't claim: {', '.join(gaps)}" if gaps else ""
        )
        with session_scope(db_url) as session:
            job = session.get(JobRow, job_id)
            assert job is not None
            payload = templates.build_resume_message(job, result.summary, ats_line)
        if result.pdf_path is not None:
            sent = await notifier.send_files(
                payload, [(result.pdf_path.name, result.pdf_path.read_bytes(), "application/pdf")]
            )
        else:
            payload["embeds"][0]["description"] += f"\n(PDF not compiled: {result.compile_error})"
            sent = await notifier.send(payload)
        if sent or not notifier.configured:
            with session_scope(db_url) as session:
                job = session.get(JobRow, job_id)
                if job is not None:
                    job.resume_sent_at = utcnow()
            report.delivered.append(f"{company}: {title}")
        else:
            report.failed.append(f"{company}: {title}")
        # Public-repo CI logs: never log resume content, only ids and numbers.
        logger.info(
            "resume_delivered", job_id=job_id, sent=sent, coverage=round(result.report.coverage, 2)
        )
    report.git = commit_and_push(
        private_dir(), f"Tailored resumes for {len(report.delivered)} alert(s)", push=push
    )
    return report
