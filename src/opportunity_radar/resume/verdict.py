"""One-line resume verdict for an alert: apply as-is, or a review is coming.

Deterministic and instant (no model call), computed when the alert is built,
so every high-priority alert says whether the standing resume is good enough
for that role. Roles that need work get the full review from the scan's
resume-check step (core/strong companies) or on demand.
"""

from __future__ import annotations

from functools import lru_cache

from opportunity_radar.resume.assess import MIN_DESCRIPTION, assess
from opportunity_radar.resume.paths import resume_source
from opportunity_radar.resume.selector import Posting


@lru_cache(maxsize=2)
def _bank_and_master(mtime: float):  # cache keyed by resume.tex mtime
    from opportunity_radar.resume.tailor import load_bank, master_text

    bank = load_bank()
    return bank, master_text(bank)


def resume_fit_line(title: str, description: str, important: bool) -> str | None:
    """None when there is no resume to judge against (e.g. tests, no checkout)."""
    source = resume_source()
    if not source.exists():
        return None
    if len(description or "") < MIN_DESCRIPTION:
        return "❔ Not assessed yet (no full description stored); a check runs if this role is a priority"
    try:
        bank, master = _bank_and_master(source.stat().st_mtime)
        fit = assess(bank, Posting.from_text(title, description), master)
    except Exception:  # never block an alert on the resume engine
        return None
    follow = (
        "review + tailored resume follow"
        if important
        else "run a review-role check if you want one"
    )
    if fit.severity == "fits":
        return (
            f"✅ Your current resume fits ({fit.master_coverage:.0%} keyword coverage): apply as-is"
        )
    if fit.severity == "tune":
        return f"⚠️ Worth tuning: {fit.reasons[0]}; {follow}"
    return f"🛠️ Gap: {fit.reasons[-1]}; {follow}"
