"""Opportunity Radar command-line interface (spec §17)."""

from __future__ import annotations

import asyncio
import csv
import json
import shutil
import sys
from pathlib import Path

import httpx
import typer
from rich.console import Console
from rich.table import Table

from opportunity_radar import __version__
from opportunity_radar.config import (
    config_dir,
    data_dir,
    get_settings,
    load_settings,
    project_root,
)
from opportunity_radar.logging import configure_logging

app = typer.Typer(name="opportunity-radar", help="Local-first SWE internship monitor.")
jobs_app = typer.Typer(help="Job listing operations.")
companies_app = typer.Typer(help="Company registry operations.")
sources_app = typer.Typer(help="Source health operations.")
notify_app = typer.Typer(help="Notification operations.")
db_app = typer.Typer(help="Database operations.")
app.add_typer(jobs_app, name="jobs")
app.add_typer(companies_app, name="companies")
app.add_typer(sources_app, name="sources")
app.add_typer(notify_app, name="notify")
app.add_typer(db_app, name="db")

console = Console()


@app.callback()
def _main_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging"),
) -> None:
    configure_logging("DEBUG" if verbose else "INFO")


def _notifier():
    from opportunity_radar.notifications.discord import DiscordNotifier

    return DiscordNotifier(get_settings().discord_webhook_url)


def _make_ctx_client():
    """(client, ctx) pair for one-off CLI operations."""
    from opportunity_radar.adapters.base import AdapterContext
    from opportunity_radar.utilities.rate_limit import RateLimiter, build_user_agent

    settings = get_settings()
    client = httpx.AsyncClient(follow_redirects=True)
    ctx = AdapterContext(
        client=client,
        limiter=RateLimiter(settings.scheduler.max_concurrency_global),
        user_agent=build_user_agent(settings.contact),
        timeout=float(settings.scheduler.request_timeout_seconds),
        retries=settings.scheduler.retries,
        backoff_seconds=tuple(settings.scheduler.backoff_seconds),
    )
    return client, ctx


# ---------------------------------------------------------------------------
# init / doctor / status


@app.command()
def init() -> None:
    """Set up config files, data directory, and database schema."""
    root = project_root()
    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)

    copies = [
        ("settings.example.yaml", "settings.yaml"),
        ("profile.example.yaml", "profile.yaml"),
        ("companies.example.yaml", "companies.yaml"),
        ("scoring.example.yaml", "scoring.yaml"),
    ]
    for example, target in copies:
        source = cfg / example
        destination = cfg / target
        if source.exists() and not destination.exists():
            shutil.copy(source, destination)
            console.print(f"[green]created[/green] config/{target}")
        elif destination.exists():
            console.print(f"[dim]exists[/dim]  config/{target}")

    env_file = root / ".env"
    env_example = root / ".env.example"
    if env_example.exists() and not env_file.exists():
        shutil.copy(env_example, env_file)
        console.print("[green]created[/green] .env  (add your DISCORD_WEBHOOK_URL)")

    from opportunity_radar.db.migrations import upgrade_to_head

    upgrade_to_head()
    console.print("[green]database migrated[/green]")
    console.print("\nNext steps:")
    console.print("  1. Put your Discord webhook URL in .env")
    console.print("  2. uv run opportunity-radar doctor")
    console.print("  3. uv run opportunity-radar baseline")


