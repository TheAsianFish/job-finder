"""Programmatic Alembic migration runner used by `opportunity-radar init/db migrate`."""

from __future__ import annotations

from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from opportunity_radar.config import get_settings, project_root
from opportunity_radar.db.engine import get_engine, normalize_db_url

logger = structlog.get_logger(__name__)


def _alembic_config(db_url: str | None = None) -> Config:
    root = _repo_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", normalize_db_url(db_url or get_settings().db_url))
    return cfg


def _repo_root() -> Path:
    """Find the directory containing alembic.ini (repo checkout or cwd)."""
    candidates = [project_root(), Path(__file__).resolve().parents[3]]
    for candidate in candidates:
        if (candidate / "alembic.ini").exists():
            return candidate
    return project_root()


def upgrade_to_head(db_url: str | None = None) -> None:
    command.upgrade(_alembic_config(db_url), "head")
    logger.info("migrations_applied")


def current_revision(db_url: str | None = None) -> str | None:
    engine = get_engine(db_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def head_revision(db_url: str | None = None) -> str | None:
    script = ScriptDirectory.from_config(_alembic_config(db_url))
    return script.get_current_head()


def is_up_to_date(db_url: str | None = None) -> bool:
    return current_revision(db_url) == head_revision(db_url)
