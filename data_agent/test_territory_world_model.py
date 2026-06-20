import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from data_agent.territory_world_model import TerritoryWorldModelService, TwmRepository, TwmStateVersion
from data_agent.api import territory_world_model_routes as routes


MMFE_DIR = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion")


def _build_service():
    repo = TwmRepository(engine=None, persist_to_db=False)
    return TerritoryWorldModelService(repository=repo)


def _build_project_and_state(service: TerritoryWorldModelService):
    project = service.create_project(
        {
            "name": "Bishan TWM Test",
            "region_code": "500227",
            "business_scenario": "planning_supervision",
        },
        username="tester",
    )
    state = service.build_state(
        project["id"],
        {
            "bundle_dir": str(MMFE_DIR),
            "include_auxiliary_tables": True,
        },
    )
    return project, state


def _fake_request(method="GET", body=b"{}", path_params=None):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {"type": "http", "method": method, "path": "/", "headers": [], "path_params": path_params or {}},
        receive,
    )


def _observed_dynamics_dataset(seed_dataset: dict, *, count: int = 6) -> dict:
    base = next(item for item in seed_dataset["examples"] if item["sample_type"] == "action_conditioned_forecast")
    examples = []
    for idx in range(count):
        item = json.loads(json.dumps(base))
        item["id"] = f"observed-{idx}"
        item["split"] = "holdout" if idx >= max(1, count - 2) else "candidate"
        item["sample_type"] = "temporal_state_transition" if idx < max(1, count // 2) else "action_conditioned_forecast"
        item["labels"]["supervision_source"] = "state_snapshots" if item["sample_type"] == "temporal_state_transition" else "expert_action_log"
        item["labels"]["evidence_supported"] = True
        item["labels"]["ranking_score"] = round(0.1 + idx * 0.02, 4)
        item["targets"]["planning_utility_delta"] = round(0.2 + idx * 0.02, 4)
        item["targets"]["future_latent_state"] = {
            "observed_next": {
                "total_area_m2": 1000.0 + idx * 10.0,
                "land_space_types": {
                    "agricultural_space": {"area_m2": 600.0 + idx * 5.0},
                    "ecological_space": {"area_m2": 400.0 + idx * 5.0},
                },
            }
        }
        item["provenance"]["ground_truth"] = True
        item["not_for_training_reasons"] = []
        examples.append(item)
    dataset = json.loads(json.dumps(seed_dataset))
    dataset["examples"] = examples
    dataset["summary"]["loss_contract"] = {
        "transition_loss": "targets.future_latent_state",
        "constraint_loss": "targets.constraint_violation_probability",
        "planning_ranking_loss": "labels.ranking_score",
        "calibration_loss": "targets.calibration",
        "uncertainty_calibration_loss": "targets.uncertainty.confidence",
        "evidence_consistency_loss": "evidence_gate.status",
        "action_mask_loss": "targets.action_mask.allowed",
    }
    return dataset


def test_state_build_loads_mmfe_bundle_and_auxiliary_tables():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)

    object_roles = state["object_counts_by_role"]
    assert state["state_version"]["object_count"] == 5745
    assert state["state_version"]["relation_count"] > 10000
    assert object_roles["project"] == 60
    assert object_roles["parcel"] == 4900
    assert object_roles["approval_record"] == 60
    assert object_roles["multimodal_evidence_index"] == 173
    assert object_roles["review_task"] == 92


def test_state_builder_keeps_project_identity_and_planning_zone_metrics():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)

    project_objects = [obj for obj in state["objects"] if obj["canonical_role"] == "project"]
    assert len(project_objects) == 60
    assert all(obj["object_code"].startswith("XMDM") for obj in project_objects[:5])
    assert all(obj["attributes"].get("project_id", "").startswith("PRJ-DEMO-") for obj in project_objects[:5])

    planning_relations = [rel for rel in state["relations"] if rel["relation_type"] == "project_overlaps_planning_zone"]
    dominant_count = sum(1 for rel in planning_relations if rel["metrics"].get("dominant_zone_type"))
    assert len(planning_relations) == 151
    assert dominant_count == 60


def test_default_rule_catalog_contains_system_gates_and_rule_codes():
    svc = _build_service()

    default_rules = svc.ensure_default_rules()
    rule_codes = {item["rule_code"] for item in default_rules["rules"]}

    assert rule_codes == {
        "TWM-DQ-001",
        "TWM-FARM-001",
        "TWM-ECO-001",
        "TWM-PLAN-001",
        "TWM-URBAN-001",
        "TWM-EVD-001",
        "TWM-GOV-001",
    }


def test_rule_evaluation_uses_rule_codes_and_builds_evidence_chain():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]

    svc.ensure_default_rules()
    result = svc.evaluate_rules(state_id, {"include_default_rules": True})
    hit_rule_ids = {item["rule_id"] for item in result["hits"]}

    assert "TWM-DQ-001" in hit_rule_ids
    assert "TWM-FARM-001" in hit_rule_ids
    assert "TWM-ECO-001" in hit_rule_ids
    assert "TWM-PLAN-001" in hit_rule_ids
    assert "TWM-URBAN-001" in hit_rule_ids
    assert "TWM-EVD-001" not in hit_rule_ids
    assert "TWM-GOV-001" in hit_rule_ids
    assert result["summary"]["data_quality_hit_count"] == 1
    assert result["summary"]["approval_consistency_hit_count"] == 36
    assert result["summary"]["hit_count"] == 96
    assert result["summary"]["evidence_item_count"] == 380
    assert all(item["checksum"] for item in result["evidence_items"])


def test_forecast_returns_multi_head_outputs_with_gate_and_calibration():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    result = svc.forecast(
        state_id,
        {
            "action_type": "allocate",
            "target_role": "project",
            "target_objects": ["PRJ-DEMO-001"],
            "spatial_scope": {"level": "county", "region_code": "500227"},
            "magnitude": 1.2,
            "scenario": "county_consolidation",
            "evidence_coverage": 0.7,
            "treatment": "causal_calibrated",
            "legal_intent": "farmland protection compliance",
            "execution_mask": {
                "allowed": True,
                "required_reviews": ["planning_committee"],
                "confidence": 0.82,
            },
            "parameters": {
                "treatment_effect": 0.08,
            },
            "scenario_context": {
                "calibration_gap": 0.05,
            },
        },
    )

    forecast = result["forecast"]
    assert {
        "future_latent_state",
        "constraint_violation_probability",
        "planning_utility_delta",
        "uncertainty",
        "calibration",
        "evidence_gate",
    }.issubset(forecast.keys())
    assert forecast["future_latent_state"]["projected"]["object_counts_by_role"]["project"] == 60
    assert forecast["uncertainty"]["confidence"] >= 0.0
    assert forecast["calibration"]["treatment_effect"] == 0.11
    assert forecast["future_latent_state"]["projected"]["action_mask"]["target_object_count"] == 1
    assert forecast["evidence_gate"]["action_mask"]["required_reviews"] == ["planning_committee"]
    assert forecast["evidence_gate"]["status"] in {"pass", "review"}


def test_forecast_action_mask_blocks_unsupported_claims():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    result = svc.forecast(
        state_id,
        {
            "action_type": "convert",
            "target_role": "project",
            "magnitude": 2.0,
            "scenario": "stress_test",
            "evidence_coverage": 0.8,
            "execution_mask": {
                "allowed": False,
                "hard_blocks": ["permanent_basic_farmland"],
                "confidence": 0.9,
            },
        },
    )

    gate = result["forecast"]["evidence_gate"]
    assert gate["status"] == "review"
    assert "action_mask_allowed" in gate["missing"]
    assert "action_mask_hard_blocks" in gate["missing"]
    assert result["forecast"]["planning_utility_delta"] < 0


def test_forecast_consumes_passed_dynamics_candidate_report():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    candidate = {
        "schema": "territory_world_model.dynamics_fit_report.v1",
        "status": "pass",
        "candidate": {
            "model_name": "hierarchical_baseline_dynamics",
            "model_version": "unit",
        },
        "predictions": {
            "selected": {
                "future_latent_state": {
                    "projected": {
                        "projected_risk_pressure": 0.22,
                        "projected_utility_delta": 0.41,
                    }
                },
                "constraint_violation_probability": 0.22,
                "planning_utility_delta": 0.41,
                "uncertainty": {"confidence": 0.76},
                "calibration": {"calibrated_utility_delta": 0.41},
            }
        },
        "evaluation": {
            "status": "pass",
            "evidence_gate": {"status": "pass", "passed": True, "missing": []},
        },
        "evidence_gate": {"status": "pass", "passed": True, "missing": []},
    }

    result = svc.forecast(
        state_id,
        {
            "action_type": "protect",
            "target_role": "project",
            "scenario": "candidate_forecast",
            "evidence_coverage": 0.72,
            "dynamics_candidate_report": candidate,
            "dynamics_prediction_id": "selected",
        },
    )

    forecast = result["forecast"]
    assert forecast["constraint_violation_probability"] == 0.22
    assert forecast["planning_utility_delta"] == 0.41
    assert forecast["uncertainty"]["confidence"] == 0.76
    assert forecast["future_latent_state"]["projected"]["dynamics_candidate_applied"] is True
    assert forecast["evidence_gate"]["dynamics_candidate"]["prediction_applied"] is True
    assert forecast["calibration"]["dynamics_backend"]["candidate"]["model_name"] == "hierarchical_baseline_dynamics"


def test_forecast_rejects_review_dynamics_candidate_report_by_default():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    baseline = svc.forecast(
        state_id,
        {
            "action_type": "protect",
            "target_role": "project",
            "scenario": "candidate_rejected",
            "evidence_coverage": 0.72,
        },
    )
    candidate = {
        "schema": "territory_world_model.dynamics_fit_report.v1",
        "status": "review",
        "candidate": {"model_name": "review_candidate"},
        "predictions": {
            "selected": {
                "constraint_violation_probability": 0.01,
                "planning_utility_delta": 0.99,
                "uncertainty": {"confidence": 0.99},
            }
        },
        "evaluation": {"status": "review", "evidence_gate": {"status": "review"}},
        "evidence_gate": {"status": "review", "missing": ["holdout"]},
    }

    result = svc.forecast(
        state_id,
        {
            "action_type": "protect",
            "target_role": "project",
            "scenario": "candidate_rejected",
            "evidence_coverage": 0.72,
            "dynamics_candidate_report": candidate,
            "dynamics_prediction_id": "selected",
        },
    )

    forecast = result["forecast"]
    assert forecast["planning_utility_delta"] == baseline["forecast"]["planning_utility_delta"]
    assert forecast["evidence_gate"]["dynamics_candidate"]["prediction_applied"] is False
    assert "dynamics_candidate_pass" in forecast["evidence_gate"]["missing"]


def test_action_mask_report_uses_rule_hits_reviews_and_evidence():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    result = svc.evaluate_rules(state_id, {"include_default_rules": True})
    project_ids = {obj["id"] for obj in state["objects"] if obj["canonical_role"] == "project"}
    target_hit = next(
        item for item in result["hits"]
        if item["severity"] in {"critical", "blocking", "high"} and item["subject_object_id"] in project_ids
    )

    report = svc.action_mask_report(
        state_id,
        {
            "action_type": "convert",
            "target_role": "project",
            "target_objects": [target_hit["subject_object_id"]],
            "scenario": "mask_test",
        },
    )

    assert report["schema"] == "territory_world_model.action_mask_report.v1"
    assert report["target_summary"]["matched_target_count"] == 1
    assert report["allowed"] is False
    assert report["execution_mask"]["allowed"] is False
    assert target_hit["rule_id"] in report["execution_mask"]["hard_blocks"]
    assert report["evidence_gate"]["status"] == "review"


def test_forecast_auto_action_mask_consumes_generated_mask():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    result = svc.evaluate_rules(state_id, {"include_default_rules": True})
    project_ids = {obj["id"] for obj in state["objects"] if obj["canonical_role"] == "project"}
    target_hit = next(
        item for item in result["hits"]
        if item["severity"] in {"critical", "blocking", "high"} and item["subject_object_id"] in project_ids
    )

    forecast = svc.forecast(
        state_id,
        {
            "action_type": "convert",
            "target_role": "project",
            "target_objects": [target_hit["subject_object_id"]],
            "scenario": "auto_mask_test",
            "evidence_coverage": 0.72,
            "auto_action_mask": True,
        },
    )

    mask = forecast["forecast"]["evidence_gate"]["action_mask"]
    assert mask["allowed"] is False
    assert target_hit["rule_id"] in mask["hard_blocks"]
    assert "action_mask_allowed" in forecast["forecast"]["evidence_gate"]["missing"]