@app.command()
def doctor() -> None:
    """Verify the installation end to end."""
    settings = load_settings(reload=True)
    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f" {mark} {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures += 1

    check(
        "Python version >= 3.12",
        sys.version_info >= (3, 12),
        f"{sys.version_info.major}.{sys.version_info.minor}",
    )
    cfg = config_dir()
    check("config directory", cfg.exists(), str(cfg))
    for name in ("profile.yaml", "companies.yaml"):
        path = cfg / name
        example = cfg / name.replace(".yaml", ".example.yaml")
        check(
            f"config/{name}",
            path.exists() or example.exists(),
            "using example defaults" if not path.exists() else "",
        )

    from opportunity_radar.db.engine import normalize_db_url

    db_url = normalize_db_url(settings.db_url)
    check("database URL", bool(db_url), db_url)
    if db_url.startswith("sqlite:///"):
        db_path = Path(db_url.removeprefix("sqlite:///"))
        if not db_path.is_absolute():
            db_path = project_root() / db_path
        parent_writable = db_path.parent.exists() or db_path.parent.parent.exists()
        check("database path writable", parent_writable, str(db_path))
        from opportunity_radar.db import migrations

        try:
            up_to_date = migrations.is_up_to_date()
            check(
                "migrations up to date",
                up_to_date,
                "" if up_to_date else "run: opportunity-radar db migrate",
            )
        except Exception as exc:
            check("migrations", False, str(exc))

    check(
        "Discord webhook configured",
        bool(settings.discord_webhook_url),
        "" if settings.discord_webhook_url else "set DISCORD_WEBHOOK_URL in .env",
    )

    try:
        import playwright  # noqa: F401

        check("Playwright installed (optional)", True)
    except ImportError:
        check(
            "Playwright installed (optional)",
            True,
            "not installed — fine unless you use adapter: playwright",
        )

    async def network_check() -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://boards-api.greenhouse.io/v1/boards/doesnotexist/jobs",
                    timeout=10.0,
                )
            return response.status_code in (200, 404)
        except httpx.HTTPError:
            return False

    check("network connectivity", asyncio.run(network_check()))

    companies = settings.companies
    check("company registry parses", True, f"{len(companies)} companies")
    enabled = [c for c in companies if c.enabled]
    check("enabled companies", len(enabled) > 0, f"{len(enabled)} enabled")

    if failures:
        console.print(f"\n[red]{failures} check(s) failed.[/red]")
        raise typer.Exit(1)
    console.print("\n[green]All checks passed.[/green]")


@app.command()
def status() -> None:
    """Overview: job counts, last scans, pending alerts."""
    from opportunity_radar.db import repositories as repo
    from opportunity_radar.db.engine import session_scope

    with session_scope() as session:
        active = repo.count_jobs(session, "active")
        closed = repo.count_jobs(session, "closed")
        states = repo.list_source_states(session)
        runs = repo.recent_scan_runs(session, limit=10)

        console.print(f"[bold]Opportunity Radar v{__version__}[/bold]")
        console.print(f"Active jobs: {active}   Closed jobs: {closed}")
        healthy = sum(1 for s in states if s.consecutive_failures == 0)
        console.print(f"Sources: {healthy}/{len(states)} healthy")

        if runs:
            table = Table(title="Recent scans")
            for column in ("When", "Company", "Adapter", "OK", "Found", "New", "Changed", "Closed"):
                table.add_column(column)
            for run in runs:
                table.add_row(
                    run.started_at.strftime("%m-%d %H:%M"),
                    run.company_id,
                    run.adapter,
                    "✓" if run.success else "✗",
                    str(run.jobs_found),
                    str(run.new_count),
                    str(run.changed_count),
                    str(run.closed_count),
                )
            console.print(table)


# ---------------------------------------------------------------------------
# scan / baseline


def _select_companies(company: str | None, adapter: str | None):
    settings = get_settings()
    companies = [c for c in settings.companies if c.enabled]
    if company:
        companies = [c for c in companies if c.id == company.lower()]
        if not companies:
            console.print(f"[red]No enabled company with id '{company}'.[/red]")
            raise typer.Exit(1)
    if adapter:
        companies = [c for c in companies if c.adapter == adapter]
        if not companies:
            console.print(f"[red]No enabled companies using adapter '{adapter}'.[/red]")
            raise typer.Exit(1)
    return settings, companies


def _print_scan_summary(summary) -> None:
    console.print(
        f"\nScanned [bold]{len(summary.outcomes)}[/bold] sources: "
        f"{summary.total_found} jobs, "
        f"[green]{summary.total_new} new[/green], "
        f"[yellow]{summary.total_changed} changed[/yellow], "
        f"[red]{summary.total_closed} closed[/red]."
    )
    for failure in summary.failures:
        console.print(f"  [red]FAILED[/red] {failure.company_id}: {failure.error}")


@app.command()
def scan(
    company: str = typer.Option(None, "--company", help="Scan a single company id"),
    adapter: str = typer.Option(None, "--adapter", help="Scan companies using this adapter"),
    no_notify: bool = typer.Option(False, "--no-notify", help="Skip Discord alerts"),
) -> None:
    """Scan sources for new/changed/closed jobs and send alerts."""
    settings, companies = _select_companies(company, adapter)
    from opportunity_radar.pipeline.scanner import scan_companies

    async def run() -> None:
        summary = await scan_companies(companies, settings)
        _print_scan_summary(summary)
        if summary.baseline:
            console.print("[yellow]First run detected — imported as baseline, no alerts.[/yellow]")
            return
        if not no_notify and summary.immediate_job_ids:
            notifier = _notifier()
            sent = await notifier.send_immediate_alerts(summary.immediate_job_ids)
            console.print(f"Sent {sent} immediate Discord alert(s).")

    asyncio.run(run())


