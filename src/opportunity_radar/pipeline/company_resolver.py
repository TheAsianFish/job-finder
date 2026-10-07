"""Map a secondary source's free-text company name onto a company.

Simplify-style lists name the employer ("Google", "Citadel Securities",
"Susquehanna International Group (SIG)"). Resolution order:

1. A registry entry that owns the posting's apply link (same Greenhouse /
   Lever / Ashby board token, Workday host or SmartRecruiters id) — the
   strongest signal, immune to naming differences.
2. A registry entry whose name or id normalises to the same key (plus a
   small alias table for names that differ in shape, not meaning).
3. A multi-word registry name that is a word-prefix of the listed name
   ("AQR Capital" for "AQR Capital Management").
4. Otherwise a synthetic ``CompanySource`` (``enabled: false``, the source's
   default tier) so the posting can be stored, scored and alerted on.

``should_ingest`` says whether the secondary source should store the
posting at all: when the registry already scans that employer directly,
the employer board is the source of truth (spec §28 "employer pages remain
primary") and the list entry is skipped rather than duplicated.
"""

from __future__ import annotations

import re

from opportunity_radar.discovery.ats_fingerprint import detect_from_url
from opportunity_radar.models.company import CompanySource

_PAREN_RE = re.compile(r"\([^)]*\)")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TRAILING_NOISE = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "the"}

# Normalised list name -> registry id, for names that differ in shape only.
ALIASES: dict[str, str] = {
    "citadelsecurities": "citadel",
    "susquehannainternationalgroup": "sig",
    "susquehanna": "sig",
    "weightsbiases": "wandb",
    "cursor": "anysphere",
    "googledeepmind": "google",
    "deepmind": "google",
    "aws": "amazon",
    "amazonwebservices": "amazon",
}


def _tokens(name: str) -> list[str]:
    tokens = _TOKEN_RE.findall(_PAREN_RE.sub(" ", name.lower()).replace("&", " "))
    while len(tokens) > 1 and tokens[-1] in _TRAILING_NOISE:
        tokens.pop()
    return tokens


def _board_keys(company: CompanySource) -> list[tuple[str, str]]:
    cfg = company.adapter_config
    keys: list[tuple[str, str]] = []
    for adapter, field in (
        ("greenhouse", "board_token"),
        ("lever", "site"),
        ("ashby", "job_board_name"),
        ("smartrecruiters", "company"),
        ("workday", "host"),
    ):
        value = cfg.get(field)
        if value and company.adapter in (adapter, "auto"):
            keys.append((adapter, str(value).lower()))
    if company.adapter == "workday" and cfg.get("host"):
        keys.append(("workday", str(cfg["host"]).split(".")[0].lower()))  # tenant
    for url in company.career_urls:
        fingerprint = detect_from_url(url)
        if fingerprint is not None:
            keys.extend((fingerprint.adapter, str(v).lower()) for v in fingerprint.config.values())
    return keys


def normalize_name(name: str) -> str:
    return "".join(_tokens(name))


def slugify(name: str) -> str:
    return "-".join(_tokens(name)) or "unknown"


class CompanyResolver:
    def __init__(self, registry: list[CompanySource], default_tier: str, source_id: str) -> None:
        self._default_tier = default_tier
        self._source_id = source_id
        self._index: dict[str, CompanySource] = {}
        self._prefixes: list[tuple[list[str], CompanySource]] = []
        self._boards: dict[tuple[str, str], CompanySource] = {}
        by_id = {c.id: c for c in registry}
        for company in registry:
            for key in (normalize_name(company.name), normalize_name(company.id)):
                if key:
                    self._index.setdefault(key, company)
            tokens = _tokens(company.name)
            if len(tokens) >= 2:
                self._prefixes.append((tokens, company))
            for board_key in _board_keys(company):
                self._boards.setdefault(board_key, company)
        for alias, company_id in ALIASES.items():
            if company_id in by_id:
                self._index.setdefault(alias, by_id[company_id])
        self._synthetic: dict[str, CompanySource] = {}

    def resolve(self, name: str, url: str | None = None) -> CompanySource:
        if url:
            fingerprint = detect_from_url(url)
            if fingerprint is not None:
                for value in fingerprint.config.values():
                    owner = self._boards.get((fingerprint.adapter, str(value).lower()))
                    if owner is not None:
                        return owner
        key = normalize_name(name)
        found = self._index.get(key)
        if found is not None:
            return found
        tokens = _tokens(name)
        for prefix, company in self._prefixes:
            if tokens[: len(prefix)] == prefix:
                return company
        slug = slugify(name)
        if slug not in self._synthetic:
            self._synthetic[slug] = CompanySource(
                id=slug,
                name=name.strip() or slug,
                tier=self._default_tier,  # type: ignore[arg-type]
                enabled=False,
                adapter="auto",
                tags=["via-secondary"],
                notes=f"Discovered via {self._source_id}; not scanned directly.",
            )
        return self._synthetic[slug]

    @staticmethod
    def should_ingest(company: CompanySource) -> bool:
        """Skip employers the registry already scans at the source."""
        return not company.enabled
