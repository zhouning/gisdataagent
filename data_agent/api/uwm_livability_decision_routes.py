"""Routes for UWM urban livability world-model decision output."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


UWM_LIVABILITY_DECISION_API_SCHEMA = "uwm.livability_decision_api.v1"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def load_uwm_livability_decision_payload() -> dict[str, Any]:
    """Load the real local UWM livability decision and comparison artifacts."""

    decision_package = _read_json(_decision_package_path())
    comparison_demo = _read_json(_comparison_demo_path())
    shared_contract = dict(comparison_demo.get("shared_data_contract") or {})
    return {
        "schema": UWM_LIVABILITY_DECISION_API_SCHEMA,
        "world_model_components_used": ["renderer", "simulator", "planner"],
        "shared_data_contract": shared_contract,
        "decision_package": decision_package,
        "comparison_demo": comparison_demo,
        "traditional_method_output": dict(
            comparison_demo.get("traditional_method_output") or {}
        ),
        "uwm_output": dict(comparison_demo.get("uwm_output") or {}),
        "capability_delta": dict(comparison_demo.get("capability_delta") or {}),
        "claim_boundary": dict(decision_package.get("claim_boundary") or {}),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


async def uwm_livability_decision(request: Request):
    """GET /api/uwm/livability-decision"""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        return JSONResponse(await asyncio.to_thread(load_uwm_livability_decision_payload))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def get_uwm_livability_decision_routes() -> list:
    """Return Route objects for UWM livability decision endpoints."""

    return [
        Route(
            "/api/uwm/livability-decision",
            uwm_livability_decision,
            methods=["GET"],
        ),
    ]


def _decision_package_path() -> Path:
    configured = os.environ.get("UWM_LIVABILITY_DECISION_PACKAGE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (
        DEFAULT_DATA_ROOT
        / "livability_decision_package_2026_07_07/uwm_livability_decision_package.json"
    )


def _comparison_demo_path() -> Path:
    configured = os.environ.get("UWM_LIVABILITY_COMPARISON_DEMO_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (
        DEFAULT_DATA_ROOT
        / "traditional_vs_world_model_demo_2026_07_07/uwm_traditional_vs_world_model_demo.json"
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload
