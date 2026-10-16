"""Portfolio project commands (AD-32): the scout proposes, Patrick approves,
the builder workflow ships one milestone PR per project at a time.

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
discord_app = typer.Typer(help="Discord hub: channels and webhooks created by the bot (AD-33).")
hub_app = typer.Typer(help="Shared memory for every agent: hub/ in the private repo (AD-33).")


def _token() -> str | None:
    return os.environ.get("AGENT_GH_TOKEN") or os.environ.get("GH_TOKEN")


def _save_and_push(projects, message: str, push: bool) -> str:
    from opportunity_radar.projects.portfolio import save_projects
    from opportunity_radar.resume.ledger import commit_and_push
    from opportunity_radar.resume.paths import private_dir

    save_projects(projects)
    return commit_and_push(private_dir(), message, push=push)


def _notify(title: str, markdown: str, channel: str = "projects") -> None:
    from opportunity_radar.notifications.discord import notifier_for

    notifier = notifier_for(channel)
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


def _bullet_history(project, gh) -> dict:
    """What the bullets writer builds on (AD-45): the project's current entry
    and talk tracks (from its open bullets PR, else resume.tex) and Patrick's
    comments on that PR. Travels only in the sealed context (AD-43)."""
    from opportunity_radar.projects.builder import GhError, find_project_entry
    from opportunity_radar.resume.paths import private_dir
    from opportunity_radar.resume.private_pr import git, repo_slug

    private = private_dir()
    branch = f"projects/{project.slug}-bullets"
    has_git = (private / ".git").exists()
    fetched = has_git and git(private, "fetch", "-q", "origin", branch).returncode == 0

    def read(path: str) -> str:
        if fetched:
            shown = git(private, "show", f"FETCH_HEAD:{path}")
            if shown.returncode == 0:
                return shown.stdout
        local = private / path
        return local.read_text(encoding="utf-8") if local.exists() else ""

    feedback: list[str] = []
    slug = repo_slug(private) if has_git else None
    if slug:
        try:
            data = json.loads(
                gh(["pr", "view", branch, "--repo", slug, "--json", "comments,reviews"])
            )
            for item in (data.get("comments") or []) + (data.get("reviews") or []):
                body = str(item.get("body") or "").strip()
                if body:
                    feedback.append(body[:2000])
        except (GhError, ValueError):
            pass  # no bullets PR yet
    return {
        "source": "the open bullets PR" if fetched else "resume.tex",
        "entry": find_project_entry(read("resume.tex"), f"github.com/{project.repo_name}"),
        "talk_tracks": read(f"prep/{project.slug}-bullets.md")[:20000],
        "feedback": feedback[-10:],
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


@projects_app.command("steer")
def projects_steer(
    slug: str,
    direction: str = typer.Argument("", help="One direction every session on it must follow"),
    clear: bool = typer.Option(False, "--clear", help="Drop all directions first"),
    push: bool = typer.Option(True, "--push/--no-push"),
) -> None:
    """Steer a project: plan, build and evolve sessions follow it (AD-44)."""
    from opportunity_radar.projects.portfolio import find, load_projects

    projects = load_projects()
    project = find(projects, slug)
    if project is None:
        console.print(f"[red]No project {slug!r} in projects.yaml[/red]")
        raise typer.Exit(1)
    if clear:
        project.steer = []
    if direction.strip():
        project.steer.append(direction.strip())
    if not clear and not direction.strip():
        for line in project.steer or ["(no directions)"]:
            console.print(f"- {line}")
        return
    console.print(_save_and_push(projects, f"projects: steer {project.slug}", push))


@projects_app.command("step")
def projects_step(
    slug: str = typer.Option(None, "--slug", help="Work on this project instead of the next one"),
    out: Path = typer.Option(None, "--out", help="Write the stage context JSON here"),
    push: bool = typer.Option(True, "--push/--no-push"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Decide only; create/merge nothing"),
    meter: Path = typer.Option(
        None, "--meter", help="Usage probe output (stream-json); governs how many projects run"
    ),
) -> None:
    """Decide the builder's next stage (creates the repo / merges on autopilot)."""
    from dataclasses import replace

    from opportunity_radar.projects.builder import (
        GhError,
        Stage,
        decide,
        gh_cli,
        pick,
        read_state,
    )
    from opportunity_radar.projects.portfolio import active_projects, find, load_projects

    projects = load_projects()
    candidates = [p for p in [find(projects, slug)] if p] if slug else active_projects(projects)
    gh = gh_cli(_token())
    from opportunity_radar.projects.usage import capacity, parse_meter

    # Usage governor (AD-42). The scan chain's dry-run wake-up check has no
    # meter: it only asks whether there is work, and the real run decides.
    reading = parse_meter(meter.read_text(encoding="utf-8")) if meter and meter.exists() else None
    room = capacity(reading)
    slots = None if dry_run and meter is None else room.projects
    if slots is not None and slug:
        # A run for one project still counts its place among all of them.
        ranked = [p.slug for p in active_projects(projects)]
        slots = 1 if any(c.slug in ranked[:slots] for c in candidates) else 0
    options = [(p, s, decide(p, s)) for p in candidates for s in [read_state(p.repo_name, gh)]]
    if slots is not None and not room.spare:
        # Evolve rounds are discretionary (AD-44): they wait for spare usage,
        # so required work on every project goes first.
        options = [
            (p, s, Stage("wait", reason=f"evolve waits for spare Claude usage ({room.summary()})"))
            if st.kind == "evolve"
            else (p, s, st)
            for p, s, st in options
        ]
    chosen = pick(options, slots)
    context: dict = {"stage": "idle", "reason": "no approved or in-flight project"}
    if chosen is not None:
        project, state, stage = chosen
        if stage.reason.startswith("usage governor"):
            stage = replace(stage, reason=f"{stage.reason} ({room.summary()})")
        if not dry_run and stage.kind == "rerun" and stage.pr:
            try:
                for run_id in stage.pr.rerunnable:
                    gh(["run", "rerun", str(run_id), "--failed", "--repo", project.repo_name])
            except GhError as exc:
                # Re-running needs "Actions: write" on the token; without it,
                # go straight to a fix rather than stall.
                console.print(f"re-run failed ({exc}); fixing instead")
                state = replace(state, pr=replace(stage.pr, rerunnable=[]))
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
            "evolve_round": len(project.evolved_at) + (1 if stage.kind == "evolve" else 0),
            "project": asdict(project),
            "usage": room.summary(),
            "seven_day_before": reading.seven_day if reading else None,
        }
        changed = False
        if not dry_run and stage.reason.startswith("CI failing") and stage.pr:
            project.ci_fix_started.append(stage.pr.number)
            changed = True
        if not dry_run and stage.kind == "evolve":
            # Counted when the round starts, like CI fixes: a round that
            # decides nothing is worth adding is not run again (AD-44).
            project.evolved_at.append(len(state.milestones))
            changed = True
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
        if not dry_run and context["stage"] in ("build", "address", "finish"):
            try:
                context["bullets_history"] = _bullet_history(project, gh)
            except Exception as exc:  # advisory: never block a build
                console.print(f"bullet history unavailable ({type(exc).__name__})")
        context["candidate"] = _candidate_summary()
        from opportunity_radar.hub import bundle

        context["hub"] = bundle()
        if changed and not dry_run:
            console.print(
                _save_and_push(projects, f"projects: {project.slug} {project.status}", push)
            )
    text = json.dumps(context, indent=1)
    if out:
        out.write_text(text, encoding="utf-8")
    console.print(f"stage={context['stage']} ({context['reason']})")
    if context.get("usage"):
        console.print(f"usage: {context['usage']}")


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
                problem=str(item.get("problem") or ""),
                pitch=str(item.get("pitch") or ""),
                why=str(item.get("why") or ""),
                questions=[str(q) for q in item.get("questions") or []],
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
            f"**Problem:** {p.problem}" if p.problem else "",
            p.pitch,
            f"- **Why:** {p.why}",
            *(f"- **Question:** {q}" for q in p.questions[:3]),
            f"- **Skills:** {', '.join(p.skills)}",
            f"- **Ships as:** {p.release}",
            "",
        ]
    _notify("🧪 New portfolio project proposals", "\n".join(lines))