def test_counterfactual_rollout_compares_baseline_and_intervention():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    result = svc.counterfactual_rollout(
        state_id,
        {
            "scenario": "future_aware_farmland_protection",
            "horizon": 3,
            "evidence_coverage": 0.72,
            "baseline_action": {
                "action_type": "inspect",
                "target_role": "project",
                "magnitude": 1.0,
            },
            "intervention_actions": [
                {
                    "action_type": "protect",
                    "target_role": "project",
                    "magnitude": 1.4,
                    "treatment": "causal_calibrated",
                    "parameters": {"treatment_effect": 0.06},
                }
            ],
            "scenario_context": {
                "observed_treatment_effect": 0.03,
                "calibration_gap": 0.04,
            },
        },
    )

    assert result["horizon"] == 3
    assert len(result["baseline_steps"]) == 3
    assert len(result["intervention_steps"]) == 3
    assert result["baseline_steps"][0]["arm"] == "baseline"
    assert result["intervention_steps"][0]["arm"] == "intervention"
    assert "future_latent_state" in result["intervention_steps"][0]["forecast"]
    assert "by_step" in result["deltas"]
    assert len(result["deltas"]["by_step"]) == 3
    assert "utility_delta_lift" in result["deltas"]["final"]
    assert result["evidence_gate"]["status"] in {"pass", "review"}
    assert result["calibration_summary"]["mean_treatment_effect"] > 0


