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
from ..uwm.traditional_livability_facility_dictionary import (
    COMPATIBILITY_SCHEMA,
    DICTIONARY_SCHEMA,
    unavailable_compatibility_matrix,
    unavailable_facility_dictionary,
)
from ..uwm.traditional_livability_s6 import analyze_s6_facility_proposal


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
S1_SCHEMA = "uwm.traditional_livability.s1_assessment.v1"
S7_SCHEMA = "uwm.traditional_livability.s7_siting.v1"
S6_RESOURCE_SCHEMA = "uwm.traditional_livability.s6_fulu_resources.v1"
S6_RESOURCE_FILES = {
    "resources": "uwm_traditional_livability_s6_resources.json",
    "dictionary": "uwm_traditional_livability_s6_dictionary.json",
    "compatibility": "uwm_traditional_livability_s6_compatibility.json",
}
S6_SCHEMAS = {
    "resources": S6_RESOURCE_SCHEMA,
    "dictionary": DICTIONARY_SCHEMA,
    "compatibility": COMPATIBILITY_SCHEMA,
}


class S1SnapshotUnavailable(RuntimeError):
    def __init__(self, payload: dict):
        super().__init__("traditional livability S1 snapshot unavailable")
        self.payload = payload


class S7SnapshotUnavailable(RuntimeError):
    def __init__(self, payload: dict):
        super().__init__("traditional livability S7 snapshot unavailable")
        self.payload = payload


class S6SnapshotUnavailable(RuntimeError):
    def __init__(self, payload: dict):
        super().__init__("traditional livability S6 snapshot unavailable")
        self.payload = payload


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


def _s1_path() -> Path:
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_S1_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DATA_ROOT / "traditional_livability_phase1a/uwm_traditional_livability_s1.json"


