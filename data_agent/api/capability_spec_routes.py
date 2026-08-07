"""Read-only API for machine-verifiable platform capability truth."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..capability_registry import (
    CAPABILITY_REGISTRY_SCHEMA,
    CapabilityNotFoundError,
    LlmMode,
    Surface,
    get_capability_registry,
)
from .helpers import _get_user_from_request, _set_user_context


def _authenticated(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    return user, None


async def capability_specs_list(request: Request):
    """List registered contracts filtered by available runtime surface."""
    _, error = _authenticated(request)
    if error is not None:
        return error
    try:
        llm_mode = LlmMode(request.query_params.get("llm_mode", LlmMode.OPTIONAL))
        surface_value = request.query_params.get("surface")
        surface = Surface(surface_value) if surface_value else None
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    registry = get_capability_registry()
    specs = registry.list_specs(surface=surface, llm_mode=llm_mode)
    return JSONResponse({
        "schema": CAPABILITY_REGISTRY_SCHEMA,
        "fingerprint": registry.fingerprint,
        "llm_mode": llm_mode.value,
        "surface": surface.value if surface else None,
        "count": len(specs),
        "capabilities": [
            {
                "capability_id": spec.capability_id,
                "version": spec.version,
                "title": spec.title,
                "tier": spec.tier,
                "lifecycle": spec.lifecycle.value,
                "operation": spec.operation.value,
                "fingerprint": spec.fingerprint,
                "available_surfaces": [
                    item.value for item in spec.available_surfaces(llm_mode)
                ],
            }
            for spec in specs
        ],
    })


async def capability_spec_detail(request: Request):
    """Return one canonical spec with generated protocol projections."""
    _, error = _authenticated(request)
    if error is not None:
        return error
    capability_id = request.path_params["capability_id"]
    version = request.query_params.get("version")
    try:
        spec = get_capability_registry().get(capability_id, version)
    except CapabilityNotFoundError:
        return JSONResponse({"error": "Capability not found"}, status_code=404)

    projections = {}
    if spec.http is not None:
        projections["openapi"] = spec.openapi_projection()
    if spec.mcp is not None:
        projections["mcp"] = spec.mcp_projection()
    if spec.async_api is not None:
        projections["asyncapi"] = spec.asyncapi_projection()
    return JSONResponse({
        "spec": spec.model_dump(mode="json", by_alias=True),
        "fingerprint": spec.fingerprint,
        "projections": projections,
    })


def get_capability_spec_routes():
    return [
        Route(
            "/api/capability-specs",
            endpoint=capability_specs_list,
            methods=["GET"],
        ),
        Route(
            "/api/capability-specs/{capability_id:str}",
            endpoint=capability_spec_detail,
            methods=["GET"],
        ),
    ]