def _revoice(block: str) -> tuple[str, str]:
    """The voice pass (AD-47): the tailor's rewriter with Patrick's voice guide
    and his own bullets as examples, behind its guard. Never raises."""
    from opportunity_radar.resume import polish
    from opportunity_radar.resume.latex import to_plain
    from opportunity_radar.resume.paths import private_dir
    from opportunity_radar.resume.tailor import load_bank

    try:
        bank = load_bank()
        corpus = to_plain((private_dir() / "resume.tex").read_text(encoding="utf-8"))
    except Exception as exc:
        return block, f"skipped: resume not readable ({type(exc).__name__})"
    return polish.revoice_project(block, bank, polish.claude_runner(model="opus"), corpus=corpus)


def _propose_entry(
    slug: str, entry: Path, results: Path, notes: Path | None, interview: Path | None, *,
    final: bool, push: bool, critique: Path | None = None, voice: bool = True,
) -> None:  # fmt: skip
    """Put a project's resume entry in front of Patrick as a private PR
    (merge = true). While the project is being built (AD-41) one PR per
    project, on a fixed branch, follows the milestones; the final entry at
    finish gets its own PR with the mock-interview gate."""
    from datetime import date

    from opportunity_radar.projects.builder import unbacked_numbers, upsert_project, validate_entry
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
    reviewed = block
    voice_note = "off"
    if voice:
        block, voice_note = _revoice(block)
        console.print(f"voice pass: {voice_note}")
    unbacked = unbacked_numbers(block, measured)
    repo_url = f"https://github.com/{project.repo_name}"
    talk = notes.read_text(encoding="utf-8").strip() if notes and notes.exists() else ""
    mock = interview.read_text(encoding="utf-8").strip() if interview else ""
    review = critique.read_text(encoding="utf-8").strip() if critique and critique.exists() else ""
    verdict = next(
        (line.strip() for line in review.splitlines() if line.lower().startswith("verdict")), ""
    )
    lead = (
        f"**{project.title}** is built: {repo_url}"
        if final
        else f"**{project.title}**, as built so far ({repo_url}). This PR updates after "
        "each milestone; merge now to use the project already, later versions come as "
        "new updates."
    )
    gate = (
        "**Before merging, pass the mock interview** in "
        f"`prep/{project.slug}-interview.md` (on this branch). If you can't answer a "
        "question, study that part first; that is the point of this gate."
        if final
        else f"**Before merging, read the talk tracks** in `prep/{project.slug}-bullets.md`: "
        "you should be able to tell each bullet's story for five minutes."
    )
    body = "\n".join(
        [
            lead,
            "",
            "This puts it in `resume.tex` as a **commented-out (reserve)** project (or "
            "updates the entry already there), so the tailor can swap it and pick its bullets "
            "per posting; the master resume is unchanged. Uncomment it to show it everywhere.",
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
            "",
            f"**Voice pass:** {voice_note}."
            + (
                "\n\n<details><summary>The reviewed version before the voice pass</summary>"
                f"\n\n```latex\n{reviewed.strip()}\n```\n</details>"
                if block != reviewed
                else ""
            ),
            "",
            (
                f"**Independent review** (a separate reviewer read the code and cut or "
                f"rewrote weak bullets): {verdict or 'see the file'}. Full critique: "
                f"`prep/{project.slug}-bullets-review.md`."
                if review
                else "No independent review ran for this version."
            ),
            "",
            gate,
        ]
    )

    def write(work: Path) -> None:
        source = work / "resume.tex"
        source.write_text(
            upsert_project(source.read_text(encoding="utf-8"), block), encoding="utf-8"
        )
        files = {f"projects/{project.slug}-RESULTS.md": measured}
        if talk:
            files[f"prep/{project.slug}-bullets.md"] = talk + "\n"
        if review:
            files[f"prep/{project.slug}-bullets-review.md"] = review + "\n"
        if final:
            files[f"prep/{project.slug}-interview.md"] = (
                mock + "\n" if mock else "# Mock interview\n\n(not generated)\n"
            )
        for name, text in files.items():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            (work / name).write_text(text, encoding="utf-8")

    url = open_private_pr(
        private_dir(),
        branch=f"projects/{project.slug}-resume-{date.today().isoformat()}"
        if final
        else f"projects/{project.slug}-bullets",
        title=f"{'Add project to resume' if final else 'Resume bullets'}: {project.title}",
        body=body,
        message=f"{'Propose resume entry' if final else 'Update resume bullets'} for {project.title}",
        write=write,
        token=_token(),
    )
    warning = f"\n⚠️ Numbers not backed by RESULTS.md: {', '.join(unbacked)}" if unbacked else ""
    if final:
        project.status = "done"
        console.print(_save_and_push(projects, f"projects: {project.slug} done", push))
        _notify(
            f"🏁 Project finished: {project.title}",
            f"Repo: {repo_url}\nResume entry for your review: {url}{warning}",
        )
    else:
        _notify(
            f"📝 Resume bullets: {project.title}",
            f"Updated from the latest milestone; merge to use them (talk tracks inside): {url}"
            f"{warning}",
            channel="resume",
        )
    console.print(f"Resume entry PR: {url}")


