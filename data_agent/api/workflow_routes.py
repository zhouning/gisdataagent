"""Workflow CRUD + execution routes — extracted from frontend_api.py (S-4 refactoring v12.1)."""

import logging
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.workflow_routes")


async def workflows_list(request: Request):
    """GET /api/workflows — list workflows visible to current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    keyword = request.query_params.get("keyword", "")
    from ..workflow_engine import list_workflows
    workflows = list_workflows(keyword=keyword)
    return JSONResponse({"workflows": workflows})


async def workflows_create(request: Request):
    """POST /api/workflows — create a new workflow."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    name = body.get("workflow_name", "").strip()
    if not name:
        return JSONResponse({"error": "workflow_name is required"}, status_code=400)

    from ..workflow_engine import create_workflow
    wf_id = create_workflow(
        name=name,
        description=body.get("description", ""),
        steps=body.get("steps", []),
        parameters=body.get("parameters", {}),
        graph_data=body.get("graph_data", {}),
        cron_schedule=body.get("cron_schedule"),
        webhook_url=body.get("webhook_url"),
        pipeline_type=body.get("pipeline_type", "general"),
    )
    if wf_id is None:
        return JSONResponse({"error": "Failed to create workflow"}, status_code=500)
    return JSONResponse({"id": wf_id, "workflow_name": name}, status_code=201)


async def workflow_detail(request: Request):
    """GET /api/workflows/{id} — get workflow detail."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    wf_id = int(request.path_params["id"])
    from ..workflow_engine import get_workflow
    wf = get_workflow(wf_id)
    if not wf:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    return JSONResponse(wf)


async def workflow_update(request: Request):
    """PUT /api/workflows/{id} — update workflow."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    wf_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    from ..workflow_engine import update_workflow
    ok = update_workflow(wf_id, **body)
    if not ok:
        return JSONResponse({"error": "Update failed or not authorized"}, status_code=403)
    return JSONResponse({"status": "ok"})


async def workflow_delete(request: Request):
    """DELETE /api/workflows/{id} — delete workflow (owner only)."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    wf_id = int(request.path_params["id"])
    from ..workflow_engine import delete_workflow
    ok = delete_workflow(wf_id)
    if not ok:
        return JSONResponse({"error": "Delete failed or not authorized"}, status_code=403)
    return JSONResponse({"status": "ok"})


async def workflow_execute(request: Request):
    """POST /api/workflows/{id}/execute — execute workflow."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    wf_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    param_overrides = body.get("parameters", {})
    from ..workflow_engine import execute_workflow, execute_workflow_dag, get_workflow, _is_dag_workflow
    workflow = get_workflow(wf_id)
    steps = workflow.get("steps", []) if workflow else []
    if _is_dag_workflow(steps):
        result = await execute_workflow_dag(workflow_id=wf_id, param_overrides=param_overrides, run_by=username)
    else:
        result = await execute_workflow(workflow_id=wf_id, param_overrides=param_overrides, run_by=username)
    status_code = 200 if result.get("status") == "completed" else 500
    return JSONResponse(result, status_code=status_code)


async def workflow_runs(request: Request):
    """GET /api/workflows/{id}/runs — get execution history."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    wf_id = int(request.path_params["id"])
    limit = int(request.query_params.get("limit", "20"))
    from ..workflow_engine import get_workflow_runs
    runs = get_workflow_runs(wf_id, limit=limit)
    return JSONResponse({"runs": runs})


async def workflow_run_status(request: Request):
    """GET /api/workflows/{id}/runs/{run_id}/status — live per-node DAG execution status."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = int(request.path_params["run_id"])
    from ..workflow_engine import get_live_run_status
    status = get_live_run_status(run_id)
    if status is None:
        return JSONResponse({"error": "Run not found or already completed"}, status_code=404)
    return JSONResponse(status)


def get_workflow_routes() -> list:
    """Return Route objects for workflow endpoints."""
    return [
        Route("/api/workflows", workflows_list, methods=["GET"]),
        Route("/api/workflows", workflows_create, methods=["POST"]),
        Route("/api/workflows/{id:int}", workflow_detail, methods=["GET"]),
        Route("/api/workflows/{id:int}", workflow_update, methods=["PUT"]),
        Route("/api/workflows/{id:int}", workflow_delete, methods=["DELETE"]),
        Route("/api/workflows/{id:int}/execute", workflow_execute, methods=["POST"]),
        Route("/api/workflows/{id:int}/runs", workflow_runs, methods=["GET"]),
        Route("/api/workflows/{id:int}/runs/{run_id:int}/status", workflow_run_status, methods=["GET"]),
    ]
