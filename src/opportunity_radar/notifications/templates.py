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


def build_digest_payload(
    title: str, sections: dict[str, list[str]], color: int = COLOR_MEDIUM
) -> dict[str, Any] | None:
    fields = []
    for section, lines in sections.items():
        if not lines:
            continue
        value = "\n".join(sanitize(line) for line in lines[:10])
        if len(lines) > 10:
            value += f"\n… and {len(lines) - 10} more"
        fields.append(
            {"name": section, "value": truncate(value, _FIELD_VALUE_LIMIT), "inline": False}
        )
    if not fields:
        return None
    return {
        "embeds": [{"title": sanitize(title), "color": color, "fields": fields}],
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
