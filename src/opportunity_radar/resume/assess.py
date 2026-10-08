"""Does the current resume compete for this role? Deterministic first.

The point is NOT to tailor every alert. For an important role, measure the
standing (master) resume against the posting and only raise a flag when
there is a material disconnect:

- coverage: share of the posting's skills the master resume visibly shows;
- lift: how much the bank (live + reserve content) could raise that by
  selection alone, i.e. strong material you have but aren't showing;
- headline gaps: skills named in the job TITLE that the master doesn't show
  (split into "bank has it" vs "you don't have it");
- project alignment: how well your shown projects match, relative to the best
  any bank project could do, and in absolute terms;
- weak bullets: master bullets with no posting-relevant skill and no metric.

severity: "fits" (stay quiet), "tune" (a concrete fixable issue, or two
independent weak signals: send a review + tailored resume), "gap" (the role
centres on a skill the resume genuinely lacks: review + project proposal).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from opportunity_radar.insights.skills import default_vocabulary
from opportunity_radar.resume.bank import Bank, Bullet
from opportunity_radar.resume.selector import Posting, bullet_score, entry_score, select

LOW_COVERAGE = 0.45
GAP_COVERAGE = 0.30
MATERIAL_LIFT = 0.15
WEAK_ALIGNMENT = 0.4
RESERVE_ADVANTAGE = 3.0  # entry-score margin for "a reserve project fits better"
MIN_SKILLS = 4  # a posting naming fewer skills says too little to flag coverage
TOP_SKILLS = 5
MIN_DESCRIPTION = 400


@dataclass
class FitAssessment:
    severity: str  # fits | tune | gap
    reasons: list[str]
    master_coverage: float
    tailored_coverage: float
    shown_skills: list[str]
    hidden_skills: list[str]  # posting wants, bank has, master hides
    true_gaps: list[str]  # posting wants, not in resume at all
    headline_gaps: list[str]  # title skills the master doesn't show
    project_alignment: float  # share of the role's top skills the shown projects evidence
    weak_bullets: list[str] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return self.severity != "fits"


def _visible(text: str) -> set[str]:
    return {s.name for s in default_vocabulary() if s.found_in(text)}


def _coverage(skills: dict[str, float], visible: set[str]) -> float:
    total = sum(skills.values())
    if not total:
        return 1.0
    return sum(w for s, w in skills.items() if s in visible) / total


def assess(bank: Bank, posting: Posting, master_text: str) -> FitAssessment:
    master_visible = _visible(master_text)
    wanted = posting.skills
    selection = select(bank, posting)
    tailored_text = " ".join(
        [b.text for b in selection.bullets]
        + [", ".join(v) for v in selection.skills.values()]
        + [", ".join(e.tech) + " " + e.name for e, _ in selection.projects]
    )
    tailored_visible = _visible(tailored_text)
    master_cov = _coverage(wanted, master_visible)
    tailored_cov = _coverage(wanted, tailored_visible | master_visible)
    in_bank = bank.all_skills
    hidden = [s for s in wanted if s not in master_visible and s in in_bank]
    gaps = [s for s in wanted if s not in master_visible and s not in in_bank]
    headline = [s for s, w in wanted.items() if w >= 3.0 and s not in master_visible]

    live_projects = [e for e in bank.projects if e.active]
    best_live = max((entry_score(e, posting) for e in live_projects), default=0.0)
    best_any = max((entry_score(e, posting) for e in bank.projects), default=0.0)
    # Project alignment: of the role's top skills, how many do the shown
    # projects evidence (tech stack or bullets)? Interpretable and stable.
    top = [name for name, _ in sorted(wanted.items(), key=lambda kv: -kv[1])][:TOP_SKILLS]
    project_skills: set[str] = set()
    for entry in live_projects:
        project_skills |= entry.skills
    alignment = (sum(1 for name in top if name in project_skills) / len(top)) if top else 1.0
    enough = len(wanted) >= MIN_SKILLS

    weak: list[Bullet] = [
        b
        for e in bank.entries
        if e.active
        for b in e.live_bullets
        if not (b.skills & set(wanted)) and not b.has_metric and bullet_score(b, posting) < 1.0
    ]

    reasons: list[str] = []
    if enough and master_cov < LOW_COVERAGE:
        reasons.append(f"standing resume shows only {master_cov:.0%} of the role's skills")
    if tailored_cov - master_cov >= MATERIAL_LIFT:
        reasons.append(
            f"your own unused material lifts coverage {master_cov:.0%} -> {tailored_cov:.0%}"
        )
    if len(hidden) >= 2:
        reasons.append("you have but don't show: " + ", ".join(hidden[:5]))
    if enough and alignment < WEAK_ALIGNMENT:
        reasons.append(
            f"shown projects evidence {alignment:.0%} of the role's top skills ({', '.join(top)})"
        )
    if best_any >= best_live + RESERVE_ADVANTAGE:
        reasons.append("a reserve project fits this role clearly better than the ones shown")
    headline_true_gaps = [s for s in headline if s not in in_bank]
    if headline_true_gaps:
        reasons.append(
            "role centres on " + ", ".join(headline_true_gaps) + ", which your resume lacks"
        )

    # "Major deviation" only: a concrete fixable issue (hidden material, a
    # better reserve, measurable lift) or two independent weak signals. One
    # soft signal on its own (e.g. projects don't show C++) stays quiet.
    fixable = (
        len(hidden) >= 2
        or tailored_cov - master_cov >= MATERIAL_LIFT
        or best_any >= best_live + RESERVE_ADVANTAGE
    )
    if headline_true_gaps or (enough and master_cov < GAP_COVERAGE and not hidden):
        severity = "gap"
    elif fixable or len(reasons) >= 2:
        severity = "tune"
    else:
        severity = "fits"
    return FitAssessment(
        severity=severity,
        reasons=reasons,
        master_coverage=master_cov,
        tailored_coverage=tailored_cov,
        shown_skills=[s for s in wanted if s in master_visible],
        hidden_skills=hidden,
        true_gaps=gaps,
        headline_gaps=headline,
        project_alignment=alignment,
        weak_bullets=[b.text for b in weak][:5],
    )