@app.command()
def baseline(
    alert_existing: bool = typer.Option(
        False, "--alert-existing", help="Also alert on already-open matching roles"
    ),
) -> None:
    """First-run import: store everything, send one summary, no per-job alerts."""
    settings, companies = _select_companies(None, None)
    from opportunity_radar.pipeline.scanner import scan_companies

    async def run() -> None:
        summary = await scan_companies(companies, settings, baseline=not alert_existing)
        _print_scan_summary(summary)
        notifier = _notifier()
        if alert_existing:
            if summary.immediate_job_ids:
                sent = await notifier.send_immediate_alerts(summary.immediate_job_ids)
                console.print(f"Sent {sent} immediate alert(s) for existing roles.")
        elif notifier.configured:
            await notifier.send_baseline_summary()
            console.print("Baseline summary sent to Discord.")

    asyncio.run(run())


@app.command()
def daemon() -> None:
    """Run the long-lived scheduler (used by launchd)."""
    from opportunity_radar.scheduler.daemon import run_daemon

    asyncio.run(run_daemon())


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address (keep it local)"),
    port: int = typer.Option(8765, help="Port"),
) -> None:
    """Start the local dashboard at http://127.0.0.1:8765."""
    import uvicorn

    if host not in ("127.0.0.1", "localhost", "::1"):
        console.print(
            "[yellow]Warning: binding to a non-loopback address exposes the "
            "dashboard beyond this machine.[/yellow]"
        )
    uvicorn.run(
        "opportunity_radar.web.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="warning",
    )


# ---------------------------------------------------------------------------
# jobs


@jobs_app.command("list")
def jobs_list(
    status: str = typer.Option("active", help="active/closed/all"),
    season: str = typer.Option(None),
    min_score: float = typer.Option(None, "--min-score"),
    limit: int = typer.Option(25),
    search: str = typer.Option(None),
) -> None:
    """List jobs sorted by score."""
    from opportunity_radar.db import repositories as repo
    from opportunity_radar.db.engine import session_scope

    with session_scope() as session:
        rows = repo.list_jobs(
            session,
            status=None if status == "all" else status,
            season=season,
            min_score=min_score,
            search=search,
            limit=limit,
        )
        table = Table(title=f"Jobs ({len(rows)})")
        for column in ("ID", "Score", "Company", "Title", "Season", "Location", "Status"):
            table.add_column(column)
        for row in rows:
            season_label = row.season if row.season != "unspecified" else "—"
            if row.season_year:
                season_label += f" {row.season_year}"
            table.add_row(
                str(row.id),
                f"{row.match_score:.0f}",
                row.company_name,
                row.title[:60],
                season_label,
                (row.primary_location or row.remote_type)[:28],
                row.status,
            )
        console.print(table)


@jobs_app.command("show")
def jobs_show(job_id: int) -> None:
    """Full detail for one job."""
    from opportunity_radar.db import repositories as repo
    from opportunity_radar.db.engine import session_scope

    with session_scope() as session:
        job = repo.get_job(session, job_id)
        if job is None:
            console.print(f"[red]No job {job_id}[/red]")
            raise typer.Exit(1)
        console.print(f"[bold]{job.title}[/bold] @ {job.company_name}")
        console.print(f"Score: {job.match_score:.0f}  Status: {job.status}")
        console.print(
            f"Season: {job.season} {job.season_year or ''} (confidence {job.season_confidence:.0%})"
        )
        console.print(f"Location: {', '.join(job.all_locations) or job.remote_type}")
        console.print(f"Eligibility: {job.eligibility_level}")
        if job.eligibility_text:
            console.print(f"  “{job.eligibility_text}”")
        console.print(f"Apply: {job.apply_url}")
        if job.match_reasons:
            console.print("Reasons:")
            for reason in job.match_reasons:
                console.print(f"  • {reason}")
        if job.risk_flags:
            console.print("Risks:")
            for risk in job.risk_flags:
                console.print(f"  • {risk}")
        components = job.score_components or {}
        if components:
            console.print("Score components: " + json.dumps(components))


