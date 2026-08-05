"""Meaningful-change detection (spec §14.2).

The content hash already normalizes whitespace/HTML/tracking noise, so a
differing hash implies a real content difference; this module decides which
field-level changes are worth surfacing or alerting on.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from opportunity_radar.db.tables import JobRow
from opportunity_radar.models.job import JobRecord
from opportunity_radar.utilities.text import normalize_for_comparison

# Description similarity below this (0-100) counts as a substantial rewrite.
_DESCRIPTION_SIMILARITY_THRESHOLD = 85.0


@dataclass
class FieldChange:
    field: str
    old_value: str | None
    new_value: str | None
    meaningful: bool


def detect_changes(existing: JobRow, record: JobRecord) -> list[FieldChange]:
    """Compare a stored job with a freshly normalized record."""
    changes: list[FieldChange] = []

    if existing.content_hash == record.content_hash and existing.status == "active":
        return changes

    if existing.title != record.title:
        changes.append(FieldChange("title", existing.title, record.title, True))

    old_locations = set(existing.all_locations or [])
    new_locations = set(record.all_locations)
    if old_locations != new_locations:
        added = new_locations - old_locations
        expanded_reach = existing.remote_type != "remote" and record.remote_type == "remote"
        meaningful = bool(added) or expanded_reach
        changes.append(
            FieldChange(
                "locations",
                ", ".join(sorted(old_locations)) or None,
                ", ".join(sorted(new_locations)) or None,
                meaningful,
            )
        )

    if existing.remote_type != record.remote_type:
        changes.append(
            FieldChange(
                "remote_type",
                existing.remote_type,
                record.remote_type,
                record.remote_type == "remote",
            )
        )

    if (existing.season, existing.season_year) != (record.season, record.season_year):
        changes.append(
            FieldChange(
                "season",
                f"{existing.season} {existing.season_year or ''}".strip(),
                f"{record.season} {record.season_year or ''}".strip(),
                True,
            )
        )

    if existing.start_date_min != record.start_date_min:
        changes.append(
            FieldChange(
                "start_date",
                str(existing.start_date_min) if existing.start_date_min else None,
                str(record.start_date_min) if record.start_date_min else None,
                True,
            )
        )

    if existing.eligibility_level != record.eligibility_level:
        changes.append(
            FieldChange("eligibility", existing.eligibility_level, record.eligibility_level, True)
        )

    comp_added = existing.compensation_min is None and record.compensation_min is not None
    if comp_added:
        changes.append(
            FieldChange(
                "compensation",
                None,
                f"{record.compensation_min}-{record.compensation_max} "
                f"{record.compensation_currency or ''}/{record.compensation_period or ''}",
                True,
            )
        )

    if existing.status == "closed" and record.status == "active":
        changes.append(FieldChange("status", "closed", "active", True))

    old_desc = normalize_for_comparison(existing.description_text or "")
    new_desc = normalize_for_comparison(record.description_text or "")
    if old_desc != new_desc:
        similarity = fuzz.ratio(old_desc, new_desc) if old_desc and new_desc else 0.0
        changes.append(
            FieldChange(
                "description",
                None,  # full old text lives in the row; don't duplicate megabytes
                f"similarity {similarity:.0f}%",
                similarity < _DESCRIPTION_SIMILARITY_THRESHOLD,
            )
        )

    return changes


def has_meaningful_change(changes: list[FieldChange]) -> bool:
    return any(change.meaningful for change in changes)
