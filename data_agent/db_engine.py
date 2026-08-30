"""
Connection pool singleton for GIS Data Agent (v18.0).

Provides read-write and read-only engine singletons with validated, configurable
pool settings.  When DATABASE_READ_URL is set (e.g. a cloud RDS read-replica
endpoint), queries routed through ``get_engine(readonly=True)`` will hit
the replica; otherwise they fall back to the primary.

Pool sizes are tuned for Huawei Cloud RDS (default pool_size=20).
"""
import os

from sqlalchemy import create_engine

_engine = None
_read_engine = None


def _bounded_int(
    name: str,
    raw: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Read a bounded integer without silently accepting unsafe pool values."""
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(
            f"{name} must be between {minimum} and {maximum}, got {value}"
        )
    return value


def _pool_size() -> int:
    """Configurable pool size via DB_POOL_SIZE env var (default 20)."""
    return _bounded_int(
        "DB_POOL_SIZE",
        os.environ.get("DB_POOL_SIZE", "20"),
        minimum=1,
        maximum=500,
    )


def _max_overflow() -> int:
    """Configurable max overflow via DB_MAX_OVERFLOW env var (default 30)."""
    return _bounded_int(
        "DB_MAX_OVERFLOW",
        os.environ.get("DB_MAX_OVERFLOW", "30"),
        minimum=0,
        maximum=1000,
    )


def get_pool_configuration() -> dict[str, int | bool]:
    """Return the non-secret, process-local connection pool contract."""
    pool_size = _pool_size()
    max_overflow = _max_overflow()
    return {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "configured_capacity": pool_size + max_overflow,
        "read_replica_configured": bool(os.environ.get("DATABASE_READ_URL")),
    }


def get_connection_budget() -> dict[str, int | str | bool | None]:
    """Calculate this workload's peak connection demand without credentials.

    ``DB_POOL_PROCESS_COUNT`` represents database-using OS processes inside
    the workload. Deployment replicas must still be multiplied and summed by
    the orchestrator because a process cannot discover the whole topology.
    """
    sync_capacity = _pool_size() + _max_overflow()
    async_capacity = _bounded_int(
        "ASYNC_POOL_MAX",
        os.environ.get("ASYNC_POOL_MAX", "20"),
        minimum=1,
        maximum=1000,
    )
    process_count = _bounded_int(
        "DB_POOL_PROCESS_COUNT",
        os.environ.get("DB_POOL_PROCESS_COUNT", "1"),
        minimum=1,
        maximum=1000,
    )
    operational_reserve = _bounded_int(
        "POSTGRES_CONNECTION_RESERVE",
        os.environ.get("POSTGRES_CONNECTION_RESERVE", "10"),
        minimum=3,
        maximum=1000,
    )
    primary_peak = (sync_capacity + async_capacity) * process_count
    read_replica_peak = (
        sync_capacity * process_count
        if os.environ.get("DATABASE_READ_URL")
        else 0
    )
    raw_server_limit = os.environ.get("POSTGRES_MAX_CONNECTIONS")
    server_limit = None
    application_capacity = None
    headroom = None
    status = "server_limit_unconfigured"
    if raw_server_limit:
        try:
            server_limit = int(raw_server_limit)
        except ValueError as exc:
            raise ValueError("POSTGRES_MAX_CONNECTIONS must be an integer") from exc
        if not 10 <= server_limit <= 10000:
            raise ValueError(
                "POSTGRES_MAX_CONNECTIONS must be between 10 and 10000"
            )
        application_capacity = server_limit - operational_reserve
        headroom = application_capacity - primary_peak
        status = "within_budget" if headroom >= 0 else "over_budget"
    return {
        "status": status,
        "declared_server_max_connections": server_limit,
        "operational_reserve": operational_reserve,
        "application_capacity": application_capacity,
        "process_count": process_count,
        "sync_capacity_per_process": sync_capacity,
        "async_capacity_per_process": async_capacity,
        "primary_peak_connections": primary_peak,
        "read_replica_configured": bool(os.environ.get("DATABASE_READ_URL")),
        "read_replica_peak_connections": read_replica_peak,
        "primary_headroom": headroom,
    }


def _create_sa_engine(url: str, *, pool_size: int | None = None,
                      max_overflow: int | None = None):
    """Create a SQLAlchemy engine with standardised pool configuration."""
    resolved_pool_size = _pool_size() if pool_size is None else pool_size
    resolved_max_overflow = (
        _max_overflow() if max_overflow is None else max_overflow
    )
    if not 1 <= resolved_pool_size <= 500:
        raise ValueError("pool_size must be between 1 and 500")
    if not 0 <= resolved_max_overflow <= 1000:
        raise ValueError("max_overflow must be between 0 and 1000")
    return create_engine(
        url,
        pool_size=resolved_pool_size,
        max_overflow=resolved_max_overflow,
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

    Returns process-local usage and configured peak capacity, or None if no
    engine exists. No connection URL or credential is exposed.
    """
    eng = _engine
    if eng is None:
        return None
    pool = eng.pool
    pool_size = pool.size()
    max_overflow = pool._max_overflow
    overflow = max(pool.overflow(), 0)
    return {
        "pool_size": pool_size,
        "checkedin": pool.checkedin(),
        "checkedout": pool.checkedout(),
        "overflow": overflow,
        "max_overflow": max_overflow,
        "configured_capacity": pool_size + max_overflow,
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