def test_counterfactual_rollout_consumes_passed_dynamics_candidate_report():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    candidate = {
        "schema": "territory_world_model.dynamics_fit_report.v1",
        "status": "pass",
        "candidate": {"model_name": "rollout_candidate"},
        "predictions": {
            "baseline:0": {
                "constraint_violation_probability": 0.31,
                "planning_utility_delta": 0.12,
                "uncertainty": {"confidence": 0.63},
            },
            "intervention:0": {
                "constraint_violation_probability": 0.18,
                "planning_utility_delta": 0.38,
                "uncertainty": {"confidence": 0.74},
            },
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass", "passed": True}},
        "evidence_gate": {"status": "pass", "passed": True},
    }

    result = svc.counterfactual_rollout(
        state_id,
        {
            "scenario": "candidate_rollout",
            "horizon": 1,
            "evidence_coverage": 0.72,
            "baseline_action": {"action_type": "inspect", "target_role": "project"},
            "intervention_actions": [{"action_type": "protect", "target_role": "project"}],
            "dynamics_candidate_report": candidate,
        },
    )

    assert result["baseline_steps"][0]["metrics"]["planning_utility_delta"] == 0.12
    assert result["intervention_steps"][0]["metrics"]["planning_utility_delta"] == 0.38
    assert result["deltas"]["final"]["utility_delta_lift"] == 0.26
    assert result["summary"]["dynamics_candidate_applied"] is True


def test_beam_plan_ranks_candidate_actions_with_dynamics_backend_and_gate():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    candidate = {
        "schema": "territory_world_model.dynamics_fit_report.v1",
        "status": "pass",
        "candidate": {"model_name": "beam_candidate"},
        "predictions": {
            "candidate:0": {
                "constraint_violation_probability": 0.28,
                "planning_utility_delta": 0.18,
                "uncertainty": {"confidence": 0.62},
            },
            "candidate:1": {
                "constraint_violation_probability": 0.18,
                "planning_utility_delta": 0.42,
                "uncertainty": {"confidence": 0.74},
            },
            "candidate:2": {
                "constraint_violation_probability": 0.55,
                "planning_utility_delta": 0.5,
                "uncertainty": {"confidence": 0.4},
            },
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass"}},
        "evidence_gate": {"status": "pass"},
    }

    report = svc.beam_plan(
        state_id,
        {
            "scenario": "beam_candidate",
            "evidence_coverage": 0.72,
            "dynamics_candidate_report": candidate,
            "actions": [
                {"candidate_id": "a0", "action_type": "inspect", "target_role": "project"},
                {"candidate_id": "a1", "action_type": "protect", "target_role": "project"},
                {
                    "candidate_id": "a2",
                    "action_type": "convert",
                    "target_role": "project",
                    "execution_mask": {"allowed": False, "hard_blocks": ["pbf"], "confidence": 0.9},
                },
            ],
        },
    )

    assert report["schema"] == "territory_world_model.beam_plan_report.v1"
    assert report["ranking_policy"]["schema"] == "territory_world_model.beam_ranking_policy.v1"
    assert report["ranking_policy"]["weights"]["confidence"] == 0.1
    assert report["ranking"][0]["candidate_id"] == "a1"
    assert report["ranking"][0]["ranking_policy_id"] == "utility_risk_confidence_v1"
    assert report["selected"]["candidate_id"] == "a1"
    assert report["selected"]["ranking_policy_id"] == "utility_risk_confidence_v1"
    assert report["selected"]["forecast"]["planning_utility_delta"] == 0.42
    assert report["evidence_gate"]["candidate_count"] == 3
    assert report["candidates"][-1]["candidate_id"] == "a2"


def test_beam_plan_accepts_custom_ranking_policy_for_experimental_selection():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    candidate = {
        "schema": "territory_world_model.dynamics_fit_report.v1",
        "status": "pass",
        "candidate": {"model_name": "beam_candidate_policy"},
        "predictions": {
            "candidate:0": {
                "constraint_violation_probability": 0.2,
                "planning_utility_delta": 0.5,
                "uncertainty": {"confidence": 0.1},
            },
            "candidate:1": {
                "constraint_violation_probability": 0.2,
                "planning_utility_delta": 0.35,
                "uncertainty": {"confidence": 0.95},
            },
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass"}},
        "evidence_gate": {"status": "pass"},
    }
    payload = {
        "scenario": "beam_candidate_policy",
        "evidence_coverage": 0.72,
        "dynamics_candidate_report": candidate,
        "actions": [
            {"candidate_id": "utility_first", "action_type": "inspect", "target_role": "project"},
            {"candidate_id": "confidence_first", "action_type": "protect", "target_role": "project"},
        ],
    }

    default_report = svc.beam_plan(state_id, payload)
    custom_report = svc.beam_plan(
        state_id,
        {
            **payload,
            "ranking_policy": {
                "policy_id": "confidence_sensitive_policy",
                "weights": {"utility": 1.0, "risk": 1.0, "confidence": 0.5},
                "penalties": {"blocked": 1.0, "review": 0.15},
            },
        },
    )

    assert default_report["selected"]["candidate_id"] == "utility_first"
    assert default_report["ranking_policy"]["source"] == "default"
    assert custom_report["selected"]["candidate_id"] == "confidence_first"
    assert custom_report["ranking_policy"]["source"] == "payload"
    assert custom_report["ranking_policy"]["weights"]["confidence"] == 0.5
    assert custom_report["selected"]["ranking_policy_id"] == "confidence_sensitive_policy"


def test_state_contract_report_exposes_hierarchical_token_boundary():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.state_contract_report(state_id, {})

    assert report["schema"] == "territory_world_model.state_contract_report.v1"
    assert report["hierarchy"]["schema"] == "territory_world_model.hierarchical_state_contract.v1"
    assert report["feature_channels"]["schema"] == "territory_world_model.state_feature_channels.v1"
    assert report["constraint_channels"]["schema"] == "territory_world_model.constraint_channels.v1"
    assert report["temporal_support"]["schema"] == "territory_world_model.history_delta_contract.v1"
    token_status = {item["level"]: item["status"] for item in report["hierarchy"]["tokens"]}
    assert token_status["parcel"] == "available"
    assert token_status["block"] in {"available", "review"}
    assert token_status["township"] in {"review", "missing"}
    assert "action_conditioned_forecast" in report["downstream_consumers"]
    assert report["claim_boundary"]["status"] in {"review", "blocked", "pass"}


def test_validation_report_outputs_layered_evidence_ladder():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.validation_report(
        state_id,
        {
            "scenario": "validation_future_aware",
            "horizon": 2,
            "evidence_coverage": 0.72,
            "treatment": "causal_calibrated",
            "parameters": {"treatment_effect": 0.04},
            "scenario_context": {"observed_treatment_effect": 0.02},
        },
    )

    stage_codes = {stage["stage_code"] for stage in report["stages"]}
    assert report["state_version_id"] == state_id
    assert report["summary"]["stage_count"] == 6
    assert {
        "state_build",
        "future_state_prediction",
        "constraint_prediction",
        "counterfactual_rollout",
        "planning_lift",
        "gis_deployability",
    } == stage_codes
    assert report["overall_status"] in {"pass", "review", "blocked"}
    assert report["summary"]["validation_ladder"][0] == "state_build"
    assert any(stage["evidence"] for stage in report["stages"])


def test_validation_report_propagates_dynamics_candidate_into_counterfactual_stage():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    candidate = {
        "schema": "territory_world_model.dynamics_fit_report.v1",
        "status": "pass",
        "candidate": {"model_name": "validation_candidate"},
        "predictions": {
            "selected": {
                "constraint_violation_probability": 0.21,
                "planning_utility_delta": 0.35,
                "uncertainty": {"confidence": 0.71},
            },
            "baseline:0": {
                "constraint_violation_probability": 0.27,
                "planning_utility_delta": 0.14,
                "uncertainty": {"confidence": 0.66},
            },
            "intervention:0": {
                "constraint_violation_probability": 0.2,
                "planning_utility_delta": 0.32,
                "uncertainty": {"confidence": 0.72},
            },
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass", "passed": True}},
        "evidence_gate": {"status": "pass", "passed": True},
    }

    report = svc.validation_report(
        state_id,
        {
            "scenario": "validation_candidate",
            "horizon": 1,
            "evidence_coverage": 0.72,
            "dynamics_candidate_report": candidate,
            "dynamics_prediction_id": "selected",
        },
    )

    counterfactual = next(stage for stage in report["stages"] if stage["stage_code"] == "counterfactual_rollout")
    assert counterfactual["evidence"]["evidence_gate"]["status"] in {"pass", "review"}
    assert counterfactual["evidence"]["delta_final"]["utility_delta_lift"] == 0.18


def test_world_model_profile_maps_twm_to_functional_taxonomy():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    profile = svc.world_model_profile(
        state_id,
        {
            "scenario": "functional_taxonomy_alignment",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )

    axes = {item["axis"] for item in profile["capabilities"]}
    assert profile["taxonomy"] == "fei_fei_li_functional_taxonomy_plus_gis_evidence"
    assert {"rendering", "simulation", "planning", "closed_loop", "evidence_provenance"} == axes
    assert profile["summary"]["source_article"]["title"] == "A Functional Taxonomy of World Models"
    assert profile["summary"]["source_article"]["published_at"] == "2026-06-03"
    assert "renderer -> GIS-operational state rendering" in profile["summary"]["core_alignment"]
    rendering = next(item for item in profile["capabilities"] if item["axis"] == "rendering")
    simulation = next(item for item in profile["capabilities"] if item["axis"] == "simulation")
    planning = next(item for item in profile["capabilities"] if item["axis"] == "planning")
    assert rendering["core_algorithm"]["role_in_taxonomy"] == "renderer"
    assert rendering["core_algorithm"]["algorithm_family"] == "structured GIS state renderer"
    assert simulation["core_algorithm"]["role_in_taxonomy"] == "simulator"
    assert "hierarchical graph-temporal candidate" in simulation["core_algorithm"]["core_algorithm"]
    assert "spatiotemporal transformer candidate" in simulation["core_algorithm"]["core_algorithm"]
    assert planning["core_algorithm"]["role_in_taxonomy"] == "planner"
    assert "constrained beam search" in planning["core_algorithm"]["core_algorithm"]
    assert "photorealistic" in rendering["gaps"][0]


def test_dynamics_training_examples_define_multi_head_training_contract():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    dataset = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "training_contract",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )

    assert dataset["schema"] == "territory_world_model.dynamics_training_dataset.v1"
    assert dataset["summary"]["example_count"] >= 4
    assert dataset["summary"]["forecast_scaffold_example_count"] == 3
    assert dataset["summary"]["temporal_transition_example_count"] >= 1
    assert dataset["summary"]["supervision_sources"]["state_snapshots"] >= 1
    assert dataset["examples"][0]["labels"]["ranking_score"] >= dataset["examples"][-1]["labels"]["ranking_score"]
    first = next(item for item in dataset["examples"] if item["sample_type"] == "action_conditioned_forecast")
    assert {
        "future_latent_state",
        "constraint_violation_probability",
        "planning_utility_delta",
        "uncertainty",
        "calibration",
    }.issubset(first["targets"].keys())
    assert first["losses"]["planning_ranking_loss"] == "ranking_score"
    assert first["provenance"]["state_version_id"] == state_id
    transition = next(item for item in dataset["examples"] if item["sample_type"] == "temporal_state_transition")
    assert transition["targets"]["future_latent_state"]["schema"] == "territory_world_model.observed_temporal_latent_state.v1"
    assert transition["split"] == "holdout"
    assert transition["labels"]["supervision_source"] == "state_snapshots"
    assert "synthetic_temporal_transition" in transition["not_for_training_reasons"]
    assert "Forecast scaffold targets are generated by deterministic TWM logic" in dataset["summary"]["schema_notes"][1]


def test_dynamics_readiness_report_blocks_synthetic_or_scaffold_only_training_claims():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.dynamics_readiness_report(
        state_id,
        {
            "scenario": "readiness_default",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )

    assert report["schema"] == "territory_world_model.dynamics_readiness_report.v1"
    assert report["status"] == "blocked"
    assert report["training_scope"] == "contract_only"
    assert report["sample_inventory"]["observed_temporal_example_count"] == 0
    assert report["gate_results"]["multi_head_targets"]["passed"] is True
    assert "observed_temporal_support" in report["gate_results"]["summary"]["blocked_gates"]
    assert "usable_volume" in report["gate_results"]["summary"]["blocked_gates"]
    assert report["target_model_contract"]["state_encoder"]["geofm_policy"].startswith("B1")


def test_dynamics_readiness_report_passes_with_evidence_supported_observed_dataset():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    dataset = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "readiness_seed",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )
    dataset = _observed_dynamics_dataset(dataset)

    report = svc.dynamics_readiness_report(
        state_id,
        {
            "dataset": dataset,
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["status"] == "pass"
    assert report["training_scope"] == "trainable_action_conditioned_dynamics"
    assert report["sample_inventory"]["usable_example_count"] == 6
    assert report["gate_results"]["summary"]["blocked_gates"] == []
    assert report["target_model_contract"]["state_contract"]["schema"] == "territory_world_model.state_contract_report.v1"
    assert report["target_model_contract"]["dynamics"]["conditioned_on"] == [
        "current_state",
        "action",
        "scenario",
        "causal_calibration",
    ]


def test_dynamics_evaluation_report_blocks_scaffold_or_missing_ground_truth_claims():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.dynamics_evaluation_report(
        state_id,
        {
            "scenario": "evaluation_default",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )

    assert report["schema"] == "territory_world_model.dynamics_evaluation_report.v1"
    assert report["status"] == "blocked"
    assert report["candidate"]["is_scaffold_baseline"] is True
    assert "ground_truth_holdout_examples" in report["evidence_gate"]["missing"]
    assert "non_scaffold_candidate" in report["evidence_gate"]["missing"]


def test_dynamics_evaluation_report_passes_candidate_predictions_on_observed_holdout():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "evaluation_seed",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )
    dataset = _observed_dynamics_dataset(seed)
    predictions = {
        item["id"]: {
            "future_latent_state": item["targets"]["future_latent_state"],
            "constraint_violation_probability": item["targets"]["constraint_violation_probability"],
            "planning_utility_delta": item["targets"]["planning_utility_delta"],
            "uncertainty": {"confidence": 0.82},
            "action_mask": item["targets"]["action_mask"],
        }
        for item in dataset["examples"]
    }

    report = svc.dynamics_evaluation_report(
        state_id,
        {
            "dataset": dataset,
            "predictions": predictions,
            "candidate": {
                "model_name": "hierarchical_twm_candidate",
                "model_version": "dev",
            },
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "evaluation_thresholds": {
                "min_ground_truth_examples": 3,
                "max_mean_transition_error": 0.001,
                "max_mean_constraint_error": 0.001,
                "max_mean_utility_error": 0.001,
                "min_ranking_correlation_proxy": 0.5,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["status"] == "pass"
    assert report["candidate"]["model_name"] == "hierarchical_twm_candidate"
    assert report["evidence_gate"]["passed"] is True
    assert report["metrics"]["mean_transition_error"] == 0.0
    assert report["target_head_metrics"]["planning_utility_delta"]["ranking_correlation_proxy"] == 1.0


def test_fit_dynamics_candidate_blocks_when_readiness_fails():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.fit_dynamics_candidate(
        state_id,
        {
            "scenario": "fit_default",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )

    assert report["schema"] == "territory_world_model.dynamics_fit_report.v1"
    assert report["status"] == "blocked"
    assert report["evidence_gate"]["missing"] == ["readiness_pass"]
    assert report["learned_parameters"] == {}
    assert report["candidate"]["is_scaffold_baseline"] is False


def test_fit_dynamics_candidate_outputs_baseline_candidate_and_evaluation():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "fit_seed",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )
    dataset = _observed_dynamics_dataset(seed)

    report = svc.fit_dynamics_candidate(
        state_id,
        {
            "dataset": dataset,
            "candidate": {
                "model_name": "hierarchical_baseline_dynamics",
                "model_version": "unit",
            },
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "evaluation_thresholds": {
                "min_ground_truth_examples": 3,
                "max_mean_transition_error": 0.1,
                "max_mean_constraint_error": 0.2,
                "max_mean_utility_error": 0.2,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["schema"] == "territory_world_model.dynamics_fit_report.v1"
    assert report["readiness"]["status"] == "pass"
    assert report["learned_parameters"]["schema"] == "territory_world_model.hierarchical_baseline_dynamics_parameters.v1"
    assert report["learned_parameters"]["sample_count"] == 6
    assert len(report["predictions"]) == 6
    assert report["evaluation"]["schema"] == "territory_world_model.dynamics_evaluation_report.v1"
    assert report["candidate"]["model_name"] == "hierarchical_baseline_dynamics"


def test_dynamics_backend_report_wraps_passed_candidate_for_forecast_consumption():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(state_id, {"scenario": "backend_seed", "horizon": 2, "evidence_coverage": 0.72})
    dataset = _observed_dynamics_dataset(seed)
    first_id = dataset["examples"][0]["id"]
    candidate = {
        "schema": "territory_world_model.external_dynamics_candidate.v1",
        "status": "pass",
        "candidate": {
            "model_name": "neural_hierarchical_twm_stub",
            "model_version": "contract-test",
            "model_family": "trainable_action_conditioned_dynamics",
            "uses_causal_calibration": False,
            "is_scaffold_baseline": False,
        },
        "predictions": {
            first_id: {
                "future_latent_state": {"projected": {"projected_utility_delta": 0.51, "projected_risk_pressure": 0.11}},
                "constraint_violation_probability": 0.11,
                "planning_utility_delta": 0.51,
                "uncertainty": {"confidence": 0.82},
                "calibration": {"calibrated_utility_delta": 0.51},
                "action_mask": {"allowed": True},
            }
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass"}},
        "evidence_gate": {"status": "pass"},
    }

    report = svc.dynamics_backend_report(
        state_id,
        {
            "dataset": dataset,
            "backend": {
                "backend_id": "neural-contract",
                "backend_type": "trainable_candidate",
                "model_name": "neural_hierarchical_twm_stub",
                "trainable": True,
                "action_conditioned": True,
                "uses_causal_calibration": False,
            },
            "candidate_report": candidate,
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["schema"] == "territory_world_model.dynamics_backend_report.v1"
    assert report["status"] == "pass"
    assert report["output_contract"]["multi_head_ready"] is True
    assert report["adapter_contract"]["forecast_consumable"] is True
    assert report["claim_boundary"]["claim_scope"] == "backend_can_drive_forecast_rollout_and_beam"

    forecast = svc.forecast(
        state_id,
        {
            "action_type": "protect",
            "target_role": "project",
            "scenario": "backend_forecast",
            "evidence_coverage": 0.72,
            "dynamics_backend_report": report,
            "dynamics_prediction_id": first_id,
        },
    )

    assert forecast["forecast"]["planning_utility_delta"] == 0.51
    assert forecast["forecast"]["evidence_gate"]["dynamics_candidate"]["prediction_applied"] is True
    assert forecast["forecast"]["evidence_gate"]["dynamics_candidate"]["candidate"]["model_name"] == "neural_hierarchical_twm_stub"


def test_dynamics_backend_report_blocks_missing_multi_head_predictions():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(state_id, {"scenario": "backend_block_seed", "horizon": 2, "evidence_coverage": 0.72})
    dataset = _observed_dynamics_dataset(seed)
    candidate = {
        "schema": "territory_world_model.external_dynamics_candidate.v1",
        "status": "pass",
        "candidate": {"model_name": "bad_backend", "is_scaffold_baseline": False},
        "predictions": {"bad": {"planning_utility_delta": 0.3}},
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass"}},
        "evidence_gate": {"status": "pass"},
    }

    report = svc.dynamics_backend_report(
        state_id,
        {
            "dataset": dataset,
            "backend": {"backend_id": "bad", "backend_type": "trainable_candidate", "action_conditioned": True},
            "candidate_report": candidate,
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["status"] == "blocked"
    assert "multi_head_output" in report["gate_results"]["summary"]["blocked_gates"]
    assert report["evidence_gate"]["status"] == "blocked"


def test_training_objective_report_scores_multi_head_losses_from_passed_backend():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(state_id, {"scenario": "objective_seed", "horizon": 2, "evidence_coverage": 0.72})
    dataset = _observed_dynamics_dataset(seed)
    first_id = dataset["examples"][0]["id"]
    candidate = {
        "schema": "territory_world_model.external_dynamics_candidate.v1",
        "status": "pass",
        "candidate": {
            "model_name": "objective_backend",
            "model_version": "v1",
            "model_family": "trainable_action_conditioned_dynamics",
            "uses_causal_calibration": False,
            "is_scaffold_baseline": False,
        },
        "predictions": {
            first_id: {
                "future_latent_state": dataset["examples"][0]["targets"]["future_latent_state"],
                "constraint_violation_probability": dataset["examples"][0]["targets"]["constraint_violation_probability"],
                "planning_utility_delta": dataset["examples"][0]["targets"]["planning_utility_delta"],
                "uncertainty": dataset["examples"][0]["targets"]["uncertainty"],
                "calibration": {"calibrated_utility_delta": dataset["examples"][0]["targets"]["planning_utility_delta"]},
                "action_mask": dataset["examples"][0]["targets"]["action_mask"],
            }
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass"}},
        "evidence_gate": {"status": "pass"},
    }
    backend = svc.dynamics_backend_report(
        state_id,
        {
            "dataset": dataset,
            "backend": {
                "backend_id": "objective-backend",
                "backend_type": "trainable_candidate",
                "model_name": "objective_backend",
                "trainable": True,
                "action_conditioned": True,
                "uses_causal_calibration": False,
            },
            "candidate_report": candidate,
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    report = svc.training_objective_report(
        state_id,
        {
            "dataset": dataset,
            "dynamics_backend_report": backend,
        },
    )

    assert report["schema"] == "territory_world_model.training_objective_report.v1"
    assert report["objective_contract"]["schema"] == "territory_world_model.training_objective_contract.v1"
    assert report["loss_components"]["transition_loss"]["coverage"] >= 1
    assert report["loss_components"]["planning_ranking_loss"]["value"] is not None
    assert report["ranking_diagnostics"]["objective"].startswith("maximize planning utility")
    assert report["calibration_diagnostics"]["objective"].startswith("align calibrated utility")
    assert report["evidence_gate"]["status"] in {"pass", "review"}


def test_train_dynamics_candidate_emits_scaffold_candidate_and_backend_report():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(state_id, {"scenario": "trainer_seed", "horizon": 2, "evidence_coverage": 0.72})
    dataset = _observed_dynamics_dataset(seed)

    report = svc.train_dynamics_candidate(
        state_id,
        {
            "dataset": dataset,
            "trainer": {
                "trainer_id": "trainer-scaffold",
                "model_name": "hierarchical_trainable_dynamics_scaffold",
                "model_version": "unit",
            },
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["schema"] == "territory_world_model.train_dynamics_report.v1"
    assert report["learned_parameters"]["schema"] == "territory_world_model.trainable_dynamics_scaffold_parameters.v1"
    assert report["candidate_report"]["schema"] == "territory_world_model.trainable_dynamics_candidate_report.v1"
    assert report["backend_report"]["schema"] == "territory_world_model.dynamics_backend_report.v1"
    assert report["objective"]["schema"] == "territory_world_model.training_objective_report.v1"
    assert report["trainer"]["is_scaffold_trainer"] is True
    assert report["evidence_gate"]["status"] in {"review", "blocked"}


def test_train_dynamics_candidate_supports_neural_multi_head_trainer_contract():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(state_id, {"scenario": "trainer_neural_seed", "horizon": 2, "evidence_coverage": 0.72})
    dataset = _observed_dynamics_dataset(seed, count=8)

    report = svc.train_dynamics_candidate(
        state_id,
        {
            "dataset": dataset,
            "trainer": {
                "trainer_id": "trainer-neural",
                "model_name": "hierarchical_neural_multi_head_dynamics",
                "model_version": "unit",
                "training_method": "torch_multi_head_mlp",
            },
            "training_config": {
                "epochs": 10,
                "hidden_dim": 16,
                "learning_rate": 0.02,
                "seed": 7,
            },
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["schema"] == "territory_world_model.train_dynamics_report.v1"
    assert report["trainer"]["is_scaffold_trainer"] is False
    assert report["learned_parameters"]["schema"] == "territory_world_model.neural_multi_head_dynamics_parameters.v1"
    assert report["candidate_report"]["schema"] == "territory_world_model.neural_multi_head_dynamics_candidate_report.v1"
    assert report["backend_report"]["schema"] == "territory_world_model.dynamics_backend_report.v1"
    assert report["objective"]["schema"] == "territory_world_model.training_objective_report.v1"
    assert report["candidate_report"]["candidate"]["is_scaffold_trainer"] is False
    assert report["learned_parameters"]["training_diagnostics"]["prediction_count"] >= 1
    assert report["learned_parameters"]["feature_contract"]["action_mask_context_feature_names"]
    assert "action_mask_context.risk_proxy" in report["learned_parameters"]["feature_contract"]["action_mask_context_feature_names"]
    assert report["evidence_gate"]["status"] in {"pass", "review", "blocked"}


def test_train_dynamics_candidate_supports_hierarchical_graph_token_trainer_contract():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(state_id, {"scenario": "trainer_graph_seed", "horizon": 2, "evidence_coverage": 0.72})
    dataset = _observed_dynamics_dataset(seed, count=8)

    report = svc.train_dynamics_candidate(
        state_id,
        {
            "dataset": dataset,
            "trainer": {
                "trainer_id": "trainer-hierarchical-graph",
                "model_name": "hierarchical_graph_token_dynamics",
                "model_version": "unit",
                "training_method": "torch_hierarchical_graph",
            },
            "training_config": {
                "epochs": 8,
                "hidden_dim": 16,
                "learning_rate": 0.02,
                "seed": 11,
            },
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["schema"] == "territory_world_model.train_dynamics_report.v1"
    assert report["trainer"]["is_scaffold_trainer"] is False
    assert report["learned_parameters"]["schema"] == "territory_world_model.hierarchical_graph_dynamics_parameters.v1"
    assert report["candidate_report"]["schema"] == "territory_world_model.hierarchical_graph_dynamics_candidate_report.v1"
    assert report["candidate_report"]["candidate"]["parameter_schema"] == "territory_world_model.hierarchical_graph_dynamics_parameters.v1"
    assert report["learned_parameters"]["architecture"]["model_type"] == "torch_hierarchical_graph_candidate"
    assert {"parcel", "block", "township", "county"}.issubset(set(report["learned_parameters"]["architecture"]["token_groups"]))
    assert report["learned_parameters"]["architecture"]["temporal_message_passing"] is True
    assert report["learned_parameters"]["architecture"]["temporal_feature_count"] >= 1
    assert report["learned_parameters"]["architecture"]["action_mask_context_feature_count"] >= 1
    assert report["learned_parameters"]["feature_contract"]["flat_vector_allowed"] is False
    assert report["learned_parameters"]["feature_contract"]["temporal_feature_names"]
    assert report["learned_parameters"]["feature_contract"]["action_mask_context_feature_names"]
    assert report["learned_parameters"]["feature_contract"]["normalization"]["temporal_stats"]["mean"]
    assert report["learned_parameters"]["training_diagnostics"]["prediction_count"] >= 1
    assert report["backend_report"]["schema"] == "territory_world_model.dynamics_backend_report.v1"
    assert report["objective"]["schema"] == "territory_world_model.training_objective_report.v1"
    assert report["evidence_gate"]["status"] in {"pass", "review", "blocked"}


def test_train_dynamics_candidate_supports_spatiotemporal_transformer_trainer_contract():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(state_id, {"scenario": "trainer_transformer_seed", "horizon": 2, "evidence_coverage": 0.72})
    dataset = _observed_dynamics_dataset(seed, count=8)

    report = svc.train_dynamics_candidate(
        state_id,
        {
            "dataset": dataset,
            "trainer": {
                "trainer_id": "trainer-spatiotemporal-transformer",
                "model_name": "spatiotemporal_transformer_dynamics",
                "model_version": "unit",
                "training_method": "torch_spatiotemporal_transformer",
            },
            "training_config": {
                "epochs": 6,
                "hidden_dim": 16,
                "learning_rate": 0.02,
                "constraint_risk_calibration_weight": 0.55,
                "seed": 13,
            },
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    assert report["schema"] == "territory_world_model.train_dynamics_report.v1"
    assert report["trainer"]["is_scaffold_trainer"] is False
    assert report["learned_parameters"]["schema"] == "territory_world_model.spatiotemporal_transformer_dynamics_parameters.v1"
    assert report["candidate_report"]["schema"] == "territory_world_model.spatiotemporal_transformer_dynamics_candidate_report.v1"
    assert report["candidate_report"]["candidate"]["parameter_schema"] == "territory_world_model.spatiotemporal_transformer_dynamics_parameters.v1"
    architecture = report["learned_parameters"]["architecture"]
    assert architecture["model_type"] == "torch_spatiotemporal_transformer_candidate"
    assert {"parcel", "block", "township", "county"}.issubset(set(architecture["token_groups"]))
    assert architecture["uses_attention_backbone"] is True
    assert architecture["temporal_token_present"] is True
    assert architecture["sequence_token_count"] >= 9
    assert architecture["action_mask_context_feature_count"] >= 1
    assert report["learned_parameters"]["feature_contract"]["flat_vector_allowed"] is False
    assert "temporal" in report["learned_parameters"]["feature_contract"]["sequence_feature_names"]
    assert report["learned_parameters"]["feature_contract"]["action_mask_context_feature_names"]
    assert report["learned_parameters"]["training_config"]["constraint_risk_calibration_weight"] == 0.55
    assert report["learned_parameters"]["training_diagnostics"]["constraint_risk_calibration_weight"] == 0.55
    assert report["learned_parameters"]["training_diagnostics"]["prediction_count"] >= 1
    first_prediction = next(iter(report["predictions"].values()))
    assert first_prediction["hierarchical_token_summary"]["attention_backbone"] is True
    assert first_prediction["uncertainty"]["source"] == "torch_spatiotemporal_transformer"
    assert report["backend_report"]["schema"] == "territory_world_model.dynamics_backend_report.v1"
    assert report["objective"]["schema"] == "territory_world_model.training_objective_report.v1"
    assert report["evidence_gate"]["status"] in {"pass", "review", "blocked"}


def test_geofm_ablation_gate_defaults_to_review_without_explicit_downstream_metrics():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.geofm_ablation_gate(
        state_id,
        {
            "scenario": "geofm_gate_default",
            "evidence_coverage": 0.72,
        },
    )

    assert report["schema"] == "territory_world_model.geofm_ablation_gate.v1"
    assert report["baseline"]["variant_id"] == "B0"
    assert report["augmented"]["variant_id"] == "B1"
    assert report["augmented"]["provenance"]["vector_inventory"]["available"] is True
    assert report["evidence"]["architecture_audit"]["schema"] == "territory_world_model.geofm_architecture_audit.v1"
    assert report["evidence"]["architecture_audit"]["status"] == "review"
    assert "adapter_type" in report["evidence"]["architecture_audit"]["missing"]
    assert report["gate_status"] == "review"
    assert report["decision"] == "review_required"
    assert any("explicit B0/B1" in item for item in report["recommendations"])


def test_geofm_ablation_gate_retains_only_when_planning_lift_passes():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.geofm_ablation_gate(
        state_id,
        {
            "scenario": "geofm_gate_explicit",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
            },
            "baseline_metrics": {
                "planning_lift": 0.24,
                "constraint_risk": 0.32,
                "confidence": 0.58,
            },
            "augmented_metrics": {
                "planning_lift": 0.31,
                "constraint_risk": 0.31,
                "confidence": 0.59,
            },
        },
    )

    assert report["gate_status"] == "pass"
    assert report["decision"] == "retain_geofm_for_downstream_planning"
    assert report["deltas"]["planning_lift_delta"] >= report["thresholds"]["min_planning_lift_delta"]
    assert report["deltas"]["constraint_risk_delta"] <= report["thresholds"]["max_constraint_risk_delta"]


def test_geofm_ablation_gate_retains_when_required_architecture_audit_passes():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.geofm_ablation_gate(
        state_id,
        {
            "scenario": "geofm_gate_architecture_pass",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
                "require_architecture_audit": True,
            },
            "baseline_metrics": {
                "planning_lift": 0.24,
                "constraint_risk": 0.32,
                "confidence": 0.58,
            },
            "augmented_metrics": {
                "planning_lift": 0.31,
                "constraint_risk": 0.31,
                "confidence": 0.60,
            },
            "geofm_architecture_audit": {
                "backbone": {
                    "name": "Prithvi-100M",
                    "fused_qkv": True,
                    "input_modalities": ["sentinel-2", "dem", "explicit_gis_features"],
                },
                "adapter": {
                    "type": "lora",
                    "target_modules": ["encoder.blocks.*.attn.q_proj", "encoder.blocks.*.attn.v_proj"],
                    "capacity_score": 0.62,
                    "trainable_parameter_ratio": 0.028,
                },
                "validation": {
                    "geographic_split": True,
                    "temporal_holdout": True,
                    "production_labels": True,
                    "domain_shift_score": 0.14,
                    "label_quality": 0.82,
                },
            },
        },
    )

    audit = report["evidence"]["architecture_audit"]
    assert report["gate_status"] == "pass"
    assert report["decision"] == "retain_geofm_for_downstream_planning"
    assert audit["required"] is True
    assert audit["status"] == "pass"
    assert audit["backbone"]["architecture"] == "vision_transformer"
    assert audit["adapter"]["target_modules"]


def test_geofm_ablation_gate_blocks_required_fused_qkv_lora_without_target_modules():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.geofm_ablation_gate(
        state_id,
        {
            "scenario": "geofm_gate_architecture_blocked",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
                "require_architecture_audit": True,
            },
            "baseline_metrics": {
                "planning_lift": 0.24,
                "constraint_risk": 0.32,
                "confidence": 0.58,
            },
            "augmented_metrics": {
                "planning_lift": 0.31,
                "constraint_risk": 0.31,
                "confidence": 0.60,
            },
            "geofm_architecture_audit": {
                "backbone": {
                    "name": "Prithvi-100M",
                    "fused_qkv": True,
                    "input_modalities": ["sentinel-2", "dem"],
                },
                "adapter": {
                    "type": "lora",
                    "capacity_score": 0.62,
                    "trainable_parameter_ratio": 0.028,
                },
                "validation": {
                    "geographic_split": True,
                    "temporal_holdout": True,
                    "production_labels": True,
                    "domain_shift_score": 0.14,
                    "label_quality": 0.82,
                },
            },
        },
    )

    audit = report["evidence"]["architecture_audit"]
    assert report["gate_status"] == "blocked"
    assert report["decision"] == "gate_out_geofm"
    assert audit["status"] == "blocked"
    assert "fused_qkv_adapter_target_modules" in audit["failed"]
    assert any("fused-QKV" in item for item in report["recommendations"])


def test_geofm_ablation_gate_retains_when_required_extended_validation_passes():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.geofm_ablation_gate(
        state_id,
        {
            "scenario": "geofm_gate_extended_pass",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
                "require_extended_validation": True,
            },
            "baseline_metrics": {
                "planning_lift": 0.24,
                "constraint_risk": 0.32,
                "confidence": 0.58,
            },
            "augmented_metrics": {
                "planning_lift": 0.31,
                "constraint_risk": 0.31,
                "confidence": 0.60,
            },
            "extended_validation": {
                "D2": {
                    "sample_count": 8,
                    "planning_lift_delta": 0.06,
                    "constraint_risk_delta": -0.01,
                    "ranking_score_delta": 0.05,
                },
                "D3": {
                    "regions": [
                        {"region": "county-a", "planning_lift_delta": 0.04, "constraint_risk_delta": 0.00},
                        {"region": "county-b", "planning_lift_delta": 0.03, "constraint_risk_delta": 0.01},
                    ],
                },
                "D4": {
                    "domain_shift_score": 0.18,
                    "holdout_regret_delta": 0.01,
                    "temporal_holdout_confidence": 0.62,
                    "production_label_quality": 0.78,
                },
            },
        },
    )

    extended = report["evidence"]["extended_validation"]
    assert report["gate_status"] == "pass"
    assert report["decision"] == "retain_geofm_for_downstream_planning"
    assert extended["schema"] == "territory_world_model.geofm_extended_validation.v1"
    assert extended["required"] is True
    assert extended["status"] == "pass"
    assert extended["checks"]["D2"]["status"] == "pass"
    assert extended["checks"]["D3"]["region_count"] == 2
    assert extended["checks"]["D4"]["status"] == "pass"


def test_geofm_ablation_gate_gates_out_when_required_cross_region_validation_fails():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.geofm_ablation_gate(
        state_id,
        {
            "scenario": "geofm_gate_extended_failed",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
                "require_extended_validation": True,
            },
            "baseline_metrics": {
                "planning_lift": 0.24,
                "constraint_risk": 0.32,
                "confidence": 0.58,
            },
            "augmented_metrics": {
                "planning_lift": 0.31,
                "constraint_risk": 0.31,
                "confidence": 0.60,
            },
            "extended_validation": {
                "D2": {
                    "sample_count": 8,
                    "planning_lift_delta": 0.06,
                    "constraint_risk_delta": -0.01,
                    "ranking_score_delta": 0.05,
                },
                "D3": {
                    "regions": [
                        {"region": "county-a", "planning_lift_delta": 0.04, "constraint_risk_delta": 0.00},
                        {"region": "county-b", "planning_lift_delta": 0.00, "constraint_risk_delta": 0.01},
                    ],
                },
                "D4": {
                    "domain_shift_score": 0.18,
                    "holdout_regret_delta": 0.01,
                    "temporal_holdout_confidence": 0.62,
                    "production_label_quality": 0.78,
                },
            },
        },
    )

    extended = report["evidence"]["extended_validation"]
    assert report["gate_status"] == "blocked"
    assert report["decision"] == "gate_out_geofm"
    assert extended["status"] == "blocked"
    assert extended["failed"] == ["D3"]
    assert extended["checks"]["D3"]["regions"][1]["status"] == "blocked"
    assert any("D3 cross-region" in item for item in report["recommendations"])


def test_geofm_ablation_gate_infers_extended_validation_from_holdout_predictions():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "geofm_auto_validation_seed",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )
    dataset = _observed_dynamics_dataset(seed)
    holdout_regions = ["county-a", "county-b"]
    holdout_idx = 0
    for item in dataset["examples"]:
        if item["split"] == "holdout":
            item["provenance"]["region_code"] = holdout_regions[holdout_idx]
            holdout_idx += 1
        else:
            item["provenance"]["region_code"] = "train-county"

    baseline_predictions = {}
    augmented_predictions = {}
    for item in dataset["examples"]:
        target_lift = item["targets"]["planning_utility_delta"]
        target_risk = item["targets"]["constraint_violation_probability"]
        baseline_predictions[item["id"]] = {
            "planning_utility_delta": round(target_lift - 0.04, 4),
            "constraint_violation_probability": round(target_risk + 0.02, 4),
            "uncertainty": {"confidence": 0.61},
        }
        augmented_predictions[item["id"]] = {
            "planning_utility_delta": round(target_lift + 0.02, 4),
            "constraint_violation_probability": target_risk,
            "uncertainty": {"confidence": 0.76},
        }

    report = svc.geofm_ablation_gate(
        state_id,
        {
            "scenario": "geofm_auto_validation",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
                "require_extended_validation": True,
            },
            "baseline_metrics": {
                "planning_lift": 0.24,
                "constraint_risk": 0.32,
                "confidence": 0.58,
            },
            "augmented_metrics": {
                "planning_lift": 0.31,
                "constraint_risk": 0.31,
                "confidence": 0.60,
            },
            "dataset": dataset,
            "baseline_predictions": baseline_predictions,
            "augmented_predictions": augmented_predictions,
        },
    )

    extended = report["evidence"]["extended_validation"]
    assert report["gate_status"] == "pass"
    assert report["decision"] == "retain_geofm_for_downstream_planning"
    assert extended["auto_inferred"] is True
    assert extended["source"] == "auto_inferred"
    assert "dataset_holdout_prediction_comparison" in extended["inference_sources"]
    assert extended["checks"]["D2"]["status"] == "pass"
    assert extended["checks"]["D2"]["sample_count"] == 2
    assert extended["checks"]["D3"]["status"] == "pass"
    assert extended["checks"]["D3"]["region_count"] == 2
    assert extended["checks"]["D4"]["status"] == "pass"
    assert extended["checks"]["D4"]["metrics"]["production_label_quality"] == 1.0


def test_geofm_downstream_experiment_report_wraps_auto_inferred_evidence_and_gate():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "geofm_experiment_seed",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )
    dataset = _observed_dynamics_dataset(seed)
    holdout_regions = ["county-a", "county-b"]
    holdout_idx = 0
    for item in dataset["examples"]:
        if item["split"] == "holdout":
            item["provenance"]["region_code"] = holdout_regions[holdout_idx]
            holdout_idx += 1
        else:
            item["provenance"]["region_code"] = "train-county"

    baseline_predictions = {}
    augmented_predictions = {}
    for item in dataset["examples"]:
        target_lift = item["targets"]["planning_utility_delta"]
        target_risk = item["targets"]["constraint_violation_probability"]
        baseline_predictions[item["id"]] = {
            "planning_utility_delta": round(target_lift - 0.04, 4),
            "constraint_violation_probability": round(target_risk + 0.02, 4),
            "uncertainty": {"confidence": 0.61},
        }
        augmented_predictions[item["id"]] = {
            "planning_utility_delta": round(target_lift + 0.02, 4),
            "constraint_violation_probability": target_risk,
            "uncertainty": {"confidence": 0.76},
        }

    report = svc.geofm_downstream_experiment_report(
        state_id,
        {
            "scenario": "geofm_experiment_auto",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
                "require_extended_validation": True,
            },
            "baseline_metrics": {
                "planning_lift": 0.24,
                "constraint_risk": 0.32,
                "confidence": 0.58,
            },
            "augmented_metrics": {
                "planning_lift": 0.31,
                "constraint_risk": 0.31,
                "confidence": 0.60,
            },
            "dataset": dataset,
            "baseline_predictions": baseline_predictions,
            "augmented_predictions": augmented_predictions,
        },
    )

    assert report["schema"] == "territory_world_model.geofm_downstream_experiment_report.v1"
    assert report["status"] == "pass"
    assert report["experiment"]["comparison"].startswith("B0 GIS-only")
    assert report["variants"]["deltas"]["planning_lift_delta"] >= 0.03
    assert report["evidence"]["extended_validation"]["auto_inferred"] is True
    assert report["evidence"]["comparison_summary"]["holdout_row_count"] == 2
    assert report["evidence"]["comparison_summary"]["region_count"] == 2
    assert report["gate_report"]["schema"] == "territory_world_model.geofm_ablation_gate.v1"
    assert report["gate_report"]["decision"] == "retain_geofm_for_downstream_planning"


def test_geofm_downstream_experiment_report_auto_generates_review_only_prediction_scaffold():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "geofm_experiment_scaffold_seed",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )
    dataset = _observed_dynamics_dataset(seed)
    holdout_regions = ["county-a", "county-b"]
    holdout_idx = 0
    for item in dataset["examples"]:
        if item["split"] == "holdout":
            item["provenance"]["region_code"] = holdout_regions[holdout_idx]
            holdout_idx += 1
        else:
            item["provenance"]["region_code"] = "train-county"

    report = svc.geofm_downstream_experiment_report(
        state_id,
        {
            "scenario": "geofm_experiment_scaffold",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
                "require_extended_validation": True,
            },
            "dataset": dataset,
        },
    )

    prediction_evidence = report["evidence"]["prediction_evidence"]
    assert report["schema"] == "territory_world_model.geofm_downstream_experiment_report.v1"
    assert report["status"] == "review"
    assert prediction_evidence["prediction_source"] == "deterministic_experiment_scaffold"
    assert prediction_evidence["auto_generated"] is True
    assert prediction_evidence["baseline_prediction_count"] == len(dataset["examples"])
    assert report["evidence"]["extended_validation"]["auto_inferred"] is True
    assert report["evidence"]["comparison_summary"]["holdout_row_count"] == 2
    assert report["gate_report"]["gate_status"] == "pass"
    assert any("replace deterministic B0/B1 scaffold predictions" in item for item in report["recommendations"])


def test_geofm_ablation_gate_blocks_auto_inferred_poor_production_holdout_quality():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(
        state_id,
        {
            "scenario": "geofm_auto_validation_bad_seed",
            "horizon": 2,
            "evidence_coverage": 0.72,
        },
    )
    dataset = _observed_dynamics_dataset(seed)
    for idx, item in enumerate(dataset["examples"]):
        item["provenance"]["region_code"] = "county-a" if idx % 2 == 0 else "county-b"
        if item["split"] == "holdout":
            item["not_for_training_reasons"] = ["not_for_production_holdout"]
            item["provenance"]["not_for_production"] = True

    baseline_predictions = {}
    augmented_predictions = {}
    for item in dataset["examples"]:
        target_lift = item["targets"]["planning_utility_delta"]
        target_risk = item["targets"]["constraint_violation_probability"]
        baseline_predictions[item["id"]] = {
            "planning_utility_delta": round(target_lift - 0.04, 4),
            "constraint_violation_probability": round(target_risk + 0.02, 4),
            "uncertainty": {"confidence": 0.61},
        }
        augmented_predictions[item["id"]] = {
            "planning_utility_delta": round(target_lift + 0.02, 4),
            "constraint_violation_probability": target_risk,
            "uncertainty": {"confidence": 0.76},
        }

    report = svc.geofm_ablation_gate(
        state_id,
        {
            "scenario": "geofm_auto_validation_bad",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
                "require_extended_validation": True,
            },
            "baseline_metrics": {
                "planning_lift": 0.24,
                "constraint_risk": 0.32,
                "confidence": 0.58,
            },
            "augmented_metrics": {
                "planning_lift": 0.31,
                "constraint_risk": 0.31,
                "confidence": 0.60,
            },
            "dataset": dataset,
            "baseline_predictions": baseline_predictions,
            "augmented_predictions": augmented_predictions,
        },
    )

    extended = report["evidence"]["extended_validation"]
    assert report["gate_status"] == "blocked"
    assert report["decision"] == "gate_out_geofm"
    assert extended["auto_inferred"] is True
    assert extended["status"] == "blocked"
    assert extended["failed"] == ["D4"]
    assert extended["checks"]["D4"]["metrics"]["production_label_quality"] == 0.0
    assert "production_label_quality" in extended["checks"]["D4"]["failed"]


def test_geofm_ablation_gate_gates_out_when_lift_fails():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.geofm_ablation_gate(
        state_id,
        {
            "scenario": "geofm_gate_failed",
            "evidence_coverage": 0.72,
            "thresholds": {
                "allow_not_for_production_vectors": True,
            },
            "baseline_metrics": {
                "planning_lift": 0.24,
                "constraint_risk": 0.32,
                "confidence": 0.58,
            },
            "augmented_metrics": {
                "planning_lift": 0.25,
                "constraint_risk": 0.37,
                "confidence": 0.60,
            },
        },
    )

    assert report["gate_status"] == "blocked"
    assert report["decision"] == "gate_out_geofm"
    assert report["deltas"]["planning_lift_delta"] < report["thresholds"]["min_planning_lift_delta"]
    assert any("gate out GeoFM" in item for item in report["recommendations"])


def test_causal_calibration_report_passes_with_balanced_observations():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    records = []
    for idx in range(6):
        covariates = {"area_m2": 1000 + idx * 10, "quality_score": 0.82 + idx * 0.01}
        records.append({"unit_id": f"c-{idx}", "treatment": 0, "outcome": 0.10 + idx * 0.005, "stratum": "project", "covariates": covariates})
        records.append({"unit_id": f"t-{idx}", "treatment": 1, "outcome": 0.20 + idx * 0.005, "stratum": "project", "covariates": covariates})

    report = svc.causal_calibration_report(
        state_id,
        {
            "treatment": "farmland_protection",
            "outcome": "planning_utility_delta",
            "model_effect": 0.05,
            "records": records,
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
            },
        },
    )

    assert report["schema"] == "territory_world_model.causal_calibration_report.v1"
    assert report["status"] == "pass"
    assert report["estimate"]["treated_count"] == 6
    assert report["estimate"]["control_count"] == 6
    assert report["estimate"]["att"] > 0
    assert report["estimate"]["backend"]["schema"] == "territory_world_model.causal_calibration_backend.v1"
    assert report["estimate"]["estimator"]["primary"] == "augmented_ipw_ate"
    assert report["estimate"]["overlap"]["status"] == "pass"
    assert report["estimate"]["balance"]["status"] == "pass"
    assert report["estimate"]["spatial"]["status"] == "not_applicable"
    assert report["estimate"]["spatial_estimator"]["status"] == "not_applicable"
    assert report["calibration"]["calibration_factor"] > 1.0
    assert report["evidence_gate"]["status"] == "pass"


def test_causal_calibration_report_uses_observed_approval_history_before_state_objects():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    observed_history = []
    for idx in range(6):
        covariates = {"area_m2": 1000 + idx * 10, "quality_score": 0.82 + idx * 0.01}
        observed_history.append(
            {
                "approval_id": f"OBS-C-{idx}",
                "project_id": f"OBS-PRJ-C-{idx}",
                "approval_status": "in_review",
                "outcome": 0.10 + idx * 0.005,
                "stratum": "observed-county",
                "cluster": f"observed-pair-{idx}",
                "covariates": covariates,
                "synthetic": False,
                "not_for_production": False,
            }
        )
        observed_history.append(
            {
                "approval_id": f"OBS-T-{idx}",
                "project_id": f"OBS-PRJ-T-{idx}",
                "approval_status": "approved",
                "outcome": 0.20 + idx * 0.005,
                "stratum": "observed-county",
                "cluster": f"observed-pair-{idx}",
                "covariates": covariates,
                "synthetic": False,
                "not_for_production": False,
            }
        )

    report = svc.causal_calibration_report(
        state_id,
        {
            "treatment": "approval_intervention",
            "outcome": "planning_utility_delta",
            "model_effect": 0.05,
            "observed_history": observed_history,
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_residual_moran": 1.0,
            },
        },
    )

    assert report["status"] == "pass"
    assert report["provenance"]["record_source"] == "observed_approval_review_history"
    assert report["provenance"]["record_count"] == 12
    inventory = report["provenance"]["record_inventory"]
    assert inventory["schema"] == "territory_world_model.causal_record_inventory.v1"
    assert inventory["record_count"] == 12
    assert inventory["source_count"] == 1
    assert inventory["treated_count"] == 6
    assert inventory["control_count"] == 6
    assert inventory["cluster_count"] == 6
    assert inventory["spatial_support"]["has_clusters"] is True
    assert inventory["synthetic_record_count"] == 0
    assert inventory["not_for_production_record_count"] == 0
    assert report["estimate"]["raw_record_count"] == 12
    assert report["estimate"]["usable_record_count"] == 12
    assert report["estimate"]["treated_count"] == 6
    assert report["estimate"]["control_count"] == 6
    assert report["estimate"]["att"] > 0
    assert report["evidence_gate"]["synthetic_record_count"] == 0
    assert report["evidence_gate"]["not_for_production_record_count"] == 0
    assert report["evidence_gate"]["record_source"] == "observed_approval_review_history"
    assert "synthetic_records" not in report["evidence_gate"]["missing"]
    assert "not_for_production_records" not in report["evidence_gate"]["missing"]


def test_causal_calibration_report_loads_observed_approval_history_csv(tmp_path):
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    history_path = tmp_path / "observed_approval_history.csv"
    rows = ["approval_id,project_id,approval_status,outcome,stratum,area_m2,quality_score,synthetic,not_for_production"]
    for idx in range(6):
        rows.append(f"CSV-C-{idx},CSV-PRJ-C-{idx},in_review,{0.10 + idx * 0.005:.3f},csv-county,{1000 + idx * 10},{0.82 + idx * 0.01:.3f},False,False")
        rows.append(f"CSV-T-{idx},CSV-PRJ-T-{idx},approved,{0.20 + idx * 0.005:.3f},csv-county,{1000 + idx * 10},{0.82 + idx * 0.01:.3f},False,False")
    history_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history_path": str(history_path),
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
            },
        },
    )

    assert report["status"] == "pass"
    assert report["provenance"]["record_source"] == "observed_approval_review_history"
    assert report["provenance"]["record_count"] == 12
    inventory = report["provenance"]["record_inventory"]
    assert inventory["source_path_count"] == 1
    assert inventory["source_paths"] == [str(history_path)]
    assert inventory["treated_count"] == 6
    assert inventory["control_count"] == 6
    assert report["estimate"]["usable_record_count"] == 12
    assert report["evidence_gate"]["status"] == "pass"


def test_causal_calibration_report_maps_observed_history_admin_code_to_cluster(tmp_path):
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    history_path = tmp_path / "observed_approval_history_admin.csv"
    rows = ["approval_id,project_id,approval_status,outcome,stratum,DKXZQDM,DKMJ,synthetic,not_for_production"]
    for idx in range(6):
        rows.append(f"ADM-C-{idx},ADM-PRJ-C-{idx},in_review,{0.10 + idx * 0.005:.3f},admin-county,500227,{1000 + idx * 10},False,False")
        rows.append(f"ADM-T-{idx},ADM-PRJ-T-{idx},approved,{0.20 + idx * 0.005:.3f},admin-county,500227,{1000 + idx * 10},False,False")
    history_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history_path": str(history_path),
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
            },
        },
    )

    inventory = report["provenance"]["record_inventory"]
    assert report["provenance"]["record_source"] == "observed_approval_review_history"
    assert inventory["cluster_count"] == 1
    assert inventory["clusters"] == ["500227"]
    assert inventory["spatial_support"]["has_clusters"] is True
    assert inventory["spatial_support"]["spatial_record_count"] == 12


def test_causal_calibration_report_uses_observed_history_spatial_support():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    observed_history = []
    for idx in range(6):
        covariates = {"area_m2": 1000 + idx * 10, "quality_score": 0.82 + idx * 0.01}
        control_id = f"OBS-SP-C-{idx}"
        treated_id = f"OBS-SP-T-{idx}"
        observed_history.append(
            {
                "unit_id": control_id,
                "approval_id": control_id,
                "project_id": f"OBS-SP-PRJ-C-{idx}",
                "approval_status": "in_review",
                "outcome": 0.10 + idx * 0.005,
                "stratum": "observed-county",
                "cluster": f"observed-block-{idx}",
                "neighbors": [treated_id],
                "x": 106.20 + idx * 0.01,
                "y": 29.60 + idx * 0.01,
                "covariates": covariates,
                "synthetic": False,
                "not_for_production": False,
            }
        )
        observed_history.append(
            {
                "unit_id": treated_id,
                "approval_id": treated_id,
                "project_id": f"OBS-SP-PRJ-T-{idx}",
                "approval_status": "approved",
                "outcome": 0.20 + idx * 0.005,
                "stratum": "observed-county",
                "cluster": f"observed-block-{idx}",
                "neighbors": [control_id],
                "x": 106.205 + idx * 0.01,
                "y": 29.605 + idx * 0.01,
                "covariates": covariates,
                "synthetic": False,
                "not_for_production": False,
            }
        )

    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history": observed_history,
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_residual_moran": 1.0,
            },
        },
    )

    inventory = report["provenance"]["record_inventory"]
    assert report["status"] == "pass"
    assert report["provenance"]["record_source"] == "observed_approval_review_history"
    assert inventory["cluster_count"] == 6
    assert inventory["neighbor_record_count"] == 12
    assert inventory["coordinate_record_count"] == 12
    assert inventory["spatial_support"]["has_clusters"] is True
    assert inventory["spatial_support"]["has_neighbor_links"] is True
    assert inventory["spatial_support"]["has_coordinates"] is True
    assert inventory["spatial_support"]["spatial_record_count"] == 12
    assert report["estimate"]["estimator"]["primary"] == "spatial_fixed_effect_neighbor_adapter"
    assert report["estimate"]["spatial"]["neighbor_edge_count"] == 6
    assert report["estimate"]["spatial_estimator"]["status"] == "pass"
    assert report["estimate"]["spatial_estimator"]["support"]["mixed_spatial_unit_count"] == 6
    assert "spatial_estimator" not in report["evidence_gate"]["missing"]


def test_causal_calibration_report_loads_observed_history_csv_spatial_support(tmp_path):
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    history_path = tmp_path / "observed_approval_history_spatial.csv"
    rows = [
        "unit_id,approval_id,project_id,approval_status,outcome,stratum,cluster,neighbors,x,y,area_m2,quality_score,synthetic,not_for_production"
    ]
    for idx in range(6):
        control_id = f"CSV-SP-C-{idx}"
        treated_id = f"CSV-SP-T-{idx}"
        rows.append(
            f"{control_id},{control_id},CSV-SP-PRJ-C-{idx},in_review,{0.10 + idx * 0.005:.3f},csv-county,csv-block-{idx},{treated_id},{106.20 + idx * 0.01:.4f},{29.60 + idx * 0.01:.4f},{1000 + idx * 10},{0.82 + idx * 0.01:.3f},False,False"
        )
        rows.append(
            f"{treated_id},{treated_id},CSV-SP-PRJ-T-{idx},approved,{0.20 + idx * 0.005:.3f},csv-county,csv-block-{idx},{control_id},{106.205 + idx * 0.01:.4f},{29.605 + idx * 0.01:.4f},{1000 + idx * 10},{0.82 + idx * 0.01:.3f},False,False"
        )
    history_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "observed_history_path": str(history_path),
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_residual_moran": 1.0,
            },
        },
    )

    inventory = report["provenance"]["record_inventory"]
    assert report["status"] == "pass"
    assert report["provenance"]["record_source"] == "observed_approval_review_history"
    assert inventory["source_paths"] == [str(history_path)]
    assert inventory["cluster_count"] == 6
    assert inventory["neighbor_record_count"] == 12
    assert inventory["coordinate_record_count"] == 12
    assert inventory["spatial_support"]["spatial_record_count"] == 12
    assert report["estimate"]["estimator"]["primary"] == "spatial_fixed_effect_neighbor_adapter"
    assert report["estimate"]["spatial"]["neighbor_edge_count"] == 6
    assert report["estimate"]["spatial_estimator"]["status"] == "pass"
    assert report["estimate"]["spatial_estimator"]["support"]["cross_treatment_neighbor_edge_count"] == 6
    assert "spatial_estimator" not in report["evidence_gate"]["missing"]


def test_causal_record_inventory_requires_complete_coordinate_pair_for_spatial_support():
    svc = _build_service()

    inventory = svc._causal_record_inventory(
        [
            {"unit_id": "x-only", "treatment": 0, "outcome": 0.10, "x": 106.20},
            {"unit_id": "y-only", "treatment": 1, "outcome": 0.20, "y": 29.60},
            {"unit_id": "xy", "treatment": 1, "outcome": 0.21, "x": 106.21, "y": 29.61},
            {"unit_id": "cluster", "treatment": 0, "outcome": 0.11, "cluster": "block-a"},
            {"unit_id": "neighbor", "treatment": 1, "outcome": 0.22, "neighbors": ["cluster"]},
        ]
    )

    assert inventory["coordinate_record_count"] == 1
    assert inventory["neighbor_record_count"] == 1
    assert inventory["cluster_count"] == 1
    assert inventory["spatial_support"]["has_coordinates"] is True
    assert inventory["spatial_support"]["spatial_record_count"] == 3


def test_causal_calibration_report_reviews_poor_overlap_even_with_balanced_counts():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    records = []
    for idx in range(6):
        records.append(
            {
                "unit_id": f"c-low-overlap-{idx}",
                "treatment": 0,
                "outcome": 0.10 + idx * 0.004,
                "stratum": "project",
                "propensity_score": 0.02,
                "covariates": {"baseline_outcome": 0.10 + idx * 0.004},
            }
        )
        records.append(
            {
                "unit_id": f"t-low-overlap-{idx}",
                "treatment": 1,
                "outcome": 0.22 + idx * 0.004,
                "stratum": "project",
                "propensity_score": 0.98,
                "covariates": {"baseline_outcome": 0.22 + idx * 0.004},
            }
        )

    report = svc.causal_calibration_report(
        state_id,
        {
            "treatment": "farmland_protection",
            "outcome": "planning_utility_delta",
            "model_effect": 0.05,
            "records": records,
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
                "min_overlap_ratio": 0.8,
                "min_propensity": 0.05,
            },
        },
    )

    assert report["status"] == "review"
    assert report["estimate"]["overlap"]["status"] == "review"
    assert report["estimate"]["overlap"]["clipped_propensity_count"] == 12
    assert "overlap" in report["evidence_gate"]["missing"]
    assert any("overlap" in item for item in report["recommendations"])


def test_causal_calibration_report_uses_spatial_estimator_with_balanced_units():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    records = []
    for idx in range(6):
        covariates = {"area_m2": 1000 + idx * 10, "quality_score": 0.82 + idx * 0.01}
        records.append(
            {
                "unit_id": f"c-spatial-{idx}",
                "treatment": 0,
                "outcome": 0.10 + idx * 0.005,
                "stratum": "project",
                "cluster": f"pair-{idx}",
                "neighbors": [f"t-spatial-{idx}"],
                "covariates": covariates,
            }
        )
        records.append(
            {
                "unit_id": f"t-spatial-{idx}",
                "treatment": 1,
                "outcome": 0.20 + idx * 0.005,
                "stratum": "project",
                "cluster": f"pair-{idx}",
                "neighbors": [f"c-spatial-{idx}"],
                "covariates": covariates,
            }
        )

    report = svc.causal_calibration_report(
        state_id,
        {
            "treatment": "farmland_protection",
            "outcome": "planning_utility_delta",
            "model_effect": 0.05,
            "records": records,
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_residual_moran": 1.0,
            },
        },
    )

    assert report["status"] == "pass"
    assert report["estimate"]["estimator"]["primary"] == "spatial_fixed_effect_neighbor_adapter"
    assert report["estimate"]["spatial"]["status"] == "pass"
    assert report["estimate"]["spatial"]["neighbor_edge_count"] == 6
    assert report["estimate"]["spatial"]["spatial_cluster_count"] == 6
    assert report["estimate"]["spatial_estimator"]["schema"] == "territory_world_model.spatial_causal_estimator.v1"
    assert report["estimate"]["spatial_estimator"]["status"] == "pass"
    assert report["estimate"]["spatial_estimator"]["support"]["mixed_spatial_unit_count"] == 6
    assert report["estimate"]["spatial_estimator"]["support"]["cross_treatment_neighbor_edge_count"] == 6
    assert report["estimate"]["spatial_estimator"]["effect"] > 0
    assert report["estimate"]["spatial_estimator"]["uncertainty"]["spatial_block_bootstrap"]["status"] == "pass"
    assert report["estimate"]["spatial_estimator"]["uncertainty"]["geographic_holdout"]["status"] == "pass"
    assert "spatial_interference" not in report["evidence_gate"]["missing"]
    assert "spatial_estimator" not in report["evidence_gate"]["missing"]


def test_causal_calibration_report_reviews_unstable_geographic_holdout():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    records = []
    effects = [0.10, 0.10, 0.10, 0.10, 0.10, -0.35]
    for idx, effect in enumerate(effects):
        covariates = {"area_m2": 1000 + idx * 10, "quality_score": 0.82 + idx * 0.01}
        base = 0.10 + idx * 0.005
        records.append(
            {
                "unit_id": f"unstable-c-{idx}",
                "treatment": 0,
                "outcome": base,
                "stratum": "project",
                "cluster": f"unstable-pair-{idx}",
                "neighbors": [f"unstable-t-{idx}"],
                "covariates": covariates,
            }
        )
        records.append(
            {
                "unit_id": f"unstable-t-{idx}",
                "treatment": 1,
                "outcome": base + effect,
                "stratum": "project",
                "cluster": f"unstable-pair-{idx}",
                "neighbors": [f"unstable-c-{idx}"],
                "covariates": covariates,
            }
        )

    report = svc.causal_calibration_report(
        state_id,
        {
            "treatment": "farmland_protection",
            "outcome": "planning_utility_delta",
            "model_effect": 0.05,
            "records": records,
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
                "max_neighbor_exposure_gap": 1.0,
                "max_spatial_residual_moran": 1.0,
                "max_spatial_effect_gap": 1.0,
                "max_spatial_bootstrap_interval_width": 1.0,
                "max_spatial_holdout_delta": 0.05,
            },
        },
    )

    assert report["status"] == "review"
    estimator = report["estimate"]["spatial_estimator"]
    assert estimator["status"] == "review"
    assert estimator["uncertainty"]["geographic_holdout"]["status"] == "review"
    assert "geographic_holdout_instability" in estimator["review_reasons"]
    assert "spatial_estimator" in report["evidence_gate"]["missing"]
    assert any("geographic holdout" in item for item in report["recommendations"])


