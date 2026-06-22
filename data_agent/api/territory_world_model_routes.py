"""Territory World Model routes."""

from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..territory_world_model import get_territory_world_model_service


async def twm_status(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(get_territory_world_model_service().status())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_business_scenarios(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse({"scenarios": get_territory_world_model_service().list_business_scenarios()})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_research_positioning(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(get_territory_world_model_service().research_positioning())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_research_claim_matrix(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(get_territory_world_model_service().research_claim_matrix())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_baseline_export_schema(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(get_territory_world_model_service().baseline_export_schema())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_baseline_export_templates(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(get_territory_world_model_service().baseline_export_templates())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_baseline_export_validation_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(get_territory_world_model_service().baseline_export_validation_report(body))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_baseline_export_import(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(get_territory_world_model_service().import_baseline_export(body, username=username))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_baseline_comparison_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(get_territory_world_model_service().baseline_comparison_report(body))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_baseline_evidence_pipeline_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(get_territory_world_model_service().baseline_evidence_pipeline_report(body))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_data_foundation_assessment(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(get_territory_world_model_service().data_foundation_assessment())
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def twm_projects(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)
    svc = get_territory_world_model_service()
    if request.method == "GET":
        return JSONResponse({"projects": svc.list_projects(owner_username=username)})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.create_project(body, username))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_project_detail(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    project_id = request.path_params["id"]
    project = svc.get_project(project_id)
    if project is None:
        return JSONResponse({"error": "project not found"}, status_code=404)
    return JSONResponse(project)


async def twm_project_bindings(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    project_id = request.path_params["id"]
    if request.method == "GET":
        return JSONResponse({"bindings": svc.list_layer_bindings(project_id)})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.bind_layer(project_id, body))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_project_states(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    return JSONResponse({"states": svc.list_states(project_id=request.path_params["id"])})


async def twm_build_state(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        result = await asyncio.to_thread(svc.build_state, request.path_params["id"], body)
        return JSONResponse(result)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_state_detail(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    state = svc.get_state(request.path_params["id"])
    if state is None:
        return JSONResponse({"error": "state not found"}, status_code=404)
    return JSONResponse(state)


async def twm_evaluate_rules(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        result = await asyncio.to_thread(svc.evaluate_rules, request.path_params["id"], body)
        return JSONResponse(result)
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_rule_hits(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    return JSONResponse({
        "hits": svc.get_rule_hits(
            request.path_params["id"],
            severity=request.query_params.get("severity"),
            status=request.query_params.get("status"),
        )
    })


async def twm_rule_hit_detail(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    payload = svc.get_rule_hit(request.path_params["id"])
    if payload is None:
        return JSONResponse({"error": "rule hit not found"}, status_code=404)
    return JSONResponse(payload)


async def twm_rule_hit_review(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role = _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    body.setdefault("assignee", username)
    try:
        return JSONResponse(svc.review_hit(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_audit_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        return JSONResponse(svc.generate_audit_report(request.path_params["id"]))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


async def twm_scenarios(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        if request.method == "POST":
            return JSONResponse(svc.create_scenario(body))
        project_id = request.query_params.get("project_id") or (body.get("project_id") if body else None)
        scenarios = svc.repository.list_scenarios(project_id=project_id)
        return JSONResponse({"scenarios": [item.to_dict() for item in scenarios]})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_scenario_compare(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        return JSONResponse(svc.compare_scenario(request.path_params["id"]))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)


async def twm_forecast(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.forecast(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_action_mask_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.action_mask_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_counterfactual_rollout(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.counterfactual_rollout(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_beam_plan(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.beam_plan(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_farmland_layout_optimization_capability(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.farmland_layout_optimization_capability_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_farmland_layout_candidates(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    optimization_dir = body.get("optimization_dir") or body.get("optimization_bundle_dir")
    if not optimization_dir:
        return JSONResponse({"error": "optimization_dir is required"}, status_code=400)
    try:
        return JSONResponse(svc.farmland_layout_candidate_actions_from_optimization_bundle(optimization_dir, body))
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_farmland_layout_optimization_beam_plan(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    optimization_dir = body.get("optimization_dir") or body.get("optimization_bundle_dir")
    if not optimization_dir:
        return JSONResponse({"error": "optimization_dir is required"}, status_code=400)
    try:
        return JSONResponse(svc.farmland_layout_beam_plan_from_optimization_bundle(request.path_params["id"], optimization_dir, body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_selected_plan_evaluation_bundle(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.selected_plan_evaluation_bundle(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_validation_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.validation_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_world_model_profile(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.world_model_profile(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_state_contract_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.state_contract_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_dynamics_backend_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.dynamics_backend_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_training_objective_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.training_objective_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_dynamics_training_examples(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.dynamics_training_examples(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_dynamics_readiness_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.dynamics_readiness_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_dynamics_evaluation_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.dynamics_evaluation_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_fit_dynamics_candidate(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.fit_dynamics_candidate(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_train_dynamics_candidate(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.train_dynamics_candidate(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_geofm_ablation_gate(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.geofm_ablation_gate(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_geofm_downstream_experiment_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.geofm_downstream_experiment_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_causal_calibration_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.causal_calibration_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def twm_scca_causal_evidence_report(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    svc = get_territory_world_model_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    try:
        return JSONResponse(svc.scca_causal_evidence_report(request.path_params["id"], body))
    except LookupError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


def get_territory_world_model_routes() -> list[Route]:
    return [
        Route("/api/twm/status", endpoint=twm_status, methods=["GET"]),
        Route("/api/twm/business-scenarios", endpoint=twm_business_scenarios, methods=["GET"]),
        Route("/api/twm/research-positioning", endpoint=twm_research_positioning, methods=["GET"]),
        Route("/api/twm/research-claim-matrix", endpoint=twm_research_claim_matrix, methods=["GET"]),
        Route("/api/twm/baseline-export-schema", endpoint=twm_baseline_export_schema, methods=["GET"]),
        Route("/api/twm/baseline-export-templates", endpoint=twm_baseline_export_templates, methods=["GET"]),
        Route("/api/twm/baseline-export-import", endpoint=twm_baseline_export_import, methods=["POST"]),
        Route("/api/twm/baseline-export-validation-report", endpoint=twm_baseline_export_validation_report, methods=["POST"]),
        Route("/api/twm/baseline-comparison-report", endpoint=twm_baseline_comparison_report, methods=["POST"]),
        Route("/api/twm/baseline-evidence-pipeline-report", endpoint=twm_baseline_evidence_pipeline_report, methods=["POST"]),
        Route("/api/twm/data-foundation-assessment", endpoint=twm_data_foundation_assessment, methods=["GET"]),
        Route("/api/twm/projects", endpoint=twm_projects, methods=["GET", "POST"]),
        Route("/api/twm/projects/{id}", endpoint=twm_project_detail, methods=["GET"]),
        Route("/api/twm/projects/{id}/layer-bindings", endpoint=twm_project_bindings, methods=["GET", "POST"]),
        Route("/api/twm/projects/{id}/states", endpoint=twm_project_states, methods=["GET"]),
        Route("/api/twm/projects/{id}/build-state", endpoint=twm_build_state, methods=["POST"]),
        Route("/api/twm/states/{id}", endpoint=twm_state_detail, methods=["GET"]),
        Route("/api/twm/states/{id}/evaluate-rules", endpoint=twm_evaluate_rules, methods=["POST"]),
        Route("/api/twm/states/{id}/rule-hits", endpoint=twm_rule_hits, methods=["GET"]),
        Route("/api/twm/rule-hits/{id}", endpoint=twm_rule_hit_detail, methods=["GET"]),
        Route("/api/twm/rule-hits/{id}/review", endpoint=twm_rule_hit_review, methods=["PATCH"]),
        Route("/api/twm/states/{id}/audit-report", endpoint=twm_audit_report, methods=["GET"]),
        Route("/api/twm/states/{id}/forecast", endpoint=twm_forecast, methods=["POST"]),
        Route("/api/twm/states/{id}/action-mask-report", endpoint=twm_action_mask_report, methods=["POST"]),
        Route("/api/twm/states/{id}/counterfactual-rollout", endpoint=twm_counterfactual_rollout, methods=["POST"]),
        Route("/api/twm/states/{id}/beam-plan", endpoint=twm_beam_plan, methods=["POST"]),
        Route("/api/twm/states/{id}/farmland-layout-optimization-capability", endpoint=twm_farmland_layout_optimization_capability, methods=["POST"]),
        Route("/api/twm/states/{id}/farmland-layout-candidates", endpoint=twm_farmland_layout_candidates, methods=["POST"]),
        Route("/api/twm/states/{id}/farmland-layout-optimization-beam-plan", endpoint=twm_farmland_layout_optimization_beam_plan, methods=["POST"]),
        Route("/api/twm/states/{id}/selected-plan-evaluation-bundle", endpoint=twm_selected_plan_evaluation_bundle, methods=["POST"]),
        Route("/api/twm/states/{id}/validation-report", endpoint=twm_validation_report, methods=["POST"]),
        Route("/api/twm/states/{id}/world-model-profile", endpoint=twm_world_model_profile, methods=["POST"]),
        Route("/api/twm/states/{id}/state-contract-report", endpoint=twm_state_contract_report, methods=["POST"]),
        Route("/api/twm/states/{id}/dynamics-backend-report", endpoint=twm_dynamics_backend_report, methods=["POST"]),
        Route("/api/twm/states/{id}/training-objective-report", endpoint=twm_training_objective_report, methods=["POST"]),
        Route("/api/twm/states/{id}/dynamics-training-examples", endpoint=twm_dynamics_training_examples, methods=["POST"]),
        Route("/api/twm/states/{id}/dynamics-readiness-report", endpoint=twm_dynamics_readiness_report, methods=["POST"]),
        Route("/api/twm/states/{id}/dynamics-evaluation-report", endpoint=twm_dynamics_evaluation_report, methods=["POST"]),
        Route("/api/twm/states/{id}/fit-dynamics-candidate", endpoint=twm_fit_dynamics_candidate, methods=["POST"]),
        Route("/api/twm/states/{id}/train-dynamics-candidate", endpoint=twm_train_dynamics_candidate, methods=["POST"]),
        Route("/api/twm/states/{id}/geofm-ablation-gate", endpoint=twm_geofm_ablation_gate, methods=["POST"]),
        Route("/api/twm/states/{id}/geofm-downstream-experiment-report", endpoint=twm_geofm_downstream_experiment_report, methods=["POST"]),
        Route("/api/twm/states/{id}/causal-calibration-report", endpoint=twm_causal_calibration_report, methods=["POST"]),
        Route("/api/twm/states/{id}/scca-causal-evidence-report", endpoint=twm_scca_causal_evidence_report, methods=["POST"]),
        Route("/api/twm/scenarios", endpoint=twm_scenarios, methods=["GET", "POST"]),
        Route("/api/twm/scenarios/{id}/compare", endpoint=twm_scenario_compare, methods=["GET", "POST"]),
    ]
