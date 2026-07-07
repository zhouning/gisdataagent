"""Routes for UWM livability data catalog and lineage readiness."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from data_agent.uwm.livability_data_catalog import (
    build_uwm_livability_data_catalog,
    sync_uwm_livability_assets_to_data_agent_catalog,
)

from .helpers import _get_user_from_request, _set_user_context


UWM_LIVABILITY_DATA_CATALOG_API_SCHEMA = "uwm.livability_data_catalog_api.v1"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def load_uwm_livability_data_catalog_payload() -> dict[str, Any]:
    """Load a current machine-readable catalog for local UWM livability assets."""

    catalog = build_uwm_livability_data_catalog(
        data_root=_data_root(),
        catalog_id="uwm-livability-data-catalog-2026-07-07",
        created_at="2026-07-07T00:00:00Z",
    )
    return {
        "schema": UWM_LIVABILITY_DATA_CATALOG_API_SCHEMA,
        "data_catalog": catalog,
        "mmfe_readiness": dict(catalog.get("mmfe_readiness") or {}),
        "model_based_rl_boundary": dict(
            catalog.get("model_based_rl_boundary") or {}
        ),
        "claim_boundary": dict(catalog.get("claim_boundary") or {}),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


async def uwm_livability_data_catalog(request: Request):
    """GET /api/uwm/livability-data-catalog"""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        return JSONResponse(
            await asyncio.to_thread(load_uwm_livability_data_catalog_payload)
        )
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def uwm_livability_data_catalog_sync(request: Request):
    """POST /api/uwm/livability-data-catalog/sync"""

    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    try:
        payload = await asyncio.to_thread(load_uwm_livability_data_catalog_payload)
        plan = (
            payload.get("data_catalog", {})
            .get("data_agent_catalog_integration", {})
            .get("registration_plan", {})
        )
        result = await asyncio.to_thread(
            sync_uwm_livability_assets_to_data_agent_catalog,
            plan,
        )
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def get_uwm_livability_data_catalog_routes() -> list:
    """Return Route objects for UWM livability data catalog endpoints."""

    return [
        Route(
            "/api/uwm/livability-data-catalog",
            uwm_livability_data_catalog,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/livability-data-catalog/sync",
            uwm_livability_data_catalog_sync,
            methods=["POST"],
        ),
    ]


def _data_root() -> Path:
    configured = os.environ.get("UWM_LIVABILITY_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DATA_ROOT
