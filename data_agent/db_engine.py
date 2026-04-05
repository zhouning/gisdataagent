"""
Connection pool singleton for GIS Data Agent (v18.0).

Provides read-write and read-only engine singletons with configurable pool
settings.  When DATABASE_READ_URL is set (e.g. a cloud RDS read-replica
endpoint), queries routed through ``get_engine(readonly=True)`` will hit
the replica; otherwise they fall back to the primary.

Pool sizes are tuned for Huawei Cloud RDS (default pool_size=20).
"""
import os

from sqlalchemy import create_engine, event


_engine = None
_read_engine = None


def _pool_size() -> int:
    """Configurable pool size via DB_POOL_SIZE env var (default 20)."""
    return int(os.environ.get("DB_POOL_SIZE", "20"))


def _max_overflow() -> int:
    """Configurable max overflow via DB_MAX_OVERFLOW env var (default 30)."""
    return int(os.environ.get("DB_MAX_OVERFLOW", "30"))


def _create_sa_engine(url: str, *, pool_size: int | None = None,
                      max_overflow: int | None = None):
    """Create a SQLAlchemy engine with standardised pool configuration."""
    return create_engine(
        url,
        pool_size=pool_size or _pool_size(),
        max_overflow=max_overflow or _max_overflow(),
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def get_engine(readonly: bool = False):
    """Return a singleton SQLAlchemy engine with connection pooling.

    Args:
        readonly: When True, returns a read-only engine backed by
            DATABASE_READ_URL if configured; otherwise falls back to the
            primary engine.  Use this for analytics / report queries.

    Returns None if database credentials are not configured.
    Pool settings: size=20, max_overflow=30, recycle=1800s (30 min).
    """
    global _engine, _read_engine

    if readonly and _read_engine is not None:
        return _read_engine

    if _engine is None:
        from .database_tools import get_db_connection_url
        url = get_db_connection_url()
        if url:
            _engine = _create_sa_engine(url)

    if readonly:
        read_url = os.environ.get("DATABASE_READ_URL")
        if read_url:
            _read_engine = _create_sa_engine(read_url)
            return _read_engine
        # Fallback: use the primary engine for reads
        return _engine

    return _engine


def get_pool_status() -> dict | None:
    """Return connection pool statistics for monitoring.

    Returns dict with keys: pool_size, checkedin, checkedout, overflow,
    or None if no engine exists.
    """
    eng = _engine
    if eng is None:
        return None
    pool = eng.pool
    return {
        "pool_size": pool.size(),
        "checkedin": pool.checkedin(),
        "checkedout": pool.checkedout(),
        "overflow": pool.overflow(),
        "max_overflow": pool._max_overflow,
    }


def reset_engine():
    """Dispose and reset all singleton engines. Used for testing and shutdown."""
    global _engine, _read_engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
    if _read_engine is not None:
        _read_engine.dispose()
        _read_engine = None
