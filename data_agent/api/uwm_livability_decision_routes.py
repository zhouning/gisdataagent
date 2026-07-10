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
from data_agent.uwm.livability_requirement_registry import (
    build_livability_requirement_registry,
    requirement_coverage_for_route,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


UWM_LIVABILITY_DECISION_API_SCHEMA = "uwm.livability_decision_api.v1"
UWM_LIVABILITY_ROUTE = "uwm_livability"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def load_uwm_livability_decision_payload() -> dict[str, Any]:
    """Load the real local UWM livability decision and comparison artifacts."""

    decision_package = _read_json(_decision_package_path())
    full_admin_decision_package = _read_json(_full_admin_decision_package_path())
    comparison_demo = _read_json(_comparison_demo_path())
    data_foundation_gate = _read_json(_data_foundation_evidence_gate_path())
    world_model_readiness = build_world_model_evidence_readiness(data_foundation_gate)
    shared_contract = dict(comparison_demo.get("shared_data_contract") or {})
    governance_evidence = dict(
        full_admin_decision_package.get("production_governance_binding_evidence")
        or {}
    )
    spatial_causal_registry = dict(
        (data_foundation_gate.get("evidence_slices") or {}).get(
            "spatial_causal_question_registry"
        )
        or {}
    )
    full_admin_action_inventory = dict(
        (data_foundation_gate.get("evidence_slices") or {}).get(
            "full_admin_action_inventory"
        )
        or {}
    )
    registry = build_livability_requirement_registry()
    requirement_ownership = requirement_coverage_for_route(
        registry,
        UWM_LIVABILITY_ROUTE,
    )
    return {
        "schema": UWM_LIVABILITY_DECISION_API_SCHEMA,
        "world_model_components_used": ["renderer", "simulator", "planner"],
        "requirement_ownership": requirement_ownership,
        "active_decision_package_scope": full_admin_decision_package.get(
            "experiment_scope"
        ),
        "shared_data_contract": shared_contract,
        "decision_package": decision_package,
        "full_admin_decision_package": full_admin_decision_package,
        "production_governance_binding_evidence": governance_evidence,
        "full_admin_action_inventory_evidence": full_admin_action_inventory,
        "spatial_causal_question_registry_evidence": spatial_causal_registry,
        "world_model_evidence_readiness": world_model_readiness,
        "planner_governance_binding_ready": bool(
            full_admin_decision_package.get("planner_governance_binding_ready")
        ),
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


def _full_admin_decision_package_path() -> Path:
    configured = os.environ.get(
        "UWM_FULL_ADMIN_LIVABILITY_DECISION_PACKAGE_PATH", ""
    ).strip()
    if configured:
        return Path(configured).expanduser()
    return (
        DEFAULT_DATA_ROOT
        / "full_admin_livability_decision_package_2026_07_08/uwm_full_admin_livability_decision_package.json"
    )


def _comparison_demo_path() -> Path:
    configured = os.environ.get("UWM_LIVABILITY_COMPARISON_DEMO_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (
        DEFAULT_DATA_ROOT
        / "traditional_vs_world_model_demo_2026_07_07/uwm_traditional_vs_world_model_demo.json"
    )


def _data_foundation_evidence_gate_path() -> Path:
    configured = os.environ.get("UWM_DATA_FOUNDATION_EVIDENCE_GATE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (
        DEFAULT_DATA_ROOT
        / "data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json"
    )


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload
