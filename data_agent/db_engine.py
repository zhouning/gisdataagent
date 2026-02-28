"""
Connection pool singleton for GIS Data Agent.

Eliminates per-function `create_engine()` calls across 10 modules by providing
a single shared SQLAlchemy engine with configurable pool settings.
"""
from sqlalchemy import create_engine


_engine = None


def get_engine():
    """Return a singleton SQLAlchemy engine with connection pooling.

    Returns None if database credentials are not configured.
    Pool settings: size=5, max_overflow=10, recycle=1800s (30 min).
    """
    global _engine
    if _engine is None:
        from .database_tools import get_db_connection_url
        url = get_db_connection_url()
        if url:
            _engine = create_engine(
                url,
                pool_size=5,
                max_overflow=10,
                pool_recycle=1800,
                pool_pre_ping=True,
            )
    return _engine


def reset_engine():
    """Dispose and reset the singleton engine. Used for testing and shutdown."""
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None