def _set_status(job_id: int, status: str, **fields) -> None:
    from opportunity_radar.db import repositories as repo
    from opportunity_radar.db.engine import session_scope

    with session_scope() as session:
        if repo.get_job(session, job_id) is None:
            console.print(f"[red]No job {job_id}[/red]")
            raise typer.Exit(1)
        repo.set_application_status(session, job_id, status, **fields)
    console.print(f"Job {job_id} marked [bold]{status}[/bold].")


@jobs_app.command("save")
def jobs_save(job_id: int) -> None:
    """Save a job for follow-up."""
    _set_status(job_id, "saved")


@jobs_app.command("dismiss")
def jobs_dismiss(job_id: int) -> None:
    """Dismiss a job."""
    _set_status(job_id, "dismissed")


@jobs_app.command("applied")
def jobs_applied(
    job_id: int,
    resume: str = typer.Option(None, "--resume", help="Resume variant used"),
    notes: str = typer.Option(None, "--notes"),
) -> None:
    """Mark a job as applied."""
    _set_status(job_id, "applied", resume_variant=resume, notes=notes)


@jobs_app.command("export")
def jobs_export(
    fmt: str = typer.Option("csv", "--format", help="csv or json"),
    output: Path = typer.Option(None, "--output", "-o"),
    status: str = typer.Option("all"),
) -> None:
    """Export jobs to CSV or JSON."""
    from opportunity_radar.db import repositories as repo
    from opportunity_radar.db.engine import session_scope

    with session_scope() as session:
        rows = repo.list_jobs(session, status=None if status == "all" else status, limit=100_000)
        records = []
        for row in rows:
            app_row = row.application
            records.append(
                {
                    "id": row.id,
                    "company": row.company_name,
                    "title": row.title,
                    "score": row.match_score,
                    "season": row.season,
                    "season_year": row.season_year,
                    "locations": "; ".join(row.all_locations or []),
                    "remote_type": row.remote_type,
                    "role_family": row.role_family,
                    "eligibility": row.eligibility_level,
                    "status": row.status,
                    "application_status": app_row.status if app_row else "none",
                    "apply_url": row.apply_url,
                    "posted_at": row.posted_at.isoformat() if row.posted_at else "",
                    "first_seen_at": row.first_seen_at.isoformat(),
                    "risk_flags": "; ".join(row.risk_flags or []),
                }
            )
    destination = output or Path(f"jobs_export.{fmt}")
    if fmt == "json":
        destination.write_text(json.dumps(records, indent=2), encoding="utf-8")
    else:
        with destination.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(records[0].keys()) if records else ["id"]
            )
            writer.writeheader()
            writer.writerows(records)
    console.print(f"Exported {len(records)} jobs to {destination}")


# ---------------------------------------------------------------------------
# companies


@companies_app.command("list")
def companies_list() -> None:
    """List the company registry."""
    settings = get_settings()
    table = Table(title=f"Companies ({len(settings.companies)})")
    for column in ("ID", "Name", "Tier", "Adapter", "Enabled"):
        table.add_column(column)
    for company in settings.companies:
        table.add_row(
            company.id,
            company.name,
            company.tier,
            company.adapter,
            "yes" if company.enabled else "no",
        )
    console.print(table)


@companies_app.command("add")
def companies_add(
    company_id: str = typer.Option(..., "--id", prompt=True),
    name: str = typer.Option(..., prompt=True),
    tier: str = typer.Option("broad", prompt=True),
    adapter: str = typer.Option("auto", prompt=True),
    career_url: str = typer.Option("", prompt="Career URL (optional)"),
) -> None:
    """Append a company to config/companies.yaml."""
    import yaml

    path = config_dir() / "companies.yaml"
    if not path.exists():
        example = config_dir() / "companies.example.yaml"
        if example.exists():
            shutil.copy(example, path)
        else:
            path.write_text("companies: []\n", encoding="utf-8")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {"companies": []}
    entry: dict = {
        "id": company_id.lower().strip(),
        "name": name,
        "tier": tier,
        "enabled": True,
        "adapter": adapter,
    }
    if career_url:
        entry["career_urls"] = [career_url]
    data.setdefault("companies", []).append(entry)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    console.print(f"[green]Added {company_id} to config/companies.yaml[/green]")


