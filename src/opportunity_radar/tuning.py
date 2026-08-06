"""Feedback-driven parameter tuning.

Learns from what Patrick actually does with jobs (save / apply / dismiss) and
nudges scoring parameters — deterministically, in small bounded steps, with
every change explained and logged. This is intentionally NOT a black box:

- minimum sample sizes before any change
- ±1 weight / ±2 threshold nudges per run, hard floors and caps
- changes write to config/scoring.yaml (local, gitignored) with an audit trail
- company-tier changes are only ever *suggested*, never auto-applied

Run manually with `opportunity-radar tune [--apply]`; the daemon can run it
weekly when `scheduler.auto_tune: true`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from opportunity_radar.config import ScoringConfig, config_dir, get_settings
from opportunity_radar.db.engine import session_scope
from opportunity_radar.db.tables import ApplicationRow, JobRow
from opportunity_radar.utilities.dates import utcnow

logger = structlog.get_logger(__name__)

# Feedback weights: how strongly each action counts.
_POSITIVE_WEIGHTS = {"saved": 1, "applied": 2, "oa": 3, "interview": 3, "offer": 3}
_NEGATIVE_STATUSES = {"dismissed"}

# Bounds that tuning can never exceed.
_FAMILY_WEIGHT_CAP = 20.0
_FAMILY_WEIGHT_FLOOR = 4.0
_IMMEDIATE_CAP = 92
_IMMEDIATE_FLOOR = 75
_MIN_FAMILY_EVENTS = 3
_MIN_THRESHOLD_EVENTS = 5


@dataclass
class Adjustment:
    key: str
    old: float
    new: float
    reason: str


@dataclass
class TuneReport:
    adjustments: list[Adjustment] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    feedback_events: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.adjustments)


@dataclass
class FeedbackStats:
    family_pos: dict[str, int] = field(default_factory=dict)
    family_neg: dict[str, int] = field(default_factory=dict)
    company_pos: dict[str, int] = field(default_factory=dict)
    company_neg: dict[str, int] = field(default_factory=dict)
    alerted_pos: int = 0  # jobs that immediate-alerted and were saved/applied
    alerted_neg: int = 0  # jobs that immediate-alerted and were dismissed
    digest_band_pos: int = 0  # digest-tier jobs (60..immediate) saved/applied
    total_events: int = 0


def gather_feedback(session: Session) -> FeedbackStats:
    stats = FeedbackStats()
    immediate_min = get_settings().scoring.alerts.immediate_min_score
    digest_min = get_settings().scoring.alerts.digest_min_score

    rows = session.execute(
        select(ApplicationRow, JobRow).join(JobRow, JobRow.id == ApplicationRow.job_id)
    ).all()
    for application, job in rows:
        status = application.status
        positive = _POSITIVE_WEIGHTS.get(status, 0)
        negative = 1 if status in _NEGATIVE_STATUSES else 0
        if not positive and not negative:
            continue
        stats.total_events += 1
        family = job.role_family or "general_swe"
        if positive:
            stats.family_pos[family] = stats.family_pos.get(family, 0) + positive
            stats.company_pos[job.company_id] = stats.company_pos.get(job.company_id, 0) + positive
        if negative:
            stats.family_neg[family] = stats.family_neg.get(family, 0) + negative
            stats.company_neg[job.company_id] = stats.company_neg.get(job.company_id, 0) + negative
        if job.alerted_at is not None:
            if positive:
                stats.alerted_pos += 1
            elif negative:
                stats.alerted_neg += 1
        elif digest_min <= job.match_score < immediate_min and positive:
            stats.digest_band_pos += 1
    return stats


def compute_adjustments(stats: FeedbackStats, scoring: ScoringConfig) -> TuneReport:
    """Pure function: feedback stats + current config -> bounded adjustments."""
    report = TuneReport(feedback_events=stats.total_events)

    # --- Role-family weights ------------------------------------------------
    families = set(stats.family_pos) | set(stats.family_neg)
    for family in sorted(families):
        pos = stats.family_pos.get(family, 0)
        neg = stats.family_neg.get(family, 0)
        if pos + neg < _MIN_FAMILY_EVENTS:
            continue
        current = scoring.role_family_weights.get(family)
        if current is None:
            continue
        net = pos - neg
        if net >= 2 and current < _FAMILY_WEIGHT_CAP:
            report.adjustments.append(
                Adjustment(
                    key=f"role_family_weights.{family}",
                    old=current,
                    new=min(current + 1.0, _FAMILY_WEIGHT_CAP),
                    reason=f"{pos} positive vs {neg} dismiss signals for {family} roles",
                )
            )
        elif net <= -2 and current > _FAMILY_WEIGHT_FLOOR:
            report.adjustments.append(
                Adjustment(
                    key=f"role_family_weights.{family}",
                    old=current,
                    new=max(current - 1.0, _FAMILY_WEIGHT_FLOOR),
                    reason=f"{neg} dismissals vs {pos} positive signals for {family} roles",
                )
            )

    # --- Immediate-alert threshold -------------------------------------------
    immediate = scoring.alerts.immediate_min_score
    alerted_total = stats.alerted_pos + stats.alerted_neg
    if alerted_total >= _MIN_THRESHOLD_EVENTS and stats.alerted_neg / alerted_total >= 0.8:
        if immediate < _IMMEDIATE_CAP:
            report.adjustments.append(
                Adjustment(
                    key="alerts.immediate_min_score",
                    old=immediate,
                    new=min(immediate + 2, _IMMEDIATE_CAP),
                    reason=f"{stats.alerted_neg}/{alerted_total} immediate alerts were dismissed — raising the bar",
                )
            )
    elif stats.digest_band_pos >= _MIN_THRESHOLD_EVENTS and immediate > _IMMEDIATE_FLOOR:
        report.adjustments.append(
            Adjustment(
                key="alerts.immediate_min_score",
                old=immediate,
                new=max(immediate - 2, _IMMEDIATE_FLOOR),
                reason=f"{stats.digest_band_pos} digest-tier jobs were saved/applied — you want these sooner",
            )
        )

    # --- Company suggestions (never auto-applied) -----------------------------
    for company_id in sorted(set(stats.company_neg)):
        neg = stats.company_neg.get(company_id, 0)
        pos = stats.company_pos.get(company_id, 0)
        if neg >= 3 and pos == 0:
            report.suggestions.append(
                f"{company_id}: {neg} dismissals, 0 saves — consider a lower tier or "
                f"`opportunity-radar companies disable {company_id}`"
            )
    return report


def _scoring_yaml_path() -> Path:
    return config_dir() / "scoring.yaml"


def apply_adjustments(report: TuneReport, scoring: ScoringConfig) -> Path:
    """Write adjusted values to config/scoring.yaml (creating it if needed)."""
    path = _scoring_yaml_path()
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    else:
        data = {}
    # Ensure current effective values are present before nudging.
    data.setdefault("role_family_weights", dict(scoring.role_family_weights))
    data.setdefault("alerts", scoring.alerts.model_dump())
    data.setdefault("company_tier_points", dict(scoring.company_tier_points))
    data.setdefault(
        "target_windows",
        [
            {"name": w.name, "start": w.start, "end": w.end, "priority": w.priority}
            for w in scoring.target_windows
        ],
    )

    for adjustment in report.adjustments:
        section, _, key = adjustment.key.partition(".")
        if section == "role_family_weights":
            data["role_family_weights"][key] = adjustment.new
        elif section == "alerts":
            data["alerts"][key] = (
                int(adjustment.new) if adjustment.new == int(adjustment.new) else adjustment.new
            )

    history = data.setdefault("tuning_history", [])
    history.append(
        {
            "at": utcnow().isoformat(),
            "changes": [
                {"key": a.key, "old": a.old, "new": a.new, "reason": a.reason}
                for a in report.adjustments
            ],
        }
    )
    path.write_text(
        "# Managed by `opportunity-radar tune` — safe to edit by hand.\n"
        "# tuning_history is an audit log of automatic adjustments.\n"
        + yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    logger.info("tuning_applied", changes=len(report.adjustments), path=str(path))
    return path


def run_tune(apply: bool = False, db_url: str | None = None) -> TuneReport:
    settings = get_settings()
    with session_scope(db_url) as session:
        stats = gather_feedback(session)
    report = compute_adjustments(stats, settings.scoring)
    if apply and report.has_changes:
        apply_adjustments(report, settings.scoring)
        from opportunity_radar.config import load_settings

        load_settings(reload=True)
    return report
