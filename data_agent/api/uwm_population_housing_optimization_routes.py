"""Authenticated API routes for the bounded population/housing MILP PoC."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..uwm.population_housing_optimization_service import (
    DEFAULT_BOUNDARY_PATH,
    SERVICE_LIMITS,
    PopulationHousingOptimizationService,
    PopulationHousingProductError,
    PopulationHousingRequestLimitError,
)
from .helpers import _get_user_from_request, _set_user_context

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRODUCT_DIR = ROOT / (
    "data/uwm_public_proxy/abu_dhabi_city/"
    "population_housing_optimization_demo_2026_08_01"
)
_SERVICE_CACHE: tuple[Path, Path, PopulationHousingOptimizationService] | None = None


class _RequestBodyError(ValueError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def _product_dir() -> Path:
    configured = os.environ.get("UWM_POPULATION_HOUSING_OPTIMIZATION_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_PRODUCT_DIR


def _boundary_path(product_dir: Path) -> Path:
    configured = os.environ.get("UWM_POPULATION_HOUSING_BOUNDARY_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    try:
        manifest = json.loads((product_dir / "snapshot_manifest.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_BOUNDARY_PATH
    manifest_path = str(manifest.get("boundary_path") or "").strip()
    if not manifest_path:
        return DEFAULT_BOUNDARY_PATH
    path = Path(manifest_path).expanduser()
    return path if path.is_absolute() else ROOT / path


def _service() -> PopulationHousingOptimizationService:
    global _SERVICE_CACHE
    path = _product_dir()
    boundary_path = _boundary_path(path)
    if _SERVICE_CACHE is None or _SERVICE_CACHE[:2] != (path, boundary_path):
        _SERVICE_CACHE = (
            path,
            boundary_path,
            PopulationHousingOptimizationService(path, boundary_path=boundary_path),
        )
    return _SERVICE_CACHE[2]


def _reset_service_cache() -> None:
    global _SERVICE_CACHE
    _SERVICE_CACHE = None


def _authorized(request: Request) -> tuple[str | None, JSONResponse | None]:
    user = _get_user_from_request(request)
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    return str(username), None


async def _json_object(request: Request) -> dict[str, Any]:
    max_bytes = int(SERVICE_LIMITS["max_request_bytes"])
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_bytes = int(content_length)
        except ValueError as error:
            raise _RequestBodyError("Invalid Content-Length", 400) from error
        if declared_bytes < 0:
            raise _RequestBodyError("Invalid Content-Length", 400)
        if declared_bytes > max_bytes:
            raise _RequestBodyError("Request body exceeds service limit", 413)

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise _RequestBodyError("Request body exceeds service limit", 413)
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise _RequestBodyError("Invalid JSON payload", 400) from error
    if not isinstance(payload, dict):
        raise _RequestBodyError("Request object required", 400)
    return payload


def _product_unavailable(error: Exception) -> JSONResponse:
    return JSONResponse(
        {
            "error": str(error),
            "ready": False,
            "blockers": ["population_housing_optimization_product_unavailable"],
            "empirical_policy_optimality_claim": False,
        },
        status_code=503,
    )


async def population_housing_catalog(request: Request) -> JSONResponse:
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().catalog))
    except Exception as error:
        return _product_unavailable(error)


async def population_housing_default_input(request: Request) -> JSONResponse:
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().default_input))
    except Exception as error:
        return _product_unavailable(error)


async def population_housing_default_portfolio(request: Request) -> JSONResponse:
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().default_portfolio))
    except Exception as error:
        return _product_unavailable(error)


async def population_housing_map_context(request: Request) -> JSONResponse:
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        return JSONResponse(await asyncio.to_thread(_service().map_context))
    except Exception as error:
        return _product_unavailable(error)


async def population_housing_validate(request: Request) -> JSONResponse:
    _, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        payload = await _json_object(request)
        return JSONResponse(await asyncio.to_thread(_service().validate, payload))
    except _RequestBodyError as error:
        return JSONResponse({"error": str(error)}, status_code=error.status_code)
    except PopulationHousingRequestLimitError as error:
        return JSONResponse(error.as_dict(), status_code=422)
    except PopulationHousingProductError as error:
        return _product_unavailable(error)
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    except Exception as error:
        return _product_unavailable(error)


async def population_housing_solve(request: Request) -> JSONResponse:
    actor, unauthorized = _authorized(request)
    if unauthorized:
        return unauthorized
    try:
        payload = await _json_object(request)
        result = await asyncio.to_thread(_service().solve, payload, actor=str(actor))
        return JSONResponse(result)
    except _RequestBodyError as error:
        return JSONResponse({"error": str(error)}, status_code=error.status_code)
    except PopulationHousingRequestLimitError as error:
        return JSONResponse(error.as_dict(), status_code=422)
    except PopulationHousingProductError as error:
        return _product_unavailable(error)
    except ValueError as error:
        return JSONResponse(
            {
                "error": str(error),
                "empirical_policy_optimality_claim": False,
            },
            status_code=400,
        )
    except Exception as error:
        return JSONResponse(
            {
                "error": str(error),
                "ready": False,
                "empirical_policy_optimality_claim": False,
            },
            status_code=503,
        )


def get_uwm_population_housing_optimization_routes() -> list[Route]:
    base = "/api/uwm/population-housing"
    return [
        Route(f"{base}/catalog", population_housing_catalog, methods=["GET"]),
        Route(
            f"{base}/default-input",
            population_housing_default_input,
            methods=["GET"],
        ),
        Route(
            f"{base}/default-portfolio",
            population_housing_default_portfolio,
            methods=["GET"],
        ),
        Route(
            f"{base}/map-context",
            population_housing_map_context,
            methods=["GET"],
        ),
        Route(f"{base}/validate", population_housing_validate, methods=["POST"]),
        Route(f"{base}/solve", population_housing_solve, methods=["POST"]),
    ]


__all__ = [
    "get_uwm_population_housing_optimization_routes",
    "population_housing_catalog",
    "population_housing_default_input",
    "population_housing_default_portfolio",
    "population_housing_map_context",
    "population_housing_solve",
    "population_housing_validate",
]
