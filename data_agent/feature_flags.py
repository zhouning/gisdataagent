"""
Feature Flags — dynamic feature control for safe rollouts.

Provides runtime feature toggling without redeployment:
- Environment-based flags (FEATURE_FLAGS env var)
- DB-persisted flags (admin CRUD)
- API endpoints for flag management
- Middleware-compatible flag checking

Usage:
    from data_agent.feature_flags import is_enabled, get_all_flags

    if is_enabled("new_report_engine"):
        # use new code path
    else:
        # use old code path

Environment:
    FEATURE_FLAGS=flag1:true,flag2:false,new_ui:true
"""
import os
import threading
from typing import Optional

from .observability import get_logger

logger = get_logger("feature_flags")

# ---------------------------------------------------------------------------
# In-memory flag store (env + DB merge)
# ---------------------------------------------------------------------------

_flags: dict[str, bool] = {}
_flags_lock = threading.Lock()
_initialized = False


def _parse_env_flags() -> dict[str, bool]:
    """Parse FEATURE_FLAGS environment variable."""
    raw = os.environ.get("FEATURE_FLAGS", "")
    flags = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            key, val = entry.split(":", 1)
            flags[key.strip()] = val.strip().lower() in ("true", "1", "yes", "on")
        else:
            flags[entry] = True  # Bare name = enabled
    return flags


def _load_db_flags() -> dict[str, bool]:
    """Load flags from database (if table exists)."""
    try:
        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return {}
        with engine.connect() as conn:
            # Check if table exists
            exists = conn.execute(text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'agent_feature_flags'"
            )).fetchone()
            if not exists:
                return {}
            rows = conn.execute(text(
                "SELECT flag_name, enabled FROM agent_feature_flags"
            )).fetchall()
            return {r[0]: bool(r[1]) for r in rows}
    except Exception:
        return {}


def _init_flags():
    """Initialize flags from env + DB. DB overrides env."""
    global _flags, _initialized
    with _flags_lock:
        if _initialized:
            return
        env_flags = _parse_env_flags()
        db_flags = _load_db_flags()
        _flags = {**env_flags, **db_flags}  # DB wins
        _initialized = True
        if _flags:
            logger.info("Feature flags loaded: %s", _flags)


def reload_flags():
    """Force reload flags from env + DB."""
    global _initialized
    _initialized = False
    _init_flags()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_enabled(flag_name: str, default: bool = False) -> bool:
    """Check if a feature flag is enabled.

    Args:
        flag_name: The flag identifier.
        default: Default value if flag is not defined.

    Returns:
        True if the flag is enabled.
    """
    _init_flags()
    return _flags.get(flag_name, default)


def get_all_flags() -> dict[str, bool]:
    """Return all defined feature flags."""
    _init_flags()
    return dict(_flags)


def set_flag(flag_name: str, enabled: bool, persist: bool = True) -> None:
    """Set a feature flag value.

    Args:
        flag_name: The flag identifier.
        enabled: Whether the flag should be enabled.
        persist: If True, save to database for persistence across restarts.
    """
    with _flags_lock:
        _flags[flag_name] = enabled

    if persist:
        _persist_flag(flag_name, enabled)

    logger.info("Feature flag '%s' set to %s (persist=%s)", flag_name, enabled, persist)


def delete_flag(flag_name: str) -> bool:
    """Delete a feature flag."""
    with _flags_lock:
        removed = _flags.pop(flag_name, None) is not None

    if removed:
        _delete_persisted_flag(flag_name)
        logger.info("Feature flag '%s' deleted", flag_name)

    return removed


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

def ensure_flags_table():
    """Create feature_flags table if not exists."""
    try:
        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_feature_flags (
                    flag_name VARCHAR(100) PRIMARY KEY,
                    enabled BOOLEAN DEFAULT false,
                    description TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
    except Exception:
        pass


def _persist_flag(flag_name: str, enabled: bool):
    """Upsert flag to database."""
    try:
        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return
        ensure_flags_table()
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO agent_feature_flags (flag_name, enabled, updated_at)
                VALUES (:name, :enabled, NOW())
                ON CONFLICT (flag_name) DO UPDATE
                SET enabled = :enabled, updated_at = NOW()
            """), {"name": flag_name, "enabled": enabled})
            conn.commit()
    except Exception:
        pass


def _delete_persisted_flag(flag_name: str):
    """Delete flag from database."""
    try:
        from .db_engine import get_engine
        from sqlalchemy import text
        engine = get_engine()
        if not engine:
            return
        with engine.connect() as conn:
            conn.execute(text(
                "DELETE FROM agent_feature_flags WHERE flag_name = :name"
            ), {"name": flag_name})
            conn.commit()
    except Exception:
        pass
