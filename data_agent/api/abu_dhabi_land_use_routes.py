"""Authenticated routes for the frozen Abu Dhabi three-model benchmark."""

from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from ..abu_dhabi_land_use import AbuDhabiLandUseService
from ..abu_dhabi_land_use_runtime import (
    build_map_config,
    load_run,
    resolve_run_raster,
    start_run,
)
from .helpers import _get_user_from_request, _set_user_context


def _service() -> AbuDhabiLandUseService:
    return AbuDhabiLandUseService()


def _authorize(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return None
    _set_user_context(user)
    return user


def _error_response(exc: Exception) -> JSONResponse:
    if isinstance(exc, KeyError):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, ValueError):
        return JSONResponse({"error": str(exc)}, status_code=400)
    if isinstance(exc, FileNotFoundError):
        if "run_not_found" in str(exc):
            return JSONResponse({"error": str(exc)}, status_code=404)
        return JSONResponse(
            {
                "ready": False,
                "error": str(exc),
                "blockers": ["abu_dhabi_benchmark_artifact_missing"],
            },
            status_code=503,
        )
    return JSONResponse({"error": str(exc)}, status_code=500)


async def overview(request: Request):
    if not _authorize(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        return JSONResponse(await asyncio.to_thread(_service().overview))
    except Exception as exc:
        return _error_response(exc)


async def model(request: Request):
    if not _authorize(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        return JSONResponse(
            await asyncio.to_thread(
                _service().model,
                str(request.path_params.get("model_id") or ""),
            )
        )
    except Exception as exc:
        return _error_response(exc)


async def raster_preview(request: Request):
    if not _authorize(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        query = request.query_params
        service = _service()
        path = await asyncio.to_thread(
            service.resolve_raster,
            str(request.path_params.get("model_id") or ""),
            track=str(query.get("track") or "historical"),
            year=int(query.get("year") or 2024),
            seed=str(query.get("seed") or "ensemble"),
            scenario=query.get("scenario"),
        )
        content = await asyncio.to_thread(service.render_raster_png, path)
        return Response(
            content,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except Exception as exc:
        return _error_response(exc)


async def figure(request: Request):
    if not _authorize(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        path = await asyncio.to_thread(
            _service().resolve_figure,
            str(request.path_params.get("figure_id") or ""),
        )
        return FileResponse(path, media_type="image/png")
    except Exception as exc:
        return _error_response(exc)


async def create_run(request: Request):
    user = _authorize(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("invalid_json_body")
        record = await asyncio.to_thread(
            start_run,
            _service(),
            model_id=str(body.get("model_id") or ""),
            track=str(body.get("track") or "historical"),
            seed=int(body.get("seed") or 31),
            scenario=body.get("scenario"),
            username=str(user.identifier),
        )
        return JSONResponse(record, status_code=202)
    except Exception as exc:
        return _error_response(exc)


def _authorized_run(request: Request, user) -> tuple[AbuDhabiLandUseService, dict]:
    service = _service()
    record = load_run(service, str(request.path_params.get("run_id") or ""))
    role = user.metadata.get("role") if isinstance(user.metadata, dict) else None
    if record.get("requested_by") != user.identifier and role != "admin":
        raise PermissionError("run_access_denied")
    return service, record


async def run_status(request: Request):
    user = _authorize(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        _, record = await asyncio.to_thread(_authorized_run, request, user)
        return JSONResponse(record)
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    except Exception as exc:
        return _error_response(exc)


async def run_raster_preview(request: Request):
    user = _authorize(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        service, _ = await asyncio.to_thread(_authorized_run, request, user)
        path = await asyncio.to_thread(
            resolve_run_raster,
            service,
            str(request.path_params.get("run_id") or ""),
            int(request.path_params.get("year") or 0),
        )
        content = await asyncio.to_thread(service.render_raster_png, path)
        return Response(
            content,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    except Exception as exc:
        return _error_response(exc)


def _queue_map(username: str, map_config: dict) -> None:
    from ..frontend_api import _pending_lock, pending_map_updates

    with _pending_lock:
        pending_map_updates[username] = map_config


async def queue_map(request: Request):
    user = _authorize(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("invalid_json_body")
        service = _service()
        run_id = str(body.get("run_id") or "") or None
        if run_id:
            record = await asyncio.to_thread(load_run, service, run_id)
            role = user.metadata.get("role") if isinstance(user.metadata, dict) else None
            if record.get("requested_by") != user.identifier and role != "admin":
                raise PermissionError("run_access_denied")
        map_config = await asyncio.to_thread(
            build_map_config,
            service,
            model_id=str(body.get("model_id") or ""),
            track=str(body.get("track") or "historical"),
            seed=str(body.get("seed") or "ensemble"),
            scenario=body.get("scenario"),
            run_id=run_id,
        )
        await asyncio.to_thread(_queue_map, str(user.identifier), map_config)
        return JSONResponse(
            {
                "status": "ready",
                "map_update_queued": True,
                "map_update": map_config,
            }
        )
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    except Exception as exc:
        return _error_response(exc)


def get_abu_dhabi_land_use_routes() -> list:
    base = "/api/benchmarks/abu-dhabi-land-use"
    return [
        Route(f"{base}/overview", overview, methods=["GET"]),
        Route(f"{base}/models/{{model_id}}", model, methods=["GET"]),
        Route(f"{base}/rasters/{{model_id}}", raster_preview, methods=["GET"]),
        Route(f"{base}/figures/{{figure_id}}", figure, methods=["GET"]),
        Route(f"{base}/runs", create_run, methods=["POST"]),
        Route(f"{base}/runs/{{run_id}}", run_status, methods=["GET"]),
        Route(
            f"{base}/runs/{{run_id}}/rasters/{{year:int}}",
            run_raster_preview,
            methods=["GET"],
        ),
        Route(f"{base}/map", queue_map, methods=["POST"]),
    ]