def test_causal_calibration_report_reviews_spatial_interference():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    records = []
    for idx in range(6):
        records.append(
            {
                "unit_id": f"spatial-control-{idx}",
                "treatment": 0,
                "outcome": 0.10 + idx * 0.004,
                "stratum": "project",
                "cluster": "control_cluster",
                "neighbors": [f"spatial-control-{(idx + 1) % 6}"],
                "covariates": {"area_m2": 1000 + idx * 10, "quality_score": 0.80 + idx * 0.01},
            }
        )
        records.append(
            {
                "unit_id": f"spatial-treated-{idx}",
                "treatment": 1,
                "outcome": 0.22 + idx * 0.004,
                "stratum": "project",
                "cluster": "treated_cluster",
                "neighbors": [f"spatial-treated-{(idx + 1) % 6}"],
                "covariates": {"area_m2": 1000 + idx * 10, "quality_score": 0.80 + idx * 0.01},
            }
        )

    report = svc.causal_calibration_report(
        state_id,
        {
            "treatment": "farmland_protection",
            "outcome": "planning_utility_delta",
            "model_effect": 0.05,
            "records": records,
            "thresholds": {
                "min_records": 10,
                "min_treated": 5,
                "min_control": 5,
                "max_neighbor_exposure_gap": 0.35,
                "max_spatial_cluster_treatment_gap": 0.2,
            },
        },
    )

    assert report["status"] == "review"
    assert report["estimate"]["spatial"]["status"] == "review"
    assert report["estimate"]["spatial"]["cluster_balance"]["max_abs_treatment_share_gap"] == 0.5
    assert report["estimate"]["spatial_estimator"]["status"] == "review"
    assert "spatial_treatment_concentration" in report["estimate"]["spatial_estimator"]["review_reasons"]
    assert "spatial_interference" in report["evidence_gate"]["missing"]
    assert "spatial_estimator" in report["evidence_gate"]["missing"]
    assert any("spatial spillover" in item for item in report["recommendations"])


