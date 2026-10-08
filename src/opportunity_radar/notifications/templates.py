"""Discord embed construction (spec §15).

All job-derived text is sanitized: mentions are neutralized both here and via
allowed_mentions in the payload, and lengths are capped to Discord limits.
"""

from __future__ import annotations

from typing import Any

from opportunity_radar.constants import DASHBOARD_HOST, DASHBOARD_PORT
from opportunity_radar.db.tables import JobRow
from opportunity_radar.utilities.dates import ensure_utc, humanize_age
from opportunity_radar.utilities.text import truncate

COLOR_HIGH = 0x2ECC71  # green
COLOR_MEDIUM = 0xF1C40F  # yellow
COLOR_LOW = 0x95A5A6  # gray
COLOR_ERROR = 0xE74C3C  # red

_EMBED_TITLE_LIMIT = 256
_FIELD_VALUE_LIMIT = 1024
_SECTION_LINE_LIMIT = 15
# Job lines run ~95 chars; 10 keep a summary field under Discord's 1024 limit.
SUMMARY_LINE_LIMIT = 10


def sanitize(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("@everyone", "@​everyone").replace("@here", "@​here").replace("<@", "<​@")


def score_color(score: float) -> int:
    if score >= 82:
        return COLOR_HIGH
    if score >= 60:
        return COLOR_MEDIUM
    return COLOR_LOW


def dashboard_job_url(job_id: int) -> str:
    return f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/jobs/{job_id}"


def _season_label(job: JobRow) -> str:
    if job.season == "unspecified":
        return "Not stated"
    label = job.season.replace("_", "-").title()
    if job.season_year:
        label = f"{label} {job.season_year}"
    if job.season_confidence < 0.9:
        label += f" (inferred, {job.season_confidence:.0%})"
    return label


def _keyword_line(job: JobRow) -> str | None:
    """Cross-reference the posting against your profile/resume skills."""
    from opportunity_radar.config import get_settings
    from opportunity_radar.insights.skills import keyword_fit

    text = f"{job.title}\n{job.description_text or ''}"
    if len(job.description_text or "") < 200:
        return None  # list-sourced rows have no real description to compare
    have, missing = keyword_fit(text, get_settings().profile)
    if not have and not missing:
        return None
    parts = []
    if have:
        parts.append("✅ " + ", ".join(have[:8]))
    if missing:
        parts.append("🔸 missing: " + ", ".join(missing[:6]))
    return truncate(sanitize(" · ".join(parts)), _FIELD_VALUE_LIMIT)


def build_job_embed(job: JobRow, *, header: str = "🚨 NEW HIGH-PRIORITY ROLE") -> dict[str, Any]:
    reasons = "\n".join(f"• {sanitize(reason)}" for reason in (job.match_reasons or [])[:8])
    risks = "\n".join(f"• {sanitize(risk)}" for risk in (job.risk_flags or [])[:8])

    fields: list[dict[str, Any]] = [
        {"name": "Company", "value": sanitize(job.company_name) or "—", "inline": True},
        {"name": "Score", "value": f"{job.match_score:.0f}/100", "inline": True},
        {"name": "Season", "value": _season_label(job), "inline": True},
        {
            "name": "Location",
            "value": sanitize(job.primary_location or job.remote_type or "unknown"),
            "inline": True,
        },
        {
            "name": "First seen",
            "value": humanize_age(ensure_utc(job.first_seen_at)),
            "inline": True,
        },
        {"name": "Source", "value": job.source_adapter, "inline": True},
    ]
    if job.posted_at is not None:
        fields.append(
            {
                "name": "Posted",
                "value": ensure_utc(job.posted_at).strftime("%Y-%m-%d"),  # type: ignore[union-attr]
                "inline": True,
            }
        )
    keyword_line = _keyword_line(job)
    if keyword_line:
        fields.append({"name": "Your keywords", "value": keyword_line, "inline": False})
    if reasons:
        fields.append(
            {
                "name": "Why it matches",
                "value": truncate(reasons, _FIELD_VALUE_LIMIT),
                "inline": False,
            }
        )
    if risks:
        fields.append(
            {"name": "Risks", "value": truncate(risks, _FIELD_VALUE_LIMIT), "inline": False}
        )
    fields.append(
        {
            "name": "Links",
            "value": f"[Apply directly]({job.apply_url}) · "
            f"[Dashboard]({dashboard_job_url(job.id)})",
            "inline": False,
        }
    )

    return {
        "content": sanitize(header),
        "embeds": [
            {
                "title": truncate(sanitize(job.title), _EMBED_TITLE_LIMIT),
                "url": job.apply_url,
                "color": score_color(job.match_score),
                "fields": fields,
                "timestamp": (
                    ensure_utc(job.first_seen_at).isoformat()  # type: ignore[union-attr]
                    if job.first_seen_at
                    else None
                ),
                "footer": {"text": f"Opportunity Radar · {job.company_id}"},
            }
        ],
        "allowed_mentions": {"parse": []},
    }


_EMBED_TOTAL_LIMIT = 5600  # Discord caps an embed at 6000 chars across all parts.


def _chunked_fields(name: str, lines: list[str]) -> list[dict[str, Any]]:
    """Split lines into as many fields as needed so no line is cut mid-link.

    A single job line (long Workday apply URL) can approach 200 chars, so a
    fixed line count per field would silently truncate; chunk by size instead.
    """
    fields: list[dict[str, Any]] = []
    current: list[str] = []
    size = 0
    for line in lines:
        clean = truncate(sanitize(line), _FIELD_VALUE_LIMIT)
        if current and size + len(clean) + 1 > _FIELD_VALUE_LIMIT:
            fields.append({"name": name, "value": "\n".join(current), "inline": False})
            name = "(cont.)"
            current, size = [], 0
        current.append(clean)
        size += len(clean) + 1
    if current:
        fields.append({"name": name, "value": "\n".join(current), "inline": False})
    return fields


def _fit_embed(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    total = 0
    for field in fields:
        total += len(field["name"]) + len(field["value"])
        if total > _EMBED_TOTAL_LIMIT or len(kept) >= 25:
            kept.append({"name": "…", "value": "_more on the dashboard_", "inline": False})
            break
        kept.append(field)
    return kept


def build_digest_payload(
    title: str, sections: dict[str, list[str]], color: int = COLOR_MEDIUM
) -> dict[str, Any] | None:
    fields: list[dict[str, Any]] = []
    for section, lines in sections.items():
        if not lines:
            continue
        shown = list(lines[:_SECTION_LINE_LIMIT])
        if len(lines) > _SECTION_LINE_LIMIT:
            shown.append(f"… and {len(lines) - _SECTION_LINE_LIMIT} more")
        fields.extend(_chunked_fields(section, shown))
    if not fields:
        return None
    return {
        "embeds": [{"title": sanitize(title), "color": color, "fields": _fit_embed(fields)}],
        "allowed_mentions": {"parse": []},
    }


def build_quiet_digest_payload(title: str, detail: str) -> dict[str, Any]:
    """Compact 'nothing new' notice so silence is distinguishable from breakage."""
    return {
        "embeds": [
            {
                "title": sanitize(title),
                "description": sanitize(detail),
                "color": COLOR_LOW,
            }
        ],
        "allowed_mentions": {"parse": []},
    }


def build_baseline_summary(
    total: int, by_source: dict[str, int], by_score_band: dict[str, int]
) -> dict[str, Any]:
    source_lines = [f"• {name}: {count}" for name, count in sorted(by_source.items())]
    band_lines = [f"• {band}: {count}" for band, count in by_score_band.items()]
    return {
        "embeds": [
            {
                "title": "📊 Baseline import complete",
                "description": f"Imported **{total}** active listings. "
                "No individual alerts were sent (baseline mode).",
                "color": COLOR_LOW,
                "fields": [
                    {
                        "name": "By score",
                        "value": truncate("\n".join(band_lines) or "—", _FIELD_VALUE_LIMIT),
                        "inline": True,
                    },
                    {
                        "name": "By source",
                        "value": truncate("\n".join(source_lines) or "—", _FIELD_VALUE_LIMIT),
                        "inline": True,
                    },
                ],
            }
        ],
        "allowed_mentions": {"parse": []},
    }


def build_new_sources_summary(
    company_names: list[str], jobs: list[JobRow], hidden_count: int
) -> dict[str, Any]:
    """One embed when newly added sources are imported for the first time.

    Their whole backlog is 'new' to the database, so per-job alerts would be
    a flood; instead the best currently-open matches are listed once.
    """
    lines = [
        f"**{job.match_score:.0f}** · [{sanitize(job.title)}]({job.apply_url}) — "
        f"{sanitize(job.company_name)} ({sanitize(job.primary_location or job.remote_type)})"
        for job in jobs[:SUMMARY_LINE_LIMIT]
    ]
    if not lines:
        lines = ["_No early-career software roles open right now._"]
    if hidden_count > 0:
        lines.append(f"_+ {hidden_count} more on the dashboard_")
    names = ", ".join(sanitize(n) for n in company_names[:20])
    if len(company_names) > 20:
        names += f" … (+{len(company_names) - 20})"
    return {
        "embeds": [
            {
                "title": f"📡 {len(company_names)} new source(s) imported",
                "description": truncate(names, 2000),
                "color": COLOR_MEDIUM,
                "fields": _fit_embed(
                    _chunked_fields("Best open matches (not alerted individually)", lines)
                ),
            }
        ],
        "allowed_mentions": {"parse": []},
    }


def build_failure_payload(subject: str, detail: str) -> dict[str, Any]:
    return {
        "embeds": [
            {
                "title": f"⚠️ {sanitize(subject)}",
                "description": truncate(sanitize(detail), 2000),
                "color": COLOR_ERROR,
            }
        ],
        "allowed_mentions": {"parse": []},
    }


def build_test_payload() -> dict[str, Any]:
    return {
        "content": "✅ Opportunity Radar is connected to this channel.",
        "allowed_mentions": {"parse": []},
    }


_DESCRIPTION_LIMIT = 4000


def markdown_chunks(markdown: str, limit: int = _DESCRIPTION_LIMIT) -> list[str]:
    """Split markdown on line boundaries into Discord-sized description chunks.

    Discord embeds render bold/links/lists but not headings or tables, so
    headings become bold lines and table pipes are kept readable.
    """
    lines = []
    for line in sanitize(markdown).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            lines.append(f"**{stripped.lstrip('#').strip()}**")
        elif set(stripped) <= {"|", "-", ":", " "} and stripped:
            continue  # table separator row
        else:
            lines.append(line)
    chunks: list[str] = []
    current = ""
    for line in lines:
        piece = line[:limit]
        if len(current) + len(piece) + 1 > limit:
            chunks.append(current.rstrip())
            current = ""
        current += piece + "\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or ["(empty report)"]


def build_resume_message(job: JobRow, summary: str, ats_line: str) -> dict[str, Any]:
    """Companion message for a tailored resume attachment."""
    return {
        "content": sanitize(f"📄 Tailored resume for **{job.title}** at **{job.company_name}**"),
        "embeds": [
            {
                "title": truncate(sanitize(job.title), _EMBED_TITLE_LIMIT),
                "url": job.apply_url,
                "color": COLOR_HIGH,
                "description": truncate(sanitize(f"{summary}\n{ats_line}"), 2000),
                "footer": {"text": "Attached PDF uses only content from your resume"},
            }
        ],
        "allowed_mentions": {"parse": []},
    }
