from __future__ import annotations

import asyncio
import os
from pathlib import Path

from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.public_feedback_readiness_service import PublicFeedbackReadinessService


ROOT = Path(__file__).resolve().parents[2]; DEFAULT = ROOT / "data/uwm_public_proxy/chongqing_central/public_feedback_readiness_chongqing"; CACHE = None


def _service():
    global CACHE
    path = Path(os.environ.get("UWM_PUBLIC_FEEDBACK_READINESS_PATH") or DEFAULT)
    if CACHE is None or CACHE[0] != path: CACHE = (path, PublicFeedbackReadinessService(path))
    return CACHE[1]


def _auth(request):
    user = _get_user_from_request(request)
    if not user: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user); return None


async def _endpoint(request, method):
    if response := _auth(request): return response
    try: return JSONResponse(await asyncio.to_thread(getattr(_service(), method)))
    except (FileNotFoundError, ValueError) as exc: return JSONResponse({"error": str(exc)}, status_code=503)


def get_uwm_public_feedback_readiness_routes():
    base = "/api/uwm/public-feedback-readiness"
    return [Route(base + "/overview", lambda request: _endpoint(request, "overview")), Route(base + "/capabilities", lambda request: _endpoint(request, "capabilities")), Route(base + "/feedback-channels", lambda request: _endpoint(request, "feedback_channels")), Route(base + "/data-contracts", lambda request: _endpoint(request, "data_contracts")), Route(base + "/analysis-gate", lambda request: _endpoint(request, "analysis_gate")), Route(base + "/map", lambda request: _endpoint(request, "map_payload"))]
