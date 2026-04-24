"""Intake Routes — REST API for the NL2Semantic2SQL cold-start intake pipeline.

Endpoints:
- POST /api/intake/scan          — start a schema scan job
- GET  /api/intake/{job_id}      — get job status
- GET  /api/intake/profiles      — list dataset profiles
- GET  /api/intake/{dataset_id}/draft — get semantic draft
- POST /api/intake/{dataset_id}/draft — generate semantic draft
- POST /api/intake/{draft_id}/review  — submit human review
- POST /api/intake/{draft_id}/activate — activate into production
- POST /api/intake/{dataset_id}/rollback — rollback activation
"""
from __future__ import annotations

import json

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


def _json_response(data, status_code=200):
    """JSONResponse with default=str for datetime serialization."""
    body = json.dumps(data, ensure_ascii=False, default=str)
    return Response(content=body, status_code=status_code, media_type="application/json")


async def _api_intake_scan(request: Request):
    """POST /api/intake/scan — start schema scan."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    schema_name = body.get("schema", "public")
    table_filter = body.get("tables")
    user = getattr(request.state, "user_id", "admin")

    from ..dataset_intake import scan_tables
    result = scan_tables(
        schema_name=schema_name,
        table_filter=table_filter,
        created_by=user,
    )
    code = 200 if result.get("status") == "ok" else 500
    return JSONResponse(result, status_code=code)


async def _api_intake_job(request: Request):
    """GET /api/intake/{job_id} — get job status."""
    job_id = int(request.path_params["job_id"])
    from ..dataset_intake import get_job
    job = get_job(job_id)
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return _json_response(job)


async def _api_intake_profiles(request: Request):
    """GET /api/intake/profiles — list dataset profiles."""
    status = request.query_params.get("status")
    job_id = request.query_params.get("job_id")
    schema_name = request.query_params.get("schema", "public")
    latest_only = request.query_params.get("latest", "1") != "0"
    from ..dataset_intake import list_profiles
    profiles = list_profiles(
        status=status,
        job_id=int(job_id) if job_id else None,
        schema_name=schema_name,
        latest_only=latest_only,
    )
    return _json_response({"profiles": profiles})


async def _api_intake_get_draft(request: Request):
    """GET /api/intake/{dataset_id}/draft — get semantic draft."""
    dataset_id = request.path_params["dataset_id"]
    from ..dataset_intake import get_profile
    from ..semantic_drafting import get_draft

    profile = get_profile(table_name=None, job_id=None)
    # Try by profile ID first, then by table name
    try:
        pid = int(dataset_id)
        from sqlalchemy import text
        from ..db_engine import get_engine
        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT table_name FROM agent_dataset_profiles WHERE id = :pid"
            ), {"pid": pid}).fetchone()
            tbl = row[0] if row else dataset_id
    except (ValueError, Exception):
        tbl = dataset_id

    draft = get_draft(tbl)
    if not draft:
        return JSONResponse({"error": "no draft found"}, status_code=404)
    return _json_response(draft)


async def _api_intake_generate_draft(request: Request):
    """POST /api/intake/{dataset_id}/draft — generate semantic draft."""
    dataset_id = int(request.path_params["dataset_id"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    use_llm = body.get("use_llm", True)

    from ..semantic_drafting import generate_draft
    result = generate_draft(profile_id=dataset_id, use_llm=use_llm)
    if not result:
        return JSONResponse({"error": "profile not found"}, status_code=404)
    return _json_response(result)


async def _api_intake_review(request: Request):
    """POST /api/intake/{draft_id}/review — submit human review."""
    draft_id = int(request.path_params["draft_id"])
    try:
        body = await request.json()
    except Exception:
        body = {}

    user = getattr(request.state, "user_id", "admin")
    from ..intake_registry import review_draft
    result = review_draft(
        draft_id=draft_id,
        approved_columns=body.get("approved_columns"),
        blocked_columns=body.get("blocked_columns"),
        approved_joins=body.get("approved_joins"),
        notes=body.get("notes", ""),
        reviewed_by=user,
    )
    code = 200 if result.get("status") == "ok" else 400
    return JSONResponse(result, status_code=code)


async def _api_intake_activate(request: Request):
    """POST /api/intake/{draft_id}/activate — activate into production.

    Requires eval_score >= 0.8 (from prior validation) or force=true.
    """
    draft_id = int(request.path_params["draft_id"])
    try:
        body = await request.json()
    except Exception:
        body = {}

    force = body.get("force", False)
    eval_score = body.get("eval_score")

    if not force and (eval_score is None or eval_score < 0.8):
        return JSONResponse({
            "status": "error",
            "error": "eval_score >= 0.8 required for activation. Run /api/intake/{dataset_id}/validate first, or pass force=true.",
        }, status_code=400)

    user = getattr(request.state, "user_id", "admin")
    from ..intake_registry import activate_draft
    result = activate_draft(
        draft_id=draft_id,
        eval_score=eval_score,
        eval_details=body.get("eval_details"),
        activated_by=user,
    )
    code = 200 if result.get("status") == "ok" else 400
    return _json_response(result)


async def _api_intake_validate(request: Request):
    """POST /api/intake/{dataset_id}/validate — run cold-start validation."""
    dataset_id = int(request.path_params["dataset_id"])
    from ..intake_validation import validate_dataset
    result = validate_dataset(profile_id=dataset_id)
    code = 200 if result.get("status") == "ok" else 400
    return _json_response(result)


async def _api_intake_rollback(request: Request):
    """POST /api/intake/{dataset_id}/rollback — rollback activation."""
    dataset_id = int(request.path_params["dataset_id"])
    from ..intake_registry import rollback_activation
    result = rollback_activation(dataset_id=dataset_id)
    code = 200 if result.get("status") == "ok" else 400
    return _json_response(result)


def get_intake_routes() -> list[Route]:
    return [
        Route("/api/intake/scan", endpoint=_api_intake_scan, methods=["POST"]),
        Route("/api/intake/profiles", endpoint=_api_intake_profiles, methods=["GET"]),
        Route("/api/intake/{job_id:int}", endpoint=_api_intake_job, methods=["GET"]),
        Route("/api/intake/{dataset_id}/draft", endpoint=_api_intake_get_draft, methods=["GET"]),
        Route("/api/intake/{dataset_id:int}/draft", endpoint=_api_intake_generate_draft, methods=["POST"]),
        Route("/api/intake/{draft_id:int}/review", endpoint=_api_intake_review, methods=["POST"]),
        Route("/api/intake/{draft_id:int}/activate", endpoint=_api_intake_activate, methods=["POST"]),
        Route("/api/intake/{dataset_id:int}/validate", endpoint=_api_intake_validate, methods=["POST"]),
        Route("/api/intake/{dataset_id:int}/rollback", endpoint=_api_intake_rollback, methods=["POST"]),
    ]
