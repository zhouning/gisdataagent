"""
Causal World Model API routes — REST endpoints for intervention + counterfactual (Angle C).
"""

import asyncio
import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


async def cwm_intervene(request: Request):
    """POST /api/causal-world-model/intervene — spatial intervention prediction."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    bbox = body.get("bbox", "")
    sub_bbox = body.get("intervention_sub_bbox", "")
    if not bbox or not sub_bbox:
        return JSONResponse({"error": "bbox 和 intervention_sub_bbox 必填"}, status_code=400)

    from ..causal_world_model import intervention_predict

    try:
        result_str = await asyncio.to_thread(
            intervention_predict,
            bbox=bbox,
            intervention_sub_bbox=sub_bbox,
            intervention_type=body.get("intervention_type", "ecological_restoration"),
            baseline_scenario=body.get("baseline_scenario", "baseline"),
            start_year=str(body.get("start_year", "2023")),
            n_years=str(body.get("n_years", "5")),
        )
        return JSONResponse(json.loads(result_str))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def cwm_counterfactual(request: Request):
    """POST /api/causal-world-model/counterfactual — parallel-world comparison."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    bbox = body.get("bbox", "")
    if not bbox:
        return JSONResponse({"error": "bbox 必填"}, status_code=400)

    from ..causal_world_model import counterfactual_comparison

    try:
        result_str = await asyncio.to_thread(
            counterfactual_comparison,
            bbox=bbox,
            scenario_a=body.get("scenario_a", "baseline"),
            scenario_b=body.get("scenario_b", "ecological_restoration"),
            start_year=str(body.get("start_year", "2023")),
            n_years=str(body.get("n_years", "5")),
        )
        return JSONResponse(json.loads(result_str))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def cwm_embedding_effect(request: Request):
    """POST /api/causal-world-model/embedding-effect — embedding space treatment effect."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    bbox = body.get("bbox", "")
    if not bbox:
        return JSONResponse({"error": "bbox 必填"}, status_code=400)

    from ..causal_world_model import embedding_treatment_effect

    try:
        result_str = await asyncio.to_thread(
            embedding_treatment_effect,
            bbox=bbox,
            scenario_a=body.get("scenario_a", "baseline"),
            scenario_b=body.get("scenario_b", "ecological_restoration"),
            start_year=str(body.get("start_year", "2023")),
            n_years=str(body.get("n_years", "5")),
            metric=body.get("metric", "cosine"),
        )
        return JSONResponse(json.loads(result_str))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def cwm_calibrate(request: Request):
    """POST /api/causal-world-model/calibrate — integrate statistical prior."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    bbox = body.get("bbox", "")
    att_estimate = body.get("att_estimate")
    if not bbox or att_estimate is None:
        return JSONResponse({"error": "bbox 和 att_estimate 必填"}, status_code=400)

    from ..causal_world_model import integrate_statistical_prior

    try:
        result_str = await asyncio.to_thread(
            integrate_statistical_prior,
            bbox=bbox,
            att_estimate=float(att_estimate),
            att_se=float(body.get("att_se", 0.0)),
            treatment_variable=body.get("treatment_variable", "建设用地"),
            outcome_variable=body.get("outcome_variable", "耕地"),
            scenario=body.get("scenario", "urban_sprawl"),
            start_year=str(body.get("start_year", "2023")),
            n_years=str(body.get("n_years", "5")),
        )
        return JSONResponse(json.loads(result_str))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def get_causal_world_model_routes() -> list:
    """Return Starlette routes for causal world model endpoints."""
    return [
        Route("/api/causal-world-model/intervene", cwm_intervene, methods=["POST"]),
        Route("/api/causal-world-model/counterfactual", cwm_counterfactual, methods=["POST"]),
        Route("/api/causal-world-model/embedding-effect", cwm_embedding_effect, methods=["POST"]),
        Route("/api/causal-world-model/calibrate", cwm_calibrate, methods=["POST"]),
    ]
