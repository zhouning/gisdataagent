"""Routes for the traditional static urban livability analysis tab."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.traditional_livability_analysis import (
    build_traditional_livability_analysis,
    queue_traditional_livability_map,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _scene_path() -> Path:
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_SCENE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (
        DEFAULT_DATA_ROOT
        / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json"
    )


def _admin_units_path() -> Path:
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_ADMIN_GEOJSON", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"


def _load_default_analysis(top_n: int = 8) -> dict:
    scene = json.loads(_scene_path().read_text(encoding="utf-8"))
    return build_traditional_livability_analysis(
        analysis_id="uwm-traditional-livability-analysis-chongqing-central-current",
        created_at=_utc_now(),
        multisource_livability_scene=scene,
        top_n=top_n,
    )


async def uwm_traditional_livability(request: Request):
    """GET /api/uwm/traditional-livability"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    top_n = _safe_int(request.query_params.get("top_n"), default=8)
    top_n = max(1, min(top_n, 20))
    try:
        return JSONResponse(await asyncio.to_thread(_load_default_analysis, top_n))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def uwm_traditional_livability_map(request: Request):
    """POST /api/uwm/traditional-livability/map"""
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

    top_n = max(1, min(_safe_int(body.get("top_n"), default=8), 20))
    try:
        analysis = await asyncio.to_thread(_load_default_analysis, top_n)
        payload = await asyncio.to_thread(
            queue_traditional_livability_map,
            username=username,
            analysis=analysis,
            admin_units_geojson_path=_admin_units_path(),
        )
        return JSONResponse(payload)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def get_uwm_traditional_livability_routes() -> list:
    """Return Route objects for traditional livability analysis endpoints."""
    return [
        Route(
            "/api/uwm/traditional-livability",
            uwm_traditional_livability,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/map",
            uwm_traditional_livability_map,
            methods=["POST"],
        ),
    ]


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )
