"""
Health check and system diagnostics module.

Provides subsystem probes (database, cloud storage, Redis, session service),
aggregated health endpoints for K8s liveness/readiness probes, and a startup
diagnostics banner.
"""

import os
import platform
import sys
import time

from .db_engine import get_engine
from .cloud_storage import get_cloud_adapter
from .stream_engine import get_stream_engine

_start_time = time.time()


# ---------------------------------------------------------------------------
# Individual subsystem checks
# ---------------------------------------------------------------------------

def check_database() -> dict:
    """Check PostgreSQL connectivity via get_engine() + SELECT 1."""
    engine = get_engine()
    if engine is None:
        return {"status": "unconfigured", "latency_ms": 0, "detail": "No database credentials"}

    try:
        from sqlalchemy import text
        t0 = time.time()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency = round((time.time() - t0) * 1000, 1)
        return {"status": "ok", "latency_ms": latency, "detail": "Connected"}
    except Exception as e:
        return {"status": "error", "latency_ms": 0, "detail": str(e)}


def check_cloud_storage() -> dict:
    """Check cloud storage via adapter health_check()."""
    adapter = get_cloud_adapter()
    if adapter is None:
        return {"status": "unconfigured", "provider": "", "bucket": ""}

    try:
        provider = type(adapter).__name__.replace("Adapter", "")
        bucket = getattr(adapter, "get_bucket_name", lambda: "")()
        healthy = adapter.health_check()
        if healthy:
            return {"status": "ok", "provider": provider, "bucket": bucket}
        return {"status": "error", "provider": provider, "bucket": bucket}
    except Exception as e:
        return {"status": "error", "provider": "", "bucket": "", "detail": str(e)}


def check_redis() -> dict:
    """Check Redis connectivity via redis_client (v20.0)."""
    try:
        from .redis_client import check_redis_health
        return check_redis_health()
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def check_session_service(session_svc=None) -> dict:
    """Check if session service is DB-backed or in-memory fallback."""
    if session_svc is None:
        return {"status": "unconfigured", "backend": "unknown"}

    class_name = type(session_svc).__name__
    if "Database" in class_name:
        return {"status": "ok", "backend": "postgresql"}
    if "InMemory" in class_name:
        return {"status": "degraded", "backend": "memory"}
    return {"status": "ok", "backend": class_name}


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def _get_feature_flags() -> dict:
    """Collect enabled/disabled feature flags."""
    flags = {}

    # Dynamic planner
    flags["dynamic_planner"] = os.environ.get(
        "DYNAMIC_PLANNER", "true"
    ).lower() in ("true", "1", "yes")

    # ArcPy
    try:
        from .toolsets.geo_processing_tools import ARCPY_AVAILABLE
        flags["arcpy"] = ARCPY_AVAILABLE
    except Exception:
        flags["arcpy"] = False

    # Cloud storage
    try:
        flags["cloud_storage"] = get_cloud_adapter() is not None
    except Exception:
        flags["cloud_storage"] = False

    # Streaming
    try:
        from .stream_engine import HAS_REDIS
        flags["streaming_redis"] = HAS_REDIS
    except Exception:
        flags["streaming_redis"] = False

    # World Model
    flags["world_model"] = os.environ.get(
        "WORLD_MODEL_ENABLED", "true"
    ).lower() in ("true", "1", "yes")

    # Bots
    for bot_name, module_name, func_name in [
        ("wecom", "wecom_bot", "is_wecom_configured"),
        ("dingtalk", "dingtalk_bot", "is_dingtalk_configured"),
        ("feishu", "feishu_bot", "is_feishu_configured"),
    ]:
        try:
            import importlib
            mod = importlib.import_module(f".{module_name}", package="data_agent")
            flags[bot_name] = getattr(mod, func_name)()
        except Exception:
            flags[bot_name] = False

    return flags


def check_mcp_hub() -> dict:
    """Check MCP Hub connection status."""
    try:
        from .mcp_hub import get_mcp_hub
        hub = get_mcp_hub()
        statuses = hub.get_server_statuses()
        connected = sum(1 for s in statuses if s["status"] == "connected")
        enabled = sum(1 for s in statuses if s.get("enabled", True))
        total = len(statuses)
        if total == 0:
            return {"status": "unconfigured", "connected": 0, "enabled": 0, "total": 0}
        if enabled == 0:
            return {"status": "all_disabled", "connected": 0, "enabled": 0, "total": total}
        return {
            "status": "ok" if connected > 0 else "disconnected",
            "connected": connected,
            "enabled": enabled,
            "total": total,
        }
    except Exception:
        return {"status": "unconfigured", "connected": 0, "enabled": 0, "total": 0}