@companies_app.command("discover")
def companies_discover(company_id: str) -> None:
    """Probe a company's site for career pages and ATS fingerprints."""
    settings = get_settings()
    company = next((c for c in settings.companies if c.id == company_id.lower()), None)
    domain = company.domain if company else company_id
    if not domain or "." not in domain:
        console.print("[red]Provide a registered company id or a domain name.[/red]")
        raise typer.Exit(1)

    from opportunity_radar.discovery.career_links import discover

    async def run() -> None:
        client, ctx = _make_ctx_client()
        try:
            result = await discover(domain, ctx)
        finally:
            await client.aclose()
        if result.fingerprint:
            console.print(
                f"[green]ATS detected:[/green] {result.fingerprint.adapter} "
                f"({result.fingerprint.config or 'no token extracted'})"
            )
            console.print(f"  evidence: {result.fingerprint.evidence}")
        else:
            console.print("[yellow]No known ATS fingerprint found.[/yellow]")
        if result.career_urls:
            console.print("Candidate career URLs:")
            for url in result.career_urls:
                console.print(f"  {url}")
        for note in result.notes:
            console.print(f"  [dim]{note}[/dim]")

    asyncio.run(run())


@companies_app.command("validate")
def companies_validate(
    company: str = typer.Option(None, "--company", help="Validate one company"),
) -> None:
    """Check that each enabled company's source responds with jobs."""
    settings = get_settings()
    companies = [c for c in settings.companies if c.enabled]
    if company:
        companies = [c for c in companies if c.id == company.lower()]

    from opportunity_radar.discovery.source_validator import validate_company

    async def run() -> None:
        client, ctx = _make_ctx_client()
        try:
            for entry in companies:
                result = await validate_company(entry, ctx)
                mark = "[green]✓[/green]" if result.ok else "[red]✗[/red]"
                console.print(f" {mark} {entry.id} [{result.adapter}] {result.detail}")
        finally:
            await client.aclose()

    asyncio.run(run())


def _toggle_company(company_id: str, enabled: bool) -> None:
    import yaml

    path = config_dir() / "companies.yaml"
    if not path.exists():
        console.print("[red]config/companies.yaml not found — run init first.[/red]")
        raise typer.Exit(1)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    found = False
    for entry in data.get("companies", []):
        if entry.get("id") == company_id.lower():
            entry["enabled"] = enabled
            found = True
    if not found:
        console.print(f"[red]Company '{company_id}' not in registry.[/red]")
        raise typer.Exit(1)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    console.print(f"{company_id} {'enabled' if enabled else 'disabled'}.")


@companies_app.command("disable")
def companies_disable(company_id: str) -> None:
    """Disable a company in the registry."""
    _toggle_company(company_id, False)


@companies_app.command("enable")
def companies_enable(company_id: str) -> None:
    """Enable a company in the registry."""
    _toggle_company(company_id, True)


# ---------------------------------------------------------------------------
# sources / notify / db


@sources_app.command("health")
def sources_health() -> None:
    """Show adapter health per company."""
    from opportunity_radar.db import repositories as repo
    from opportunity_radar.db.engine import session_scope

    with session_scope() as session:
        states = repo.list_source_states(session)
        table = Table(title="Source health")
        for column in ("Company", "Last success", "Failures", "Jobs", "Last error"):
            table.add_column(column)
        for state in states:
            table.add_row(
                state.company_id,
                state.last_success_at.strftime("%m-%d %H:%M") if state.last_success_at else "never",
                str(state.consecutive_failures),
                str(state.last_job_count if state.last_job_count is not None else "—"),
                (state.last_error or "")[:60],
            )
        console.print(table)


@notify_app.command("test")
def notify_test() -> None:
    """Send a test message to the configured Discord webhook."""
    notifier = _notifier()
    if not notifier.configured:
        console.print("[red]DISCORD_WEBHOOK_URL is not set in .env[/red]")
        raise typer.Exit(1)
    ok = asyncio.run(notifier.send_test())
    if ok:
        console.print("[green]Test message sent.[/green]")
    else:
        console.print("[red]Failed to send — check the webhook URL.[/red]")
        raise typer.Exit(1)


@notify_app.command("digest")
def notify_digest() -> None:
    """Send a digest now (normally the daemon schedules this)."""
    from opportunity_radar.notifications.digest import send_digest

    settings = get_settings()
    ok = asyncio.run(send_digest(settings, _notifier()))
    console.print("Digest sent." if ok else "Nothing to send (or webhook failed).")


@db_app.command("migrate")
def db_migrate() -> None:
    """Apply pending database migrations."""
    from opportunity_radar.db.migrations import upgrade_to_head

    upgrade_to_head()
    console.print("[green]Database is up to date.[/green]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
