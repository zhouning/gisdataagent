"""Self-evolution admin REST routes."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _require_admin


def _int_query(request: Request, name: str, default: int) -> int:
    try:
        return int(request.query_params.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_body(body: dict, name: str, default: float) -> float:
    try:
        return float(body.get(name, default))
    except (TypeError, ValueError):
        return default


async def _api_self_evolution_cycles(request: Request):
    """GET /api/self-evolution/cycles — list recent cycle audit records."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    limit = _int_query(request, "limit", 50)
    status = request.query_params.get("status") or None
    from ..self_evolution import list_cycles

    return JSONResponse({
        "cycles": list_cycles(limit=limit, status=status),
        "limit": limit,
        "status": status,
    })


async def _api_self_evolution_cycle_detail(request: Request):
    """GET /api/self-evolution/cycles/{id} — return one full cycle report."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    from ..self_evolution import get_cycle

    cycle = get_cycle(request.path_params["id"])
    if not cycle:
        return JSONResponse({"error": "cycle not found"}, status_code=404)
    return JSONResponse(cycle)


async def _api_self_evolution_review_summary(request: Request):
    """GET /api/self-evolution/review-summary — pending review reminders."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    from ..self_evolution import get_review_summary

    return JSONResponse(get_review_summary(limit=_int_query(request, "limit", 5)))


async def _api_self_evolution_run(request: Request):
    """POST /api/self-evolution/run — run and persist one dry-run cycle by default."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    from ..self_evolution import SelfEvolutionEngine

    result = await SelfEvolutionEngine().run_cycle(
        limit=body.get("limit", 50),
        days=body.get("days", 7),
        min_score=_float_body(body, "min_score", 0.5),
        include_prompt_suggestions=body.get("include_prompt_suggestions", False),
        apply=body.get("apply", False),
        environment=body.get("environment", "dev"),
        persist=body.get("persist", True),
        triggered_by=body.get("triggered_by") or username or "",
        trigger_source=body.get("trigger_source", "api"),
    )
    return JSONResponse(result)


async def _api_self_evolution_review(request: Request):
    """POST /api/self-evolution/cycles/{id}/review — apply a reviewed action."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    action = body.get("action", "")
    if not action:
        return JSONResponse({"error": "action required"}, status_code=400)

    from ..self_evolution import review_cycle_action

    result = review_cycle_action(
        request.path_params["id"],
        action=action,
        reviewed_by=body.get("reviewed_by") or username or "",
        environment=body.get("environment", "dev"),
        target_environment=body.get("target_environment", "prod"),
        dataset_name=body.get("dataset_name", ""),
        notes=body.get("notes", ""),
    )
    if result.get("status") == "error":
        return JSONResponse({"error": result.get("message", "review action failed"), **result}, status_code=400)
    return JSONResponse(result)


async def _api_self_evolution_scheduler_status(request: Request):
    """GET /api/self-evolution/scheduler — scheduler status."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    from ..self_evolution_scheduler import get_self_evolution_scheduler

    return JSONResponse(get_self_evolution_scheduler().status())


async def _api_self_evolution_scheduler_control(request: Request):
    """POST /api/self-evolution/scheduler — start/stop/run-once scheduler."""
    user, username, role, err = _require_admin(request)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    action = body.get("action", "status")

    from ..self_evolution_scheduler import get_self_evolution_scheduler

    scheduler = get_self_evolution_scheduler()
    if action == "start":
        scheduler.enabled = True
        started = scheduler.start()
        return JSONResponse({"status": "success", "started": started, "scheduler": scheduler.status()})
    if action == "stop":
        scheduler.enabled = False
        await scheduler.stop()
        return JSONResponse({"status": "success", "stopped": True, "scheduler": scheduler.status()})
    if action in {"run_once", "run-now"}:
        result = await scheduler.run_once()
        return JSONResponse({"status": result.get("status", "success"), "result": result, "scheduler": scheduler.status()})
    if action == "status":
        return JSONResponse({"status": "success", "scheduler": scheduler.status()})
    return JSONResponse({"error": f"unsupported action: {action}"}, status_code=400)


def get_self_evolution_routes() -> list[Route]:
    return [
        Route("/api/self-evolution/cycles", endpoint=_api_self_evolution_cycles, methods=["GET"]),
        Route("/api/self-evolution/review-summary", endpoint=_api_self_evolution_review_summary, methods=["GET"]),
        Route("/api/self-evolution/cycles/{id:int}", endpoint=_api_self_evolution_cycle_detail, methods=["GET"]),
        Route("/api/self-evolution/cycles/{id:int}/review", endpoint=_api_self_evolution_review, methods=["POST"]),
        Route("/api/self-evolution/run", endpoint=_api_self_evolution_run, methods=["POST"]),
        Route("/api/self-evolution/scheduler", endpoint=_api_self_evolution_scheduler_status, methods=["GET"]),
        Route("/api/self-evolution/scheduler", endpoint=_api_self_evolution_scheduler_control, methods=["POST"]),
    ]
