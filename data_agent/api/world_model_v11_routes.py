"""World Model v1.1 Paper58 external benchmark evidence routes."""

import asyncio
import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from scripts.run_twm_validation_bundle import build_paper58_external_benchmark

from .helpers import _get_user_from_request, _set_user_context
from ..paper58_visualization import (
    build_paper58_visualization,
    queue_paper58_visualization_map,
)
from ..paper58_runtime.runner import (
    load_runtime_run,
    queue_runtime_map,
    run_runtime_once,
    runtime_cases_payload,
)


def _configured_paper58_benchmark_dir() -> Path | None:
    configured = os.environ.get("TWM_PAPER58_BENCHMARK_DIR", "").strip()
    return Path(configured).expanduser() if configured else None


def _configured_flus_executable() -> Path:
    configured = os.environ.get(
        "GEOSOS_FLUS_EXECUTABLE",
        "/Users/zhouning/FLUS_console_crossplatform/build/flus_console",
    ).strip()
    return Path(configured).expanduser()


def _configured_runtime_output_root() -> Path:
    configured = os.environ.get(
        "TWM_WORLD_MODEL_V11_RUN_DIR",
        "outputs/world_model_v11_runs",
    ).strip()
    return Path(configured).expanduser()


async def _paper58_benchmark_response(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        return JSONResponse(
            await asyncio.to_thread(
                build_paper58_external_benchmark,
                _configured_paper58_benchmark_dir(),
            )
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_paper58_benchmark(request: Request):
    """GET /api/twm/paper58-benchmark"""
    return await _paper58_benchmark_response(request)


async def twm_paper58_benchmark_refresh(request: Request):
    """POST /api/twm/paper58-benchmark/refresh"""
    return await _paper58_benchmark_response(request)


async def twm_paper58_visualization(request: Request):
    """GET /api/twm/paper58-visualization"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        return JSONResponse(
            await asyncio.to_thread(
                build_paper58_visualization,
                _configured_paper58_benchmark_dir(),
                request.query_params.get("area"),
                request.query_params.get("method"),
            )
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_paper58_visualization_map(request: Request):
    """POST /api/twm/paper58-visualization/map"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    try:
        return JSONResponse(
            await asyncio.to_thread(
                queue_paper58_visualization_map,
                _configured_paper58_benchmark_dir(),
                username,
                body.get("area"),
                body.get("method"),
            )
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_runtime_cases(request: Request):
    """GET /api/twm/world-model-v11/runtime/cases"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        return JSONResponse(
            await asyncio.to_thread(
                runtime_cases_payload,
                _configured_paper58_benchmark_dir(),
                _configured_flus_executable(),
            )
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_runtime_runs(request: Request):
    """POST /api/twm/world-model-v11/runtime/runs"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    try:
        benchmark_dir = _configured_paper58_benchmark_dir()
        if benchmark_dir is None:
            return JSONResponse(
                {"error": "TWM_PAPER58_BENCHMARK_DIR is not configured"},
                status_code=500,
            )
        return JSONResponse(
            await asyncio.to_thread(
                run_runtime_once,
                benchmark_dir,
                _configured_runtime_output_root(),
                str(body.get("area") or ""),
                str(
                    body.get("method")
                    or "paper58_spatial_demand_ratio_claim_robustness_v4"
                ),
                _configured_flus_executable(),
            )
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_runtime_run_status(request: Request):
    """GET /api/twm/world-model-v11/runtime/runs/{run_id}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")

    try:
        return JSONResponse(
            await asyncio.to_thread(
                load_runtime_run,
                _configured_runtime_output_root(),
                run_id,
            )
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_runtime_run_map(request: Request):
    """POST /api/twm/world-model-v11/runtime/runs/{run_id}/map"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    run_id = str(request.path_params.get("run_id") or "")

    try:
        return JSONResponse(
            await asyncio.to_thread(
                queue_runtime_map,
                _configured_runtime_output_root() / run_id,
                username,
            )
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def get_world_model_v11_routes() -> list:
    """Return Route objects for World Model v1.1 Paper58 evidence endpoints."""
    return [
        Route("/api/twm/paper58-benchmark", twm_paper58_benchmark, methods=["GET"]),
        Route(
            "/api/twm/paper58-benchmark/refresh",
            twm_paper58_benchmark_refresh,
            methods=["POST"],
        ),
        Route(
            "/api/twm/paper58-visualization",
            twm_paper58_visualization,
            methods=["GET"],
        ),
        Route(
            "/api/twm/paper58-visualization/map",
            twm_paper58_visualization_map,
            methods=["POST"],
        ),
        Route(
            "/api/twm/world-model-v11/runtime/cases",
            twm_runtime_cases,
            methods=["GET"],
        ),
        Route(
            "/api/twm/world-model-v11/runtime/runs",
            twm_runtime_runs,
            methods=["POST"],
        ),
        Route(
            "/api/twm/world-model-v11/runtime/runs/{run_id}",
            twm_runtime_run_status,
            methods=["GET"],
        ),
        Route(
            "/api/twm/world-model-v11/runtime/runs/{run_id}/map",
            twm_runtime_run_map,
            methods=["POST"],
        ),
    ]
