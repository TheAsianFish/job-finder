"""Career commands: applications log, adaptive resumes, report posting.

Registered onto the main Typer app by cli.py (kept separate so the core
scanner CLI stays readable).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()

resume_app = typer.Typer(help="Adaptive resumes: bullet bank, tailoring, variants, delivery.")
applications_app = typer.Typer(help="Applications log (private career repo).")


# ---------------------------------------------------------------------------
# Applications log


def _resolve_target(target: str) -> tuple[int | None, str | None, str, str]:
    """job id or URL -> (job id, apply url, company, title) using the local DB."""
    from opportunity_radar.db import repositories as repo
    from opportunity_radar.db.engine import session_scope
    from opportunity_radar.resume.ledger import find_job

    with session_scope() as session:
        job = repo.get_job(session, int(target)) if target.isdigit() else find_job(session, target)
        if job is None:
            if target.isdigit():
                console.print(f"[red]No job {target} in the local database.[/red]")
                raise typer.Exit(1)
            return None, target, "", ""
        return job.id, job.apply_url, job.company_name, job.title


def record_application(
    target: str,
    status: str,
    *,
    resume: str | None = None,
    referral: str | None = None,
    notes: str | None = None,
    company: str | None = None,
    title: str | None = None,
    stage: str | None = None,
    push: bool = True,
) -> None:
    from opportunity_radar.db import repositories as repo
    from opportunity_radar.db.engine import session_scope
    from opportunity_radar.resume.ledger import commit_and_push, upsert
    from opportunity_radar.resume.paths import ledger_path, private_dir

    job_id, url, found_company, found_title = _resolve_target(target)
    if job_id is not None:
        with session_scope() as session:
            fields = {"resume_variant": resume, "notes": notes, "referral_status": referral}
            if stage:
                fields["interview_stage"] = stage
            repo.set_application_status(session, job_id, status, **fields)
    if private_dir().exists() and url:
        entry = upsert(
            ledger_path(),
            url,
            status=status,
            company=company or found_company,
            title=title or found_title,
            resume=resume,
            referral=referral,
            notes=notes,
        )
        git = commit_and_push(
            private_dir(), f"{status}: {entry.company or url} {entry.title}".strip(), push=push
        )
        console.print(f"Logged [bold]{status}[/bold] for {entry.company} {entry.title} ({git}).")
    else:
        console.print(f"Marked [bold]{status}[/bold] locally (no private career repo found).")


def register(app: typer.Typer, jobs_app: typer.Typer, notify_app: typer.Typer) -> None:
    app.add_typer(resume_app, name="resume")
    app.add_typer(applications_app, name="applications")

    @app.command("apply")
    def apply(
        target: str = typer.Argument(..., help="Job id (local DB) or the apply URL"),
        resume: str = typer.Option(None, "--resume", help="Resume version used, e.g. backend"),
        referral: str = typer.Option(None, "--referral", help="Referrer name, or 'yes'"),
        notes: str = typer.Option(None, "--notes"),
        company: str = typer.Option(None, "--company", help="If the job isn't in the DB"),
        title: str = typer.Option(None, "--title", help="If the job isn't in the DB"),
        push: bool = typer.Option(True, "--push/--no-push", help="Push the private repo"),
    ) -> None:
        """Log an application (DB + private applications.yaml, pushed)."""
        record_application(
            target,
            "applied",
            resume=resume,
            referral=referral,
            notes=notes,
            company=company,
            title=title,
            push=push,
        )

    @jobs_app.command("applied")
    def jobs_applied(
        target: str = typer.Argument(..., help="Job id or apply URL"),
        resume: str = typer.Option(None, "--resume", help="Resume version used"),
        notes: str = typer.Option(None, "--notes"),
        push: bool = typer.Option(True, "--push/--no-push"),
    ) -> None:
        """Mark a job as applied (same as `apply`)."""
        record_application(target, "applied", resume=resume, notes=notes, push=push)

    @jobs_app.command("status")
    def jobs_status(
        target: str = typer.Argument(..., help="Job id or apply URL"),
        status: str = typer.Argument(..., help="oa | interview | offer | rejected | withdrawn"),
        stage: str = typer.Option(None, "--stage", help="Interview stage, e.g. 'final round'"),
        notes: str = typer.Option(None, "--notes"),
        push: bool = typer.Option(True, "--push/--no-push"),
    ) -> None:
        """Record an application outcome (feeds `insights outcomes`)."""
        if status not in ("oa", "interview", "offer", "rejected", "withdrawn"):
            console.print("[red]status must be oa, interview, offer, rejected, or withdrawn.[/red]")
            raise typer.Exit(1)
        record_application(target, status, stage=stage, notes=notes, push=push)

    @notify_app.command("markdown")
    def notify_markdown(
        path: Path = typer.Argument(..., exists=True, readable=True),
        title: str = typer.Option("Opportunity Radar report", "--title"),
        channel: str = typer.Option(
            "agent-log", "--channel", help="alerts | resume | projects | study | agent-log"
        ),
    ) -> None:
        """Post a markdown report (e.g. the weekly review) to a Discord hub channel."""
        from opportunity_radar.notifications.discord import notifier_for

        notifier = notifier_for(channel)
        ok = asyncio.run(notifier.send_markdown(title, path.read_text(encoding="utf-8")))
        console.print(
            "Posted." if ok else "[yellow]Not posted (webhook missing or failed).[/yellow]"
        )


@applications_app.command("import-simplify")
def applications_import_simplify(
    csv_path: Path = typer.Argument(..., exists=True, help="Simplify Job Tracker -> Export CSV"),
    push: bool = typer.Option(True, "--push/--no-push"),
) -> None:
    """Merge a Simplify tracker export into applications.yaml (never downgrades)."""
    from opportunity_radar.resume.ledger import commit_and_push, merge
    from opportunity_radar.resume.paths import ledger_path, private_dir
    from opportunity_radar.resume.simplify_import import parse_simplify_csv

    apps, skipped = parse_simplify_csv(csv_path)
    added, updated = merge(ledger_path(), apps)
    git = commit_and_push(private_dir(), f"Import Simplify tracker ({added} new)", push=push)
    console.print(
        f"Simplify import: {added} new, {updated} updated, {skipped} skipped "
        f"(saved/wishlist or incomplete rows); {git}."
    )


def import_drop_folder(push: bool) -> str | None:
    """Import every CSV in the private repo's imports/ folder (idempotent)."""
    from opportunity_radar.resume.ledger import commit_and_push, merge
    from opportunity_radar.resume.paths import ledger_path, private_dir
    from opportunity_radar.resume.simplify_import import parse_simplify_csv

    folder = private_dir() / "imports"
    files = sorted(folder.glob("*.csv")) if folder.exists() else []
    added = updated = 0
    for path in files:
        try:
            apps, _ = parse_simplify_csv(path)
        except (ValueError, OSError) as exc:
            console.print(f"[yellow]skipped {path.name}: {exc}[/yellow]")
            continue
        a, u = merge(ledger_path(), apps)
        added, updated = added + a, updated + u
    if not files:
        return None
    git = commit_and_push(private_dir(), f"Import tracker exports ({added} new)", push=push)
    return f"{len(files)} export(s): {added} new, {updated} updated; {git}"


