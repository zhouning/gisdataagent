"""
Self-Improvement — prompt optimization + tool preference tracking (v11.0.5, Ch20).

Records pipeline outcomes and tool success rates to generate
improvement hints for agent prompts.

All DB operations are non-fatal.
"""
import hashlib
import json
import os
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine

try:
    from .observability import get_logger
    logger = get_logger("self_improvement")
except Exception:
    import logging
    logger = logging.getLogger("self_improvement")


T_PROMPT_OUTCOMES = "agent_prompt_outcomes"
T_TOOL_PREFERENCES = "agent_tool_preferences"
SELF_IMPROVEMENT_ENABLED = os.environ.get("SELF_IMPROVEMENT_ENABLED", "true").lower() == "true"


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------

def ensure_self_improvement_tables() -> bool:
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_PROMPT_OUTCOMES} (
                    id SERIAL PRIMARY KEY,
                    pipeline_type VARCHAR(30) NOT NULL,
                    prompt_hash VARCHAR(64) NOT NULL,
                    success BOOLEAN DEFAULT TRUE,
                    confidence REAL DEFAULT 0.5,
                    duration REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_TOOL_PREFERENCES} (
                    id SERIAL PRIMARY KEY,
                    tool_name VARCHAR(100) NOT NULL,
                    data_type VARCHAR(50) DEFAULT '',
                    crs VARCHAR(50) DEFAULT '',
                    success_rate REAL DEFAULT 0.5,
                    avg_duration REAL DEFAULT 0,
                    sample_count INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(tool_name, data_type, crs)
                )
            """))
            conn.commit()
        return True
    except Exception as e:
        logger.warning("Failed to create self_improvement tables: %s", e)
        return False


# ---------------------------------------------------------------------------
# Prompt outcome tracking
# ---------------------------------------------------------------------------

def _hash_prompt(prompt: str) -> str:
    """Hash a prompt for deduplication."""
    return hashlib.sha256(prompt.encode()).hexdigest()[:16]


def record_outcome(pipeline_type: str, prompt: str, success: bool,
                   confidence: float = 0.5, duration: float = 0.0):
    """Record the outcome of a pipeline execution."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_PROMPT_OUTCOMES}
                    (pipeline_type, prompt_hash, success, confidence, duration)
                VALUES (:pt, :hash, :success, :conf, :dur)
            """), {
                "pt": pipeline_type,
                "hash": _hash_prompt(prompt),
                "success": success,
                "conf": confidence,
                "dur": duration,
            })
            conn.commit()
    except Exception as e:
        logger.debug("Failed to record outcome: %s", e)


def get_pipeline_success_rates() -> dict:
    """Get success rates by pipeline type."""
    engine = get_engine()
    if not engine:
        return {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT pipeline_type,
                       COUNT(*) as total,
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes,
                       AVG(confidence) as avg_confidence,
                       AVG(duration) as avg_duration
                FROM {T_PROMPT_OUTCOMES}
                GROUP BY pipeline_type
            """)).fetchall()
        return {
            r[0]: {
                "total": r[1],
                "success_rate": round(r[2] / max(r[1], 1), 3),
                "avg_confidence": round(float(r[3] or 0), 3),
                "avg_duration": round(float(r[4] or 0), 2),
            }
            for r in rows
        }
    except Exception as e:
        logger.debug("Failed to get success rates: %s", e)
        return {}


# ---------------------------------------------------------------------------
# Tool preference tracking
# ---------------------------------------------------------------------------

def record_tool_usage(tool_name: str, success: bool, duration: float = 0.0,
                      data_type: str = "", crs: str = ""):
    """Record a tool execution outcome for preference learning."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            # Upsert with running average
            conn.execute(text(f"""
                INSERT INTO {T_TOOL_PREFERENCES}
                    (tool_name, data_type, crs, success_rate, avg_duration, sample_count, updated_at)
                VALUES (:tool, :dt, :crs, :sr, :dur, 1, NOW())
                ON CONFLICT (tool_name, data_type, crs) DO UPDATE SET
                    success_rate = (
                        {T_TOOL_PREFERENCES}.success_rate * {T_TOOL_PREFERENCES}.sample_count + :sr
                    ) / ({T_TOOL_PREFERENCES}.sample_count + 1),
                    avg_duration = (
                        {T_TOOL_PREFERENCES}.avg_duration * {T_TOOL_PREFERENCES}.sample_count + :dur
                    ) / ({T_TOOL_PREFERENCES}.sample_count + 1),
                    sample_count = {T_TOOL_PREFERENCES}.sample_count + 1,
                    updated_at = NOW()
            """), {
                "tool": tool_name,
                "dt": data_type,
                "crs": crs,
                "sr": 1.0 if success else 0.0,
                "dur": duration,
            })
            conn.commit()
    except Exception as e:
        logger.debug("Failed to record tool usage: %s", e)


def get_tool_preferences(min_samples: int = 5) -> list[dict]:
    """Get tool preferences with sufficient sample size."""
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT tool_name, data_type, crs, success_rate, avg_duration, sample_count
                FROM {T_TOOL_PREFERENCES}
                WHERE sample_count >= :min
                ORDER BY success_rate DESC
            """), {"min": min_samples}).fetchall()
        return [
            {
                "tool_name": r[0], "data_type": r[1], "crs": r[2],
                "success_rate": round(float(r[3]), 3),
                "avg_duration": round(float(r[4]), 2),
                "sample_count": r[5],
            }
            for r in rows
        ]
    except Exception as e:
        logger.debug("Failed to get tool preferences: %s", e)
        return []


def generate_tool_hints(data_type: str = "", crs: str = "") -> str:
    """Generate tool preference hints for agent prompt injection."""
    prefs = get_tool_preferences()
    if not prefs:
        return ""

    relevant = prefs
    if data_type:
        relevant = [p for p in relevant if p["data_type"] == data_type or not p["data_type"]]
    if crs:
        relevant = [p for p in relevant if p["crs"] == crs or not p["crs"]]

    if not relevant:
        return ""

    # Top 3 most successful tools
    top = relevant[:3]
    hints = []
    for p in top:
        if p["success_rate"] > 0.8:
            hints.append(f"- {p['tool_name']}: 成功率 {p['success_rate']*100:.0f}% "
                        f"(平均 {p['avg_duration']:.1f}s, {p['sample_count']} 次)")

    if not hints:
        return ""
    return "## 推荐工具 (基于历史表现)\n" + "\n".join(hints)
