"""Portfolio project commands (AD-32): the scout proposes, Patrick approves,
the builder workflow ships one milestone PR at a time.

Registered onto the main Typer app by cli.py.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

console = Console()
projects_app = typer.Typer(help="Agent-built portfolio projects (projects.yaml, private repo).")


def _token() -> str | None:
    return os.environ.get("AGENT_GH_TOKEN") or os.environ.get("GH_TOKEN")


def _save_and_push(projects, message: str, push: bool) -> str:
    from opportunity_radar.projects.portfolio import save_projects
    from opportunity_radar.resume.ledger import commit_and_push
    from opportunity_radar.resume.paths import private_dir

    save_projects(projects)
    return commit_and_push(private_dir(), message, push=push)


def _notify(title: str, markdown: str) -> None:
    from opportunity_radar.config import get_settings
    from opportunity_radar.notifications.discord import DiscordNotifier

    notifier = DiscordNotifier(get_settings().discord_webhook_url)
    if notifier.configured:
        asyncio.run(notifier.send_markdown(title, markdown))


def _candidate_summary() -> dict:
    """Just enough about Patrick for the builder to play to his strengths:
    skills and existing project names/stacks, never resume text."""
    try:
        from opportunity_radar.resume.tailor import load_bank

        bank = load_bank()
    except Exception:
        return {}
    return {
        "skills": bank.skills,
        "existing_projects": [f"{e.name} ({', '.join(e.tech)})" for e in bank.projects if e.active],
    }


@projects_app.command("list")
def projects_list() -> None:
    """Show the portfolio pipeline."""
    from opportunity_radar.projects.portfolio import load_projects

    table = Table(title="Portfolio projects")
    for column in ("Slug", "Status", "Title", "Repo", "Autopilot"):
        table.add_column(column)
    for p in load_projects():
        table.add_row(p.slug, p.status, p.title[:50], p.repo, "yes" if p.autopilot else "")
    console.print(table)


def _set(slug: str, status: str, push: bool) -> None:
    from opportunity_radar.projects.portfolio import load_projects, set_status

    projects = load_projects()
    try:
        project = set_status(projects, slug, status)
    except (KeyError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    git = _save_and_push(projects, f"projects: {status} {project.slug}", push)
    console.print(f"{project.slug} -> {status} ({git})")


@projects_app.command("approve")
def projects_approve(slug: str, push: bool = typer.Option(True, "--push/--no-push")) -> None:
    """Approve a proposed project; the builder starts on its next run."""
    _set(slug, "approved", push)


@projects_app.command("pause")
def projects_pause(slug: str, push: bool = typer.Option(True, "--push/--no-push")) -> None:
    """Stop the builder from working on a project."""
    _set(slug, "paused", push)


@projects_app.command("reject")
def projects_reject(slug: str, push: bool = typer.Option(True, "--push/--no-push")) -> None:
    """Never build this project."""
    _set(slug, "rejected", push)


@projects_app.command("step")
def projects_step(
    slug: str = typer.Option(None, "--slug", help="Work on this project instead of the next one"),
    out: Path = typer.Option(None, "--out", help="Write the stage context JSON here"),
    push: bool = typer.Option(True, "--push/--no-push"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Decide only; create/merge nothing"),
) -> None:
    """Decide the builder's next stage (creates the repo / merges on autopilot)."""
    from opportunity_radar.projects.builder import decide, gh_cli, read_state
    from opportunity_radar.projects.portfolio import find, load_projects, next_project

    projects = load_projects()
    project = find(projects, slug) if slug else next_project(projects)
    context: dict = {"stage": "idle", "reason": "no approved or in-flight project"}
    if project is not None:
        gh = gh_cli(_token())
        state = read_state(project.repo_name, gh)
        stage = decide(project, state)
        context = {
            "stage": stage.kind,
            "reason": stage.reason,
            "slug": project.slug,
            "repo": project.repo_name,
            "milestone": stage.milestone or "",
            "milestones_done": sum(m.done for m in state.milestones),
            "milestones_total": len(state.milestones),
            "pr_number": stage.pr.number if stage.pr else "",
            "pr_branch": stage.pr.branch if stage.pr else "",
            "pr_url": stage.pr.url if stage.pr else "",
            "feedback": stage.pr.feedback if stage.pr else [],
            "project": asdict(project),
        }
        changed = False
        if not dry_run and stage.kind == "create":
            gh(
                ["repo", "create", project.repo_name, "--private",
                 "--description", (project.pitch or project.title)[:300]]
            )  # fmt: skip
            project.repo = project.repo_name
            context.update(stage="plan", reason="repository created; planning next")
            changed = True
        if not dry_run and stage.kind == "merge" and stage.pr:
            gh(["pr", "merge", str(stage.pr.number), "--repo", project.repo_name,
                "--squash", "--delete-branch"])  # fmt: skip
            context.update(stage="merged")
        if project.status == "approved" and context["stage"] != "idle":
            project.status = "building"
            changed = True
        if context["stage"] == "finish" and project.status != "finishing":
            project.status = "finishing"
            changed = True
        context["project"] = asdict(project)
        context["candidate"] = _candidate_summary()
        if changed and not dry_run:
            console.print(
                _save_and_push(projects, f"projects: {project.slug} {project.status}", push)
            )
    text = json.dumps(context, indent=1)
    if out:
        out.write_text(text, encoding="utf-8")
    console.print(f"stage={context['stage']} ({context['reason']})")


