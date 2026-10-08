"""ATS readiness report for a resume against one posting.

Checks what screening software and a skimming recruiter see: is the text
extractable, are the standard sections and contact details present, is it
one page, and which of the posting's skills are visible. Missing skills are
split honestly into "you have it but this resume doesn't show it" and "not
in your resume at all" (a real gap, never something to paper over).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from opportunity_radar.insights.skills import default_vocabulary
from opportunity_radar.resume.bank import Bank
from opportunity_radar.resume.selector import Posting

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")
_SECTIONS = ("education", "experience", "project", "skill")


@dataclass
class AtsReport:
    coverage: float
    matched: list[str]
    in_bank_not_shown: list[str]
    true_gaps: list[str]
    checks: dict[str, bool] = field(default_factory=dict)
    pages: int | None = None
    baseline_coverage: float | None = None

    @property
    def passed_checks(self) -> bool:
        return all(self.checks.values())


def _visible(text: str) -> set[str]:
    return {s.name for s in default_vocabulary() if s.found_in(text)}


def analyse(
    resume_text: str,
    posting: Posting,
    bank: Bank,
    pages: int | None = None,
    baseline_text: str | None = None,
) -> AtsReport:
    wanted = list(posting.skills)
    visible = _visible(resume_text)
    matched = [s for s in wanted if s in visible]
    unmatched = [s for s in wanted if s not in visible]
    in_bank = bank.all_skills
    lowered = resume_text.lower()
    checks = {
        "text extractable": len(resume_text.strip()) > 400,
        "one page": pages is None or pages == 1,
        "email present": bool(_EMAIL_RE.search(resume_text)),
        "phone present": bool(_PHONE_RE.search(resume_text)),
        **{f"'{s.title()}' section": s in lowered for s in _SECTIONS},
    }
    baseline = None
    if baseline_text is not None and wanted:
        baseline = len([s for s in wanted if s in _visible(baseline_text)]) / len(wanted)
    return AtsReport(
        coverage=len(matched) / len(wanted) if wanted else 1.0,
        matched=matched,
        in_bank_not_shown=[s for s in unmatched if s in in_bank],
        true_gaps=[s for s in unmatched if s not in in_bank],
        checks=checks,
        pages=pages,
        baseline_coverage=baseline,
    )


def render_markdown(report: AtsReport, title: str, company: str) -> str:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.0%}"

    lines = [
        f"# ATS report: {title} ({company})",
        "",
        f"- Keyword coverage: **{pct(report.coverage)}** "
        f"(master resume: {pct(report.baseline_coverage)})",
        f"- Matched: {', '.join(report.matched) or 'none'}",
        f"- You have but not shown here: {', '.join(report.in_bank_not_shown) or 'none'}",
        f"- Not in your resume (real gaps, don't fake them): {', '.join(report.true_gaps) or 'none'}",
        "",
        "## Checks",
        "",
    ]
    lines += [f"- [{'x' if ok else ' '}] {name}" for name, ok in report.checks.items()]
    return "\n".join(lines) + "\n"