@applications_app.command("sync")
def applications_sync(
    push: bool = typer.Option(False, "--push/--no-push", help="Push imported changes"),
) -> None:
    """Import drop-folder exports, then mirror applications.yaml into the job database."""
    from opportunity_radar.db.engine import session_scope
    from opportunity_radar.resume.ledger import load, sync_to_db
    from opportunity_radar.resume.paths import ledger_path

    imported = import_drop_folder(push)
    if imported:
        console.print(f"Imported {imported}")
    apps = load(ledger_path())
    if not apps:
        console.print(f"No applications in {ledger_path()}.")
        return
    with session_scope() as session:
        result = sync_to_db(session, apps)
    console.print(f"Synced {result.matched} application(s); {len(result.unmatched)} not in the DB.")


@applications_app.command("list")
def applications_list() -> None:
    """Show the applications log."""
    from opportunity_radar.resume.ledger import load
    from opportunity_radar.resume.paths import ledger_path

    table = Table(title="Applications")
    for column in ("Applied", "Status", "Company", "Title", "Resume"):
        table.add_column(column)
    for app in sorted(load(ledger_path()), key=lambda a: a.applied, reverse=True):
        table.add_row(app.applied, app.status, app.company, app.title, app.resume or "")
    console.print(table)


# ---------------------------------------------------------------------------
# Resumes