@projects_app.command("scout-merge")
def projects_scout_merge(
    proposals_file: Path = typer.Argument(..., exists=True, help="JSON list from the scout"),
    push: bool = typer.Option(True, "--push/--no-push"),
) -> None:
    """Add the scout's proposals to projects.yaml and ask Patrick on Discord."""
    from opportunity_radar.projects.portfolio import Project, add_proposals, load_projects, slugify

    raw = json.loads(proposals_file.read_text(encoding="utf-8"))
    items = raw.get("projects", raw) if isinstance(raw, dict) else raw
    new = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        new.append(
            Project(
                slug=slugify(str(item.get("slug") or item["title"])),
                title=str(item["title"]),
                pitch=str(item.get("pitch") or ""),
                why=str(item.get("why") or ""),
                skills=[str(s) for s in item.get("skills") or []],
                stack=[str(s) for s in item.get("stack") or []],
                release=str(item.get("release") or ""),
            )
        )
    projects = load_projects()
    added = add_proposals(projects, new)
    if not added:
        console.print("No new project proposals.")
        return
    console.print(_save_and_push(projects, f"projects: scout proposed {len(added)}", push))
    lines = [
        "Approve one to start building: GitHub → TheAsianFish/job-finder → Actions → "
        "**Project builder** → Run workflow → action `approve`, project `<slug>` "
        "(works from the GitHub app), or set `status: approved` in `projects.yaml`.",
        "",
    ]
    for p in added:
        lines += [
            f"### `{p.slug}`: {p.title}",
            p.pitch,
            f"- **Why:** {p.why}",
            f"- **Skills:** {', '.join(p.skills)}",
            f"- **Ships as:** {p.release}",
            "",
        ]
    _notify("🧪 New portfolio project proposals", "\n".join(lines))


@projects_app.command("finish")
def projects_finish(
    slug: str,
    entry: Path = typer.Option(..., "--entry", exists=True, help="RESUME.tex from the project"),
    results: Path = typer.Option(..., "--results", exists=True, help="RESULTS.md (measured)"),
    push: bool = typer.Option(True, "--push/--no-push"),
) -> None:
    """Propose the finished project's resume entry as a reserve entry (private PR)."""
    from datetime import date

    from opportunity_radar.projects.builder import (
        insert_reserve_project,
        unbacked_numbers,
        validate_entry,
    )
    from opportunity_radar.projects.portfolio import find, load_projects
    from opportunity_radar.resume.paths import private_dir
    from opportunity_radar.resume.private_pr import open_private_pr

    projects = load_projects()
    project = find(projects, slug)
    if project is None:
        console.print(f"[red]no project {slug}[/red]")
        raise typer.Exit(1)
    block = entry.read_text(encoding="utf-8")
    measured = results.read_text(encoding="utf-8")
    problems = validate_entry(block)
    if problems:
        console.print(f"[red]Resume entry rejected: {'; '.join(problems)}[/red]")
        raise typer.Exit(1)
    unbacked = unbacked_numbers(block, measured)
    repo_url = f"https://github.com/{project.repo_name}"
    body = "\n".join(
        [
            f"**{project.title}** is built: {repo_url}",
            "",
            "This adds it to `resume.tex` as a **commented-out (reserve)** project, so the "
            "tailor can swap it in for roles that want it; your master resume is unchanged. "
            "Uncomment it to show it everywhere.",
            "",
            "**Merge = this entry is true.** Edit the bullets on this branch first if needed; "
            "close to reject.",
            "",
            "Every number must come from a real run recorded in the repo's `RESULTS.md`"
            + (
                f". ⚠️ Not found in RESULTS.md: {', '.join(unbacked)}. Fix or remove before merging."
                if unbacked
                else " (all numbers found there)."
            ),
            "",
            "```latex",
            block.strip(),
            "```",
        ]
    )

    def write(work: Path) -> None:
        source = work / "resume.tex"
        source.write_text(
            insert_reserve_project(source.read_text(encoding="utf-8"), block), encoding="utf-8"
        )
        evidence = work / "projects" / f"{project.slug}-RESULTS.md"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(measured, encoding="utf-8")

    url = open_private_pr(
        private_dir(),
        branch=f"projects/{project.slug}-resume-{date.today().isoformat()}",
        title=f"Add project to resume: {project.title}",
        body=body,
        message=f"Propose resume entry for {project.title}",
        write=write,
        token=_token(),
    )
    project.status = "done"
    console.print(_save_and_push(projects, f"projects: {project.slug} done", push))
    _notify(
        f"🏁 Project finished: {project.title}",
        f"Repo: {repo_url}\nResume entry for your review: {url}"
        + (f"\n⚠️ Numbers not backed by RESULTS.md: {', '.join(unbacked)}" if unbacked else ""),
    )
    console.print(f"Resume entry PR: {url}")


def register(app: typer.Typer) -> None:
    app.add_typer(projects_app, name="projects")
