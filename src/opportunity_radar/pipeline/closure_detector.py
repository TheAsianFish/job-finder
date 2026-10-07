"""Closure detection with failure safety (spec §14.3, §22).

A job is closed only after CLOSURE_MISS_THRESHOLD consecutive *successful*
scans fail to return it. Failed scans never advance the counter. A source
that drops from many jobs to zero in one scan is treated as an anomaly:
nothing is closed, a warning is logged.
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from opportunity_radar.constants import CLOSURE_MISS_THRESHOLD
from opportunity_radar.db import repositories as repo
from opportunity_radar.utilities.dates import utcnow

logger = structlog.get_logger(__name__)

# If a source had at least this many jobs and suddenly reports zero, suspect
# an outage/migration instead of a mass closure.
_ZERO_DROP_ANOMALY_MIN = 5


def process_closures(
    session: Session,
    source_name: str,
    seen_identity_hashes: set[str],
    jobs_found: int,
    previous_job_count: int | None,
) -> int:
    """Update miss counters after a SUCCESSFUL scan; close jobs past threshold.

    Returns the number of jobs newly closed.
    """
    if (
        jobs_found == 0
        and previous_job_count is not None
        and previous_job_count >= _ZERO_DROP_ANOMALY_MIN
    ):
        logger.warning(
            "zero_job_anomaly",
            source_name=source_name,
            previous_job_count=previous_job_count,
            action="skipping closure processing",
        )
        return 0

    # Scoped by source, not company: a secondary source (Simplify) stores
    # postings under many companies, and a company can be fed by more than
    # one source — each source only closes what it itself reported.
    closed = 0
    for job in repo.active_jobs_for_source(session, source_name):
        if job.identity_hash in seen_identity_hashes:
            if job.consecutive_misses:
                job.consecutive_misses = 0
            continue
        job.consecutive_misses += 1
        if job.consecutive_misses >= CLOSURE_MISS_THRESHOLD:
            job.status = "closed"
            job.closed_at = utcnow()
            repo.record_change(session, job.id, "status", "active", "closed", meaningful=True)
            closed += 1
            logger.info(
                "job_closed",
                company_id=job.company_id,
                source=source_name,
                job_id=job.id,
                title=job.title,
                misses=job.consecutive_misses,
            )
    return closed