# ---------------------------------------------------------------------------
# Aggregated endpoints
# ---------------------------------------------------------------------------

def liveness_check() -> dict:
    """Lightweight liveness: confirms process is alive."""
    uptime = round(time.time() - _start_time, 1)
    return {"status": "ok", "uptime_seconds": uptime}


def readiness_check() -> dict:
    """Readiness: checks critical subsystem (database).

    Database is the critical dependency — if it's down, the pod should not
    receive traffic. Cloud storage and Redis are optional.
    """
    db = check_database()
    if db["status"] == "ok":
        return {"status": "ok", "checks": {"database": db}}
    if db["status"] == "unconfigured":
        # DB not configured → degraded but still ready (local-only mode)
        return {"status": "ok", "checks": {"database": db}}
    return {"status": "not_ready", "checks": {"database": db}}


def get_system_status(session_svc=None) -> dict:
    """Comprehensive system status for admin dashboard."""
    return {
        "version": _get_version(),
        "uptime_seconds": round(time.time() - _start_time, 1),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "features": _get_feature_flags(),
        "subsystems": {
            "database": check_database(),
            "cloud_storage": check_cloud_storage(),
            "redis": check_redis(),
            "session_service": check_session_service(session_svc),
            "mcp_hub": check_mcp_hub(),
        },
    }


def _get_version() -> str:
    """Get application version from package or fallback."""
    try:
        from . import __version__
        return __version__
    except (ImportError, AttributeError):
        pass
    return "4.0-beta"


# ---------------------------------------------------------------------------
# Startup diagnostics banner
# ---------------------------------------------------------------------------

def format_startup_summary(session_svc=None) -> str:
    """Format a startup diagnostics banner with all subsystem statuses."""
    db = check_database()
    cloud = check_cloud_storage()
    redis = check_redis()
    session = check_session_service(session_svc)
    flags = _get_feature_flags()

    def _icon(status):
        return "OK" if status in ("ok",) else ("--" if status in ("unconfigured", "degraded", "all_disabled") else "!!")

    lines = [
        "=" * 50,
        "  GIS Data Agent — System Status",
        "=" * 50,
    ]

    # Database
    db_detail = f"Connected ({db['latency_ms']}ms)" if db["status"] == "ok" else (
        "Not configured" if db["status"] == "unconfigured" else f"ERROR: {db.get('detail', '')}"
    )
    lines.append(f"  [{_icon(db['status'])}] Database:       {db_detail}")

    # Cloud storage
    if cloud["status"] == "ok":
        cloud_detail = f"{cloud['provider']} ({cloud['bucket']})"
    elif cloud["status"] == "unconfigured":
        cloud_detail = "Not configured"
    else:
        cloud_detail = f"ERROR: {cloud.get('detail', 'health check failed')}"
    lines.append(f"  [{_icon(cloud['status'])}] Cloud Storage:  {cloud_detail}")

    # Redis
    redis_detail = "Connected" if redis["status"] == "ok" else (
        "Not configured" if redis["status"] == "unconfigured" else f"ERROR: {redis.get('detail', '')}"
    )
    lines.append(f"  [{_icon(redis['status'])}] Redis:          {redis_detail}")

    # Session service
    session_detail = f"{session['backend']}" + (" (fallback)" if session["status"] == "degraded" else "")
    lines.append(f"  [{_icon(session['status'])}] Session:        {session_detail}")

    # MCP Hub
    mcp = check_mcp_hub()
    if mcp["status"] == "unconfigured":
        mcp_detail = "Not configured"
    elif mcp["status"] == "all_disabled":
        mcp_detail = f"{mcp['total']} servers configured (all disabled)"
    elif mcp["status"] == "ok":
        mcp_detail = f"{mcp['connected']}/{mcp['enabled']} servers connected"
    else:
        mcp_detail = f"0/{mcp['enabled']} servers connected"
    lines.append(f"  [{_icon(mcp['status'])}] MCP Hub:        {mcp_detail}")

    lines.append("-" * 50)

    # Feature flags
    lines.append(f"  Dynamic Planner: {'Yes' if flags.get('dynamic_planner') else 'No'}")
    lines.append(f"  ArcPy Engine:    {'Yes' if flags.get('arcpy') else 'No'}")

    # Bots
    bots = []
    for name in ("wecom", "dingtalk", "feishu"):
        if flags.get(name):
            bots.append(name)
    lines.append(f"  Bots:            {', '.join(bots) if bots else 'None configured'}")

    lines.append("=" * 50)
    return "\n".join(lines)
