"""
Causal Reasoning API routes — REST endpoints for LLM causal inference (Angle B).
"""

import asyncio
import json

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context


async def causal_dag(request: Request):
    """POST /api/causal/dag — construct causal DAG via LLM."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    question = body.get("question", "")
    if not question:
        return JSONResponse({"error": "question 必填"}, status_code=400)

    from ..llm_causal import construct_causal_dag

    try:
        result_str = await asyncio.to_thread(
            construct_causal_dag,
            question=question,
            domain=body.get("domain", "urban_geography"),
            context_file=body.get("context_file", ""),
            max_variables=body.get("max_variables", 12),
            use_geofm_embedding=body.get("use_geofm_embedding", False),
        )
        return JSONResponse(json.loads(result_str))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def causal_counterfactual(request: Request):
    """POST /api/causal/counterfactual — counterfactual reasoning via LLM."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    question = body.get("question", "")
    if not question:
        return JSONResponse({"error": "question 必填"}, status_code=400)

    from ..llm_causal import counterfactual_reasoning

    try:
        result_str = await asyncio.to_thread(
            counterfactual_reasoning,
            question=question,
            observed_data_file=body.get("observed_data_file", ""),
            treatment_description=body.get("treatment_description", ""),
            time_range=body.get("time_range", ""),
            spatial_context=body.get("spatial_context", ""),
        )
        return JSONResponse(json.loads(result_str))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def causal_explain(request: Request):
    """POST /api/causal/explain — explain causal mechanism from statistical results."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    statistical_result = body.get("statistical_result", "")
    if not statistical_result:
        return JSONResponse({"error": "statistical_result 必填"}, status_code=400)

    from ..llm_causal import explain_causal_mechanism

    try:
        result_str = await asyncio.to_thread(
            explain_causal_mechanism,
            statistical_result=statistical_result if isinstance(statistical_result, str)
                else json.dumps(statistical_result, ensure_ascii=False),
            method_name=body.get("method_name", ""),
            question=body.get("question", ""),
            domain=body.get("domain", "urban_geography"),
        )
        return JSONResponse(json.loads(result_str))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def causal_scenarios(request: Request):
    """POST /api/causal/scenarios — generate what-if scenarios via LLM."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    body = await request.json()
    base_context = body.get("base_context", "")
    if not base_context:
        return JSONResponse({"error": "base_context 必填"}, status_code=400)

    from ..llm_causal import generate_what_if_scenarios

    try:
        result_str = await asyncio.to_thread(
            generate_what_if_scenarios,
            base_context=base_context,
            n_scenarios=body.get("n_scenarios", 3),
            target_variable=body.get("target_variable", ""),
            constraint=body.get("constraint", ""),
        )
        return JSONResponse(json.loads(result_str))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def get_causal_routes() -> list:
    """Return Starlette routes for causal reasoning endpoints."""
    return [
        Route("/api/causal/dag", causal_dag, methods=["POST"]),
        Route("/api/causal/counterfactual", causal_counterfactual, methods=["POST"]),
        Route("/api/causal/explain", causal_explain, methods=["POST"]),
        Route("/api/causal/scenarios", causal_scenarios, methods=["POST"]),
    ]