def test_causal_calibration_report_uses_state_object_observations_before_scaffold():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.causal_calibration_report(
        state_id,
        {
            "scenario": "causal_scaffold_review",
            "evidence_coverage": 0.72,
            "model_effect": 0.05,
        },
    )

    assert report["status"] == "review"
    assert report["evidence_gate"]["status"] == "review"
    assert report["provenance"]["record_source"] == "state_object_observations"
    assert report["provenance"]["record_count"] == 60
    assert report["estimate"]["raw_record_count"] == 60
    assert report["estimate"]["usable_record_count"] == 0
    assert report["evidence_gate"]["synthetic_record_count"] == 60
    assert report["evidence_gate"]["not_for_production_record_count"] == 60
    assert "synthetic_records" in report["evidence_gate"]["missing"]
    assert "not_for_production_records" in report["evidence_gate"]["missing"]
    assert any("not_for_production" in item for item in report["recommendations"])


def test_causal_calibration_report_falls_back_to_scaffold_without_state_object_observations():
    svc = _build_service()
    project = svc.create_project(
        {
            "name": "Empty TWM Causal Test",
            "region_code": "500227",
            "business_scenario": "planning_supervision",
        },
        username="tester",
    )
    state = TwmStateVersion(
        project_id=project["id"],
        label="empty causal fallback",
        object_count=0,
        relation_count=0,
        quality_summary={},
        build_status="ready",
        summary={"object_counts_by_role": {}, "relation_counts_by_type": {}},
    )
    svc.repository.save_state_version(state)

    report = svc.causal_calibration_report(
        state.id,
        {
            "scenario": "causal_scaffold_review",
            "evidence_coverage": 0.72,
            "model_effect": 0.05,
        },
    )

    assert report["status"] == "review"
    assert report["evidence_gate"]["status"] == "review"
    assert report["provenance"]["record_source"] == "dynamics_training_examples_scaffold"
    assert any("scaffold-derived calibration" in item for item in report["recommendations"])


