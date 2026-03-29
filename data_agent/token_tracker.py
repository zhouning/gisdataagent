"""
Token Usage Tracking for per-user LLM consumption management.
Stores usage records in PostgreSQL (token_usage table).
Supports daily analysis limits, monthly usage summaries, and USD cost calculation.
"""
import os
from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import _inject_user_context, T_TOKEN_USAGE
from .user_context import current_user_id


# ---------------------------------------------------------------------------
# Model pricing (USD per 1M tokens, as of 2026-03)
# ---------------------------------------------------------------------------

MODEL_PRICING = {
    # Gemini
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    # GPT
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # Claude
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-haiku-3.5": {"input": 0.80, "output": 4.00},
    # Default fallback
    "_default": {"input": 0.50, "output": 2.00},
}


def calculate_cost_usd(input_tokens: int, output_tokens: int,
                       model_name: str = "gemini-2.5-flash") -> float:
    """Calculate USD cost for a given token count and model.

    Returns cost in USD (float).
    """
    pricing = MODEL_PRICING.get(model_name, MODEL_PRICING["_default"])
    cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
    return round(cost, 6)


def estimate_pipeline_cost(pipeline_type: str, model_name: str = "gemini-2.5-flash") -> dict:
    """Estimate cost for a pipeline run based on historical averages.

    Returns:
        {"estimated_tokens": int, "estimated_cost_usd": float, "based_on_runs": int}
    """
    engine = get_engine()
    if not engine:
        return {"estimated_tokens": 0, "estimated_cost_usd": 0.0, "based_on_runs": 0}

    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT COUNT(*) AS cnt,
                       COALESCE(AVG(input_tokens), 0) AS avg_in,
                       COALESCE(AVG(output_tokens), 0) AS avg_out
                FROM {T_TOKEN_USAGE}
                WHERE pipeline_type = :p
                  AND created_at >= NOW() - INTERVAL '30 days'
            """), {"p": pipeline_type}).fetchone()
            avg_in = int(row[1])
            avg_out = int(row[2])
            cost = calculate_cost_usd(avg_in, avg_out, model_name)
            return {
                "estimated_tokens": avg_in + avg_out,
                "estimated_cost_usd": cost,
                "based_on_runs": row[0],
                "model": model_name,
            }
    except Exception:
        return {"estimated_tokens": 0, "estimated_cost_usd": 0.0, "based_on_runs": 0}


def ensure_token_table():
    """Create token_usage table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[TokenTracker] WARNING: Database not configured. Token tracking disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_TOKEN_USAGE} (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    pipeline_type VARCHAR(30),
                    model_name VARCHAR(50) DEFAULT 'gemini-2.5-flash',
                    input_tokens INT DEFAULT 0,
                    output_tokens INT DEFAULT 0,
                    total_tokens INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_token_usage_user ON {T_TOKEN_USAGE} (username)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_token_usage_date ON {T_TOKEN_USAGE} (username, created_at)"
            ))
            conn.commit()
        print("[TokenTracker] Token usage table ready.")
    except Exception as e:
        print(f"[TokenTracker] Error initializing token table: {e}")


def record_usage(username: str, pipeline_type: str, input_tokens: int,
                 output_tokens: int, model_name: str = "gemini-2.5-flash",
                 scenario: str = None, project_id: str = None) -> None:
    """
    Record a pipeline run's token consumption with USD cost. Non-fatal on failure.
    """
    engine = get_engine()
    if not engine:
        return

    cost_usd = calculate_cost_usd(input_tokens, output_tokens, model_name)

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            conn.execute(text(f"""
                INSERT INTO {T_TOKEN_USAGE} (username, pipeline_type, model_name,
                                         input_tokens, output_tokens, total_tokens,
                                         scenario, project_id)
                VALUES (:u, :p, :m, :i, :o, :i + :o, :s, :proj)
            """), {"u": username, "p": pipeline_type, "m": model_name,
                   "i": input_tokens, "o": output_tokens, "s": scenario, "proj": project_id})
            conn.commit()
    except Exception as e:
        print(f"[TokenTracker] Failed to record usage: {e}")


def get_daily_usage(username: str) -> dict:
    """
    Get today's usage stats for a user.

    Returns:
        {"count": int, "tokens": int}
    """
    engine = get_engine()
    if not engine:
        return {"count": 0, "tokens": 0}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            row = conn.execute(text(f"""
                SELECT COUNT(*) AS cnt, COALESCE(SUM(total_tokens), 0) AS tokens
                FROM {T_TOKEN_USAGE}
                WHERE username = :u AND created_at >= CURRENT_DATE
            """), {"u": username}).fetchone()
            return {"count": row[0], "tokens": row[1]}
    except Exception:
        return {"count": 0, "tokens": 0}


