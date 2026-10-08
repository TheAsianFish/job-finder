"""Candid resume review for one important role (Claude, read-only advice).

Produced only when the deterministic assessment flags a disconnect. The
reviewer sees the standing resume, the bank's reserve entries, the job
description and the assessment numbers, and answers as a hiring-side
reviewer would: which bullets are weak and how to fix them (STAR/XYZ,
technical depth), whether each project fits the role and the company's
apparent values, how the candidate stacks up against typical applicants,
which reserves to swap in, and whether a new project is warranted.
Advice only: it never writes resume content, so it cannot fabricate any.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from opportunity_radar.resume.assess import FitAssessment
from opportunity_radar.resume.bank import Bank
from opportunity_radar.resume.polish import Runner, parse_json_object

DESCRIPTION_EXCERPT = 5000


@dataclass
class Review:
    verdict: str = ""
    strengths: list[str] = field(default_factory=list)
    weak_bullets: list[dict] = field(default_factory=list)  # bullet, problem, fix
    projects: list[dict] = field(default_factory=list)  # name, fit, why
    culture_fit: str = ""
    competitiveness: str = ""
    swaps: list[str] = field(default_factory=list)
    new_project: dict = field(default_factory=dict)  # needed, title, pitch, skills, why
    error: str | None = None


def build_prompt(
    bank: Bank, master_text: str, *, title: str, company: str, description: str, fit: FitAssessment
) -> str:
    reserves = [
        {"name": e.name, "skills": sorted(e.skills), "facts": [b.text for b in e.bullets]}
        for e in bank.entries
        if not e.active
    ]
    numbers = {
        "keyword_coverage_now": round(fit.master_coverage, 2),
        "coverage_if_reselected": round(fit.tailored_coverage, 2),
        "skills_shown": fit.shown_skills,
        "skills_you_have_but_hide": fit.hidden_skills,
        "skills_not_in_resume": fit.true_gaps,
        "project_alignment": round(fit.project_alignment, 2),
        "flags": fit.reasons,
    }
    return f"""You are a senior software engineer who screens internship and new-grad resumes
for {company}. Review this candidate's CURRENT resume for the role "{title}".

Be candid and specific, like a mentor who wants them to get the interview. Judge:
1. Bullets: which are weak for this role (vague, no technical depth, no result, wrong
   emphasis) and exactly how to strengthen each using STAR/XYZ and precise engineering
   vocabulary, using only facts already in the resume or the reserve entries.
2. Projects: for each shown project, does it fit this role and what {company} appears to
   value (infer values only from the job description)? strong / okay / weak, and why.
3. Competitiveness: how this resume compares with typical applicants for this role at this
   company. Be honest about where it falls short.
4. Swaps: which reserve entries (listed below) should replace weaker shown ones, if any.
5. New project: only if the role centres on skills the candidate cannot truthfully claim
   from anything below, propose one 2-3 week project that would close that gap and earn a
   strong bullet; otherwise needed=false.

Never invent experience, employers, metrics or skills for the candidate.

Reply with only JSON:
{{"verdict": "one sentence", "strengths": ["..."],
 "weak_bullets": [{{"bullet": "...", "problem": "...", "fix": "..."}}],
 "projects": [{{"name": "...", "fit": "strong|okay|weak", "why": "..."}}],
 "culture_fit": "...", "competitiveness": "...", "swaps": ["..."],
 "new_project": {{"needed": true, "title": "...", "pitch": "...", "skills": ["..."], "why": "..."}}}}

Assessment numbers (deterministic): {json.dumps(numbers)}

Current resume (plain text):
\"\"\"{master_text[:6000]}\"\"\"

Reserve entries (true, not currently shown): {json.dumps(reserves, ensure_ascii=False)}

Job description excerpt:
\"\"\"{(description or "")[:DESCRIPTION_EXCERPT]}\"\"\"
"""


def review(
    bank: Bank,
    master_text: str,
    *,
    title: str,
    company: str,
    description: str,
    fit: FitAssessment,
    runner: Runner | None,
) -> Review:
    if runner is None:
        return Review(error="Claude Code CLI not available")
    prompt = build_prompt(
        bank, master_text, title=title, company=company, description=description, fit=fit
    )
    try:
        data = parse_json_object(runner(prompt))
    except Exception as exc:
        return Review(error=f"review failed: {exc}")
    if not data:
        return Review(error="model reply was not the requested JSON")

    def as_list(key: str) -> list:
        value = data.get(key)
        return value if isinstance(value, list) else []

    new_project = data.get("new_project")
    return Review(
        verdict=str(data.get("verdict", "")),
        strengths=[str(s) for s in as_list("strengths")],
        weak_bullets=[w for w in as_list("weak_bullets") if isinstance(w, dict)],
        projects=[p for p in as_list("projects") if isinstance(p, dict)],
        culture_fit=str(data.get("culture_fit", "")),
        competitiveness=str(data.get("competitiveness", "")),
        swaps=[str(s) for s in as_list("swaps")],
        new_project=new_project if isinstance(new_project, dict) else {},
    )


def render_markdown(
    rev: Review, fit: FitAssessment, *, title: str, company: str, url: str | None = None
) -> str:
    head = f"# Resume check: {title} ({company})"
    lines = [head, ""]
    if url:
        lines += [f"Apply: {url}", ""]
    lines += [
        f"**Severity: {fit.severity.upper()}**. Keyword coverage {fit.master_coverage:.0%} now, "
        f"{fit.tailored_coverage:.0%} with your own unused material; project alignment "
        f"{fit.project_alignment:.0%}.",
        "",
        "## Why this was flagged",
        *[f"- {r}" for r in fit.reasons],
        "",
    ]
    if rev.error:
        lines += [f"_(Written review unavailable: {rev.error})_", ""]
        return "\n".join(lines)
    lines += [f"**Verdict:** {rev.verdict}", ""]
    if rev.strengths:
        lines += ["## Strengths", *[f"- {s}" for s in rev.strengths], ""]
    if rev.weak_bullets:
        lines += ["## Weak bullets"]
        for w in rev.weak_bullets:
            lines += [
                f"- **{w.get('bullet', '')}**",
                f"  - Problem: {w.get('problem', '')}",
                f"  - Fix: {w.get('fix', '')}",
            ]
        lines.append("")
    if rev.projects:
        lines += ["## Project fit"]
        lines += [
            f"- {p.get('name', '')}: **{p.get('fit', '')}**. {p.get('why', '')}"
            for p in rev.projects
        ]
        lines.append("")
    if rev.culture_fit:
        lines += ["## Culture fit", rev.culture_fit, ""]
    if rev.competitiveness:
        lines += ["## Against other candidates", rev.competitiveness, ""]
    if rev.swaps:
        lines += ["## Swap in", *[f"- {s}" for s in rev.swaps], ""]
    project = rev.new_project
    if project.get("needed"):
        lines += [
            f"## New project: {project.get('title', '')}",
            str(project.get("pitch", "")),
            f"Closes: {', '.join(project.get('skills') or [])}. {project.get('why', '')}",
            "",
        ]
    return "\n".join(lines)