def _load_s1_snapshot() -> dict:
    path = _s1_path()
    if not path.is_file():
        raise S1SnapshotUnavailable(
            {
                "schema": S1_SCHEMA,
                "ready": False,
                "blockers": ["s1_snapshot_missing"],
                "claim_boundary": {
                    "assessment_fabricated": False,
                    "source_path_disclosed": False,
                },
            }
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != S1_SCHEMA:
        raise S1SnapshotUnavailable(
            {
                "schema": S1_SCHEMA,
                "ready": False,
                "blockers": ["s1_snapshot_schema_invalid"],
                "claim_boundary": {"assessment_fabricated": False},
            }
        )
    return payload


def _s7_path() -> Path:
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_S7_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DATA_ROOT / "traditional_livability_s7_fulu/uwm_traditional_livability_s7.json"


def _load_s7_snapshot() -> dict:
    path = _s7_path()
    if not path.is_file():
        raise S7SnapshotUnavailable(
            {
                "schema": S7_SCHEMA,
                "ready": False,
                "blockers": ["s7_snapshot_missing"],
                "claim_boundary": {
                    "recommendation_fabricated": False,
                    "source_path_disclosed": False,
                },
            }
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != S7_SCHEMA:
        raise S7SnapshotUnavailable(
            {
                "schema": S7_SCHEMA,
                "ready": False,
                "blockers": ["s7_snapshot_schema_invalid"],
                "claim_boundary": {"recommendation_fabricated": False},
            }
        )
    return payload


def _resolve_s6_path(snapshot: str) -> Path:
    filename = S6_RESOURCE_FILES[snapshot]
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_S6_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir() or path.suffix.lower() != ".json":
            return path / filename
        return path if snapshot == "resources" else path.parent / filename
    return DEFAULT_DATA_ROOT / "traditional_livability_s6_fulu" / filename


def _s6_unavailable_payload(snapshot: str, blocker: str) -> dict:
    return {
        "schema": S6_SCHEMAS[snapshot],
        "ready": False,
        "blockers": [blocker],
        "claim_boundary": {
            "analysis_fabricated": False,
            "source_path_disclosed": False,
        },
    }


def _load_s6_snapshot(snapshot: str) -> dict:
    path = _resolve_s6_path(snapshot)
    if not path.is_file():
        raise S6SnapshotUnavailable(
            _s6_unavailable_payload(snapshot, f"s6_{snapshot}_snapshot_missing")
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise S6SnapshotUnavailable(
            _s6_unavailable_payload(snapshot, f"s6_{snapshot}_snapshot_unreadable")
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != S6_SCHEMAS[snapshot]:
        raise S6SnapshotUnavailable(
            _s6_unavailable_payload(snapshot, f"s6_{snapshot}_snapshot_schema_invalid")
        )
    return payload


def _load_optional_s6_snapshot(snapshot: str) -> dict:
    try:
        return _load_s6_snapshot(snapshot)
    except S6SnapshotUnavailable as exc:
        if snapshot == "dictionary":
            payload = unavailable_facility_dictionary()
        else:
            payload = unavailable_compatibility_matrix()
        payload["blockers"] = list(
            dict.fromkeys([*(payload.get("blockers") or []), *exc.payload["blockers"]])
        )
        return payload


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


async def uwm_traditional_livability_s1(request: Request):
    """GET /api/uwm/traditional-livability/s1"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(await asyncio.to_thread(_load_s1_snapshot))
    except S1SnapshotUnavailable as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            {
                "schema": S1_SCHEMA,
                "ready": False,
                "blockers": ["s1_snapshot_unreadable"],
                "claim_boundary": {"assessment_fabricated": False},
            },
            status_code=503,
        )


async def uwm_traditional_livability_s7(request: Request):
    """GET /api/uwm/traditional-livability/s7"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(await asyncio.to_thread(_load_s7_snapshot))
    except S7SnapshotUnavailable as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            {
                "schema": S7_SCHEMA,
                "ready": False,
                "blockers": ["s7_snapshot_unreadable"],
                "claim_boundary": {"recommendation_fabricated": False},
            },
            status_code=503,
        )


async def uwm_traditional_livability_s6_resources(request: Request):
    """GET /api/uwm/traditional-livability/s6/resources"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(await asyncio.to_thread(_load_s6_snapshot, "resources"))
    except S6SnapshotUnavailable as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            _s6_unavailable_payload("resources", "s6_resources_snapshot_unreadable"),
            status_code=503,
        )


async def uwm_traditional_livability_s6_dictionary(request: Request):
    """GET /api/uwm/traditional-livability/s6/dictionary"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    payload = await asyncio.to_thread(_load_optional_s6_snapshot, "dictionary")
    if payload.get("ready") is not True and "blockers" not in payload:
        payload["blockers"] = list(payload.get("production_blockers") or [])
    return JSONResponse(payload)


async def uwm_traditional_livability_s6_analyze(request: Request):
    """POST /api/uwm/traditional-livability/s6/analyze"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON payload", "blockers": ["request_json_invalid"]},
            status_code=400,
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            {"error": "Invalid request payload", "blockers": ["request_object_required"]},
            status_code=400,
        )
    try:
        resources = await asyncio.to_thread(_load_s6_snapshot, "resources")
        dictionary, compatibility = await asyncio.gather(
            asyncio.to_thread(_load_optional_s6_snapshot, "dictionary"),
            asyncio.to_thread(_load_optional_s6_snapshot, "compatibility"),
        )
        result = await asyncio.to_thread(
            analyze_s6_facility_proposal,
            request=payload,
            resources=resources,
            dictionary=dictionary,
            compatibility=compatibility,
        )
    except S6SnapshotUnavailable as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            _s6_unavailable_payload("resources", "s6_analysis_failed"),
            status_code=503,
        )
    blockers = result.get("blockers") or result.get("validation", {}).get("blockers") or []
    status_code = 400 if result.get("status") == "insufficient_evidence" and blockers else 200
    return JSONResponse(result, status_code=status_code)


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
        Route(
            "/api/uwm/traditional-livability/s1",
            uwm_traditional_livability_s1,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s7",
            uwm_traditional_livability_s7,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s6/resources",
            uwm_traditional_livability_s6_resources,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s6/dictionary",
            uwm_traditional_livability_s6_dictionary,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s6/analyze",
            uwm_traditional_livability_s6_analyze,
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