def get_monthly_usage(username: str) -> dict:
    """
    Get current month's usage stats for a user.

    Returns:
        {"count": int, "total_tokens": int, "input_tokens": int, "output_tokens": int}
    """
    engine = get_engine()
    if not engine:
        return {"count": 0, "total_tokens": 0, "input_tokens": 0, "output_tokens": 0}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            row = conn.execute(text(f"""
                SELECT COUNT(*) AS cnt,
                       COALESCE(SUM(total_tokens), 0) AS total,
                       COALESCE(SUM(input_tokens), 0) AS inp,
                       COALESCE(SUM(output_tokens), 0) AS outp
                FROM {T_TOKEN_USAGE}
                WHERE username = :u
                  AND created_at >= date_trunc('month', CURRENT_DATE)
            """), {"u": username}).fetchone()
            return {
                "count": row[0],
                "total_tokens": row[1],
                "input_tokens": row[2],
                "output_tokens": row[3],
            }
    except Exception:
        return {"count": 0, "total_tokens": 0, "input_tokens": 0, "output_tokens": 0}


def check_usage_limit(username: str, role: str) -> dict:
    """
    Check if the user is within usage limits.

    Rules:
    - admin: no limits
    - Others: daily analysis count limit (DAILY_ANALYSIS_LIMIT env, default 20)
    - Monthly token limit (MONTHLY_TOKEN_LIMIT env, default 0 = unlimited)

    Returns:
        {"allowed": bool, "reason": str, "daily_count": int, "daily_limit": int}
    """
    daily_limit = int(os.environ.get("DAILY_ANALYSIS_LIMIT", 20))
    monthly_token_limit = int(os.environ.get("MONTHLY_TOKEN_LIMIT", 0))

    if role == "admin":
        return {"allowed": True, "reason": "", "daily_count": 0, "daily_limit": daily_limit}

    daily = get_daily_usage(username)

    if daily["count"] >= daily_limit:
        return {
            "allowed": False,
            "reason": f"今日分析次数已达上限({daily['count']}/{daily_limit})，请明天再试或联系管理员。",
            "daily_count": daily["count"],
            "daily_limit": daily_limit,
        }

    if monthly_token_limit > 0:
        monthly = get_monthly_usage(username)
        if monthly["total_tokens"] >= monthly_token_limit:
            return {
                "allowed": False,
                "reason": f"本月 Token 用量已达上限({monthly['total_tokens']:,}/{monthly_token_limit:,})，请联系管理员。",
                "daily_count": daily["count"],
                "daily_limit": daily_limit,
            }

    return {
        "allowed": True,
        "reason": "",
        "daily_count": daily["count"],
        "daily_limit": daily_limit,
    }


def get_usage_summary() -> dict:
    """
    查看当前用户的 Token 消费统计摘要，包括今日和本月用量及 USD 成本。

    Returns:
        用量统计信息，包含今日次数、token数、成本和本月汇总。
    """
    username = current_user_id.get()
    daily = get_daily_usage(username)
    monthly = get_monthly_usage(username)
    daily_limit = int(os.environ.get("DAILY_ANALYSIS_LIMIT", 20))

    # Calculate costs
    daily_cost = calculate_cost_usd(
        daily.get("tokens", 0) // 2, daily.get("tokens", 0) // 2)  # rough split
    monthly_cost = calculate_cost_usd(
        monthly.get("input_tokens", 0), monthly.get("output_tokens", 0))

    return {
        "status": "success",
        "message": (
            f"Token 消费统计\n"
            f"今日：{daily['count']} 次分析，{daily['tokens']:,} tokens"
            f"（限额 {daily_limit} 次/天），约 ${daily_cost:.4f}\n"
            f"本月：{monthly['count']} 次分析，{monthly['total_tokens']:,} tokens"
            f"，约 ${monthly_cost:.4f}\n"
            f"  输入：{monthly['input_tokens']:,} | 输出：{monthly['output_tokens']:,}"
        ),
        "daily_cost_usd": daily_cost,
        "monthly_cost_usd": monthly_cost,
    }


def get_pipeline_breakdown(username: str) -> list:
    """
    Get current month's usage broken down by pipeline_type.

    Returns:
        [{"pipeline_type": "optimization", "count": 5, "tokens": 12340}, ...]
    """
    engine = get_engine()
    if not engine:
        return []

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            rows = conn.execute(text(f"""
                SELECT pipeline_type,
                       COUNT(*) AS cnt,
                       COALESCE(SUM(total_tokens), 0) AS tokens
                FROM {T_TOKEN_USAGE}
                WHERE username = :u
                  AND created_at >= date_trunc('month', CURRENT_DATE)
                GROUP BY pipeline_type
                ORDER BY tokens DESC
            """), {"u": username}).fetchall()
            return [
                {"pipeline_type": row[0] or "unknown", "count": row[1], "tokens": row[2]}
                for row in rows
            ]
    except Exception:
        return []
