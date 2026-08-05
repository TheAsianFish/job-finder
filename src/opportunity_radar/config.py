"""Configuration loading.

Sources, in order of precedence:
1. Environment variables / .env  (secrets, DB URL)
2. config/*.yaml                 (profile, companies, scoring, settings)
3. Built-in defaults             (the app runs even with no config files)

Secrets live only in .env (gitignored). YAML files are copies of the
*.example.yaml templates and are also gitignored so personal edits stay local.
"""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from opportunity_radar.constants import (
    DASHBOARD_MIN_SCORE,
    DEFAULT_DB_URL,
    DIGEST_MIN_SCORE,
    IMMEDIATE_MIN_SCORE,
    SUPPRESS_BELOW_SCORE,
)
from opportunity_radar.models.company import CompanySource


def project_root() -> Path:
    """Root directory for config/data. Overridable for tests and launchd."""
    env_root = os.environ.get("OPPORTUNITY_RADAR_HOME")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path.cwd()


def config_dir() -> Path:
    return project_root() / "config"


def data_dir() -> Path:
    return project_root() / "data"


class TargetWindow(BaseModel):
    name: str
    start: date
    end: date
    priority: int = 50


class SchedulerSettings(BaseModel):
    default_interval_minutes: int = 30
    core_interval_minutes: int = 20
    strong_interval_minutes: int = 45
    broad_interval_minutes: int = 120
    exploratory_interval_minutes: int = 360
    max_concurrency_global: int = 8
    max_concurrency_per_domain: int = 1
    request_timeout_seconds: int = 30
    retries: int = 3
    backoff_seconds: list[float] = Field(default_factory=lambda: [2.0, 8.0, 30.0])
    jitter_seconds: int = 45
    morning_digest_hour: int = 8
    evening_digest_hour: int = 18

    def tier_intervals(self) -> dict[str, int]:
        return {
            "core": self.core_interval_minutes,
            "strong": self.strong_interval_minutes,
            "broad": self.broad_interval_minutes,
            "exploratory": self.exploratory_interval_minutes,
        }


class AlertSettings(BaseModel):
    immediate_min_score: int = IMMEDIATE_MIN_SCORE
    digest_min_score: int = DIGEST_MIN_SCORE
    dashboard_min_score: int = DASHBOARD_MIN_SCORE
    suppress_below_score: int = SUPPRESS_BELOW_SCORE
    alert_on_changes: bool = True


class CandidateProfile(BaseModel):
    expected_graduation: date = date(2027, 12, 1)
    degree_level: str = "bachelors"
    school: str = "University of California, San Diego"
    country: str = "US"
    requires_sponsorship: bool | None = None
    us_citizen: bool | None = None
    permanent_resident: bool | None = None
    clearance_eligible: bool | None = None


class Preferences(BaseModel):
    countries: list[str] = Field(default_factory=lambda: ["US"])
    allow_remote: bool = True
    willing_to_relocate: bool = True
    preferred_locations: list[str] = Field(
        default_factory=lambda: ["California", "New York", "Seattle", "Boston", "Austin", "Remote"]
    )
    role_families: list[str] = Field(
        default_factory=lambda: [
            "general_swe",
            "backend",
            "infrastructure",
            "ml_systems",
            "developer_tools",
            "data_infrastructure",
            "fullstack",
        ]
    )
    target_seasons: list[str] = Field(
        default_factory=lambda: ["spring_2027", "summer_2027", "fall_2027", "new_grad_late_2027"]
    )


class SkillsConfig(BaseModel):
    languages: list[str] = Field(
        default_factory=lambda: [
            "Python",
            "Java",
            "C#",
            "C",
            "C++",
            "JavaScript",
            "TypeScript",
            "SQL",
        ]
    )
    technologies: list[str] = Field(
        default_factory=lambda: [
            "React",
            ".NET",
            "Blazor",
            "Entity Framework Core",
            "FastAPI",
            "Flask",
            "PostgreSQL",
            "SQL Server",
            "AWS",
            "Docker",
            "Kubernetes",
            "Kubeflow",
            "Jenkins",
            "Azure DevOps",
            "Jest",
            "Git",
            "Tree-sitter",
            "ChromaDB",
        ]
    )
    concepts: list[str] = Field(
        default_factory=lambda: [
            "production software",
            "backend systems",
            "cloud infrastructure",
            "distributed systems",
            "machine learning systems",
            "developer tooling",
            "databases",
            "operating systems",
            "concurrency",
            "data pipelines",
        ]
    )