_ENTRY = typer.Option(..., "--entry", exists=True, help="RESUME.tex from the project")
_RESULTS = typer.Option(..., "--results", exists=True, help="RESULTS.md (measured)")
_NOTES = typer.Option(None, "--notes", help="BULLETS.md: each bullet's talk track")
_CRITIQUE = typer.Option(None, "--critique", help="The independent bullets review (AD-45)")
_VOICE = typer.Option(True, "--voice/--no-voice", help="Rewrite in Patrick's voice (AD-47)")


@projects_app.command("finish")
def projects_finish(
    slug: str,
    entry: Path = _ENTRY,
    results: Path = _RESULTS,
    notes: Path = _NOTES,
    interview: Path = typer.Option(
        None, "--interview", help="INTERVIEW.md: the mock interview to pass first"
    ),
    critique: Path = _CRITIQUE,
    voice: bool = _VOICE,
    push: bool = typer.Option(True, "--push/--no-push"),
) -> None:
    """Propose the finished project's resume entry as a reserve entry (private PR)."""
    _propose_entry(
        slug, entry, results, notes, interview, final=True, push=push, critique=critique,
        voice=voice,
    )  # fmt: skip


@projects_app.command("bullets")
def projects_bullets(
    slug: str,
    entry: Path = _ENTRY,
    results: Path = _RESULTS,
    notes: Path = _NOTES,
    critique: Path = _CRITIQUE,
    voice: bool = _VOICE,
    push: bool = typer.Option(True, "--push/--no-push"),
) -> None:
    """Propose or update a project's resume entry mid-build (one PR per project)."""
    _propose_entry(
        slug, entry, results, notes, None, final=False, push=push, critique=critique,
        voice=voice,
    )  # fmt: skip


