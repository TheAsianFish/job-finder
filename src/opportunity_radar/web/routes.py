"""Dashboard routes: home, jobs, job detail, companies, health, settings."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from opportunity_radar.config import get_settings
from opportunity_radar.db import repositories as repo
from opportunity_radar.db.engine import session_scope
from opportunity_radar.db.tables import ApplicationRow, JobChangeRow, JobRow
from opportunity_radar.utilities.dates import ensure_utc, humanize_age, utcnow
from opportunity_radar.web.schemas import check_csrf, csrf_token

router = APIRouter()


def _templates():
    from opportunity_radar.web.app import templates

    return templates


def _render(request: Request, template: str, **context):
    context.setdefault("csrf_token", csrf_token())
    context.setdefault("humanize_age", lambda dt: humanize_age(ensure_utc(dt)))
    return _templates().TemplateResponse(request, template, context)


@router.get("/")
def home(request: Request):
    settings = get_settings()
    alerts = settings.scoring.alerts
    now = utcnow()
    with session_scope() as session:
        day_ago = now - timedelta(hours=24)
        high_today = [
            j
            for j in repo.list_jobs(
                session, status="active", min_score=alerts.immediate_min_score, limit=20
            )
            if (ensure_utc(j.first_seen_at) or day_ago) >= day_ago
        ]
        off_season = [
            j
            for j in session.scalars(
                select(JobRow)
                .where(
                    JobRow.status == "active",
                    JobRow.season.in_(["winter", "spring", "fall", "off_cycle"]),
                    JobRow.match_score >= alerts.dashboard_min_score,
                )
                .order_by(JobRow.match_score.desc())
                .limit(15)
            )
        ]
        summer = [
            j
            for j in session.scalars(
                select(JobRow)
                .where(
                    JobRow.status == "active",
                    JobRow.season == "summer",
                    JobRow.season_year == 2027,
                    JobRow.match_score >= alerts.dashboard_min_score,
                )
                .order_by(JobRow.match_score.desc())
                .limit(15)
            )
        ]
        deadlines = list(
            session.scalars(
                select(ApplicationRow)
                .where(
                    ApplicationRow.deadline.isnot(None),
                    ApplicationRow.deadline <= (now + timedelta(days=14)).date(),
                )
                .order_by(ApplicationRow.deadline)
                .limit(10)
            )
        )
        deadline_jobs = [(app, repo.get_job(session, app.job_id)) for app in deadlines]
        recent_changes = list(
            session.scalars(
                select(JobChangeRow)
                .where(JobChangeRow.meaningful.is_(True))
                .order_by(JobChangeRow.changed_at.desc())
                .limit(10)
            )
        )
        change_jobs = {c.job_id: repo.get_job(session, c.job_id) for c in recent_changes}
        states = repo.list_source_states(session)
        failing = [s for s in states if s.consecutive_failures > 0]
        return _render(
            request,
            "home.html",
            high_today=high_today,
            off_season=off_season,
            summer=summer,
            deadline_jobs=deadline_jobs,
            recent_changes=recent_changes,
            change_jobs=change_jobs,
            source_total=len(states),
            source_failing=failing,
        )


@router.get("/jobs")
def jobs_page(
    request: Request,
    status: str = "active",
    season: str = "",
    season_year: int | None = None,
    min_score: float | None = None,
    company: str = "",
    role_family: str = "",
    remote_type: str = "",
    application_status: str = "",
    eligibility: str = "",
    q: str = "",
    order: str = "score",
    page: int = 1,
):
    page_size = 50
    with session_scope() as session:
        rows = repo.list_jobs(
            session,
            status=status or None if status != "all" else None,
            season=season or None,
            season_year=season_year,
            min_score=min_score,
            company_id=company or None,
            role_family=role_family or None,
            remote_type=remote_type or None,
            application_status=application_status or None,
            eligibility_level=eligibility or None,
            search=q or None,
            order_by=order,
            limit=page_size,
            offset=(max(page, 1) - 1) * page_size,
        )
        companies = repo.list_companies(session)
        app_statuses = {
            a.job_id: a.status
            for a in session.scalars(
                select(ApplicationRow).where(ApplicationRow.job_id.in_([r.id for r in rows] or [0]))
            )
        }
    return _render(
        request,
        "jobs.html",
        jobs=rows,
        companies=companies,
        app_statuses=app_statuses,
        filters={
            "status": status,
            "season": season,
            "season_year": season_year or "",
            "min_score": min_score or "",
            "company": company,
            "role_family": role_family,
            "remote_type": remote_type,
            "application_status": application_status,
            "eligibility": eligibility,
            "q": q,
            "order": order,
        },
        page=page,
        page_size=page_size,
    )


@router.get("/jobs/{job_id}")
def job_detail(request: Request, job_id: int):
    with session_scope() as session:
        job = repo.get_job(session, job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        changes = list(
            session.scalars(
                select(JobChangeRow)
                .where(JobChangeRow.job_id == job_id)
                .order_by(JobChangeRow.changed_at.desc())
                .limit(50)
            )
        )
        application = session.get(ApplicationRow, job_id)
        aliases = list(job.aliases)
        return _render(
            request,
            "job_detail.html",
            job=job,
            changes=changes,
            application=application,
            aliases=aliases,
            resume_variants=[
                "general_swe",
                "backend_infrastructure",
                "ai_ml_systems",
                "startup_product",
            ],
        )


@router.post("/jobs/{job_id}/status")
def job_set_status(
    job_id: int,
    status: str = Form(...),
    csrf: str = Form(None),
    resume_variant: str = Form(None),
    notes: str = Form(None),
    recruiter_name: str = Form(None),
    referral_status: str = Form(None),
    deadline: str = Form(None),
):
    if not check_csrf(csrf):
        raise HTTPException(403, "bad csrf token")
    allowed = {"saved", "dismissed", "applied", "oa", "interview", "offer", "rejected", "none"}
    if status not in allowed:
        raise HTTPException(400, f"status must be one of {sorted(allowed)}")
    from opportunity_radar.utilities.dates import parse_date

    with session_scope() as session:
        if repo.get_job(session, job_id) is None:
            raise HTTPException(404, "job not found")
        repo.set_application_status(
            session,
            job_id,
            status,
            resume_variant=resume_variant or None,
            notes=notes or None,
            recruiter_name=recruiter_name or None,
            referral_status=referral_status or None,
            deadline=parse_date(deadline) if deadline else None,
        )
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/note")
def job_add_note(job_id: int, notes: str = Form(...), csrf: str = Form(None)):
    if not check_csrf(csrf):
        raise HTTPException(403, "bad csrf token")
    with session_scope() as session:
        if repo.get_job(session, job_id) is None:
            raise HTTPException(404, "job not found")
        application = repo.get_or_create_application(session, job_id)
        application.notes = notes
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


@router.get("/companies")
def companies_page(request: Request):
    with session_scope() as session:
        companies = repo.list_companies(session)
        states = {s.company_id: s for s in repo.list_source_states(session)}
        active_counts = {c.id: len(repo.active_jobs_for_company(session, c.id)) for c in companies}
    return _render(
        request,
        "companies.html",
        companies=companies,
        states=states,
        active_counts=active_counts,
    )


@router.post("/companies/{company_id}/toggle")
def company_toggle(company_id: str, csrf: str = Form(None)):
    if not check_csrf(csrf):
        raise HTTPException(403, "bad csrf token")
    with session_scope() as session:
        company = repo.get_company(session, company_id)
        if company is None:
            raise HTTPException(404, "company not found")
        repo.set_company_enabled(session, company_id, not company.enabled)
    return RedirectResponse(url="/companies", status_code=303)


@router.get("/health")
def health_page(request: Request):
    with session_scope() as session:
        states = repo.list_source_states(session)
        runs = repo.recent_scan_runs(session, limit=100)
    return _render(request, "health.html", states=states, runs=runs)


@router.get("/settings")
def settings_page(request: Request):
    settings = get_settings()
    return _render(
        request,
        "settings.html",
        profile=settings.profile,
        scheduler=settings.scheduler,
        alerts=settings.scoring.alerts,
        windows=settings.scoring.target_windows,
        webhook_configured=bool(settings.discord_webhook_url),
    )


@router.get("/api/health")
def api_health():
    return {"status": "ok"}
