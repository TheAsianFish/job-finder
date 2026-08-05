"""Database engine and session management.

Decision: synchronous SQLAlchemy on sqlite3. Network fetching is async (httpx),
but persistence is a local single-user SQLite file where sync sessions are
simpler, fully supported by Alembic, and eliminate a whole class of async-ORM
bugs. See docs/architecture-decisions.md.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from opportunity_radar.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def normalize_db_url(url: str) -> str:
    """Accept both sqlite:// and sqlite+aiosqlite:// forms from .env."""
    return url.replace("sqlite+aiosqlite://", "sqlite://")


def get_engine(db_url: str | None = None) -> Engine:
    global _engine, _session_factory
    if _engine is None or db_url is not None:
        url = normalize_db_url(db_url or get_settings().db_url)
        if url.startswith("sqlite:///"):
            db_path = Path(url.removeprefix("sqlite:///"))
            if not db_path.is_absolute():
                db_path = Path.cwd() / db_path
            db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True)

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def reset_engine() -> None:
    """Dispose the cached engine (used by tests and after config changes)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


@contextmanager
def session_scope(db_url: str | None = None) -> Iterator[Session]:
    get_engine(db_url)
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
