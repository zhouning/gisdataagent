"""Custom Skills CRUD routes — extracted from frontend_api.py (S-4 refactoring v12.1)."""

import logging
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.skills_routes")


async def skills_list(request: Request):
    """GET /api/skills — list custom skills for current user."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..custom_skills import list_custom_skills
    skills = list_custom_skills(include_shared=True)
    return JSONResponse({"skills": skills})


async def skills_create(request: Request):
    """POST /api/skills — create a custom skill."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from ..custom_skills import (
        validate_skill_name, validate_instruction, validate_toolset_names,
        create_custom_skill, VALID_MODEL_TIERS,
    )
    err = validate_skill_name(body.get("skill_name", ""))
    if err:
        return JSONResponse({"error": err}, status_code=400)
    err = validate_instruction(body.get("instruction", ""))
    if err:
        return JSONResponse({"error": err}, status_code=400)
    err = validate_toolset_names(body.get("toolset_names") or [])
    if err:
        return JSONResponse({"error": err}, status_code=400)
    model_tier = body.get("model_tier", "standard")
    if model_tier not in VALID_MODEL_TIERS:
        return JSONResponse({"error": f"model_tier must be one of {sorted(VALID_MODEL_TIERS)}"}, status_code=400)

    skill_id = create_custom_skill(
        skill_name=body["skill_name"].strip(),
        instruction=body["instruction"].strip(),
        description=body.get("description", ""),
        toolset_names=body.get("toolset_names") or [],
        model_tier=model_tier,
        output_mode=body.get("output_mode", ""),
        is_shared=body.get("is_shared", False),
    )
    if skill_id is None:
        return JSONResponse({"error": "Failed to create skill"}, status_code=500)

    try:
        from ..audit_logger import record_audit, ACTION_CUSTOM_SKILL_CREATE
        record_audit(ACTION_CUSTOM_SKILL_CREATE, details={"id": skill_id, "name": body["skill_name"]})
    except Exception:
        pass

    return JSONResponse({"id": skill_id, "skill_name": body["skill_name"].strip()}, status_code=201)


async def skills_detail(request: Request):
    """GET /api/skills/{id} — get skill detail."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    skill_id = request.path_params.get("id", 0)
    from ..custom_skills import get_custom_skill
    skill = get_custom_skill(int(skill_id))
    if not skill:
        return JSONResponse({"error": "Skill not found"}, status_code=404)
    return JSONResponse(skill)


async def skills_update(request: Request):
    """PUT /api/skills/{id} — update a custom skill."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    skill_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    from ..custom_skills import (
        validate_skill_name, validate_instruction, validate_toolset_names,
        update_custom_skill, VALID_MODEL_TIERS,
    )
    if "skill_name" in body:
        err = validate_skill_name(body["skill_name"])
        if err:
            return JSONResponse({"error": err}, status_code=400)
    if "instruction" in body:
        err = validate_instruction(body["instruction"])
        if err:
            return JSONResponse({"error": err}, status_code=400)
    if "toolset_names" in body:
        err = validate_toolset_names(body["toolset_names"] or [])
        if err:
            return JSONResponse({"error": err}, status_code=400)
    if "model_tier" in body and body["model_tier"] not in VALID_MODEL_TIERS:
        return JSONResponse({"error": f"model_tier must be one of {sorted(VALID_MODEL_TIERS)}"}, status_code=400)

    ok = update_custom_skill(skill_id, **body)
    if not ok:
        return JSONResponse({"error": "Skill not found or not owned by you"}, status_code=404)

    try:
        from ..audit_logger import record_audit, ACTION_CUSTOM_SKILL_UPDATE
        record_audit(ACTION_CUSTOM_SKILL_UPDATE, details={"id": skill_id})
    except Exception:
        pass

    return JSONResponse({"ok": True})


async def skills_delete(request: Request):
    """DELETE /api/skills/{id} — delete a custom skill."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    skill_id = int(request.path_params.get("id", 0))
    from ..custom_skills import delete_custom_skill
    ok = delete_custom_skill(skill_id)
    if not ok:
        return JSONResponse({"error": "Skill not found or not owned by you"}, status_code=404)

    try:
        from ..audit_logger import record_audit, ACTION_CUSTOM_SKILL_DELETE
        record_audit(ACTION_CUSTOM_SKILL_DELETE, details={"id": skill_id})
    except Exception:
        pass

    return JSONResponse({"ok": True})


def get_skills_routes() -> list:
    """Return Route objects for custom skills endpoints."""
    return [
        Route("/api/skills", skills_list, methods=["GET"]),
        Route("/api/skills", skills_create, methods=["POST"]),
        Route("/api/skills/{id:int}", skills_detail, methods=["GET"]),
        Route("/api/skills/{id:int}", skills_update, methods=["PUT"]),
        Route("/api/skills/{id:int}", skills_delete, methods=["DELETE"]),
    ]