def _runner(polish: bool):
    if not polish:
        return None
    from opportunity_radar.resume.polish import claude_runner

    runner = claude_runner()
    if runner is None:
        console.print("[yellow]Claude Code CLI not found; tailoring without polish.[/yellow]")
    return runner


@resume_app.command("bank")
def resume_bank() -> None:
    """Show what the bullet bank parsed from resume.tex (live vs reserve)."""
    from opportunity_radar.resume.tailor import load_bank

    bank = load_bank()
    table = Table(title=f"Bullet bank: {bank.candidate_name}")
    for column in ("", "Kind", "Entry", "Dates", "Bullets (+verified)", "Skills evidenced"):
        table.add_column(column)
    for entry in bank.entries:
        table.add_row(
            "live" if entry.active else "reserve",
            entry.kind,
            entry.name[:48],
            entry.dates,
            f"{len(entry.live_bullets)}"
            + (
                f" (+{len(entry.bullets) - len(entry.live_bullets)})"
                if entry.live_bullets != entry.bullets
                else ""
            ),
            ", ".join(sorted(entry.skills))[:60],
        )
    console.print(table)
    for label, items in bank.skills.items():
        console.print(f"[bold]{label}[/bold]: {', '.join(items)}")


@resume_app.command("tailor")
def resume_tailor(
    target: str = typer.Argument(None, help="Job id (local DB) or apply URL"),
    title: str = typer.Option(None, "--title"),
    company: str = typer.Option(None, "--company"),
    description_file: Path = typer.Option(None, "--description-file", exists=True),
    polish: bool = typer.Option(True, "--polish/--no-polish", help="Reword with Claude (guarded)"),
    out: Path = typer.Option(None, "--out", help="Output directory"),
    propose: bool = typer.Option(
        True, "--propose/--no-propose", help="Open a review PR for bullets needing your OK"
    ),
) -> None:
    """Tailor your resume to one posting: PDF + ATS report in the private repo."""
    from datetime import date

    from opportunity_radar.db.engine import session_scope
    from opportunity_radar.db.tables import JobRow
    from opportunity_radar.resume.ledger import find_job
    from opportunity_radar.resume.paths import private_dir
    from opportunity_radar.resume.tailor import load_bank, master_text, slug, tailor

    description = description_file.read_text(encoding="utf-8") if description_file else ""
    meta: dict = {}
    if target:
        with session_scope() as session:
            job = (
                session.get(JobRow, int(target)) if target.isdigit() else find_job(session, target)
            )
            if job is None:
                console.print(
                    "[red]Job not found; pass --title/--company/--description-file.[/red]"
                )
                raise typer.Exit(1)
            title = title or job.title
            company = company or job.company_name
            description = description or job.description_text or ""
            meta = {"job_id": job.id, "apply_url": job.apply_url}
    if not (title and company):
        console.print("[red]Need a job id/URL or --title and --company.[/red]")
        raise typer.Exit(1)
    bank = load_bank()
    out_dir = (
        out
        or private_dir()
        / "tailored"
        / f"{date.today().isoformat()}-{slug(company, 24)}-{slug(title)}"
    )
    result = tailor(
        bank,
        title=title,
        company=company,
        description=description,
        out_dir=out_dir,
        runner=_runner(polish),
        baseline_text=master_text(bank),
        meta=meta,
    )
    console.print(f"[green]{result.summary}[/green]")
    if result.polish:
        if result.polish.skipped_reason:
            console.print(f"  polish: {result.polish.skipped_reason}")
        for bullet_id, reason in result.polish.rejected.items():
            console.print(f"  [yellow]kept original[/yellow] {bullet_id}: {reason}")
    console.print(f"  PDF: {result.pdf_path or 'not compiled: ' + str(result.compile_error)}")
    console.print(f"  ATS: {out_dir / 'ats.md'}")
    if result.report.true_gaps:
        console.print(f"  Real gaps (don't claim): {', '.join(result.report.true_gaps)}")
    if result.polish and result.polish.proposals:
        for proposal in result.polish.proposals:
            console.print(f"  [cyan]proposal[/cyan] {proposal.entry_name}: {proposal.text}")
        if propose:
            from opportunity_radar.resume.proposals import submit

            submitted = submit(
                result.polish.proposals,
                repo=private_dir(),
                bank=bank,
                title=title,
                company=company,
                url=meta.get("apply_url"),
                runner=_runner(True),
            )
            where = submitted.pr_url or submitted.saved or "already proposed before"
            console.print(f"  Proposals for your review: {where}")


