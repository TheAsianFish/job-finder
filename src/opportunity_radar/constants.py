"""Shared constants for Opportunity Radar."""

from __future__ import annotations

APP_NAME = "opportunity-radar"
USER_AGENT_TEMPLATE = "OpportunityRadar/1.0 (+local personal job monitor{contact})"

DEFAULT_DB_URL = "sqlite:///./data/opportunity_radar.db"
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8765

SEASONS = ("winter", "spring", "summer", "fall", "off_cycle", "year_round", "unspecified")

ROLE_FAMILIES = (
    "general_swe",
    "backend",
    "infrastructure",
    "ml_systems",
    "data_infrastructure",
    "developer_tools",
    "frontend",
    "fullstack",
    "embedded",
    "robotics",
    "security",
    "quant_developer",
    "research_engineering",
    "adjacent",
    "irrelevant",
)

COMPANY_TIERS = ("core", "strong", "broad", "exploratory")

JOB_STATUSES = ("active", "closed", "unknown")

APPLICATION_STATUSES = (
    "none",
    "saved",
    "dismissed",
    "applied",
    "oa",
    "interview",
    "offer",
    "rejected",
)

RESUME_VARIANTS = (
    "general_swe",
    "backend_infrastructure",
    "ai_ml_systems",
    "startup_product",
)

ELIGIBILITY_LEVELS = (
    "confirmed_eligible",
    "likely_eligible",
    "uncertain",
    "likely_ineligible",
    "confirmed_ineligible",
)

# Consecutive successful scans that must miss a job before we close it.
CLOSURE_MISS_THRESHOLD = 2

# HTTP status codes worth retrying.
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

# Default alert thresholds (overridable in scoring.yaml).
IMMEDIATE_MIN_SCORE = 82
DIGEST_MIN_SCORE = 60
DASHBOARD_MIN_SCORE = 35
SUPPRESS_BELOW_SCORE = 20