def test_forecast_consumes_passed_causal_calibration_report():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    base = svc.forecast(
        state_id,
        {
            "action_type": "protect",
            "target_role": "project",
            "magnitude": 1.0,
            "scenario": "causal_scaled_forecast",
            "evidence_coverage": 0.72,
        },
    )
    report = {
        "schema": "territory_world_model.causal_calibration_report.v1",
        "status": "pass",
        "estimate": {"att": 0.1},
        "calibration": {
            "utility_scale_adjustment": 2.0,
            "scenario_scale_adjustment": 1.1,
            "status": "pass",
        },
        "evidence_gate": {"status": "pass"},
    }
    calibrated = svc.forecast(
        state_id,
        {
            "action_type": "protect",
            "target_role": "project",
            "magnitude": 1.0,
            "scenario": "causal_scaled_forecast",
            "evidence_coverage": 0.72,
            "causal_calibration_report": report,
        },
    )

    assert calibrated["forecast"]["planning_utility_delta"] > base["forecast"]["planning_utility_delta"]
    assert calibrated["forecast"]["calibration"]["utility_scale_adjustment"] == 2.0
    assert calibrated["forecast"]["future_latent_state"]["projected"]["causal_adjustment"]["source"]["status"] == "pass"


def test_forecast_ignores_review_causal_calibration_report():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    base = svc.forecast(
        state_id,
        {
            "action_type": "protect",
            "target_role": "project",
            "magnitude": 1.0,
            "scenario": "causal_review_forecast",
            "evidence_coverage": 0.72,
        },
    )
    review = svc.forecast(
        state_id,
        {
            "action_type": "protect",
            "target_role": "project",
            "magnitude": 1.0,
            "scenario": "causal_review_forecast",
            "evidence_coverage": 0.72,
            "causal_calibration_report": {
                "schema": "territory_world_model.causal_calibration_report.v1",
                "status": "review",
                "calibration": {
                    "utility_scale_adjustment": 3.0,
                    "scenario_scale_adjustment": 1.2,
                },
                "evidence_gate": {"status": "review"},
            },
        },
    )

    assert review["forecast"]["planning_utility_delta"] == base["forecast"]["planning_utility_delta"]
    assert review["forecast"]["calibration"]["utility_scale_adjustment"] == 1.0


def test_twm_toolset_lists_sync_and_long_running_tools():
    from data_agent.toolsets.territory_world_model_tools import TerritoryWorldModelToolset

    toolset = TerritoryWorldModelToolset()
    tools = asyncio.run(toolset.get_tools())
    names = {tool.name for tool in tools}

    assert "twm_status" in names
    assert "twm_create_project" in names
    assert "twm_build_state_async" in names
    assert "twm_evaluate_rules_async" in names
    assert "twm_forecast_async" in names
    assert "twm_action_mask_report" in names
    assert "twm_action_mask_report_async" in names
    assert "twm_counterfactual_rollout" in names
    assert "twm_counterfactual_rollout_async" in names
    assert "twm_beam_plan" in names
    assert "twm_beam_plan_async" in names
    assert "twm_validation_report" in names
    assert "twm_validation_report_async" in names
    assert "twm_world_model_profile" in names
    assert "twm_world_model_profile_async" in names
    assert "twm_state_contract_report" in names
    assert "twm_state_contract_report_async" in names
    assert "twm_dynamics_backend_report" in names
    assert "twm_dynamics_backend_report_async" in names
    assert "twm_training_objective_report" in names
    assert "twm_training_objective_report_async" in names
    assert "twm_train_dynamics_candidate" in names
    assert "twm_train_dynamics_candidate_async" in names
    assert "twm_dynamics_training_examples" in names
    assert "twm_dynamics_training_examples_async" in names
    assert "twm_dynamics_readiness_report" in names
    assert "twm_dynamics_readiness_report_async" in names
    assert "twm_dynamics_evaluation_report" in names
    assert "twm_dynamics_evaluation_report_async" in names
    assert "twm_fit_dynamics_candidate" in names
    assert "twm_fit_dynamics_candidate_async" in names
    assert "twm_geofm_ablation_gate" in names
    assert "twm_geofm_ablation_gate_async" in names
    assert "twm_geofm_downstream_experiment_report" in names
    assert "twm_geofm_downstream_experiment_report_async" in names
    assert "twm_causal_calibration_report" in names
    assert "twm_causal_calibration_report_async" in names


