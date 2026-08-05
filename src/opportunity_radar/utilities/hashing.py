"""Identity and content hashing.

Identity keys (spec §6.2):
1. source_adapter + company + source_job_id  (primary identity)
2. canonicalized apply URL
3. normalized company + title + location     (fuzzy fallback key)
4. content fingerprint                       (change detection)
"""

from __future__ import annotations

import hashlib

from opportunity_radar.utilities.text import normalize_for_comparison, strip_tracking_noise
from opportunity_radar.utilities.urls import canonicalize_url


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identity_hash(source_adapter: str, company_id: str, source_job_id: str) -> str:
    return _sha256(f"id|{source_adapter}|{company_id}|{source_job_id}")


def url_hash(apply_url: str) -> str:
    return _sha256(f"url|{canonicalize_url(apply_url)}")


def fuzzy_key_hash(company_id: str, title: str, locations: list[str]) -> str:
    normalized_locations = sorted(normalize_for_comparison(loc) for loc in locations if loc)
    key = "|".join(
        [
            "fuzzy",
            normalize_for_comparison(company_id),
            normalize_for_comparison(title),
            *normalized_locations,
        ]
    )
    return _sha256(key)


def content_hash(
    title: str,
    description_text: str,
    locations: list[str],
    extra_fields: list[str] | None = None,
) -> str:
    """Fingerprint of the *meaningful* content of a job posting.

    Uses normalized text so whitespace, HTML reformatting, and tracking noise
    do not register as changes (spec §14.2).
    """
    parts = [
        normalize_for_comparison(title),
        normalize_for_comparison(strip_tracking_noise(description_text or "")),
        *sorted(normalize_for_comparison(loc) for loc in locations if loc),
    ]
    if extra_fields:
        parts.extend(normalize_for_comparison(field) for field in extra_fields)
    return _sha256("content|" + "|".join(parts))
