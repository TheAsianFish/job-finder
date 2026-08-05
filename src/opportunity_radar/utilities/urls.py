"""URL canonicalization used for identity hashing and deduplication."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

# Query parameters that never change the job identity.
TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "ref",
        "referrer",
        "src",
        "source",
        "lever-source",
        "gh_src",
        "ashby_jid_src",
        "trackingtag",
        "icid",
        "mc_cid",
        "mc_eid",
    }
)

# Params that DO affect identity on ATS-hosted pages (job ids).
_IDENTITY_PARAMS = frozenset({"gh_jid", "lever-id", "ashby_jid", "jobid", "job_id", "jid", "id"})


def canonicalize_url(url: str) -> str:
    """Produce a stable canonical form of a URL for hashing and comparison."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    # Drop default ports.
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    kept_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    kept_query.sort()
    query = urlencode(kept_query)
    return urlunparse((scheme, netloc, path, "", query, ""))


def absolutize(base_url: str, maybe_relative: str) -> str:
    """Resolve a possibly-relative URL against a base page URL."""
    if not maybe_relative:
        return base_url
    return urljoin(base_url, maybe_relative.strip())


def domain_of(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc.split(":")[0]


def has_identity_param(url: str) -> bool:
    return any(k.lower() in _IDENTITY_PARAMS for k, _ in parse_qsl(urlparse(url).query))
