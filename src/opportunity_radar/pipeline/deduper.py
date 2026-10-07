"""Deduplication across sources, URLs, and location variants (spec §6.2, §14)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.tables import JobRow
from opportunity_radar.models.job import JobRecord
from opportunity_radar.pipeline.normalizer import alias_hashes_for


def find_existing(session: Session, record: JobRecord) -> JobRow | None:
    """Locate the stored job this record refers to, if any."""
    return find_existing_or_sibling(session, record)[0]


def find_existing_or_sibling(session: Session, record: JobRecord) -> tuple[JobRow | None, bool]:
    """Locate the stored job this record refers to.

    Returns ``(row, False)`` for a match, ``(None, False)`` for a genuinely
    unseen posting, and ``(None, True)`` when an alias pointed at a *sibling*
    requisition: same adapter, different concrete job ID.

    Match strength order: exact source identity, canonical apply URL,
    then company+title+locations fuzzy key. Titles alone never merge jobs —
    the fuzzy key includes company and the full location set.

    A match of ANY alias kind is rejected when both sides carry distinct
    concrete job IDs from the same adapter (AD-14, widened in AD-23): boards
    legitimately post separate requisitions with identical title, location
    or even apply URL, and merging them makes the shared row flip between
    the two postings on every scan. Aliases only bridge *different* sources.
    Rows merged before this rule existed still have stale identity/URL
    aliases; the sibling flag lets the scanner split them back out without
    treating the split-off posting as brand new.
    """
    found = repo.find_job_with_alias_kind(session, alias_hashes_for(record))
    if found is None:
        return None, False
    row, _kind = found
    if (
        row.source_adapter == record.source_adapter
        and row.source_job_id
        and record.source_job_id
        and row.source_job_id != record.source_job_id
    ):
        return None, True
    return row, False


def register(session: Session, job: JobRow, record: JobRecord) -> None:
    """Ensure all of this record's identities point at the job row."""
    repo.add_missing_aliases(session, job, alias_hashes_for(record), record)