def test_twm_forecast_tool_accepts_dynamics_candidate_report(monkeypatch):
    from data_agent.toolsets import territory_world_model_tools as tools

    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    monkeypatch.setattr(tools, "get_territory_world_model_service", lambda: svc)
    candidate = {
        "schema": "territory_world_model.dynamics_fit_report.v1",
        "status": "pass",
        "candidate": {"model_name": "tool_candidate"},
        "predictions": {
            "p1": {
                "constraint_violation_probability": 0.18,
                "planning_utility_delta": 0.36,
                "uncertainty": {"confidence": 0.7},
            }
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass"}},
        "evidence_gate": {"status": "pass"},
    }

    payload = json.loads(
        tools.twm_forecast(
            state_id,
            action_type="protect",
            target_role="project",
            scenario="tool_candidate_forecast",
            evidence_coverage="0.72",
            dynamics_candidate_report=json.dumps(candidate),
            dynamics_prediction_id="p1",
        )
    )

    assert payload["forecast"]["planning_utility_delta"] == 0.36
    assert payload["forecast"]["evidence_gate"]["dynamics_candidate"]["candidate"]["model_name"] == "tool_candidate"


def test_twm_routes_create_list_and_forecast(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(
        routes,
        "_get_user_from_request",
        lambda request: SimpleNamespace(identifier="alice", metadata={"role": "analyst"}),
    )

    req = _fake_request("POST", b'{"name":"Route Project","region_code":"500227"}')
    resp = asyncio.run(routes.twm_projects(req))
    assert resp.status_code == 200
    project = json.loads(resp.body)

    build_req = _fake_request(
        "POST",
        json.dumps({"bundle_dir": str(MMFE_DIR), "include_auxiliary_tables": True}).encode("utf-8"),
        path_params={"id": project["id"]},
    )
    build_resp = asyncio.run(routes.twm_build_state(build_req))
    assert build_resp.status_code == 200
    state = json.loads(build_resp.body)

    forecast_req = _fake_request(
        "POST",
        b'{"action_type":"inspect","target_role":"project","scenario":"baseline"}',
        path_params={"id": state["state_version"]["id"]},
    )
    forecast_resp = asyncio.run(routes.twm_forecast(forecast_req))
    assert forecast_resp.status_code == 200
    payload = json.loads(forecast_resp.body)
    assert "forecast" in payload
    assert "future_latent_state" in payload["forecast"]

    svc.ensure_default_rules()
    eval_result = svc.evaluate_rules(state["state_version"]["id"], {"include_default_rules": True})
    route_project_ids = {obj["id"] for obj in state["objects"] if obj["canonical_role"] == "project"}
    route_hit = next(
        item for item in eval_result["hits"]
        if item["severity"] in {"critical", "blocking", "high"} and item["subject_object_id"] in route_project_ids
    )
    mask_req = _fake_request(
        "POST",
        json.dumps(
            {
                "action_type": "convert",
                "target_role": "project",
                "target_objects": [route_hit["subject_object_id"]],
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    mask_resp = asyncio.run(routes.twm_action_mask_report(mask_req))
    assert mask_resp.status_code == 200
    mask_payload = json.loads(mask_resp.body)
    assert mask_payload["schema"] == "territory_world_model.action_mask_report.v1"
    assert mask_payload["allowed"] is False

    readiness_req = _fake_request(
        "POST",
        b'{"scenario":"route_readiness","evidence_coverage":0.72}',
        path_params={"id": state["state_version"]["id"]},
    )
    readiness_resp = asyncio.run(routes.twm_dynamics_readiness_report(readiness_req))
    assert readiness_resp.status_code == 200
    readiness_payload = json.loads(readiness_resp.body)
    assert readiness_payload["schema"] == "territory_world_model.dynamics_readiness_report.v1"
    assert readiness_payload["target_model_contract"]["schema"] == "territory_world_model.trainable_dynamics_contract.v1"

    eval_req = _fake_request(
        "POST",
        b'{"scenario":"route_evaluation","evidence_coverage":0.72}',
        path_params={"id": state["state_version"]["id"]},
    )
    eval_resp = asyncio.run(routes.twm_dynamics_evaluation_report(eval_req))
    assert eval_resp.status_code == 200
    eval_payload = json.loads(eval_resp.body)
    assert eval_payload["schema"] == "territory_world_model.dynamics_evaluation_report.v1"
    assert eval_payload["evidence_gate"]["status"] in {"review", "blocked"}

    fit_req = _fake_request(
        "POST",
        b'{"scenario":"route_fit","evidence_coverage":0.72}',
        path_params={"id": state["state_version"]["id"]},
    )
    fit_resp = asyncio.run(routes.twm_fit_dynamics_candidate(fit_req))
    assert fit_resp.status_code == 200
    fit_payload = json.loads(fit_resp.body)
    assert fit_payload["schema"] == "territory_world_model.dynamics_fit_report.v1"
    assert fit_payload["status"] in {"review", "blocked", "pass"}

    train_req = _fake_request(
        "POST",
        b'{"scenario":"route_train","evidence_coverage":0.72}',
        path_params={"id": state["state_version"]["id"]},
    )
    train_resp = asyncio.run(routes.twm_train_dynamics_candidate(train_req))
    assert train_resp.status_code == 200
    train_payload = json.loads(train_resp.body)
    assert train_payload["schema"] == "territory_world_model.train_dynamics_report.v1"
    assert train_payload["status"] in {"review", "blocked", "pass"}

    route_candidate = {
        "schema": "territory_world_model.dynamics_fit_report.v1",
        "status": "pass",
        "candidate": {"model_name": "route_rollout_candidate"},
        "predictions": {
            "baseline:0": {
                "constraint_violation_probability": 0.3,
                "planning_utility_delta": 0.1,
                "uncertainty": {"confidence": 0.62},
            },
            "intervention:0": {
                "constraint_violation_probability": 0.22,
                "planning_utility_delta": 0.33,
                "uncertainty": {"confidence": 0.7},
            },
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass"}},
        "evidence_gate": {"status": "pass"},
    }
    rollout_req = _fake_request(
        "POST",
        json.dumps(
            {
                "scenario": "route_counterfactual",
                "horizon": 2,
                "baseline_action": {"action_type": "inspect", "target_role": "project"},
                "intervention_actions": [{"action_type": "protect", "target_role": "project", "magnitude": 1.1}],
                "evidence_coverage": 0.7,
                "dynamics_candidate_report": route_candidate,
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    rollout_resp = asyncio.run(routes.twm_counterfactual_rollout(rollout_req))
    assert rollout_resp.status_code == 200
    rollout_payload = json.loads(rollout_resp.body)
    assert rollout_payload["horizon"] == 2
    assert len(rollout_payload["baseline_steps"]) == 2
    assert len(rollout_payload["intervention_steps"]) == 2
    assert rollout_payload["baseline_steps"][0]["metrics"]["planning_utility_delta"] == 0.1
    assert rollout_payload["intervention_steps"][0]["metrics"]["planning_utility_delta"] == 0.33

    beam_req = _fake_request(
        "POST",
        json.dumps(
            {
                "scenario": "route_beam",
                "evidence_coverage": 0.7,
                "actions": [
                    {"candidate_id": "route-a", "action_type": "inspect", "target_role": "project"},
                    {"candidate_id": "route-b", "action_type": "protect", "target_role": "project"},
                ],
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    beam_resp = asyncio.run(routes.twm_beam_plan(beam_req))
    assert beam_resp.status_code == 200
    beam_payload = json.loads(beam_resp.body)
    assert beam_payload["schema"] == "territory_world_model.beam_plan_report.v1"
    assert len(beam_payload["ranking"]) == 2

    validation_req = _fake_request(
        "POST",
        b'{"scenario":"route_validation","horizon":2,"evidence_coverage":0.7}',
        path_params={"id": state["state_version"]["id"]},
    )
    validation_resp = asyncio.run(routes.twm_validation_report(validation_req))
    assert validation_resp.status_code == 200
    validation_payload = json.loads(validation_resp.body)
    assert validation_payload["summary"]["stage_count"] == 6
    assert any(stage["stage_code"] == "gis_deployability" for stage in validation_payload["stages"])

    profile_req = _fake_request(
        "POST",
        b'{"scenario":"route_profile","horizon":2,"evidence_coverage":0.7}',
        path_params={"id": state["state_version"]["id"]},
    )
    profile_resp = asyncio.run(routes.twm_world_model_profile(profile_req))
    assert profile_resp.status_code == 200
    profile_payload = json.loads(profile_resp.body)
    assert profile_payload["summary"]["source_article"]["url"].endswith("/a-functional-taxonomy-of-world-models")
    assert any(item["axis"] == "closed_loop" for item in profile_payload["capabilities"])

    state_contract_req = _fake_request(
        "POST",
        b'{"scenario":"route_state_contract"}',
        path_params={"id": state["state_version"]["id"]},
    )
    state_contract_resp = asyncio.run(routes.twm_state_contract_report(state_contract_req))
    assert state_contract_resp.status_code == 200
    state_contract_payload = json.loads(state_contract_resp.body)
    assert state_contract_payload["schema"] == "territory_world_model.state_contract_report.v1"
    assert state_contract_payload["hierarchy"]["schema"] == "territory_world_model.hierarchical_state_contract.v1"

    backend_req = _fake_request(
        "POST",
        json.dumps(
            {
                "scenario": "route_backend",
                "backend": {"backend_id": "route-review", "backend_type": "trainable_candidate"},
                "candidate_report": {
                    "schema": "territory_world_model.external_dynamics_candidate.v1",
                    "status": "review",
                    "candidate": {"model_name": "route_backend"},
                    "predictions": {},
                },
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    backend_resp = asyncio.run(routes.twm_dynamics_backend_report(backend_req))
    assert backend_resp.status_code == 200
    backend_payload = json.loads(backend_resp.body)
    assert backend_payload["schema"] == "territory_world_model.dynamics_backend_report.v1"
    assert backend_payload["status"] in {"review", "blocked", "pass"}

    objective_req = _fake_request(
        "POST",
        json.dumps(
            {
                "scenario": "route_training_objective",
                "dynamics_backend_report": backend_payload,
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    objective_resp = asyncio.run(routes.twm_training_objective_report(objective_req))
    assert objective_resp.status_code == 200
    objective_payload = json.loads(objective_resp.body)
    assert objective_payload["schema"] == "territory_world_model.training_objective_report.v1"
    assert "planning_ranking_loss" in objective_payload["loss_components"]

    examples_req = _fake_request(
        "POST",
        b'{"scenario":"route_training_examples","horizon":2,"evidence_coverage":0.7}',
        path_params={"id": state["state_version"]["id"]},
    )
    examples_resp = asyncio.run(routes.twm_dynamics_training_examples(examples_req))
    assert examples_resp.status_code == 200
    examples_payload = json.loads(examples_resp.body)
    assert examples_payload["summary"]["forecast_scaffold_example_count"] == 3
    assert examples_payload["summary"]["temporal_transition_example_count"] >= 1
    assert any(item["sample_type"] == "action_conditioned_forecast" for item in examples_payload["examples"])

    geofm_req = _fake_request(
        "POST",
        json.dumps(
                {
                    "scenario": "route_geofm_gate",
                    "evidence_coverage": 0.7,
                    "thresholds": {"allow_not_for_production_vectors": True},
                    "baseline_metrics": {"planning_lift": 0.2, "constraint_risk": 0.31, "confidence": 0.56},
                "augmented_metrics": {"planning_lift": 0.25, "constraint_risk": 0.3, "confidence": 0.57},
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    geofm_resp = asyncio.run(routes.twm_geofm_ablation_gate(geofm_req))
    assert geofm_resp.status_code == 200
    geofm_payload = json.loads(geofm_resp.body)
    assert geofm_payload["schema"] == "territory_world_model.geofm_ablation_gate.v1"
    assert geofm_payload["decision"] == "retain_geofm_for_downstream_planning"

    geofm_experiment_req = _fake_request(
        "POST",
        json.dumps(
            {
                "scenario": "route_geofm_experiment",
                "evidence_coverage": 0.7,
                "thresholds": {
                    "allow_not_for_production_vectors": True,
                    "require_extended_validation": True,
                },
                "baseline_metrics": {"planning_lift": 0.2, "constraint_risk": 0.31, "confidence": 0.56},
                "augmented_metrics": {"planning_lift": 0.25, "constraint_risk": 0.3, "confidence": 0.58},
                "extended_validation": {
                    "D2": {
                        "sample_count": 2,
                        "planning_lift_delta": 0.05,
                        "constraint_risk_delta": -0.01,
                        "ranking_score_delta": 0.04,
                    },
                    "D3": {
                        "regions": [
                            {"region": "route-a", "planning_lift_delta": 0.03, "constraint_risk_delta": 0.0},
                            {"region": "route-b", "planning_lift_delta": 0.03, "constraint_risk_delta": 0.0},
                        ],
                    },
                    "D4": {
                        "domain_shift_score": 0.1,
                        "holdout_regret_delta": 0.01,
                        "temporal_holdout_confidence": 0.65,
                        "production_label_quality": 0.8,
                    },
                },
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    geofm_experiment_resp = asyncio.run(routes.twm_geofm_downstream_experiment_report(geofm_experiment_req))
    assert geofm_experiment_resp.status_code == 200
    geofm_experiment_payload = json.loads(geofm_experiment_resp.body)
    assert geofm_experiment_payload["schema"] == "territory_world_model.geofm_downstream_experiment_report.v1"
    assert geofm_experiment_payload["gate_report"]["decision"] == "retain_geofm_for_downstream_planning"

    calibration_req = _fake_request(
        "POST",
        json.dumps(
            {
                "model_effect": 0.05,
                "records": [
                    {"unit_id": "c1", "treatment": 0, "outcome": 0.10, "stratum": "project"},
                    {"unit_id": "c2", "treatment": 0, "outcome": 0.11, "stratum": "project"},
                    {"unit_id": "c3", "treatment": 0, "outcome": 0.12, "stratum": "project"},
                    {"unit_id": "t1", "treatment": 1, "outcome": 0.20, "stratum": "project"},
                    {"unit_id": "t2", "treatment": 1, "outcome": 0.21, "stratum": "project"},
                    {"unit_id": "t3", "treatment": 1, "outcome": 0.22, "stratum": "project"},
                ],
                "thresholds": {"min_records": 6, "min_treated": 3, "min_control": 3},
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    calibration_resp = asyncio.run(routes.twm_causal_calibration_report(calibration_req))
    assert calibration_resp.status_code == 200
    calibration_payload = json.loads(calibration_resp.body)
    assert calibration_payload["schema"] == "territory_world_model.causal_calibration_report.v1"
    assert calibration_payload["status"] == "pass"