@resume_app.command("variants")
def resume_variants(
    polish: bool = typer.Option(False, "--polish/--no-polish"),
    push: bool = typer.Option(False, "--push/--no-push", help="Commit + push the private repo"),
) -> None:
    """Build one resume per role family (backend, AI/ML, full stack, infra, general)."""
    from opportunity_radar.resume.ledger import commit_and_push
    from opportunity_radar.resume.paths import private_dir
    from opportunity_radar.resume.tailor import load_bank, master_text, tailor, variant_postings

    bank = load_bank()
    baseline = master_text(bank)
    demand = _family_demand()
    runner = _runner(polish)
    for key, (title, description) in variant_postings(demand).items():
        result = tailor(
            bank,
            title=title,
            company=key,
            description=description,
            out_dir=private_dir() / "variants" / key,
            runner=runner,
            baseline_text=baseline,
            meta={"variant": key},
        )
        console.print(f"  {key:15} {result.summary}")
    if push:
        console.print(commit_and_push(private_dir(), "Refresh role-family resume variants"))


def _family_demand() -> dict[str, list[str]]:
    """Top demanded skills per role family from live postings (empty if no DB)."""
    try:
        from opportunity_radar.config import get_settings
        from opportunity_radar.db.engine import session_scope
        from opportunity_radar.insights.skills import build_report, load_vocabulary, select_postings

        with session_scope() as session:
            postings = select_postings(session)
            report = build_report(postings, load_vocabulary(), get_settings().profile)
    except Exception:
        return {}
    demand: dict[str, list[str]] = {}
    for family in report.families:
        ranked = sorted(
            (s for s in report.stats if family in s.by_family and s.category != "soft"),
            key=lambda s: s.by_family[family],
            reverse=True,
        )
        demand[family] = [s.name for s in ranked[:10]]
    return demand


@resume_app.command("deliver")
def resume_deliver(
    count: bool = typer.Option(False, "--count", help="Only print how many are pending"),
    polish: bool = typer.Option(True, "--polish/--no-polish", help="Claude review + rewrite"),
    push: bool = typer.Option(True, "--push/--no-push"),
    max_jobs: int = typer.Option(3, "--max"),
) -> None:
    """Check fresh high-priority alerts; message only on a real resume disconnect."""
    from opportunity_radar.notifications.discord import notifier_for
    from opportunity_radar.resume.deliver import deliver_pending, pending_jobs

    if count:
        print(len(pending_jobs()))
        return
    notifier = notifier_for("resume")
    report = asyncio.run(
        deliver_pending(notifier, runner=_runner(polish), push=push, max_jobs=max_jobs)
    )
    if report.skipped_reason:
        console.print(f"[yellow]{report.skipped_reason}[/yellow]")
    # Counts only: this runs in public CI logs.
    console.print(
        f"Pending {report.pending}; checked {report.checked}: flagged {len(report.flagged)}, "
        f"fit {report.quiet}, not applicable {report.skipped}, failed {len(report.failed)}; "
        f"private repo: {report.git or 'unchanged'}"
    )


@resume_app.command("review-url")
def resume_review_url(
    url: str = typer.Argument(..., help="Any posting link (Greenhouse/Lever/Ashby/Workday)"),
    title: str = typer.Option(None, "--title"),
    company: str = typer.Option(None, "--company"),
) -> None:
    """Brutally honest review + tailored resume for any posting, sent to Discord."""
    from opportunity_radar.notifications.discord import notifier_for
    from opportunity_radar.resume.deliver import check_url

    notifier = notifier_for("resume")
    outcome, fit = asyncio.run(
        check_url(url, notifier=notifier, runner=_runner(True), title=title, company=company)
    )
    if outcome == "skipped":
        console.print(
            "[yellow]Couldn't get the full description from that link "
            "(company career sites aren't supported); pass a Greenhouse/Lever/Ashby/Workday link.[/yellow]"
        )
        raise typer.Exit(1)
    # Counts only: may run in public CI logs.
    console.print(f"Review {outcome}; severity {fit.severity if fit else 'n/a'}.")


