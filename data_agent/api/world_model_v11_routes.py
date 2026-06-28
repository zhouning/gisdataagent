"""World Model v1.1 Paper58 external benchmark evidence routes."""

import asyncio
import os
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from scripts.run_twm_validation_bundle import build_paper58_external_benchmark

from .helpers import _get_user_from_request, _set_user_context


def _configured_paper58_benchmark_dir() -> Path | None:
    configured = os.environ.get("TWM_PAPER58_BENCHMARK_DIR", "").strip()
    return Path(configured).expanduser() if configured else None


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


def get_world_model_v11_routes() -> list:
    """Return Route objects for World Model v1.1 Paper58 evidence endpoints."""
    return [
        Route("/api/twm/paper58-benchmark", twm_paper58_benchmark, methods=["GET"]),
        Route(
            "/api/twm/paper58-benchmark/refresh",
            twm_paper58_benchmark_refresh,
            methods=["POST"],
        ),
    ]
