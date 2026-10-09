"""Hiring panel: three reviewers read the resume the way real screeners do.

Layered on the single review (review.py), not a replacement for it. For a
flagged role, three focused personas run in parallel, each with its own
question:

- recruiter: a 6-second skim. What stands out, what gets it rejected?
- hiring manager: given what this team builds, which projects and bullets
  prove the candidate can do the work, and what should be swapped?
- interviewer: which bullets would fall apart under "tell me more"?

A fourth, deterministic seat is the ATS check (ats.analyse: keyword
coverage, sections, contact details) because real ATS filtering is keyword
matching, not an LLM. The lead review (review.review) then reads all four
plus what past applications taught us (insights.outcomes.lessons) and writes
the usual Review with one ranked list of changes. Advice only: personas never
write resume content, so they cannot fabricate any. A persona that fails is
recorded and skipped; the lead still runs on whatever came back.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from opportunity_radar.resume.ats import analyse
from opportunity_radar.resume.bank import Bank
from opportunity_radar.resume.polish import Runner, parse_json_object
from opportunity_radar.resume.selector import Posting

DESCRIPTION_EXCERPT = 5000

_COMMON = """Candidate: CS undergraduate (BS), applying for "{title}" at {company}.
Judge only what is on the page; never invent experience, metrics or skills.

Resume (plain text):
\"\"\"{resume}\"\"\"

Job description excerpt:
\"\"\"{description}\"\"\"
"""

PERSONAS: dict[str, str] = {
    "recruiter": """You are a technical recruiter at {company} screening hundreds of intern
resumes for "{title}". You give each one about 6 seconds before deciding.
Say what your eye lands on first, what makes you keep reading, and what makes you
pass (unclear impact, buried keywords, weak first bullets, formatting noise).

Reply with only JSON:
{{"first_impression": "...", "stands_out": ["..."], "red_flags": ["..."],
 "advance": "yes|maybe|no", "why": "one sentence"}}
""",
    "hiring_manager": """You are the engineering manager of the team hiring for "{title}" at
{company}. Infer what the team builds and needs from the job description only.
Decide which projects and bullets prove this candidate could contribute on your
team, which are noise for this role, and which unused entries (listed below)
would serve better.

Unused true entries: {reserves}

Reply with only JSON:
{{"team_needs": ["..."], "projects": [{{"name": "...", "fit": "strong|okay|weak",
 "why": "..."}}], "swaps": ["entry name to show instead, and what it replaces"],
 "missing_evidence": ["what you wanted to see and didn't"],
 "interview": "yes|maybe|no", "why": "one sentence"}}
""",
    "interviewer": """You are a senior engineer at {company} who will interview this candidate
for "{title}". Find the bullets you would dig into and where the story could fall
apart (vague ownership, unexplained numbers, buzzwords without depth), and the one
story that is strongest for this role.

Reply with only JSON:
{{"fragile_bullets": [{{"bullet": "...", "likely_question": "...", "risk": "..."}}],
 "strongest_story": "...", "prep": ["what to be ready to explain"]}}
""",
}


def persona_prompt(
    name: str, bank: Bank, resume: str, *, title: str, company: str, description: str
) -> str:
    reserves = [
        {"name": e.name, "skills": sorted(e.skills), "facts": [b.text for b in e.live_bullets]}
        for e in bank.entries
        if not e.active
    ]
    body = PERSONAS[name].format(
        title=title, company=company, reserves=json.dumps(reserves, ensure_ascii=False)
    )
    common = _COMMON.format(
        title=title,
        company=company,
        resume=resume[:6000],
        description=(description or "")[:DESCRIPTION_EXCERPT],
    )
    return f"{body}\n{common}"


def ats_seat(bank: Bank, resume: str, *, title: str, description: str) -> dict:
    report = analyse(resume, Posting.from_text(title, description), bank)
    return {
        "keyword_coverage": round(report.coverage, 2),
        "matched": report.matched,
        "have_but_not_shown": report.in_bank_not_shown,
        "not_in_resume": report.true_gaps,
        "failed_checks": [name for name, ok in report.checks.items() if not ok],
    }


def run_panel(
    bank: Bank,
    resume: str,
    *,
    title: str,
    company: str,
    description: str,
    runner: Runner | None,
) -> dict[str, dict]:
    """Run the three personas in parallel plus the ATS seat. Never raises."""
    panel: dict[str, dict] = {"ats": ats_seat(bank, resume, title=title, description=description)}
    if runner is None:
        return panel

    def ask(name: str) -> dict:
        prompt = persona_prompt(
            name, bank, resume, title=title, company=company, description=description
        )
        try:
            data = parse_json_object(runner(prompt))
        except Exception as exc:  # one seat failing must not sink the panel
            return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        return data or {"error": "reply was not the requested JSON"}

    with ThreadPoolExecutor(max_workers=len(PERSONAS)) as pool:
        answers = dict(zip(PERSONAS, pool.map(ask, PERSONAS), strict=True))
    panel.update(answers)
    return panel


def seated(panel: dict[str, dict]) -> list[str]:
    """Persona seats that answered (the ATS seat always does)."""
    return [name for name in PERSONAS if name in panel and "error" not in panel[name]]


def summary(panel: dict[str, dict]) -> dict[str, str]:
    """Short, non-sensitive verdicts for meta.json and the outcomes report."""
    out: dict[str, str] = {}
    if "error" not in panel.get("recruiter", {"error": 1}):
        out["recruiter"] = str(panel["recruiter"].get("advance", "")).lower()
    if "error" not in panel.get("hiring_manager", {"error": 1}):
        out["hiring_manager"] = str(panel["hiring_manager"].get("interview", "")).lower()
    if "ats" in panel:
        out["ats_coverage"] = str(panel["ats"].get("keyword_coverage", ""))
    return out