class ProfileConfig(BaseModel):
    candidate: CandidateProfile = Field(default_factory=CandidateProfile)
    preferences: Preferences = Field(default_factory=Preferences)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)


DEFAULT_TARGET_WINDOWS = [
    TargetWindow(name="spring_2027", start=date(2027, 1, 1), end=date(2027, 6, 15), priority=95),
    TargetWindow(name="summer_2027", start=date(2027, 5, 15), end=date(2027, 9, 15), priority=100),
    TargetWindow(name="fall_2027", start=date(2027, 8, 1), end=date(2027, 12, 31), priority=80),
    TargetWindow(
        name="new_grad_late_2027", start=date(2027, 10, 1), end=date(2028, 6, 30), priority=70
    ),
]


class ScoringConfig(BaseModel):
    company_tier_points: dict[str, float] = Field(
        default_factory=lambda: {"core": 25.0, "strong": 20.0, "broad": 14.0, "exploratory": 8.0}
    )
    role_family_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "general_swe": 20.0,
            "backend": 20.0,
            "infrastructure": 20.0,
            "ml_systems": 19.0,
            "developer_tools": 19.0,
            "data_infrastructure": 18.0,
            "fullstack": 16.0,
            "quant_developer": 15.0,
            "research_engineering": 15.0,
            "security": 14.0,
            "robotics": 14.0,
            "frontend": 12.0,
            "embedded": 10.0,
            "adjacent": 5.0,
            "irrelevant": 0.0,
        }
    )
    target_windows: list[TargetWindow] = Field(default_factory=lambda: list(DEFAULT_TARGET_WINDOWS))
    alerts: AlertSettings = Field(default_factory=AlertSettings)


class AppSettings(BaseModel):
    env: str = "local"
    db_url: str = DEFAULT_DB_URL
    discord_webhook_url: str | None = None
    secret_key: str = "dev-secret-key"
    contact: str | None = None
    ollama_base_url: str | None = None
    search_api_key: str | None = None
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    companies: list[CompanySource] = Field(default_factory=list)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    return loaded if isinstance(loaded, dict) else {}


def _first_existing(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_companies(path: Path | None = None) -> list[CompanySource]:
    cfg = config_dir()
    resolved = path or _first_existing(cfg / "companies.yaml", cfg / "companies.example.yaml")
    if resolved is None:
        return []
    raw = _load_yaml(resolved)
    return [CompanySource.model_validate(entry) for entry in raw.get("companies", [])]


def load_settings(reload: bool = False) -> AppSettings:
    if reload:
        get_settings.cache_clear()
    return get_settings()


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    root = project_root()
    load_dotenv(root / ".env", override=False)
    cfg = config_dir()

    settings_yaml = _load_yaml(
        _first_existing(cfg / "settings.yaml", cfg / "settings.example.yaml")
        or Path("/nonexistent")
    )
    profile_yaml = _load_yaml(
        _first_existing(cfg / "profile.yaml", cfg / "profile.example.yaml") or Path("/nonexistent")
    )
    scoring_yaml = _load_yaml(
        _first_existing(cfg / "scoring.yaml", cfg / "scoring.example.yaml") or Path("/nonexistent")
    )

    scheduler = SchedulerSettings.model_validate(settings_yaml.get("scheduler", {}))
    profile = ProfileConfig.model_validate(profile_yaml) if profile_yaml else ProfileConfig()

    scoring_data: dict[str, Any] = dict(scoring_yaml)
    # Allow alerts and windows to live in either settings.yaml or scoring.yaml.
    if "alerts" not in scoring_data and "alerts" in settings_yaml:
        scoring_data["alerts"] = settings_yaml["alerts"]
    if "target_windows" not in scoring_data and "target_windows" in settings_yaml:
        scoring_data["target_windows"] = settings_yaml["target_windows"]
    scoring = ScoringConfig.model_validate(scoring_data) if scoring_data else ScoringConfig()

    return AppSettings(
        env=os.environ.get("OPPORTUNITY_RADAR_ENV", "local"),
        db_url=os.environ.get("OPPORTUNITY_RADAR_DB_URL", DEFAULT_DB_URL),
        discord_webhook_url=os.environ.get("DISCORD_WEBHOOK_URL") or None,
        secret_key=os.environ.get("OPPORTUNITY_RADAR_SECRET_KEY", "dev-secret-key"),
        contact=os.environ.get("OPPORTUNITY_RADAR_CONTACT") or None,
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL") or None,
        search_api_key=os.environ.get("SEARCH_API_KEY") or None,
        scheduler=scheduler,
        profile=profile,
        scoring=scoring,
        companies=load_companies(),
    )
