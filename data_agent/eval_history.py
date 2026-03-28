"""
Evaluation History — persistent storage for agent evaluation results.

Tracks evaluation runs over time to detect quality regressions.
Stores results in PostgreSQL for querying and trend analysis.
"""
import json
import os
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .observability import get_logger

logger = get_logger("eval_history")

T_EVAL_HISTORY = "agent_eval_history"


def ensure_eval_table():
    """Create evaluation history table if not exists."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_EVAL_HISTORY} (
                    id SERIAL PRIMARY KEY,
                    run_id VARCHAR(100) NOT NULL,
                    pipeline VARCHAR(50) NOT NULL,
                    model VARCHAR(100) DEFAULT '',
                    git_commit VARCHAR(50) DEFAULT '',
                    git_branch VARCHAR(100) DEFAULT '',
                    overall_score REAL DEFAULT 0,
                    pass_rate REAL DEFAULT 0,
                    verdict VARCHAR(20) DEFAULT 'UNKNOWN',
                    num_tests INTEGER DEFAULT 0,
                    num_passed INTEGER DEFAULT 0,
                    details JSONB DEFAULT '{{}}',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_eval_history_pipeline
                ON {T_EVAL_HISTORY} (pipeline, created_at DESC)
            """))
            conn.commit()
    except Exception as e:
        logger.warning("Failed to create eval_history table: %s", e)


def record_eval_result(
    pipeline: str,
    overall_score: float,
    pass_rate: float,
    verdict: str,
    num_tests: int = 0,
    num_passed: int = 0,
    model: str = "",
    details: dict = None,
    run_id: str = None,
    scenario: str = None,
    dataset_id: int = None,
    metrics: dict = None,
) -> Optional[int]:
    """Record an evaluation result. Returns the record ID or None."""
    engine = get_engine()
    if not engine:
        return None

    import uuid
    rid = run_id or uuid.uuid4().hex[:12]

    # Try to get git info
    git_commit = ""
    git_branch = ""
    try:
        import subprocess
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(__file__), timeout=3,
        ).decode().strip()
        git_branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=os.path.dirname(__file__), timeout=3,
        ).decode().strip()
    except Exception:
        pass

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                INSERT INTO {T_EVAL_HISTORY}
                (run_id, pipeline, model, git_commit, git_branch,
                 overall_score, pass_rate, verdict, num_tests, num_passed, details,
                 scenario, dataset_id, metrics)
                VALUES (:rid, :p, :m, :gc, :gb, :score, :pr, :v, :nt, :np, :d, :s, :ds, :met)
                RETURNING id
            """), {
                "rid": rid, "p": pipeline, "m": model,
                "gc": git_commit, "gb": git_branch,
                "score": overall_score, "pr": pass_rate,
                "v": verdict, "nt": num_tests, "np": num_passed,
                "d": json.dumps(details or {}, default=str),
                "s": scenario, "ds": dataset_id,
                "met": json.dumps(metrics or {}, default=str),
            })
            conn.commit()
            row = result.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.warning("Failed to record eval result: %s", e)
        return None


def get_eval_history(pipeline: str = None, limit: int = 50) -> list[dict]:
    """Get evaluation history, optionally filtered by pipeline.

    Returns list of eval results ordered by most recent first.
    """
    engine = get_engine()
    if not engine:
        return []

    try:
        with engine.connect() as conn:
            if pipeline:
                rows = conn.execute(text(f"""
                    SELECT id, run_id, pipeline, model, git_commit, git_branch,
                           overall_score, pass_rate, verdict, num_tests, num_passed,
                           created_at
                    FROM {T_EVAL_HISTORY}
                    WHERE pipeline = :p
                    ORDER BY created_at DESC LIMIT :lim
                """), {"p": pipeline, "lim": limit}).fetchall()
            else:
                rows = conn.execute(text(f"""
                    SELECT id, run_id, pipeline, model, git_commit, git_branch,
                           overall_score, pass_rate, verdict, num_tests, num_passed,
                           created_at
                    FROM {T_EVAL_HISTORY}
                    ORDER BY created_at DESC LIMIT :lim
                """), {"lim": limit}).fetchall()

            return [{
                "id": r[0], "run_id": r[1], "pipeline": r[2],
                "model": r[3], "git_commit": r[4], "git_branch": r[5],
                "overall_score": float(r[6] or 0),
                "pass_rate": float(r[7] or 0),
                "verdict": r[8],
                "num_tests": r[9], "num_passed": r[10],
                "created_at": r[11].isoformat() if r[11] else None,
            } for r in rows]
    except Exception as e:
        logger.warning("Failed to get eval history: %s", e)
        return []


def get_eval_trend(pipeline: str, days: int = 90) -> list[dict]:
    """Get score trend for a pipeline over time.

    Returns list of {date, score, pass_rate, verdict} for trend charting.
    """
    engine = get_engine()
    if not engine:
        return []

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT DATE(created_at) AS eval_date,
                       AVG(overall_score) AS avg_score,
                       AVG(pass_rate) AS avg_pass_rate,
                       COUNT(*) AS runs
                FROM {T_EVAL_HISTORY}
                WHERE pipeline = :p
                  AND created_at >= NOW() - make_interval(days => :d)
                GROUP BY eval_date
                ORDER BY eval_date
            """), {"p": pipeline, "d": days}).fetchall()

            return [{
                "date": r[0].isoformat() if r[0] else None,
                "score": round(float(r[1] or 0), 2),
                "pass_rate": round(float(r[2] or 0), 2),
                "runs": r[3],
            } for r in rows]
    except Exception as e:
        logger.warning("Failed to get eval trend: %s", e)
        return []


def compare_eval_runs(run_id_a: str, run_id_b: str) -> dict:
    """Compare two evaluation runs side by side.

    Returns delta analysis between two runs.
    """
    engine = get_engine()
    if not engine:
        return {"error": "Database not available"}

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT run_id, pipeline, model, git_commit,
                       overall_score, pass_rate, verdict, num_tests, num_passed,
                       details, created_at
                FROM {T_EVAL_HISTORY}
                WHERE run_id IN (:a, :b)
                ORDER BY created_at
            """), {"a": run_id_a, "b": run_id_b}).fetchall()

            if len(rows) < 2:
                return {"error": "One or both runs not found"}

            a = rows[0]
            b = rows[1]

            return {
                "run_a": {
                    "run_id": a[0], "pipeline": a[1], "model": a[2],
                    "git_commit": a[3], "score": float(a[4] or 0),
                    "pass_rate": float(a[5] or 0), "verdict": a[6],
                    "created_at": a[10].isoformat() if a[10] else None,
                },
                "run_b": {
                    "run_id": b[0], "pipeline": b[1], "model": b[2],
                    "git_commit": b[3], "score": float(b[4] or 0),
                    "pass_rate": float(b[5] or 0), "verdict": b[6],
                    "created_at": b[10].isoformat() if b[10] else None,
                },
                "delta": {
                    "score": round(float(b[4] or 0) - float(a[4] or 0), 3),
                    "pass_rate": round(float(b[5] or 0) - float(a[5] or 0), 3),
                    "regression": float(b[4] or 0) < float(a[4] or 0),
                },
            }
    except Exception as e:
        return {"error": str(e)}
