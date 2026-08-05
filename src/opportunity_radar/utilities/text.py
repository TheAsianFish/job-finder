"""Text normalization helpers.

All scraped content is untrusted: these helpers never execute or interpret it,
they only normalize whitespace, strip markup, and produce stable comparison keys.
"""

from __future__ import annotations

import html as html_module
import re
import unicodedata

from bs4 import BeautifulSoup

_WHITESPACE_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(value: str | None) -> str:
    """Convert HTML to readable plain text. Safe on plain text input."""
    if not value:
        return ""
    # Fast path: no tags present, just unescape entities.
    if "<" not in value:
        return normalize_whitespace(html_module.unescape(value))
    soup = BeautifulSoup(value, "lxml")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    text = soup.get_text(separator="\n")
    lines = [normalize_whitespace(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return _WHITESPACE_RE.sub(" ", value).strip()


def normalize_for_comparison(value: str | None) -> str:
    """Lowercased, accent-stripped, punctuation-collapsed key for fuzzy matching."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^\w\s]", " ", value)
    return normalize_whitespace(value)


def normalize_title(title: str | None) -> str:
    """Normalize a job title for identity/display purposes."""
    text = normalize_whitespace(title)
    # Collapse common separators to a single form.
    text = re.sub(r"\s*[–—|/]\s*", " - ", text)  # noqa: RUF001
    return text


def truncate(value: str, limit: int, suffix: str = "…") -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - len(suffix))].rstrip() + suffix


def strip_tracking_noise(text: str) -> str:
    """Remove zero-width and control characters that create false content diffs."""
    return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in ("\n", "\t"))
