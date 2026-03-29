"""
Analysis Chains — conditional follow-up analysis automation (v14.2).

Users define rules: "if metric X from pipeline result > threshold, auto-execute Y".
Chains are evaluated after each pipeline completion and triggered automatically.
"""
import json
import logging
from typing import Optional

from sqlalchemy import text
from .db_engine import get_engine
from .user_context import current_user_id

logger = logging.getLogger("data_agent.analysis_chains")

T_ANALYSIS_CHAINS = "agent_analysis_chains"


def ensure_chains_table():
    """Create analysis chains table if not exists."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_ANALYSIS_CHAINS} (
                    id SERIAL PRIMARY KEY,
                    owner_username VARCHAR(100) NOT NULL,
                    chain_name VARCHAR(200) NOT NULL,
                    description TEXT DEFAULT '',
                    trigger_condition JSONB NOT NULL,
                    follow_up_prompt TEXT NOT NULL,
                    follow_up_pipeline VARCHAR(30) DEFAULT 'general',
                    enabled BOOLEAN DEFAULT TRUE,
                    trigger_count INTEGER DEFAULT 0,
                    last_triggered TIMESTAMP DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(owner_username, chain_name)
                )
            """))
            conn.commit()
    except Exception as e:
        logger.warning("Failed to ensure chains table: %s", e)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_chain(chain_name: str, trigger_condition: dict,
                 follow_up_prompt: str, follow_up_pipeline: str = "general",
                 description: str = "") -> dict:
    """Create a new analysis chain rule.

    trigger_condition format:
        {"metric": "record_count", "operator": ">", "threshold": 100}
        {"metric": "keyword", "operator": "contains", "threshold": "异常"}
    """
    username = current_user_id.get("")
    if not username:
        return {"status": "error", "message": "Not authenticated"}
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not available"}
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_ANALYSIS_CHAINS}
                    (owner_username, chain_name, description, trigger_condition,
                     follow_up_prompt, follow_up_pipeline)
                VALUES (:owner, :name, :desc, :cond::jsonb, :prompt, :pipeline)
            """), {
                "owner": username, "name": chain_name, "desc": description,
                "cond": json.dumps(trigger_condition),
                "prompt": follow_up_prompt, "pipeline": follow_up_pipeline,
            })
            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        if "unique" in str(e).lower():
            return {"status": "error", "message": f"Chain '{chain_name}' already exists"}
        return {"status": "error", "message": str(e)}


def list_chains(owner_username: str = None) -> list[dict]:
    """List analysis chains for a user."""
    username = owner_username or current_user_id.get("")
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT id, chain_name, description, trigger_condition, "
                f"follow_up_prompt, follow_up_pipeline, enabled, trigger_count, "
                f"last_triggered, created_at "
                f"FROM {T_ANALYSIS_CHAINS} WHERE owner_username = :u ORDER BY created_at DESC"
            ), {"u": username}).fetchall()
        return [
            {
                "id": r[0], "chain_name": r[1], "description": r[2],
                "trigger_condition": r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}"),
                "follow_up_prompt": r[4], "follow_up_pipeline": r[5],
                "enabled": bool(r[6]), "trigger_count": r[7],
                "last_triggered": str(r[8]) if r[8] else None,
                "created_at": str(r[9]),
            }
            for r in rows
        ]
    except Exception:
        return []


def delete_chain(chain_id: int) -> bool:
    """Delete an analysis chain."""
    username = current_user_id.get("")
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"DELETE FROM {T_ANALYSIS_CHAINS} WHERE id = :id AND owner_username = :u"
            ), {"id": chain_id, "u": username})
            conn.commit()
        return result.rowcount > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Chain Evaluation
# ---------------------------------------------------------------------------

def evaluate_chains(report_text: str, pipeline_type: str,
                    generated_files: list, username: str) -> list[dict]:
    """Evaluate all enabled chains against pipeline results.

    Returns list of triggered chains with their follow_up_prompt.
    """
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                f"SELECT id, chain_name, trigger_condition, follow_up_prompt, follow_up_pipeline "
                f"FROM {T_ANALYSIS_CHAINS} "
                f"WHERE owner_username = :u AND enabled = TRUE"
            ), {"u": username}).fetchall()

        triggered = []
        for r in rows:
            cond = r[2] if isinstance(r[2], dict) else json.loads(r[2] or "{}")
            if _check_condition(cond, report_text, pipeline_type, generated_files):
                triggered.append({
                    "chain_id": r[0], "chain_name": r[1],
                    "follow_up_prompt": r[3], "follow_up_pipeline": r[4],
                })
                # Update trigger stats
                try:
                    with engine.connect() as conn2:
                        conn2.execute(text(
                            f"UPDATE {T_ANALYSIS_CHAINS} SET trigger_count = trigger_count + 1, "
                            f"last_triggered = NOW() WHERE id = :id"
                        ), {"id": r[0]})
                        conn2.commit()
                except Exception:
                    pass
        return triggered
    except Exception:
        return []


def _check_condition(condition: dict, report_text: str,
                     pipeline_type: str, files: list) -> bool:
    """Check if a trigger condition is met."""
    metric = condition.get("metric", "")
    operator = condition.get("operator", "")
    threshold = condition.get("threshold", "")

    if metric == "keyword":
        if operator == "contains":
            return str(threshold).lower() in report_text.lower()
        elif operator == "not_contains":
            return str(threshold).lower() not in report_text.lower()

    elif metric == "pipeline_type":
        return pipeline_type == str(threshold)

    elif metric == "file_count":
        try:
            val = len(files)
            return _compare(val, operator, float(threshold))
        except (ValueError, TypeError):
            return False

    elif metric == "report_length":
        try:
            val = len(report_text)
            return _compare(val, operator, float(threshold))
        except (ValueError, TypeError):
            return False

    return False


def _compare(val: float, operator: str, threshold: float) -> bool:
    """Compare a numeric value against a threshold."""
    if operator == ">":
        return val > threshold
    elif operator == ">=":
        return val >= threshold
    elif operator == "<":
        return val < threshold
    elif operator == "<=":
        return val <= threshold
    elif operator == "==":
        return val == threshold
    return False