@resume_app.command("assess")
def resume_assess(
    target: str = typer.Argument(..., help="Job id (local DB) or apply URL"),
    review_it: bool = typer.Option(False, "--review", help="Add Claude's written review"),
    send: bool = typer.Option(
        False, "--send", help="Full check: review + tailored PDF to Discord + private repo"
    ),
) -> None:
    """Does your standing resume compete for this role? (deterministic, instant)"""
    from opportunity_radar.db.engine import session_scope
    from opportunity_radar.db.tables import JobRow
    from opportunity_radar.notifications.discord import notifier_for
    from opportunity_radar.resume.assess import MIN_DESCRIPTION, assess
    from opportunity_radar.resume.deliver import check_job
    from opportunity_radar.resume.describe import fetch_description
    from opportunity_radar.resume.ledger import find_job
    from opportunity_radar.resume.review import render_markdown, review
    from opportunity_radar.resume.selector import Posting
    from opportunity_radar.resume.tailor import load_bank, master_text

    with session_scope() as session:
        job = session.get(JobRow, int(target)) if target.isdigit() else find_job(session, target)
        if job is None:
            console.print("[red]Job not found in the local database.[/red]")
            raise typer.Exit(1)
        job_id, title, company, url = job.id, job.title, job.company_name, job.apply_url
        description = job.description_text or ""
    bank = load_bank()
    baseline = master_text(bank)
    if send:
        notifier = notifier_for("resume")
        outcome, _ = asyncio.run(
            check_job(
                job_id,
                notifier=notifier,
                bank=bank,
                baseline=baseline,
                runner=_runner(True),
                force=True,
            )
        )
        console.print(f"Check {outcome}; outputs in the private repo's tailored/ folder.")
        return
    if len(description) < MIN_DESCRIPTION:
        description = fetch_description(url) or description
    fit = assess(bank, Posting.from_text(title, description), baseline)
    rev = (
        review(
            bank,
            baseline,
            title=title,
            company=company,
            description=description,
            fit=fit,
            runner=_runner(review_it),
        )
        if review_it
        else None
    )
    if rev is None:
        from opportunity_radar.resume.review import Review

        rev = Review(error="not requested (use --review)")
    console.print(render_markdown(rev, fit, title=title, company=company, url=url))
    if fit.weak_bullets:
        console.print("[bold]Bullets with no link to this role:[/bold]")
        for text in fit.weak_bullets:
            console.print(f"  - {text[:120]}")


@resume_app.command("ats")
def resume_ats(
    pdf: Path = typer.Argument(..., exists=True, help="A resume PDF"),
    target: str = typer.Option(None, "--job", help="Job id or URL to check against"),
) -> None:
    """ATS check of any resume PDF, optionally against a posting."""
    from opportunity_radar.db.engine import session_scope
    from opportunity_radar.db.tables import JobRow
    from opportunity_radar.resume.ats import analyse, render_markdown
    from opportunity_radar.resume.compiler import inspect_pdf
    from opportunity_radar.resume.ledger import find_job
    from opportunity_radar.resume.selector import Posting
    from opportunity_radar.resume.tailor import load_bank

    compiled = inspect_pdf(pdf)
    title, company, description = "General software internship", "-", ""
    if target:
        with session_scope() as session:
            job = (
                session.get(JobRow, int(target)) if target.isdigit() else find_job(session, target)
            )
            if job is not None:
                title, company, description = job.title, job.company_name, job.description_text
    if not description:
        from opportunity_radar.resume.tailor import FAMILY_POSTINGS

        title, description = FAMILY_POSTINGS["general"]
    report = analyse(
        compiled.text, Posting.from_text(title, description), load_bank(), pages=compiled.pages
    )
    console.print(render_markdown(report, title, company))
