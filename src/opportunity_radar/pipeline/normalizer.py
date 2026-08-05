"""Normalize RawJob into the common JobRecord schema, fully enriched.

This is the single place where classification, season parsing, eligibility,
scoring, and explanations are applied — every adapter's output flows through
here so behavior is identical across sources.
"""

from __future__ import annotations

import re
from datetime import datetime

from opportunity_radar.config import AppSettings
from opportunity_radar.matching import eligibility as eligibility_mod
from opportunity_radar.matching import explanations, scorer, season_parser, title_classifier
from opportunity_radar.models.company import CompanySource
from opportunity_radar.models.job import JobRecord, RawJob
from opportunity_radar.utilities.dates import humanize_age, utcnow
from opportunity_radar.utilities.hashing import (
    content_hash,
    fuzzy_key_hash,
    identity_hash,
    url_hash,
)
from opportunity_radar.utilities.text import html_to_text, normalize_title
from opportunity_radar.utilities.urls import canonicalize_url

_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
_US_RE = re.compile(
    r"\b(united states|usa|u\.s\.a?\.?|remote \(us\)|us[\s\-]?remote|remote[\s\-]?us)\b"
    r"|, (al|ak|az|ar|ca|co|ct|de|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt"
    r"|ne|nv|nh|nj|nm|ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy)\b",
    re.IGNORECASE,
)


def _remote_type(raw: RawJob, description_text: str) -> str:
    if raw.remote_hint:
        return raw.remote_hint
    joined = " | ".join(raw.locations)
    if _REMOTE_RE.search(joined):
        return "remote"
    if _HYBRID_RE.search(joined) or _HYBRID_RE.search(description_text[:2000]):
        return "hybrid"
    if raw.locations:
        return "onsite"
    return "unknown"


def _country_codes(locations: list[str], remote_type: str) -> list[str]:
    joined = " | ".join(locations)
    codes: list[str] = []
    if _US_RE.search(joined):
        codes.append("US")
    return codes


def normalize(
    raw: RawJob,
    company: CompanySource,
    settings: AppSettings,
    *,
    first_seen_at: datetime | None = None,
    now: datetime | None = None,
) -> JobRecord:
    now = now or utcnow()
    first_seen = first_seen_at or now

    description_html = raw.description_html
    description_text = raw.description_text or html_to_text(description_html)
    title = normalize_title(raw.title)

    classification = title_classifier.classify(raw.title, description_text)
    season = season_parser.parse_season(raw.title, description_text)
    eligibility = eligibility_mod.evaluate(
        description_text,
        settings.profile.candidate,
        season=season.season,
        season_year=season.year,
    )

    remote_type = _remote_type(raw, description_text)
    apply_url = raw.apply_url or raw.url
    score = scorer.score_job(
        title=raw.title,
        description_text=description_text,
        locations=raw.locations,
        remote_type=remote_type,
        company_tier=company.tier,
        classification=classification,
        season=season,
        eligibility=eligibility,
        first_seen_at=first_seen,
        profile=settings.profile,
        scoring=settings.scoring,
        now=now,
    )
    reasons = explanations.build_reasons(
        company_tier=company.tier,
        classification=classification,
        season=season,
        eligibility=eligibility,
        score=score,
        freshness_label=humanize_age(first_seen, now),
    )
    risks = explanations.build_risks(eligibility, classification)

    return JobRecord(
        source_name=company.id,
        source_adapter=raw.source_adapter,
        source_job_id=raw.source_job_id,
        company_id=company.id,
        company_name=company.name,
        title=raw.title.strip(),
        normalized_title=title,
        description_html=description_html,
        description_text=description_text,
        department=raw.department,
        team=raw.team,
        primary_location=raw.locations[0] if raw.locations else None,
        all_locations=raw.locations,
        remote_type=remote_type,  # type: ignore[arg-type]
        country_codes=_country_codes(raw.locations, remote_type),
        employment_type=raw.employment_type,
        role_family=classification.role_family,
        seniority=classification.seniority,
        season=season.season,  # type: ignore[arg-type]
        season_year=season.year,
        start_date_min=season.start_min,
        start_date_max=season.start_max,
        duration_weeks=season.duration_weeks,
        full_time_required=eligibility.full_time_required,
        degree_levels=eligibility.degree_levels,
        graduation_min=eligibility.graduation_min,
        graduation_max=eligibility.graduation_max,
        requires_return_to_school=eligibility.requires_return_to_school,
        work_authorization_text=eligibility.work_authorization_text,
        citizenship_required=eligibility.citizenship_required,
        clearance_required=eligibility.clearance_required,
        compensation_min=raw.compensation_min,
        compensation_max=raw.compensation_max,
        compensation_period=raw.compensation_period,
        compensation_currency=raw.compensation_currency,
        posted_at=raw.posted_at,
        updated_at=raw.updated_at,
        first_seen_at=first_seen,
        last_seen_at=now,
        apply_url=apply_url,
        canonical_url=canonicalize_url(apply_url),
        source_url=raw.url,
        content_hash=content_hash(
            raw.title,
            description_text,
            raw.locations,
            extra_fields=[season.season, str(season.year or "")],
        ),
        identity_hash=identity_hash(raw.source_adapter, company.id, raw.source_job_id),
        status="active",
        match_score=0.0 if score.suppressed else score.total,
        score_components=score.components,
        match_reasons=reasons,
        risk_flags=risks,
        eligibility_level=eligibility.level,
        eligibility_text=eligibility.eligibility_sentence,
        season_confidence=season.confidence,
        eligibility_confidence=eligibility.confidence,
        is_early_career=classification.is_early_career,
    )


def alias_hashes_for(record: JobRecord) -> dict[str, str]:
    return {
        "identity": record.identity_hash,
        "url": url_hash(record.apply_url),
        "fuzzy": fuzzy_key_hash(record.company_id, record.normalized_title, record.all_locations),
    }
