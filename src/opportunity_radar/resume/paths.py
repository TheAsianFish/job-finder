"""Where private career data lives (never inside the public repo's history)."""

from __future__ import annotations

import os
from pathlib import Path

from opportunity_radar.config import project_root


def private_dir() -> Path:
    """Local clone of the private career repo (git-ignored by the public repo)."""
    env = os.environ.get("OPPORTUNITY_RADAR_PRIVATE_DIR")
    return Path(env).expanduser() if env else project_root() / "resume" / "private"


def resume_source() -> Path:
    return private_dir() / "resume.tex"


def ledger_path() -> Path:
    return private_dir() / "applications.yaml"