@projects_app.command("revoice")
def projects_revoice(
    slug: str,
    branch: str = typer.Option(
        None, "--branch", help="The PR branch (default: the project's open resume PR)"
    ),
    push: bool = typer.Option(True, "--push/--no-push"),
) -> None:
    """Run the voice pass on a project entry already in an open private PR (AD-47)."""
    import tempfile

    from opportunity_radar.projects.builder import find_project_entry, gh_cli, upsert_project
    from opportunity_radar.projects.portfolio import find, load_projects
    from opportunity_radar.resume.paths import private_dir
    from opportunity_radar.resume.private_pr import GIT_AUTHOR, git, repo_slug

    project = find(load_projects(), slug)
    private = private_dir()
    repo = repo_slug(private) if (private / ".git").exists() else None
    if project is None or repo is None:
        console.print("[red]Unknown project, or the private repo is not cloned[/red]")
        raise typer.Exit(1)
    if not branch:
        prs = json.loads(
            gh_cli(_token())(["pr", "list", "--repo", repo, "--json", "headRefName,number"])
        )
        mine = [p["headRefName"] for p in prs if p["headRefName"].startswith(f"projects/{slug}-")]
        if not mine:
            console.print(f"[red]No open resume PR for {slug}[/red]")
            raise typer.Exit(1)
        branch = sorted(mine)[-1]
    if git(private, "fetch", "-q", "origin", branch).returncode != 0:
        console.print(f"[red]Could not fetch {branch}[/red]")
        raise typer.Exit(1)
    with tempfile.TemporaryDirectory(prefix="revoice-") as tmp:
        work = Path(tmp) / "wt"
        git(private, "worktree", "add", "-q", "--detach", str(work), "FETCH_HEAD")
        try:
            source = work / "resume.tex"
            tex = source.read_text(encoding="utf-8")
            old = find_project_entry(tex, f"github.com/{project.repo_name}")
            if not old:
                console.print("[red]No entry for this project on that branch[/red]")
                raise typer.Exit(1)
            new, note = _revoice(old)
            console.print(f"voice pass: {note}")
            if new == old:
                return
            source.write_text(upsert_project(tex, new), encoding="utf-8")
            before = work / "prep" / f"{project.slug}-before-voice.tex"
            before.parent.mkdir(parents=True, exist_ok=True)
            before.write_text(old, encoding="utf-8")
            name, email = GIT_AUTHOR
            git(work, "add", "-A")
            git(work, "-c", f"user.name={name}", "-c", f"user.email={email}",
                "commit", "-q", "-m", f"Rewrite {project.title} bullets in my voice")  # fmt: skip
            if push:
                pushed = git(work, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
                if pushed.returncode != 0:
                    console.print(f"[red]push failed: {pushed.stderr.strip()[:150]}[/red]")
                    raise typer.Exit(1)
            console.print(new)
            console.print(
                f"Updated {branch} (previous version in prep/{before.name})"
                if push
                else "Not pushed (--no-push)"
            )
        finally:
            git(private, "worktree", "remove", "--force", str(work))


# ---------------------------------------------------------------------------
# Hub (shared memory)


@hub_app.command("context")
def hub_context(
    out: Path = typer.Option(None, "--out", help="Write here instead of printing"),
    entries: int = typer.Option(40, "--entries", help="Recent journal entries to include"),
) -> None:
    """Everything an agent should know: ABOUT, project summaries, recent journal."""
    from opportunity_radar.hub import bundle

    text = bundle(entries)
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(f"Wrote {len(text)} characters to {out}")
    else:
        print(text)


@hub_app.command("log")
def hub_log(
    source: str = typer.Argument(..., help="Who is writing, e.g. 'builder/replay' or 'session'"),
    message: str = typer.Argument(None, help="Entry text (or use --file)"),
    file: Path = typer.Option(None, "--file", exists=True),
    push: bool = typer.Option(False, "--push/--no-push"),
) -> None:
    """Append one entry to hub/JOURNAL.md."""
    from opportunity_radar.hub import append_journal
    from opportunity_radar.resume.ledger import commit_and_push
    from opportunity_radar.resume.paths import private_dir

    text = file.read_text(encoding="utf-8") if file else (message or "")
    append_journal(source, text)
    git = commit_and_push(private_dir(), f"hub: {source}", push=push) if push else "saved"
    console.print(f"Journal entry added ({git}).")


@hub_app.command("project-summary")
def hub_project_summary(
    slug: str,
    file: Path = typer.Argument(..., exists=True),
    push: bool = typer.Option(False, "--push/--no-push"),
) -> None:
    """Replace hub/projects/<slug>.md with the builder's latest summary."""
    from opportunity_radar.hub import write_project_summary
    from opportunity_radar.resume.ledger import commit_and_push
    from opportunity_radar.resume.paths import private_dir

    text = file.read_text(encoding="utf-8")
    if not text.strip():
        console.print("[yellow]Empty summary; kept the previous one.[/yellow]")
        return
    write_project_summary(slug, text)
    git = commit_and_push(private_dir(), f"hub: {slug} summary", push=push) if push else "saved"
    console.print(f"Project summary updated ({git}).")


@hub_app.command("study-note")
def hub_study_note(
    slug: str,
    name: str,
    file: Path = typer.Argument(..., exists=True),
) -> None:
    """Save a builder run's teaching notes to study/<slug>/<name>.md (private)."""
    from opportunity_radar.hub import write_study_note

    text = file.read_text(encoding="utf-8")
    if not text.strip():
        console.print("No study notes this run.")
        return
    path = write_study_note(slug, name, text)
    console.print(f"Study notes saved: {path.parent.name}/{path.name}")


# ---------------------------------------------------------------------------
# Discord hub


@discord_app.command("setup")
def discord_setup(
    guild: str = typer.Option(..., "--guild", help="Server ID (Developer Mode -> Copy Server ID)"),
) -> None:
    """Create the hub channels + webhooks with the bot (DISCORD_BOT_TOKEN in .env).

    Webhooks are saved to .env (local runs) and .env.discord (git-ignored), which
    you upload yourself: gh secret set -f .env.discord --repo TheAsianFish/job-finder
    """
    from opportunity_radar.config import get_settings, project_root
    from opportunity_radar.notifications.discord_bot import DiscordBotError, setup_hub, upsert_env

    get_settings()  # loads .env
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        console.print("[red]Set DISCORD_BOT_TOKEN in .env first (see docs/discord-hub.md).[/red]")
        raise typer.Exit(1)
    try:
        result = setup_hub(token, guild)
    except DiscordBotError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    root = project_root()
    upsert_env(root / ".env", result.env)
    upsert_env(root / ".env.discord", result.env)
    console.print(
        f"Channels: {', '.join('#' + c for c in result.webhooks)} "
        f"(created: {', '.join(result.created_channels) or 'none'}; "
        f"new webhooks: {', '.join(result.created_webhooks) or 'none'})."
    )
    console.print(
        "Saved to .env and .env.discord. Upload them for the cloud agents with:\n"
        "  gh secret set -f .env.discord --repo TheAsianFish/job-finder"
    )


def register(app: typer.Typer) -> None:
    app.add_typer(projects_app, name="projects")
    app.add_typer(hub_app, name="hub")
    app.add_typer(discord_app, name="discord")


@projects_app.command("usage-record")
def projects_usage_record(
    slug: str,
    stage: str,
    sessions: Path = typer.Option(..., "--sessions", help="JSON list from project_agent.sh"),
    before: float = typer.Option(None, "--before", help="7-day meter before the run (0-1)"),
) -> None:
    """Add one builder run to the usage ledger (AD-42); the caller commits."""
    from datetime import UTC, datetime

    from opportunity_radar.projects.usage import Row, append, ledger_path
    from opportunity_radar.resume.paths import private_dir

    try:
        records = json.loads(sessions.read_text(encoding="utf-8") or "[]")
    except (OSError, ValueError):
        records = []
    records = [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []
    if not records:
        console.print("no sessions to record")
        return
    after = [r["seven_day"] for r in records if r.get("seven_day") is not None]
    five = [r["five_hour"] for r in records if r.get("five_hour") is not None]
    row = Row(
        at=datetime.now(UTC).isoformat(timespec="seconds"),
        slug=slug,
        stage=stage,
        cost=round(sum(float(r.get("cost") or 0) for r in records), 4),
        seven_day_before=before,
        seven_day_after=max(after) if after else None,
        five_hour_after=five[-1] if five else None,
        limit_hit=any(r.get("limit_hit") for r in records),
    )
    append(ledger_path(private_dir()), [row])
    console.print(
        f"usage: {slug} {stage}: ${row.cost:.2f} list price"
        + (
            f", 7-day {before:.0%} -> {row.seven_day_after:.0%}"
            if before is not None and after
            else ""
        )
        + (" (usage limit hit)" if row.limit_hit else "")
    )


@projects_app.command("usage")
def projects_usage(
    meter: Path = typer.Option(None, "--meter", help="Usage probe output (stream-json)"),
    days: int = typer.Option(7, "--days"),
) -> None:
    """How much the builder uses: the meter, how many projects may run, and
    spend per project (AD-42)."""
    from datetime import UTC, datetime, timedelta

    from opportunity_radar.projects.usage import (
        capacity,
        ledger_path,
        load_ledger,
        parse_meter,
        projection,
    )
    from opportunity_radar.resume.paths import private_dir

    reading = parse_meter(meter.read_text(encoding="utf-8")) if meter and meter.exists() else None
    rows = load_ledger(ledger_path(private_dir()))
    console.print(capacity(reading).summary())
    console.print(projection(rows, reading))
    since = datetime.now(UTC) - timedelta(days=days)
    recent = [r for r in rows if datetime.fromisoformat(r.at) >= since]
    table = Table(title=f"Builder runs, last {days} days")
    for column in ("project", "runs", "list-price $", "7-day meter used"):
        table.add_column(column)
    for slug in sorted({r.slug for r in recent}):
        mine = [r for r in recent if r.slug == slug]
        used = sum(
            max(0.0, r.seven_day_after - r.seven_day_before)
            for r in mine
            if r.seven_day_after is not None and r.seven_day_before is not None
        )
        table.add_row(slug, str(len(mine)), f"{sum(r.cost for r in mine):.2f}", f"{used:.0%}")
    console.print(table)
