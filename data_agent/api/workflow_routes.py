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


async def workflow_retry_node(request: Request):
    """POST /api/workflows/{id}/runs/{run_id}/retry — retry a single failed node."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    run_id = int(request.path_params.get("run_id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    step_id = body.get("step_id", "")
    if not step_id:
        return JSONResponse({"error": "step_id is required"}, status_code=400)
    from ..workflow_engine import retry_workflow_node
    result = await retry_workflow_node(run_id, step_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result)


async def workflow_run_checkpoint(request: Request):
    """GET /api/workflows/{id}/runs/{run_id}/checkpoint — get checkpoint data."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = int(request.path_params.get("run_id", 0))
    from ..workflow_engine import get_run_checkpoint
    cp = get_run_checkpoint(run_id)
    if not cp:
        return JSONResponse({"error": "Checkpoint not found"}, status_code=404)
    return JSONResponse(cp)


async def workflow_resume(request: Request):
    """POST /api/workflows/{id}/runs/{run_id}/resume — resume failed/paused DAG from checkpoint."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    run_id = int(request.path_params.get("run_id", 0))
    from ..workflow_engine import resume_workflow_dag
    result = await resume_workflow_dag(run_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result["message"]}, status_code=400)
    return JSONResponse(result)


async def qc_templates_list(request: Request):
    """GET /api/workflows/qc-templates — list available QC workflow templates."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from ..workflow_engine import list_qc_templates
    return JSONResponse({"templates": list_qc_templates()})


async def qc_template_create(request: Request):
    """POST /api/workflows/from-template — create workflow from QC template."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    template_id = body.get("template_id", "").strip()
    if not template_id:
        return JSONResponse({"error": "template_id is required"}, status_code=400)

    from ..workflow_engine import create_workflow_from_template
    wf_id = create_workflow_from_template(
        template_id=template_id,
        name_override=body.get("name", ""),
        param_overrides=body.get("parameters"),
    )
    if wf_id is None:
        return JSONResponse({"error": f"Template '{template_id}' not found or creation failed"}, status_code=404)
    return JSONResponse({"id": wf_id, "template_id": template_id}, status_code=201)


async def qc_template_create_and_execute(request: Request):
    """POST /api/workflows/from-template-and-execute — create from template + immediately execute."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    template_id = body.get("template_id", "").strip()
    if not template_id:
        return JSONResponse({"error": "template_id is required"}, status_code=400)

    params = body.get("parameters") or {}

    from ..workflow_engine import create_workflow_from_template, execute_workflow
    wf_id = create_workflow_from_template(
        template_id=template_id,
        name_override=body.get("name", ""),
        param_overrides=params,
    )
    if wf_id is None:
        return JSONResponse({"error": f"Template '{template_id}' not found or creation failed"}, status_code=404)

    # Execute immediately in background
    import asyncio
    result = {"workflow_id": wf_id, "run_id": None, "status": "started"}

    async def _run():
        try:
            await execute_workflow(wf_id, param_overrides=params)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("from-template-and-execute failed: %s", e)

    asyncio.create_task(_run())

    # Return immediately — frontend can poll for status
    from ..workflow_engine import get_workflow_runs
    import time
    # Small delay to let run record be created
    await asyncio.sleep(0.3)
    runs = get_workflow_runs(wf_id, limit=1)
    if runs:
        result["run_id"] = runs[0]["id"]

    return JSONResponse(result, status_code=201)


def get_workflow_routes() -> list:
    """Return Route objects for workflow endpoints."""
    return [
        Route("/api/workflows", workflows_list, methods=["GET"]),
        Route("/api/workflows", workflows_create, methods=["POST"]),
        Route("/api/workflows/qc-templates", qc_templates_list, methods=["GET"]),
        Route("/api/workflows/from-template", qc_template_create, methods=["POST"]),
        Route("/api/workflows/from-template-and-execute", qc_template_create_and_execute, methods=["POST"]),
        Route("/api/workflows/{id:int}", workflow_detail, methods=["GET"]),
        Route("/api/workflows/{id:int}", workflow_update, methods=["PUT"]),
        Route("/api/workflows/{id:int}", workflow_delete, methods=["DELETE"]),
        Route("/api/workflows/{id:int}/execute", workflow_execute, methods=["POST"]),
        Route("/api/workflows/{id:int}/runs", workflow_runs, methods=["GET"]),
        Route("/api/workflows/{id:int}/runs/{run_id:int}/status", workflow_run_status, methods=["GET"]),
        Route("/api/workflows/{id:int}/runs/{run_id:int}/retry", workflow_retry_node, methods=["POST"]),
        Route("/api/workflows/{id:int}/runs/{run_id:int}/checkpoint", workflow_run_checkpoint, methods=["GET"]),
        Route("/api/workflows/{id:int}/runs/{run_id:int}/resume", workflow_resume, methods=["POST"]),
    ]
