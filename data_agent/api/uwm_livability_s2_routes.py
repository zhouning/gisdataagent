"""Snapshot-backed API routes for UWM livability S2 scenarios."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.livability_s2.scenario_service import (
    S2ProductInvalid,
    S2RunNotFound,
    S2ScenarioService,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRODUCT_DIR = (
    ROOT / "data/uwm_public_proxy/chongqing_central/uwm_livability_s2_fulu"
)
_SERVICE_CACHE: tuple[Path, S2ScenarioService] | None = None


def _product_dir() -> Path:
    configured = os.environ.get("UWM_LIVABILITY_S2_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_PRODUCT_DIR


def _service() -> S2ScenarioService:
    global _SERVICE_CACHE
    path = _product_dir()
    if _SERVICE_CACHE is None or _SERVICE_CACHE[0] != path:
        _SERVICE_CACHE = (path, S2ScenarioService(path))
    return _SERVICE_CACHE[1]


def _reset_service_cache() -> None:
    global _SERVICE_CACHE
    _SERVICE_CACHE = None


def _authorized(request: Request) -> tuple[str | None, JSONResponse | None]:
    user = _get_user_from_request(request)
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    return username, None


async def _json_body(request: Request) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        payload = await request.json()
    except Exception:
        return None, JSONResponse({"error": "Invalid JSON payload"}, status_code=400)
    if not isinstance(payload, dict):
        return None, JSONResponse({"error": "Request object required"}, status_code=400)
    return payload, None


def _product_error(error: Exception) -> JSONResponse:
    return JSONResponse(
        {
            "schema": "uwm.livability_s2.unavailable.v1",
            "ready": False,
            "blockers": [str(error)],
            "claim_boundary": {
                "max_claim_level": "bounded_action_conditioned_spatial_scenario"
            },
        },
        status_code=503,
    )


async def uwm_livability_s2_catalog(request: Request):
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().catalog))
    except S2ProductInvalid as error:
        return _product_error(error)


async def uwm_livability_s2_parcels(request: Request):
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().list_parcels))
    except S2ProductInvalid as error:
        return _product_error(error)


async def uwm_livability_s2_parcel(request: Request):
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        result = await asyncio.to_thread(
            _service().parcel_detail, str(request.path_params.get("parcel_id") or "")
        )
        return JSONResponse(result)
    except S2ProductInvalid as error:
        return _product_error(error)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=404)


async def uwm_livability_s2_validate_action(request: Request):
    username, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    payload, invalid = await _json_body(request)
    if invalid:
        return invalid
    try:
        result = await asyncio.to_thread(
            _service().validate_action,
            parcel_id=str(payload.get("parcel_id") or ""),
            from_land_use_class=str(payload.get("from_land_use_class") or ""),
            to_land_use_class=str(payload.get("to_land_use_class") or ""),
            snapshot_digest=str(payload.get("snapshot_digest") or ""),
            rationale=str(payload.get("rationale") or ""),
            requested_at=str(payload.get("requested_at") or ""),
            actor_id=str(username),
        )
        status = 200 if result["validation"]["valid"] else 400
        if "snapshot_digest_mismatch" in result["validation"]["errors"]:
            status = 409
        return JSONResponse(result, status_code=status)
    except S2ProductInvalid as error:
        return _product_error(error)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=404)


async def uwm_livability_s2_rollout(request: Request):
    username, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    payload, invalid = await _json_body(request)
    if invalid:
        return invalid
    try:
        result = await asyncio.to_thread(
            _service().rollout,
            parcel_id=str(payload.get("parcel_id") or ""),
            from_land_use_class=str(payload.get("from_land_use_class") or ""),
            to_land_use_class=str(payload.get("to_land_use_class") or ""),
            snapshot_digest=str(payload.get("snapshot_digest") or ""),
            rationale=str(payload.get("rationale") or ""),
            requested_at=str(payload.get("requested_at") or ""),
            actor_id=str(username),
            alternative_land_use_class=payload.get("alternative_land_use_class"),
        )
        return JSONResponse(result)
    except S2ProductInvalid as error:
        return _product_error(error)
    except ValueError as error:
        message = str(error)
        status = 409 if "snapshot_digest_mismatch" in message else 400
        if "parcel_not_found" in message:
            status = 404
        return JSONResponse({"error": message}, status_code=status)


async def uwm_livability_s2_run(request: Request):
    username, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        result = await asyncio.to_thread(
            _service().get_run,
            str(request.path_params.get("run_id") or ""),
            actor_id=str(username),
        )
        return JSONResponse(result)
    except S2ProductInvalid as error:
        return _product_error(error)
    except S2RunNotFound as error:
        return JSONResponse({"error": str(error).strip("'\"")}, status_code=404)


def get_uwm_livability_s2_routes() -> list:
    return [
        Route("/api/uwm/livability/s2/catalog", uwm_livability_s2_catalog, methods=["GET"]),
        Route("/api/uwm/livability/s2/parcels", uwm_livability_s2_parcels, methods=["GET"]),
        Route("/api/uwm/livability/s2/parcels/{parcel_id}", uwm_livability_s2_parcel, methods=["GET"]),
        Route("/api/uwm/livability/s2/validate-action", uwm_livability_s2_validate_action, methods=["POST"]),
        Route("/api/uwm/livability/s2/rollout", uwm_livability_s2_rollout, methods=["POST"]),
        Route("/api/uwm/livability/s2/runs/{run_id}", uwm_livability_s2_run, methods=["GET"]),
    ]
