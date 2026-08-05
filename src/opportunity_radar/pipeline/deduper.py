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
    """
    return repo.find_job_by_alias(session, alias_hashes_for(record))


def register(session: Session, job: JobRow, record: JobRecord) -> None:
    """Ensure all of this record's identities point at the job row."""
    repo.add_missing_aliases(session, job, alias_hashes_for(record), record)
