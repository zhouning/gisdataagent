"""Authenticated routes for the durable irrigation world-model service."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..irrigation_world_model_demo import (
    IrrigationWorldModelError,
    get_irrigation_world_model_service,
)
from ..user_context import current_tenant_id
from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.irrigation_world_model_routes")


def _actor(request: Request):
    user = _get_user_from_request(request)
    if user:
        username, role = _set_user_context(user)
        tenant_id = current_tenant_id.get().strip()
        if not tenant_id:
            return None, None, None, JSONResponse(
                {
                    "error": "Authenticated identity has no tenant binding",
                    "code": "tenant_context_required",
                },
                status_code=403,
            )
        return username, role, tenant_id, None
    return None, None, None, JSONResponse({"error": "Unauthorized"}, status_code=401)


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise IrrigationWorldModelError("invalid JSON body") from exc
    if not isinstance(body, dict):
        raise IrrigationWorldModelError("request body must be an object")
    return body


def _domain_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, IrrigationWorldModelError):
        return JSONResponse({"error": str(exc)}, status_code=exc.status_code)
    logger.exception("irrigation world-model request failed")
    return JSONResponse({"error": "irrigation world-model service unavailable"}, status_code=503)


def _cross_site_write(request: Request) -> JSONResponse | None:
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return JSONResponse(
            {"error": "cross-site irrigation world-model write rejected"}, status_code=403
        )
    return None


def _audit(request: Request, username: str, action: str, details: dict[str, Any]) -> None:
    try:
        from ..audit_logger import record_audit

        record_audit(
            username,
            action,
            ip_address=request.client.host if request.client else None,
            details=details,
        )
    except Exception:
        logger.warning("irrigation world-model platform audit failed", exc_info=True)


async def irrigation_bootstrap(request: Request):
    actor, _role, tenant_id, error = _actor(request)
    if error:
        return error
    try:
        payload = await asyncio.to_thread(
            get_irrigation_world_model_service().bootstrap, actor, tenant_id
        )
        return JSONResponse(payload)
    except Exception as exc:
        return _domain_error(exc)


async def irrigation_run(request: Request):
    actor, _role, tenant_id, error = _actor(request)
    if error:
        return error
    if cross_site_error := _cross_site_write(request):
        return cross_site_error
    try:
        body = await _json_body(request)
        run = await asyncio.to_thread(
            get_irrigation_world_model_service().run, body, actor, tenant_id
        )
        _audit(
            request,
            actor,
            "irrigation_scenario_run",
            {"run_id": run["run_id"], "version": run["version"]},
        )
        return JSONResponse(
            {"schema": "gda.irrigation-world-model.run-response.v1", "run": run}, status_code=201
        )
    except Exception as exc:
        return _domain_error(exc)


async def irrigation_run_detail(request: Request):
    actor, _role, tenant_id, error = _actor(request)
    if error:
        return error
    try:
        run = await asyncio.to_thread(
            get_irrigation_world_model_service().get_run,
            request.path_params["run_id"],
            actor,
            tenant_id,
        )
        return JSONResponse({"schema": "gda.irrigation-world-model.run-response.v1", "run": run})
    except Exception as exc:
        return _domain_error(exc)


async def irrigation_proposal_review(request: Request):
    actor, _role, tenant_id, error = _actor(request)
    if error:
        return error
    if cross_site_error := _cross_site_write(request):
        return cross_site_error
    try:
        body = await _json_body(request)
        run = await asyncio.to_thread(
            get_irrigation_world_model_service().review_proposal,
            request.path_params["proposal_id"],
            body,
            actor,
            tenant_id,
        )
        _audit(
            request,
            actor,
            "irrigation_proposal_review",
            {
                "run_id": run["run_id"],
                "proposal_id": run["proposal"]["proposal_id"],
                "decision": run["proposal"]["status"],
                "execution_allowed": False,
            },
        )
        return JSONResponse({"schema": "gda.irrigation-world-model.run-response.v1", "run": run})
    except Exception as exc:
        return _domain_error(exc)


def get_irrigation_world_model_routes() -> list[Route]:
    return [
        Route("/api/irrigation-world-model/bootstrap", irrigation_bootstrap, methods=["GET"]),
        Route("/api/irrigation-world-model/run", irrigation_run, methods=["POST"]),
        Route("/api/irrigation-world-model/runs/{run_id}", irrigation_run_detail, methods=["GET"]),
        Route(
            "/api/irrigation-world-model/proposals/{proposal_id}/review",
            irrigation_proposal_review,
            methods=["POST"],
        ),
    ]
