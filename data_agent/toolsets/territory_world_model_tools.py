"""Territory World Model toolset."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.base_toolset import BaseToolset

from ..territory_world_model import get_territory_world_model_service


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _svc():
    return get_territory_world_model_service()


def twm_status() -> str:
    return _json(_svc().status())


def twm_create_project(name: str = "", description: str = "", region_code: str = "", business_scenario: str = "planning_supervision") -> str:
    payload = {
        "name": name,
        "description": description,
        "region_code": region_code,
        "business_scenario": business_scenario,
    }
    from ..user_context import current_user_id
    return _json(_svc().create_project(payload, current_user_id.get("twm")))


def twm_list_projects(owner_username: str = "") -> str:
    return _json({"projects": _svc().list_projects(owner_username=owner_username or None)})


def twm_bind_layer(project_id: str, role: str = "", source_path: str = "", canonical_role: str = "", object_type: str = "feature", layer_alias: str = "", semantic_product_path: str = "", asset_id: str = "", time_label: str = "", synthetic: str = "false", not_for_production: str = "false") -> str:
    payload = {
        "role": role,
        "source_path": source_path,
        "canonical_role": canonical_role,
        "object_type": object_type,
        "layer_alias": layer_alias,
        "semantic_product_path": semantic_product_path,
        "asset_id": int(asset_id) if str(asset_id).strip().isdigit() else None,
        "time_label": time_label,
        "synthetic": str(synthetic).lower() in {"1", "true", "yes", "y", "on"},
        "not_for_production": str(not_for_production).lower() in {"1", "true", "yes", "y", "on"},
    }
    return _json(_svc().bind_layer(project_id, payload))


def twm_list_layer_bindings(project_id: str) -> str:
    return _json({"bindings": _svc().list_layer_bindings(project_id)})


def twm_build_state(project_id: str, bundle_dir: str = "", label: str = "", state_time: str = "", rule_set_id: str = "", include_auxiliary_tables: str = "true") -> str:
    payload = {
        "bundle_dir": bundle_dir,
        "label": label,
        "state_time": state_time,
        "rule_set_id": rule_set_id or None,
        "include_auxiliary_tables": str(include_auxiliary_tables).lower() in {"1", "true", "yes", "y", "on"},
    }
    try:
        result = _svc().build_state(project_id, payload)
        return _json(result)
    except Exception as exc:
        return _json({"error": str(exc), "project_id": project_id, "payload": payload})


async def twm_build_state_async(project_id: str, bundle_dir: str = "", label: str = "", state_time: str = "", rule_set_id: str = "", include_auxiliary_tables: str = "true") -> str:
    return await asyncio.to_thread(twm_build_state, project_id, bundle_dir, label, state_time, rule_set_id, include_auxiliary_tables)


def twm_evaluate_rules(state_version_id: str, rule_set_id: str = "", include_default_rules: str = "true", model_output: str = "", scenario_context: str = "") -> str:
    payload: dict[str, Any] = {
        "rule_set_id": rule_set_id or None,
        "include_default_rules": str(include_default_rules).lower() in {"1", "true", "yes", "y", "on"},
    }
    if model_output:
        try:
            payload["model_output"] = json.loads(model_output)
        except Exception:
            payload["model_output"] = {"raw": model_output}
    if scenario_context:
        try:
            payload["scenario_context"] = json.loads(scenario_context)
        except Exception:
            payload["scenario_context"] = {"raw": scenario_context}
    try:
        return _json(_svc().evaluate_rules(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_evaluate_rules_async(state_version_id: str, rule_set_id: str = "", include_default_rules: str = "true", model_output: str = "", scenario_context: str = "") -> str:
    return await asyncio.to_thread(twm_evaluate_rules, state_version_id, rule_set_id, include_default_rules, model_output, scenario_context)


def twm_explain_rule_hit(hit_id: str) -> str:
    payload = _svc().get_rule_hit(hit_id)
    if payload is None:
        return _json({"error": "rule hit not found", "hit_id": hit_id})
    return _json(payload)


def twm_review_hit(hit_id: str, decision: str = "", comment: str = "", status: str = "", assignee: str = "") -> str:
    payload = {
        "decision": decision,
        "comment": comment,
        "status": status,
        "assignee": assignee or None,
    }
    try:
        return _json(_svc().review_hit(hit_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "hit_id": hit_id})


def twm_generate_audit_report(state_version_id: str) -> str:
    try:
        return _json(_svc().generate_audit_report(state_version_id))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


def twm_forecast(state_version_id: str, action_type: str = "inspect", target_role: str = "project", magnitude: str = "1.0", scenario: str = "baseline", description: str = "", evidence_coverage: str = "", treatment: str = "", model_name: str = "", model_version: str = "", scenario_context: str = "", dynamics_candidate_report: str = "", dynamics_prediction_id: str = "") -> str:
    payload: dict[str, Any] = {
        "action_type": action_type,
        "target_role": target_role,
        "magnitude": float(magnitude) if str(magnitude).strip() else 1.0,
        "scenario": scenario,
        "description": description,
        "treatment": treatment,
        "model_name": model_name or None,
        "model_version": model_version or None,
    }
    if evidence_coverage:
        try:
            payload["evidence_coverage"] = float(evidence_coverage)
        except Exception:
            pass
    if scenario_context:
        try:
            payload["scenario_context"] = json.loads(scenario_context)
        except Exception:
            payload["scenario_context"] = {"raw": scenario_context}
    if dynamics_candidate_report:
        try:
            parsed = json.loads(dynamics_candidate_report)
            payload["dynamics_candidate_report"] = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload["dynamics_candidate_report"] = {"raw": dynamics_candidate_report}
    if dynamics_prediction_id:
        payload["dynamics_prediction_id"] = dynamics_prediction_id
    try:
        return _json(_svc().forecast(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_forecast_async(state_version_id: str, action_type: str = "inspect", target_role: str = "project", magnitude: str = "1.0", scenario: str = "baseline", description: str = "", evidence_coverage: str = "", treatment: str = "", model_name: str = "", model_version: str = "", scenario_context: str = "", dynamics_candidate_report: str = "", dynamics_prediction_id: str = "") -> str:
    return await asyncio.to_thread(twm_forecast, state_version_id, action_type, target_role, magnitude, scenario, description, evidence_coverage, treatment, model_name, model_version, scenario_context, dynamics_candidate_report, dynamics_prediction_id)


def twm_action_mask_report(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().action_mask_report(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_action_mask_report_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_action_mask_report, state_version_id, payload_json)


def twm_counterfactual_rollout(state_version_id: str, baseline_action: str = "", intervention_actions: str = "", horizon: str = "3", scenario: str = "baseline", evidence_coverage: str = "", scenario_context: str = "") -> str:
    payload: dict[str, Any] = {
        "scenario": scenario,
        "horizon": int(horizon) if str(horizon).strip().isdigit() else 3,
    }
    if baseline_action:
        try:
            payload["baseline_action"] = json.loads(baseline_action)
        except Exception:
            payload["baseline_action"] = {"action_type": baseline_action}
    if intervention_actions:
        try:
            parsed = json.loads(intervention_actions)
            payload["intervention_actions"] = parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            payload["intervention_actions"] = [{"action_type": intervention_actions}]
    if evidence_coverage:
        try:
            payload["evidence_coverage"] = float(evidence_coverage)
        except Exception:
            pass
    if scenario_context:
        try:
            payload["scenario_context"] = json.loads(scenario_context)
        except Exception:
            payload["scenario_context"] = {"raw": scenario_context}
    try:
        return _json(_svc().counterfactual_rollout(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_counterfactual_rollout_async(state_version_id: str, baseline_action: str = "", intervention_actions: str = "", horizon: str = "3", scenario: str = "baseline", evidence_coverage: str = "", scenario_context: str = "") -> str:
    return await asyncio.to_thread(twm_counterfactual_rollout, state_version_id, baseline_action, intervention_actions, horizon, scenario, evidence_coverage, scenario_context)


def twm_beam_plan(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().beam_plan(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_beam_plan_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_beam_plan, state_version_id, payload_json)


def twm_validation_report(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().validation_report(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_validation_report_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_validation_report, state_version_id, payload_json)


def twm_world_model_profile(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().world_model_profile(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_world_model_profile_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_world_model_profile, state_version_id, payload_json)


def twm_state_contract_report(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().state_contract_report(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_state_contract_report_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_state_contract_report, state_version_id, payload_json)


def twm_dynamics_backend_report(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().dynamics_backend_report(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_dynamics_backend_report_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_dynamics_backend_report, state_version_id, payload_json)


def twm_training_objective_report(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().training_objective_report(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_training_objective_report_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_training_objective_report, state_version_id, payload_json)


def twm_dynamics_training_examples(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().dynamics_training_examples(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_dynamics_training_examples_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_dynamics_training_examples, state_version_id, payload_json)


def twm_dynamics_readiness_report(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().dynamics_readiness_report(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_dynamics_readiness_report_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_dynamics_readiness_report, state_version_id, payload_json)


def twm_dynamics_evaluation_report(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().dynamics_evaluation_report(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_dynamics_evaluation_report_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_dynamics_evaluation_report, state_version_id, payload_json)


def twm_fit_dynamics_candidate(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().fit_dynamics_candidate(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_fit_dynamics_candidate_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_fit_dynamics_candidate, state_version_id, payload_json)


def twm_train_dynamics_candidate(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().train_dynamics_candidate(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_train_dynamics_candidate_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_train_dynamics_candidate, state_version_id, payload_json)


def twm_geofm_ablation_gate(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().geofm_ablation_gate(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_geofm_ablation_gate_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_geofm_ablation_gate, state_version_id, payload_json)


def twm_geofm_downstream_experiment_report(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().geofm_downstream_experiment_report(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_geofm_downstream_experiment_report_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_geofm_downstream_experiment_report, state_version_id, payload_json)


def twm_causal_calibration_report(state_version_id: str, payload_json: str = "") -> str:
    payload: dict[str, Any] = {}
    if payload_json:
        try:
            parsed = json.loads(payload_json)
            payload = parsed if isinstance(parsed, dict) else {"raw": parsed}
        except Exception:
            payload = {"raw": payload_json}
    try:
        return _json(_svc().causal_calibration_report(state_version_id, payload))
    except Exception as exc:
        return _json({"error": str(exc), "state_version_id": state_version_id})


async def twm_causal_calibration_report_async(state_version_id: str, payload_json: str = "") -> str:
    return await asyncio.to_thread(twm_causal_calibration_report, state_version_id, payload_json)


def twm_list_rule_hits(state_version_id: str, severity: str = "", status: str = "") -> str:
    return _json({"hits": _svc().get_rule_hits(state_version_id, severity=severity or None, status=status or None)})


def twm_status_detail() -> str:
    return _json(_svc().status())


_SYNC_FUNCS = [
    twm_status,
    twm_create_project,
    twm_list_projects,
    twm_bind_layer,
    twm_list_layer_bindings,
    twm_evaluate_rules,
    twm_explain_rule_hit,
    twm_review_hit,
    twm_generate_audit_report,
    twm_forecast,
    twm_action_mask_report,
    twm_counterfactual_rollout,
    twm_beam_plan,
    twm_validation_report,
    twm_world_model_profile,
    twm_state_contract_report,
    twm_dynamics_backend_report,
    twm_training_objective_report,
    twm_dynamics_training_examples,
    twm_dynamics_readiness_report,
    twm_dynamics_evaluation_report,
    twm_fit_dynamics_candidate,
    twm_train_dynamics_candidate,
    twm_geofm_ablation_gate,
    twm_geofm_downstream_experiment_report,
    twm_causal_calibration_report,
    twm_list_rule_hits,
    twm_status_detail,
]

_LONG_RUNNING_FUNCS = [
    twm_build_state_async,
    twm_evaluate_rules_async,
    twm_forecast_async,
    twm_action_mask_report_async,
    twm_counterfactual_rollout_async,
    twm_beam_plan_async,
    twm_validation_report_async,
    twm_world_model_profile_async,
    twm_state_contract_report_async,
    twm_dynamics_backend_report_async,
    twm_training_objective_report_async,
    twm_dynamics_training_examples_async,
    twm_dynamics_readiness_report_async,
    twm_dynamics_evaluation_report_async,
    twm_fit_dynamics_candidate_async,
    twm_train_dynamics_candidate_async,
    twm_geofm_ablation_gate_async,
    twm_geofm_downstream_experiment_report_async,
    twm_causal_calibration_report_async,
]


class TerritoryWorldModelToolset(BaseToolset):
    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(func) for func in _SYNC_FUNCS] + [LongRunningFunctionTool(func) for func in _LONG_RUNNING_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [tool for tool in all_tools if self._is_tool_selected(tool, readonly_context)]
