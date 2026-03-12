"""
Failure Learning & Adaptation for GIS Data Agent.

Records tool failures in PostgreSQL and surfaces historical hints to agents
on retry, enabling the system to learn from past mistakes.

Non-fatal: never raises exceptions to the caller.
"""
import json
from typing import Optional, List

from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import T_TOOL_FAILURES
from .user_context import current_user_id


# ---------------------------------------------------------------------------
# Table initialization
# ---------------------------------------------------------------------------

def ensure_failure_table():
    """Create tool_failures table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[FailureLearning] WARNING: Database not configured. Failure learning disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_TOOL_FAILURES} (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    tool_name VARCHAR(200) NOT NULL,
                    error_snippet VARCHAR(500),
                    hint_applied TEXT,
                    resolved BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_tf_tool "
                f"ON {T_TOOL_FAILURES} (tool_name)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_tf_user "
                f"ON {T_TOOL_FAILURES} (username)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_tf_created "
                f"ON {T_TOOL_FAILURES} (created_at DESC)"
            ))
            conn.commit()
        print("[FailureLearning] Tool failures table ready.")
    except Exception as e:
        print(f"[FailureLearning] Error initializing table: {e}")


# ---------------------------------------------------------------------------
# Record a failure
# ---------------------------------------------------------------------------

def record_failure(
    tool_name: str,
    error_snippet: str,
    hint_applied: Optional[str] = None,
) -> None:
    """Record a tool failure event. Non-fatal on failure.

    Args:
        tool_name: Name of the tool that failed.
        error_snippet: First 500 chars of error text.
        hint_applied: The correction hint that was generated.
    """
    engine = get_engine()
    if not engine:
        return

    try:
        username = current_user_id.get()
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_TOOL_FAILURES}
                    (username, tool_name, error_snippet, hint_applied)
                VALUES (:u, :tool, :err, :hint)
            """), {
                "u": username,
                "tool": tool_name,
                "err": (error_snippet or "")[:500],
                "hint": hint_applied,
            })
            conn.commit()
    except Exception as e:
        print(f"[FailureLearning] Failed to record: {e}")


# ---------------------------------------------------------------------------
# Retrieve historical hints
# ---------------------------------------------------------------------------

def get_failure_hints(tool_name: str, limit: int = 3) -> List[str]:
    """Get recent unresolved failure hints for a tool.

    Returns list of hint strings from past failures, most recent first.
    """
    engine = get_engine()
    if not engine:
        return []

    try:
        username = current_user_id.get()
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT DISTINCT ON (error_snippet) error_snippet, hint_applied
                FROM {T_TOOL_FAILURES}
                WHERE tool_name = :tool AND username = :u AND resolved = FALSE
                ORDER BY error_snippet, created_at DESC
                LIMIT :lim
            """), {"tool": tool_name, "u": username, "lim": limit}).fetchall()

        hints = []
        for row in rows:
            snippet = row[0] or ""
            hint = row[1] or ""
            if hint:
                hints.append(f"[历史经验] {snippet[:100]}... → {hint}")
        return hints
    except Exception as e:
        print(f"[FailureLearning] Failed to fetch hints: {e}")
        return []


# ---------------------------------------------------------------------------
# Mark failures as resolved
# ---------------------------------------------------------------------------

def mark_resolved(tool_name: str) -> None:
    """Mark all unresolved failures for this tool+user as resolved.

    Called when a tool succeeds after prior failures.
    """
    engine = get_engine()
    if not engine:
        return

    try:
        username = current_user_id.get()
        with engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {T_TOOL_FAILURES}
                SET resolved = TRUE
                WHERE tool_name = :tool AND username = :u AND resolved = FALSE
            """), {"tool": tool_name, "u": username})
            conn.commit()
    except Exception as e:
        print(f"[FailureLearning] Failed to mark resolved: {e}")
