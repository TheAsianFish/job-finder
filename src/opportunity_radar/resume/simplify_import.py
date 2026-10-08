"""Import the Simplify Job Tracker's "Export CSV" into the applications log.

Simplify's extension records every application you submit through it; its
tracker exports a CSV (Job Tracker -> Export CSV). Column names are matched
flexibly (company / position title / status / date / link) so small format
changes don't break the import. Rows still in a "saved"/"wishlist" stage are
skipped: they are not applications.
"""

from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

from opportunity_radar.resume.ledger import Application

_COLUMNS = {
    "company": ("company", "company name", "employer", "organization"),
    "title": ("position title", "position", "title", "job title", "role"),
    "status": ("status", "stage", "application status"),
    "applied": (
        "date applied",
        "applied date",
        "applied on",
        "applied",
        "date",
        "created",
        "created at",
    ),
    "url": (
        "url",
        "link",
        "job url",
        "job link",
        "posting url",
        "application link",
        "job posting url",
    ),
    "notes": ("notes", "note", "comments"),
}
_STATUS = [
    (r"offer|accepted", "offer"),
    (r"reject|declin|not selected|unsuccessful", "rejected"),
    (r"withdr|archiv|closed", "withdrawn"),
    (r"interview|onsite|final|superday|phone|recruiter", "interview"),
    (r"\boa\b|assessment|hackerrank|codesignal|coding test|screen", "oa"),
    (r"appl|submitted|in review|under review|pending", "applied"),
]
_NOT_APPLIED = re.compile(r"saved|wish|bookmark|interested|to apply|draft", re.IGNORECASE)


def _pick(header: list[str], field: str) -> str | None:
    lowered = {h.strip().lower(): h for h in header}
    for candidate in _COLUMNS[field]:
        if candidate in lowered:
            return lowered[candidate]
    for h in header:
        if any(candidate in h.strip().lower() for candidate in _COLUMNS[field][:2]):
            return h
    return None


def _status(raw: str) -> str | None:
    text = (raw or "applied").strip().lower()
    if _NOT_APPLIED.search(text):
        return None
    for pattern, status in _STATUS:
        if re.search(pattern, text):
            return status
    return "applied"


def _date(raw: str) -> str:
    text = (raw or "").strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return (
                datetime.strptime(text[: len(text) if "T" not in fmt else 19], fmt)
                .date()
                .isoformat()
            )
        except ValueError:
            continue
    return date.today().isoformat()


def parse_simplify_csv(path: Path) -> tuple[list[Application], int]:
    """Returns (applications, rows skipped as not-yet-applied/unusable)."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = list(reader.fieldnames or [])
        columns = {field: _pick(header, field) for field in _COLUMNS}
        if not columns["company"] or not columns["title"]:
            raise ValueError(
                f"{path.name}: need company and position columns, found {', '.join(header)}"
            )
        apps: list[Application] = []
        skipped = 0
        for row in reader:

            def get(field: str, row: dict = row) -> str:
                column = columns[field]
                return (row.get(column) or "").strip() if column else ""

            company, title = get("company"), get("title")
            status = _status(get("status"))
            if not company or not title or status is None:
                skipped += 1
                continue
            apps.append(
                Application(
                    url=get("url"),
                    company=company,
                    title=title,
                    status=status,
                    applied=_date(get("applied")),
                    notes=get("notes") or None,
                )
            )
    return apps, skipped
