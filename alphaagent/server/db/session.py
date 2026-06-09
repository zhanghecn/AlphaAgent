"""SQLAlchemy engine/session helpers for AlphaAgent."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from alphaagent.server.core.config import get_settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


class DatabaseUnavailable(RuntimeError):
    """Raised when the configured PostgreSQL database is unavailable."""


def is_database_configured() -> bool:
    """Return whether DATABASE_URL is configured."""

    return bool(get_settings().database_url.strip())


def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine."""

    global _engine
    database_url = get_settings().database_url.strip()
    if not database_url:
        raise DatabaseUnavailable("DATABASE_URL is not configured")
    if _engine is None:
        _engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            future=True,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide SQLAlchemy session factory."""

    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Open a transactional session."""

    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_database_exists() -> None:
    """Create the target PostgreSQL database when it is missing.

    Docker Compose points the API at an existing 1Panel PostgreSQL instance. For
    local startup, the database itself may not exist yet, so this function tries
    to create it through the default maintenance database using the same user.
    """

    database_url = get_settings().database_url.strip()
    if not database_url:
        return
    url = make_url(database_url)
    database = url.database
    if not database:
        return
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        return
    except OperationalError as exc:
        if not _looks_like_missing_database(exc, database):
            raise

    admin_url = url.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("select 1 from pg_database where datname = :database"),
                {"database": database},
            ).scalar_one_or_none()
            if not exists:
                conn.execute(text(f'create database "{database}"'))
    finally:
        admin_engine.dispose()
    reset_engine()


def check_database() -> dict[str, object]:
    """Return a safe PostgreSQL connectivity summary."""

    if not is_database_configured():
        return {
            "name": "postgresql",
            "ok": False,
            "message": "DATABASE_URL 未配置",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    try:
        ensure_database_exists()
        with get_engine().connect() as conn:
            version = conn.execute(text("select version()")).scalar_one()
        return {
            "name": "postgresql",
            "ok": True,
            "message": str(version).split(",", 1)[0],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        return {
            "name": "postgresql",
            "ok": False,
            "message": exc.__class__.__name__,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


def reset_engine() -> None:
    """Dispose cached engine/session factory.

    Tests and startup recovery use this after changing the database URL or
    creating the target database.
    """

    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def safe_database_dsn() -> str:
    """Return a password-redacted DATABASE_URL for diagnostics."""

    database_url = get_settings().database_url.strip()
    if not database_url:
        return ""
    parts = urlsplit(database_url)
    if "@" not in parts.netloc:
        return database_url
    userinfo, host = parts.netloc.rsplit("@", 1)
    username = userinfo.split(":", 1)[0]
    netloc = f"{username}:***@{host}" if username else f"***@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _looks_like_missing_database(exc: OperationalError, database: str) -> bool:
    message = str(exc).lower()
    return database.lower() in message and ("does not exist" in message or "不存在" in message)

