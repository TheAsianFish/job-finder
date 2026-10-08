"""Single source of truth for "may this role notify at all?".

Used by the scanner (immediate/digest classification, changed-job digest)
and by the digest builder, so both always agree.
"""

from __future__ import annotations

from datetime import date

from opportunity_radar.config import AppSettings
from opportunity_radar.matching.scorer import notify_eligible
from opportunity_radar.matching.title_classifier import classify


def role_notifiable(
    *,
    title: str,
    description: str,
    eligibility_level: str,
    start_min: date | None,
    settings: AppSettings,
) -> bool:
    candidate = settings.profile.candidate
    earliest = candidate.earliest_graduation or candidate.expected_graduation
    return notify_eligible(
        title=title,
        description=description or "",
        early_career_title=classify(title or "", "").is_early_career,
        eligibility_level=eligibility_level,
        start_min=start_min,
        preferences=settings.profile.preferences,
        earliest_class_year=earliest.year,
    )
