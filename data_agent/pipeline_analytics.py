"""
Pipeline Analytics Dashboard API (v9.0.5).

Five REST endpoints aggregating pipeline execution data from
``agent_audit_log`` and ``agent_token_usage`` tables:

- ``GET /api/analytics/latency``       — P50/P75/P90/P99 percentiles
- ``GET /api/analytics/tool-success``  — Tool success-rate ranking
- ``GET /api/analytics/token-efficiency`` — Token usage trend
- ``GET /api/analytics/throughput``     — Daily pipeline throughput
- ``GET /api/analytics/agent-breakdown`` — Per-agent execution time

All endpoints require JWT auth. Data is drawn from existing DB tables,
no new tables needed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import text

logger = logging.getLogger("data_agent.pipeline_analytics")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_json(val) -> dict:
    """Parse a JSONB/text column into a dict."""
    if isinstance(val, dict):
        return val
    try:
        return json.loads(val or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------

async def api_analytics_latency(request: Request) -> JSONResponse:
    """GET /api/analytics/latency — P50/P75/P90/P99 pipeline latency.

    Query params:
        days (int, default 30): lookback window (max 90)
        pipeline_type (str, optional): filter by pipeline type
    """
    from .frontend_api import _get_user_from_request, _set_user_context
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    days = min(int(request.query_params.get("days", "30")), 90)
    pipeline_type = request.query_params.get("pipeline_type", None)

    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return JSONResponse({"percentiles": {}, "count": 0})

    try:
        where_clause = "WHERE action = 'pipeline_complete' AND created_at >= NOW() - make_interval(days => :d)"
        params: dict[str, Any] = {"d": days}
        if pipeline_type:
            where_clause += " AND details->>'pipeline_type' = :pt"
            params["pt"] = pipeline_type

        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT details FROM agent_audit_log
                {where_clause}
                ORDER BY created_at DESC LIMIT 1000
            """), params).fetchall()

        durations = []
        for r in rows:
            details = _safe_json(r[0])
            d = details.get("duration_seconds") or details.get("duration", 0)
            if d and isinstance(d, (int, float)) and d > 0:
                durations.append(float(d))

        if not durations:
            return JSONResponse({"percentiles": {}, "count": 0})

        durations.sort()
        n = len(durations)
        percentiles = {
            "p50": round(durations[int(n * 0.50)], 2),
            "p75": round(durations[int(n * 0.75)], 2),
            "p90": round(durations[min(int(n * 0.90), n - 1)], 2),
            "p99": round(durations[min(int(n * 0.99), n - 1)], 2),
        }
        return JSONResponse({
            "percentiles": percentiles,
            "count": n,
            "min": round(min(durations), 2),
            "max": round(max(durations), 2),
            "mean": round(sum(durations) / n, 2),
        })
    except Exception as e:
        logger.warning("analytics/latency error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_analytics_tool_success(request: Request) -> JSONResponse:
    """GET /api/analytics/tool-success — Tool success-rate ranking.

    Query params:
        days (int, default 30): lookback window (max 90)
        limit (int, default 20): max tools returned
    """
    from .frontend_api import _get_user_from_request, _set_user_context
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    days = min(int(request.query_params.get("days", "30")), 90)
    limit = min(int(request.query_params.get("limit", "20")), 100)

    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return JSONResponse({"tools": []})

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT details FROM agent_audit_log
                WHERE action = 'pipeline_complete'
                  AND created_at >= NOW() - make_interval(days => :d)
                ORDER BY created_at DESC LIMIT 2000
            """), {"d": days}).fetchall()

        tool_stats: dict[str, dict] = {}
        for r in rows:
            details = _safe_json(r[0])
            tool_log = details.get("tool_execution_log", [])
            if not isinstance(tool_log, list):
                continue
            for entry in tool_log:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("tool_name", "unknown")
                if name not in tool_stats:
                    tool_stats[name] = {"total": 0, "errors": 0, "total_duration": 0.0}
                tool_stats[name]["total"] += 1
                if entry.get("is_error"):
                    tool_stats[name]["errors"] += 1
                tool_stats[name]["total_duration"] += entry.get("duration", 0) or 0

        tools = []
        for name, stats in tool_stats.items():
            total = stats["total"]
            tools.append({
                "tool_name": name,
                "total_calls": total,
                "errors": stats["errors"],
                "success_rate": round((total - stats["errors"]) / total * 100, 1) if total > 0 else 0,
                "avg_duration": round(stats["total_duration"] / total, 2) if total > 0 else 0,
            })

        tools.sort(key=lambda x: x["total_calls"], reverse=True)
        return JSONResponse({"tools": tools[:limit]})
    except Exception as e:
        logger.warning("analytics/tool-success error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_analytics_token_efficiency(request: Request) -> JSONResponse:
    """GET /api/analytics/token-efficiency — Token usage trend per day.

    Query params:
        days (int, default 30): lookback window (max 90)
    """
    from .frontend_api import _get_user_from_request, _set_user_context
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    days = min(int(request.query_params.get("days", "30")), 90)

    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return JSONResponse({"daily": []})

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DATE(created_at) as day,
                       COUNT(*) as runs,
                       SUM((details->>'input_tokens')::int) as total_input,
                       SUM((details->>'output_tokens')::int) as total_output
                FROM agent_audit_log
                WHERE action = 'pipeline_complete'
                  AND created_at >= NOW() - make_interval(days => :d)
                GROUP BY DATE(created_at)
                ORDER BY day
            """), {"d": days}).fetchall()

        daily = []
        for r in rows:
            total_tokens = (r[2] or 0) + (r[3] or 0)
            daily.append({
                "date": r[0].isoformat() if r[0] else None,
                "runs": r[1] or 0,
                "input_tokens": r[2] or 0,
                "output_tokens": r[3] or 0,
                "total_tokens": total_tokens,
                "tokens_per_run": round(total_tokens / r[1], 0) if r[1] else 0,
            })
        return JSONResponse({"daily": daily})
    except Exception as e:
        logger.warning("analytics/token-efficiency error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_analytics_throughput(request: Request) -> JSONResponse:
    """GET /api/analytics/throughput — Daily pipeline throughput.

    Query params:
        days (int, default 30): lookback window (max 90)
    """
    from .frontend_api import _get_user_from_request, _set_user_context
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    days = min(int(request.query_params.get("days", "30")), 90)

    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return JSONResponse({"daily": [], "total": 0})

    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT DATE(created_at) as day,
                       details->>'pipeline_type' as ptype,
                       COUNT(*) as cnt
                FROM agent_audit_log
                WHERE action = 'pipeline_complete'
                  AND created_at >= NOW() - make_interval(days => :d)
                GROUP BY DATE(created_at), details->>'pipeline_type'
                ORDER BY day
            """), {"d": days}).fetchall()

        by_day: dict[str, dict] = {}
        total = 0
        for r in rows:
            day_str = r[0].isoformat() if r[0] else "unknown"
            if day_str not in by_day:
                by_day[day_str] = {"date": day_str, "total": 0, "by_type": {}}
            by_day[day_str]["total"] += r[2] or 0
            by_day[day_str]["by_type"][r[1] or "unknown"] = r[2] or 0
            total += r[2] or 0

        return JSONResponse({
            "daily": list(by_day.values()),
            "total": total,
        })
    except Exception as e:
        logger.warning("analytics/throughput error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_analytics_agent_breakdown(request: Request) -> JSONResponse:
    """GET /api/analytics/agent-breakdown — Per-agent execution time distribution.

    Query params:
        days (int, default 30): lookback window (max 90)
        pipeline_type (str, optional): filter by pipeline type
    """
    from .frontend_api import _get_user_from_request, _set_user_context
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    days = min(int(request.query_params.get("days", "30")), 90)
    pipeline_type = request.query_params.get("pipeline_type", None)

    from .db_engine import get_engine
    engine = get_engine()
    if not engine:
        return JSONResponse({"agents": []})

    try:
        where_clause = "WHERE action = 'pipeline_complete' AND created_at >= NOW() - make_interval(days => :d)"
        params: dict[str, Any] = {"d": days}
        if pipeline_type:
            where_clause += " AND details->>'pipeline_type' = :pt"
            params["pt"] = pipeline_type

        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT details FROM agent_audit_log
                {where_clause}
                ORDER BY created_at DESC LIMIT 1000
            """), params).fetchall()

        agent_stats: dict[str, dict] = {}
        for r in rows:
            details = _safe_json(r[0])
            tool_log = details.get("tool_execution_log", [])
            if not isinstance(tool_log, list):
                continue
            for entry in tool_log:
                if not isinstance(entry, dict):
                    continue
                agent_name = entry.get("agent_name", "unknown")
                if not agent_name:
                    continue
                if agent_name not in agent_stats:
                    agent_stats[agent_name] = {"total_duration": 0.0, "call_count": 0}
                agent_stats[agent_name]["total_duration"] += entry.get("duration", 0) or 0
                agent_stats[agent_name]["call_count"] += 1

            # Also check provenance_trail for agent-level timing
            provenance = details.get("provenance_trail", [])
            if isinstance(provenance, list):
                for entry in provenance:
                    if not isinstance(entry, dict) or entry.get("type") != "agent":
                        continue
                    agent_name = entry.get("agent", "unknown")
                    if agent_name not in agent_stats:
                        agent_stats[agent_name] = {"total_duration": 0.0, "call_count": 0}
                    # Provenance entries may not have duration yet
                    agent_stats[agent_name]["call_count"] += 1

        agents = []
        for name, stats in agent_stats.items():
            agents.append({
                "agent_name": name,
                "total_duration": round(stats["total_duration"], 2),
                "call_count": stats["call_count"],
                "avg_duration": round(
                    stats["total_duration"] / stats["call_count"], 2
                ) if stats["call_count"] > 0 else 0,
            })

        agents.sort(key=lambda x: x["total_duration"], reverse=True)
        return JSONResponse({"agents": agents})
    except Exception as e:
        logger.warning("analytics/agent-breakdown error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)
