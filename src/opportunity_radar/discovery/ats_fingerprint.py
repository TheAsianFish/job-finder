"""ATS detection from URLs and HTML fingerprints (spec §2.1, §8.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_URL_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "greenhouse",
        re.compile(r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)"),
        "board_token",
    ),
    ("greenhouse", re.compile(r"job-boards\.greenhouse\.io/([\w-]+)"), "board_token"),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)"), "board_token"),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w-]+)"), "site"),
    ("lever", re.compile(r"api\.(?:eu\.)?lever\.co/v0/postings/([\w-]+)"), "site"),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)"), "job_board_name"),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([\w.%-]+)"), "job_board_name"),
    ("workday", re.compile(r"([\w-]+)\.(?:wd\d+\.)?myworkdayjobs\.com"), "tenant"),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)"), "company"),
    ("icims", re.compile(r"([\w-]+)\.icims\.com"), "tenant"),
    ("eightfold", re.compile(r"([\w-]+)\.eightfold\.ai"), "tenant"),
    ("successfactors", re.compile(r"career[\w-]*\.successfactors\.com"), "tenant"),
    ("taleo", re.compile(r"([\w-]+)\.taleo\.net"), "tenant"),
]

_HTML_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "greenhouse",
        re.compile(r"gh_jid|boards\.greenhouse\.io|greenhouse\.io/embed", re.IGNORECASE),
    ),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co", re.IGNORECASE)),
    ("ashby", re.compile(r"ashby_jid|jobs\.ashbyhq\.com|ashbyhq\.com/posting-api", re.IGNORECASE)),
    ("workday", re.compile(r"myworkdayjobs\.com", re.IGNORECASE)),
    ("smartrecruiters", re.compile(r"smartrecruiters\.com", re.IGNORECASE)),
]


@dataclass
class FingerprintResult:
    adapter: str
    config: dict[str, Any] = field(default_factory=dict)
    evidence: str = ""


def detect_from_url(url: str) -> FingerprintResult | None:
    for adapter, pattern, config_key in _URL_PATTERNS:
        match = pattern.search(url)
        if match:
            config: dict[str, Any] = {}
            if match.groups() and match.group(1):
                config[config_key] = match.group(1)
            if adapter == "lever" and ".eu." in match.group(0):
                config["region"] = "eu"
            return FingerprintResult(adapter=adapter, config=config, evidence=url)
    return None


def detect_from_html(html: str) -> FingerprintResult | None:
    for adapter, pattern in _HTML_PATTERNS:
        match = pattern.search(html)
        if match:
            # Try to extract a token from any embedded URL of that platform.
            for candidate in re.findall(r"https?://[^\s\"'<>]+", html):
                url_result = detect_from_url(candidate)
                if url_result and url_result.adapter == adapter and url_result.config:
                    url_result.evidence = f"embedded link: {candidate}"
                    return url_result
            return FingerprintResult(adapter=adapter, evidence=f"HTML marker: {match.group(0)}")
    return None


def detect(url: str, html: str | None = None) -> FingerprintResult | None:
    result = detect_from_url(url)
    if result:
        return result
    if html:
        return detect_from_html(html)
    return None
