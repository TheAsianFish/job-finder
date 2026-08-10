"""Deduplication across sources, URLs, and location variants (spec §6.2, §14)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from opportunity_radar.db import repositories as repo
from opportunity_radar.db.tables import JobRow
from opportunity_radar.models.job import JobRecord
from opportunity_radar.pipeline.normalizer import alias_hashes_for


def find_existing(session: Session, record: JobRecord) -> JobRow | None:
    """Locate the stored job this record refers to, if any.

    Match strength order: exact source identity, canonical apply URL,
    then company+title+locations fuzzy key. Titles alone never merge jobs —
    the fuzzy key includes company and the full location set.

    A fuzzy match is rejected when both sides carry distinct concrete job IDs
    from the same adapter: boards like Greenhouse legitimately post separate
    requisitions with identical title and location (e.g. shift variants), and
    merging them makes their descriptions flip-flop on every scan. The fuzzy
    key only bridges records from *different* sources for the same posting.
    """
    found = repo.find_job_with_alias_kind(session, alias_hashes_for(record))
    if found is None:
        return None
    row, kind = found
    if (
        kind == "fuzzy"
        and row.source_adapter == record.source_adapter
        and row.source_job_id
        and record.source_job_id
        and row.source_job_id != record.source_job_id
    ):
        return None
    return row


def register(session: Session, job: JobRow, record: JobRecord) -> None:
    """Ensure all of this record's identities point at the job row."""
    repo.add_missing_aliases(session, job, alias_hashes_for(record), record)
