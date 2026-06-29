import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from data_agent.territory_world_model import (
    StateBuildResult,
    TerritoryWorldModelService,
    TwmProject,
    TwmRepository,
    TwmRuleEvaluationResult,
    TwmStateObject,
    TwmStateVersion,
)
from data_agent.api import territory_world_model_routes as routes


MMFE_DIR = Path("data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion")
OPTIMIZATION_DIR = Path("data_agent/test_data/twm_bishan_demo/optimization")


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


def _fake_request(method="GET", body=b"{}", path_params=None, query_string=b""):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/",
            "headers": [],
            "path_params": path_params or {},
            "query_string": query_string,
        },
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


def _save_lightweight_twm_state(service: TerritoryWorldModelService):
    project = TwmProject(name="Lightweight readiness project", region_code="500227")
    state_version = TwmStateVersion(
        project_id=project.id,
        object_count=1,
        relation_count=0,
        build_status="ready",
        summary={
            "hierarchy_tokens": {"county": ["500227"]},
            "object_counts_by_role": {"parcel": 1},
        },
        quality_summary={"evidence_coverage": 0.82},
    )
    state_object = TwmStateObject(
        state_version_id=state_version.id,
        object_type="feature",
        object_code="PARCEL-LIGHT-001",
        source_role="parcel",
        canonical_role="parcel",
        attributes={"admin_code": "500227", "area_m2": 1000.0},
        quality_score=0.9,
    )
    service.repository.save_state_bundle(
        StateBuildResult(
            project=project,
            state_version=state_version,
            objects=[state_object],
            relations=[],
            object_counts_by_role={"parcel": 1},
            relation_counts_by_type={},
            hierarchy_tokens={"county": ["500227"]},
            quality_summary=state_version.quality_summary,
        )
    )
    return project, state_version


def _minimal_observed_dynamics_dataset(state_version_id: str, project_id: str, *, count: int = 6) -> dict:
    examples = []
    for idx in range(count):
        temporal = idx < max(1, count // 2)
        examples.append(
            {
                "id": f"minimal-observed-{idx}",
                "sample_type": "temporal_state_transition" if temporal else "action_conditioned_forecast",
                "split": "holdout" if idx >= count - 2 else "candidate",
                "action": {"action_type": "inspect", "target_role": "parcel"},
                "targets": {
                    "future_latent_state": {"observed_next": {"total_area_m2": 1000.0 + idx}},
                    "constraint_violation_probability": round(0.1 + idx * 0.01, 4),
                    "planning_utility_delta": round(0.2 + idx * 0.02, 4),
                    "uncertainty": {"confidence": 0.82},
                    "calibration": {"calibrated_utility_delta": round(0.2 + idx * 0.02, 4)},
                    "action_mask": {"allowed": True},
                },
                "labels": {
                    "supervision_source": "state_snapshots" if temporal else "expert_action_log",
                    "evidence_supported": True,
                    "ranking_score": round(0.1 + idx * 0.01, 4),
                },
                "provenance": {
                    "state_version_id": state_version_id,
                    "ground_truth": True,
                },
                "not_for_training_reasons": [],
            }
        )
    return {
        "schema": "territory_world_model.dynamics_training_dataset.v1",
        "state_version_id": state_version_id,
        "project_id": project_id,
        "examples": examples,
        "summary": {
            "example_count": len(examples),
            "forecast_scaffold_example_count": 0,
            "temporal_transition_example_count": sum(1 for item in examples if item["sample_type"] == "temporal_state_transition"),
            "usable_example_count": len(examples),
            "review_example_count": 0,
            "supervision_sources": {"state_snapshots": 3, "expert_action_log": 3},
            "loss_contract": {
                "transition_loss": "targets.future_latent_state",
                "constraint_loss": "targets.constraint_violation_probability",
                "planning_ranking_loss": "labels.ranking_score",
                "calibration_loss": "targets.calibration",
                "uncertainty_calibration_loss": "targets.uncertainty.confidence",
                "evidence_consistency_loss": "evidence_gate.status",
                "action_mask_loss": "targets.action_mask.allowed",
            },
        },
    }


def _capture_twm_trace(monkeypatch):
    import data_agent.territory_world_model.service as twm_service_module

    captured = []

    class FakeSpan:
        def __init__(self, attrs):
            self.attrs = attrs

        def set_attribute(self, key, value):
            self.attrs[key] = value

    @contextmanager
    def fake_trace(operation, **attrs):
        span_attrs = {}
        record = {"operation": operation, "attrs": dict(attrs), "span_attrs": span_attrs}
        captured.append(record)
        yield {"span": FakeSpan(span_attrs)}

    monkeypatch.setattr(twm_service_module, "trace_twm_operation", fake_trace, raising=False)
    return captured


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


def test_forecast_and_validation_accept_frontend_string_scenario_context():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    payload = {
        "action_type": "protect",
        "target_role": "project",
        "scenario": "farmland_protection_review",
        "evidence_coverage": 0.78,
        "treatment": "causal_calibrated",
        "scenario_context": "拟建项目是否触碰永久基本农田、生态红线，或造成耕地保护目标风险？",
    }

    forecast = svc.forecast(state_id, payload)
    validation = svc.validation_report(state_id, {**payload, "horizon": 3})

    assert forecast["forecast"]["constraint_violation_probability"] >= 0
    assert validation["summary"]["stage_count"] >= 1


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


def test_forecast_requires_active_registry_when_production_candidate_is_required():
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
                "constraint_violation_probability": 0.22,
                "planning_utility_delta": 0.41,
                "uncertainty": {"confidence": 0.76},
            }
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass"}},
        "evidence_gate": {"status": "pass"},
    }

    result = svc.forecast(
        state_id,
        {
            "action_type": "protect",
            "target_role": "project",
            "scenario": "candidate_forecast_registry_required",
            "evidence_coverage": 0.72,
            "dynamics_candidate_report": candidate,
            "dynamics_prediction_id": "selected",
            "require_active_dynamics_registry": True,
        },
    )

    gate = result["forecast"]["evidence_gate"]["dynamics_candidate"]["gate"]
    assert gate["status"] == "review"
    assert gate["registry_required"] is True
    assert "active_dynamics_model_registry" in gate["missing"]
    assert result["forecast"]["evidence_gate"]["dynamics_candidate"]["prediction_applied"] is False


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


def test_beam_plan_propagates_active_registry_requirement_to_candidate_forecasts():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    candidate = {
        "schema": "territory_world_model.dynamics_fit_report.v1",
        "status": "pass",
        "candidate": {"model_name": "beam_candidate", "model_version": "unit"},
        "predictions": {
            "candidate:0": {
                "constraint_violation_probability": 0.18,
                "planning_utility_delta": 0.42,
                "uncertainty": {"confidence": 0.74},
            },
        },
        "evaluation": {"status": "pass", "evidence_gate": {"status": "pass"}},
        "evidence_gate": {"status": "pass"},
    }

    report = svc.beam_plan(
        state_id,
        {
            "scenario": "beam_candidate_registry_required",
            "evidence_coverage": 0.72,
            "dynamics_candidate_report": candidate,
            "require_active_dynamics_registry": True,
            "actions": [
                {"candidate_id": "a0", "action_type": "protect", "target_role": "project"},
            ],
        },
    )

    gate = report["candidates"][0]["forecast"]["evidence_gate"]["dynamics_candidate"]["gate"]
    assert gate["status"] == "review"
    assert "active_dynamics_model_registry" in gate["missing"]
    assert report["candidates"][0]["forecast"]["evidence_gate"]["dynamics_candidate"]["prediction_applied"] is False


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


def test_farmland_layout_optimization_capability_reports_planner_consumer_boundary():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]

    report = svc.farmland_layout_optimization_capability_report(state_id, {})

    assert report["schema"] == "territory_world_model.farmland_layout_optimization_capability_report.v1"
    assert report["status"] == "review"
    assert report["decision"] == "planner_consumer_only_not_equivalent"
    assert report["current_capabilities"]["constrained_beam_ranking"] is True
    assert report["current_capabilities"]["built_in_layout_generator"] is False
    assert report["current_capabilities"]["built_in_model_free_drl_policy_search"] is False
    assert report["current_capabilities"]["built_in_model_based_mpc_search"] is False
    assert report["planner_contract"]["role"] == "consumer_and_auditor_of_candidate_layout_plans"
    assert "layout_search_or_policy_generator" in report["equivalence_assessment"]["missing"]
    assert "multi_head_dynamics_candidate_report" in report["equivalence_assessment"]["missing"]
    assert report["claim_boundary"]["production_claim"] == "not_supported_without_real_observed_history_and_holdout_validation"


def test_farmland_layout_optimization_capability_can_mark_paper_level_candidate_with_required_evidence():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]

    report = svc.farmland_layout_optimization_capability_report(
        state_id,
        {
            "candidate_actions": [
                {"candidate_id": "layout_a", "action_type": "protect", "target_role": "parcel"},
                {"candidate_id": "layout_b", "action_type": "restore", "target_role": "parcel"},
            ],
            "dynamics_candidate_report": {
                "schema": "territory_world_model.dynamics_fit_report.v1",
                "status": "pass",
                "evidence_gate": {"status": "pass", "passed": True},
            },
            "optimizer_evidence": {
                "algorithm_family": "paper9_model_based_world_model_mpc",
                "validation": {
                    "spatial_holdout": "pass",
                    "temporal_holdout": "pass",
                    "hard_constraint_recheck": "pass",
                    "planning_lift": "pass",
                },
            },
        },
    )

    assert report["status"] == "pass"
    assert report["decision"] == "paper_level_equivalence_candidate"
    assert report["equivalence_assessment"]["missing"] == []
    assert report["inputs"]["candidate_action_count"] == 2
    assert report["inputs"]["has_dynamics_candidate_report"] is True
    assert report["inputs"]["has_external_optimizer_evidence"] is True
    assert report["hard_constraint_policy"]["required"] is True
    assert "TWM-FARM-001" in report["hard_constraint_policy"]["supported_channels"]


def test_loads_farmland_layout_candidate_actions_from_optimization_fixture():
    svc = _build_service()

    payload = svc.farmland_layout_candidate_actions_from_optimization_bundle(OPTIMIZATION_DIR)

    assert payload["schema"] == "territory_world_model.farmland_layout_candidate_actions_from_optimization_bundle.v1"
    assert payload["status"] == "pass"
    assert payload["summary"]["candidate_count"] == 7
    assert payload["summary"]["legal_feasible_count"] == 2
    assert payload["summary"]["blocked_count"] == 5
    actions = {item["candidate_id"]: item for item in payload["candidate_actions"]}
    assert actions["SCN-BALANCED"]["execution_mask"]["allowed"] is True
    assert actions["SCN-BASELINE-CURRENT"]["execution_mask"]["allowed"] is True
    assert actions["SCN-WM-V21-REFERENCE"]["execution_mask"]["allowed"] is False
    assert "CONSTRAINT-PBF" in actions["SCN-WM-V21-REFERENCE"]["execution_mask"]["hard_blocks"]
    assert actions["SCN-WM-V21-REFERENCE"]["parameters"]["constraint_violation_probability"] >= 0.75
    assert payload["optimizer_evidence"]["validation"]["hard_constraint_recheck"] == "pass"
    assert payload["optimizer_evidence"]["validation"]["spatial_holdout"] == "not_provided"


def test_farmland_layout_capability_auto_loads_optimization_bundle_as_partial_equivalence():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]

    report = svc.farmland_layout_optimization_capability_report(
        state_id,
        {
            "optimization_dir": str(OPTIMIZATION_DIR),
            "dynamics_candidate_report": {
                "schema": "territory_world_model.dynamics_fit_report.v1",
                "status": "pass",
                "evidence_gate": {"status": "pass", "passed": True},
            },
        },
    )

    assert report["inputs"]["optimization_bundle_loaded"] is True
    assert report["inputs"]["candidate_action_count"] == 7
    assert report["optimization_bundle"]["summary"]["legal_feasible_count"] == 2
    assert report["decision"] == "partial_equivalence_review_required"
    assert "spatial_holdout_validation" in report["equivalence_assessment"]["missing"]
    assert "planning_lift_benchmark" in report["equivalence_assessment"]["missing"]


def test_farmland_layout_optimization_bundle_beam_plan_blocks_high_score_infeasible_candidate():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]

    report = svc.farmland_layout_beam_plan_from_optimization_bundle(
        state_id,
        OPTIMIZATION_DIR,
        {
            "scenario": "fixture_bundle_beam",
            "evidence_coverage": 0.8,
            "candidate_metric_overrides": {
                "SCN-WM-V21-REFERENCE": {
                    "planning_utility_delta": 2.0,
                    "constraint_violation_probability": 0.0,
                    "confidence": 1.0,
                }
            },
        },
    )

    assert report["schema"] == "territory_world_model.farmland_layout_optimization_beam_plan_report.v1"
    assert report["status"] == "review"
    assert report["optimization_bundle"]["summary"]["candidate_count"] == 7
    assert report["selection_audit"]["legal_feasible_count"] == 2
    assert report["selection_audit"]["blocked_count"] == 5
    assert "SCN-WM-V21-REFERENCE" in report["selection_audit"]["hard_blocked_candidate_ids"]
    assert report["selection_audit"]["selected_candidate_id"] in {"SCN-BALANCED", "SCN-BASELINE-CURRENT"}
    assert report["selection_audit"]["selected_from_legal_feasible_space"] is True
    assert report["selection_audit"]["selected_hard_blocked"] is False
    assert report["selection_audit"]["hard_constraint_filter_enforced"] is True
    assert report["beam_plan"]["selected"]["candidate_id"] != "SCN-WM-V21-REFERENCE"
    blocked = {
        item["candidate_id"]: item
        for item in report["beam_plan"]["candidates"]
        if item["candidate_id"] == "SCN-WM-V21-REFERENCE"
    }["SCN-WM-V21-REFERENCE"]
    assert blocked["selection_status"] == "hard_blocked"
    assert blocked["forecast"]["planning_utility_delta"] == 2.0
    assert report["claim_boundary"]["optimizer_metric_projection"] == "used_as_candidate_forecast_input_only"
    assert report["claim_boundary"]["production_claim"] == "not_supported_from_fixture_bundle_without_real_observed_history_and_holdout_validation"


def test_selected_plan_evaluation_bundle_runs_selected_rollout_and_validation_from_optimization_bundle():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.selected_plan_evaluation_bundle(
        state_id,
        {
            "optimization_dir": str(OPTIMIZATION_DIR),
            "scenario": "selected_bundle_eval",
            "horizon": 2,
            "evidence_coverage": 0.82,
            "candidate_metric_overrides": {
                "SCN-WM-V21-REFERENCE": {
                    "planning_utility_delta": 3.0,
                    "constraint_violation_probability": 0.0,
                    "confidence": 1.0,
                }
            },
        },
    )

    assert report["schema"] == "territory_world_model.selected_plan_evaluation_bundle.v1"
    assert report["source"]["kind"] == "farmland_layout_optimization_bundle"
    assert report["planning"]["selection_audit"]["selected_from_legal_feasible_space"] is True
    assert report["planning"]["selection_audit"]["selected_hard_blocked"] is False
    assert report["selected"]["candidate_id"] != "SCN-WM-V21-REFERENCE"
    assert report["selected_action"]["scenario"] in {"SCN-BALANCED", "SCN-BASELINE-CURRENT"}
    assert report["counterfactual_rollout"]["horizon"] == 2
    assert report["counterfactual_rollout"]["intervention_steps"][0]["action"]["scenario"] == report["selected_action"]["scenario"]
    assert report["validation_report"]["summary"]["stage_count"] == 6
    assert report["evidence_gate"]["status"] in {"pass", "review"}
    assert "selected_hard_blocked" not in report["evidence_gate"]["missing"]
    assert report["claim_boundary"]["selected_from_legal_feasible_space"] is True
    assert report["claim_boundary"]["production_claim"] == "not_supported_without_real_observed_history_holdout_validation_and_human_review"


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
    assert report["claim_ladder"]["schema"] == "territory_world_model.claim_ladder.v1"
    assert report["claim_ladder"]["current_level"] in {"L0", "L1"}
    assert report["claim_boundary"]["claim_level"] == report["claim_ladder"]["current_level"]
    assert report["claim_boundary"]["status"] in {"review", "blocked", "pass"}


def test_state_snapshot_lakehouse_manifest_maps_state_to_production_storage_layers():
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)

    manifest = svc.state_snapshot_lakehouse_manifest(
        state.id,
        {
            "lakehouse_uri": "s3://gis-agent-lakehouse",
            "namespace": "twm_prod",
            "include_vector_sidecar": True,
        },
    )

    assert manifest["schema"] == "territory_world_model.state_snapshot_lakehouse_manifest.v1"
    assert manifest["storage"]["object_store_uri"] == "s3://gis-agent-lakehouse"
    assert manifest["storage"]["table_format"] == "iceberg"
    assert manifest["storage"]["vector_sidecar"]["format"] == "lance"
    assert manifest["snapshot"]["state_version_id"] == state.id
    assert manifest["snapshot"]["object_count"] == 1
    assert manifest["artifacts"]["state_objects"]["format"] == "geoparquet"
    assert manifest["artifacts"]["state_objects"]["table"] == "twm_prod.state_objects"
    assert "canonical_role" in manifest["artifacts"]["state_objects"]["partitioning"]
    assert manifest["artifacts"]["state_relations"]["format"] == "geoparquet"
    assert manifest["artifacts"]["rule_hits"]["format"] == "parquet"
    assert manifest["artifacts"]["dynamics_model_registry"]["format"] == "parquet"
    assert manifest["readiness"]["sedona_batch_ready"] is True
    assert manifest["readiness"]["twm_training_snapshot_ready"] is True
    assert manifest["claim_boundary"].startswith("Manifest only")


def test_materialize_state_snapshot_lakehouse_writes_readable_parquet_artifacts(tmp_path):
    import pyarrow.parquet as pq

    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)

    export = svc.materialize_state_snapshot_lakehouse(
        state.id,
        {
            "lakehouse_uri": tmp_path.as_uri(),
            "namespace": "twm_prod",
            "include_vector_sidecar": True,
        },
    )

    objects_artifact = export["artifacts"]["state_objects"]
    objects_path = Path(objects_artifact["local_path"])
    manifest_path = Path(export["manifest_local_path"])
    table = pq.read_table(objects_path)

    assert export["schema"] == "territory_world_model.state_snapshot_lakehouse_materialization.v1"
    assert export["written_artifact_count"] >= 7
    assert manifest_path.exists()
    assert objects_path.exists()
    assert table.num_rows == 1
    assert set(["state_version_id", "object_code", "canonical_role", "attributes_json", "geometry_wkb"]).issubset(table.column_names)
    assert table.column("canonical_role").to_pylist() == ["parcel"]
    assert export["readiness"]["local_parquet_written"] is True
    assert export["readiness"]["sedona_geoparquet_read_ready"] is True
    assert export["claim_boundary"].startswith("Materialization only")


def test_state_snapshot_lakehouse_publish_plan_builds_iceberg_and_sedona_specs(tmp_path):
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)
    materialization = svc.materialize_state_snapshot_lakehouse(
        state.id,
        {
            "lakehouse_uri": tmp_path.as_uri(),
            "namespace": "twm_prod",
        },
    )

    plan = svc.state_snapshot_lakehouse_publish_plan(
        state.id,
        {
            "materialization": materialization,
            "catalog": "prod",
            "namespace": "twm_prod",
            "warehouse_uri": "s3://gis-agent-lakehouse/warehouse/iceberg",
            "geohash_precision": 8,
        },
    )

    publish_by_name = {item["artifact"]: item for item in plan["iceberg_publish_specs"]}
    object_index = next(item for item in plan["sedona_spatial_index_specs"] if item["artifact"] == "state_objects")

    assert plan["schema"] == "territory_world_model.state_snapshot_lakehouse_publish_plan.v1"
    assert plan["target"]["catalog"] == "prod"
    assert plan["target"]["warehouse_uri"] == "s3://gis-agent-lakehouse/warehouse/iceberg"
    assert len(plan["iceberg_publish_specs"]) >= 7
    assert publish_by_name["state_objects"]["table_identifier"] == "prod.twm_prod.state_objects"
    assert publish_by_name["state_objects"]["source_uri"].startswith("file://")
    assert "USING iceberg" in publish_by_name["state_objects"]["ddl"]
    assert "CREATE NAMESPACE IF NOT EXISTS prod.twm_prod" in plan["ddl_statements"][0]
    assert object_index["output_table"] == "prod.twm_prod.state_objects_spatial_index"
    assert "ST_GeomFromWKB" in object_index["sql"]
    assert "geohash_8" in object_index["sql"]
    assert plan["validation_gates"]["publish_spec_gate"]["status"] == "pass"
    assert plan["validation_gates"]["sedona_spatial_index_gate"]["status"] == "pass"
    assert plan["claim_boundary"].startswith("Publish plan only")


def test_execute_state_snapshot_lakehouse_publish_plan_validates_snapshots_and_counts(tmp_path):
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)
    materialization = svc.materialize_state_snapshot_lakehouse(
        state.id,
        {"lakehouse_uri": tmp_path.as_uri(), "namespace": "twm_prod"},
    )
    calls = []

    def executor(task):
        calls.append(task)
        if task["kind"] == "iceberg_publish":
            return {
                "returncode": 0,
                "snapshot_id": f"snap-{task['artifact']}",
                "rows_written": task["expected_row_count"],
                "table_identifier": task["table_identifier"],
            }
        if task["kind"] == "sedona_spatial_index":
            return {
                "returncode": 0,
                "snapshot_id": f"idx-{task['artifact']}",
                "rows_written": 1,
                "output_table": task["output_table"],
            }
        return {"returncode": 0}

    execution = svc.execute_state_snapshot_lakehouse_publish_plan(
        state.id,
        {
            "materialization": materialization,
            "catalog": "prod",
            "namespace": "twm_prod",
            "warehouse_uri": "s3://gis-agent-lakehouse/warehouse/iceberg",
        },
        executor=executor,
    )

    publish_results = {item["artifact"]: item for item in execution["iceberg_publish_results"]}
    index_results = {item["artifact"]: item for item in execution["sedona_spatial_index_results"]}

    assert execution["schema"] == "territory_world_model.state_snapshot_lakehouse_publish_execution.v1"
    assert execution["status"] == "pass"
    assert any(call["kind"] == "iceberg_publish" and call["artifact"] == "state_objects" for call in calls)
    assert any(call["kind"] == "sedona_spatial_index" and call["artifact"] == "state_objects" for call in calls)
    assert publish_results["state_objects"]["snapshot_id"] == "snap-state_objects"
    assert publish_results["state_objects"]["row_count_status"] == "pass"
    assert index_results["state_objects"]["snapshot_id"] == "idx-state_objects"
    assert execution["validation_gates"]["iceberg_snapshot_gate"]["status"] == "pass"
    assert execution["validation_gates"]["sedona_spatial_index_gate"]["status"] == "pass"
    assert execution["validation_gates"]["consumer_switch_gate"]["status"] == "pass"
    assert execution["claim_boundary"].startswith("Execution report")


def test_state_snapshot_lakehouse_spark_submit_bundle_writes_executor_package(tmp_path):
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)
    materialization = svc.materialize_state_snapshot_lakehouse(
        state.id,
        {"lakehouse_uri": tmp_path.joinpath("lake").as_uri(), "namespace": "twm_prod"},
    )

    bundle = svc.state_snapshot_lakehouse_spark_submit_bundle(
        state.id,
        {
            "materialization": materialization,
            "catalog": "prod",
            "namespace": "twm_prod",
            "warehouse_uri": "s3://gis-agent-lakehouse/warehouse/iceberg",
            "output_dir": str(tmp_path / "spark_bundle"),
            "spark_master": "k8s://https://spark.example.local",
            "deploy_mode": "cluster",
            "executor_image": "registry.local/gisdataagent/twm-spark:latest",
        },
    )

    command = bundle["spark_submit"]["command"]

    assert bundle["schema"] == "territory_world_model.state_snapshot_lakehouse_spark_submit_bundle.v1"
    assert Path(bundle["plan_path"]).exists()
    assert Path(bundle["executor_script"]).exists()
    assert command[0] == "spark-submit"
    assert "--master" in command
    assert "k8s://https://spark.example.local" in command
    assert "--deploy-mode" in command
    assert "cluster" in command
    assert any("spark.sql.catalog.prod.warehouse=s3://gis-agent-lakehouse/warehouse/iceberg" in item for item in command)
    assert any(item.endswith("twm_state_snapshot_lakehouse_publish_job.py") for item in command)
    assert bundle["execution_contract"]["expected_publish_task_count"] >= 7
    assert bundle["execution_contract"]["expected_spatial_index_task_count"] >= 2
    assert bundle["claim_boundary"].startswith("Spark submit bundle")


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
    assert report["summary"]["claim_ladder"]["schema"] == "territory_world_model.claim_ladder.v1"
    assert report["summary"]["claim_ladder"]["current_level"] == "L0"
    assert report["summary"]["validation_ladder"][0] == "state_build"
    assert any(stage["evidence"] for stage in report["stages"])


def test_validation_report_claim_ladder_can_be_promoted_with_explicit_gate_facts():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.validation_report(
        state_id,
        {
            "scenario": "validation_claim_upgrade",
            "horizon": 2,
            "evidence_coverage": 0.9,
            "claim_gate_facts": {
                "state_build_pass": {"status": "pass", "source": "state_contract_audit"},
                "future_state_holdout_pass": {"status": "pass", "source": "observed_holdout"},
                "counterfactual_calibration_pass": {"status": "pass", "source": "causal_validation"},
                "spatial_estimator_pass_or_not_applicable": {"status": "pass", "source": "spatial_adapter"},
                "planning_lift_pass": {"status": "pass", "source": "planner_holdout"},
                "geofm_gate_decision": {"status": "pass", "source": "b0_b1_gate"},
                "gis_audit_pass": {"status": "pass", "source": "audit_bundle"},
                "human_review_completed": {"status": "pass", "source": "review_queue"},
            },
        },
    )

    assert report["summary"]["claim_ladder"]["current_level"] == "L4"
    assert report["summary"]["claim_ladder"]["current_claim"] == "deployable_gis_supported"
    level_status = {item["level"]: item["status"] for item in report["summary"]["claim_ladder"]["levels"]}
    assert level_status == {"L0": "pass", "L1": "pass", "L2": "pass", "L3": "pass", "L4": "pass"}


def test_validation_report_require_scca_pass_blocks_claim_upgrade_without_scca():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    report = svc.validation_report(
        state_id,
        {
            "scenario": "validation_requires_scca",
            "horizon": 2,
            "evidence_coverage": 0.9,
            "require_scca_pass": True,
            "claim_gate_facts": {
                "state_build_pass": {"status": "pass", "source": "state_contract_audit"},
                "future_state_holdout_pass": {"status": "pass", "source": "observed_holdout"},
                "counterfactual_calibration_pass": {"status": "pass", "source": "causal_validation"},
                "spatial_estimator_pass_or_not_applicable": {"status": "pass", "source": "manual_override_should_not_win"},
                "planning_lift_pass": {"status": "pass", "source": "planner_holdout"},
                "geofm_gate_decision": {"status": "pass", "source": "b0_b1_gate"},
                "gis_audit_pass": {"status": "pass", "source": "audit_bundle"},
                "human_review_completed": {"status": "pass", "source": "review_queue"},
            },
        },
    )

    scca_stage = next(stage for stage in report["stages"] if stage["stage_code"] == "spatial_causal_evidence")
    assert report["summary"]["stage_count"] == 7
    assert scca_stage["status"] == "review"
    assert scca_stage["evidence"]["required"] is True
    assert scca_stage["evidence"]["provided"] is False
    assert "SCCA causal evidence report is required but not provided" in scca_stage["gaps"]
    claim_ladder = report["summary"]["claim_ladder"]
    assert claim_ladder["current_level"] == "L1"
    l2 = next(level for level in claim_ladder["levels"] if level["level"] == "L2")
    spatial_requirement = next(req for req in l2["requirements"] if req["gate"] == "spatial_estimator_pass_or_not_applicable")
    assert spatial_requirement["status"] == "review"
    assert spatial_requirement["evidence"]["scca_required"] is True


def test_validation_report_accepts_passing_scca_as_spatial_causal_gate():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    scca = svc.scca_causal_evidence_report(
        state_id,
        {
            "scca_result": {
                "case_id": "validation_scca",
                "row_count": 120,
                "credibility_decision": "strong_support",
                "evidence_grade": "core_support",
                "effect_estimates": [{"estimator": "spatial_neighbor_adjusted_ols", "coef": 0.07, "p_value": 0.03}],
                "balance_summary": [{"covariate": "cov1", "standardized_mean_difference": 0.1}],
                "spatial_diagnostics": {"graph": {"edge_count": 240}, "residual_moran": {"moran_i": 0.03}},
            },
            "thresholds": {"min_row_count": 80},
        },
    )

    report = svc.validation_report(
        state_id,
        {
            "scenario": "validation_scca_pass",
            "horizon": 2,
            "evidence_coverage": 0.9,
            "require_scca_pass": True,
            "scca_causal_evidence_report": scca,
            "claim_gate_facts": {
                "state_build_pass": {"status": "pass", "source": "state_contract_audit"},
                "future_state_holdout_pass": {"status": "pass", "source": "observed_holdout"},
                "counterfactual_calibration_pass": {"status": "pass", "source": "causal_validation"},
                "planning_lift_pass": {"status": "pass", "source": "planner_holdout"},
                "geofm_gate_decision": {"status": "pass", "source": "b0_b1_gate"},
                "gis_audit_pass": {"status": "pass", "source": "audit_bundle"},
                "human_review_completed": {"status": "pass", "source": "review_queue"},
            },
        },
    )

    scca_stage = next(stage for stage in report["stages"] if stage["stage_code"] == "spatial_causal_evidence")
    assert report["summary"]["stage_count"] == 7
    assert scca_stage["status"] == "pass"
    assert scca_stage["evidence"]["evidence_gate"]["status"] == "pass"
    assert scca_stage["evidence"]["calibration_hint"]["can_support_twm_causal_calibration"] is True
    claim_ladder = report["summary"]["claim_ladder"]
    assert claim_ladder["current_level"] == "L4"
    l2 = next(level for level in claim_ladder["levels"] if level["level"] == "L2")
    spatial_requirement = next(req for req in l2["requirements"] if req["gate"] == "spatial_estimator_pass_or_not_applicable")
    assert spatial_requirement["status"] == "pass"
    assert spatial_requirement["evidence"]["scca_status"] == "pass"


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


def test_dynamics_readiness_report_skips_optional_geofm_and_causal_gates(monkeypatch):
    svc = _build_service()
    project, state_version = _save_lightweight_twm_state(svc)
    dataset = _minimal_observed_dynamics_dataset(state_version.id, project.id)

    def fail_geofm(*_args, **_kwargs):
        raise AssertionError("GeoFM gate should not run when it is optional and no GeoFM evidence is provided")

    def fail_causal(*_args, **_kwargs):
        raise AssertionError("causal calibration should not run when it is optional and no causal evidence is provided")

    monkeypatch.setattr(svc, "geofm_ablation_gate", fail_geofm)
    monkeypatch.setattr(svc, "causal_calibration_report", fail_causal)

    report = svc.dynamics_readiness_report(state_version.id, {"dataset": dataset})

    assert report["status"] == "pass"
    geofm_gate = report["gate_results"]["geofm_gate"]
    causal_gate = report["gate_results"]["causal_calibration"]
    assert geofm_gate == {
        "passed": True,
        "required": False,
        "status": "not_required",
        "decision": "not_required",
        "source": "skipped_optional_gate",
    }
    assert causal_gate == {
        "passed": True,
        "required": False,
        "status": "not_required",
        "method": "not_required",
        "source": "skipped_optional_gate",
    }
    assert report["gate_results"]["summary"]["blocked_gates"] == []


def test_dynamics_readiness_report_computes_explicitly_required_optional_gates(monkeypatch):
    svc = _build_service()
    project, state_version = _save_lightweight_twm_state(svc)
    dataset = _minimal_observed_dynamics_dataset(state_version.id, project.id)
    calls = {"geofm": 0, "causal": 0}

    first = svc.dynamics_readiness_report(state_version.id, {"dataset": dataset})
    assert first["gate_results"]["geofm_gate"]["source"] == "skipped_optional_gate"
    assert first["gate_results"]["causal_calibration"]["source"] == "skipped_optional_gate"

    def fake_geofm(state_version_id, payload):
        calls["geofm"] += 1
        assert state_version_id == state_version.id
        assert payload["require_geofm_pass"] is True
        return {"gate_status": "pass", "decision": "retain_geofm_for_downstream_planning"}

    def fake_causal(state_version_id, payload):
        calls["causal"] += 1
        assert state_version_id == state_version.id
        assert payload["require_causal_pass"] is True
        return {"status": "pass", "method": "unit_required_gate"}

    monkeypatch.setattr(svc, "geofm_ablation_gate", fake_geofm)
    monkeypatch.setattr(svc, "causal_calibration_report", fake_causal)

    required = svc.dynamics_readiness_report(
        state_version.id,
        {
            "dataset": dataset,
            "require_geofm_pass": True,
            "require_causal_pass": True,
        },
    )

    assert calls == {"geofm": 1, "causal": 1}
    assert required["status"] == "pass"
    assert required["gate_results"]["geofm_gate"] == {
        "passed": True,
        "required": True,
        "status": "pass",
        "decision": "retain_geofm_for_downstream_planning",
        "source": "computed",
    }
    assert required["gate_results"]["causal_calibration"] == {
        "passed": True,
        "required": True,
        "status": "pass",
        "method": "unit_required_gate",
        "source": "computed",
    }
    assert required["gate_results"]["summary"]["blocked_gates"] == []


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


def test_latent_transition_error_detects_land_type_mismatch_when_total_area_matches():
    svc = _build_service()
    target = {
        "observed_next": {
            "total_area_m2": 1000.0,
            "total_feature_count": 10,
            "land_space_types": {
                "agricultural_space": {"area_m2": 600.0, "feature_count": 6, "area_delta_m2": -50.0},
                "ecological_space": {"area_m2": 400.0, "feature_count": 4, "area_delta_m2": 50.0},
            },
        },
        "delta": {
            "total_area_delta_m2": 0.0,
            "total_abs_area_delta_m2": 100.0,
        },
    }
    predicted = {
        "decoded_state": {
            "total_area_m2": 1000.0,
            "total_feature_count": 10,
            "land_space_types": {
                "agricultural_space": {"area_m2": 400.0, "feature_count": 4, "area_delta_m2": 50.0},
                "ecological_space": {"area_m2": 600.0, "feature_count": 6, "area_delta_m2": -50.0},
            },
        },
        "transition_delta": {
            "total_area_delta_m2": 0.0,
            "total_abs_area_delta_m2": 100.0,
        },
        "latent_vector": {
            "observed_next.land_space_types.agricultural_space.area_m2": 400.0,
            "observed_next.land_space_types.ecological_space.area_m2": 600.0,
        },
    }

    components = svc._latent_transition_error_components(predicted=predicted, target=target)

    assert components["total_area_error"] == 0.0
    assert components["land_type_area_mae"] > 0.0
    assert components["aggregate_error"] > 0.0
    assert svc._latent_transition_error(predicted=predicted, target=target) == components["aggregate_error"]


def test_dynamics_evaluation_reports_future_latent_state_v2_quality():
    svc = _build_service()
    target_latent = {
        "observed_next": {
            "total_area_m2": 1000.0,
            "total_feature_count": 10,
            "land_space_types": {
                "agricultural_space": {"area_m2": 580.0, "feature_count": 6, "area_delta_m2": -20.0},
                "ecological_space": {"area_m2": 420.0, "feature_count": 4, "area_delta_m2": 20.0},
            },
        },
        "delta": {
            "total_area_delta_m2": 0.0,
            "total_abs_area_delta_m2": 40.0,
            "by_land_type": {
                "agricultural_space": {"area_delta_m2": -20.0},
                "ecological_space": {"area_delta_m2": 20.0},
            },
        },
        "latent_vector": {
            "observed_next.total_area_m2": 1000.0,
            "observed_next.land_space_types.agricultural_space.area_m2": 580.0,
            "observed_next.land_space_types.ecological_space.area_m2": 420.0,
            "delta.total_abs_area_delta_m2": 40.0,
        },
    }
    predicted_latent = {
        "schema": "territory_world_model.predicted_latent_state.v2",
        "latent_head_scope": "multi_dimensional_hierarchical_state",
        "representation_boundary": "multi_dimensional_hierarchical_state_latent_not_full_geometry",
        "dimensions": list(target_latent["latent_vector"].keys()),
        "latent_vector": dict(target_latent["latent_vector"]),
        "decoded_state": dict(target_latent["observed_next"]),
        "transition_delta": dict(target_latent["delta"]),
    }
    dataset = {
        "examples": [
            {
                "id": "latent-v2-quality-1",
                "split": "holdout",
                "provenance": {"ground_truth": True},
                "targets": {
                    "future_latent_state": target_latent,
                    "constraint_violation_probability": 0.2,
                    "planning_utility_delta": 0.4,
                },
                "labels": {"ranking_score": 0.5},
            }
        ]
    }
    predictions = {
        "latent-v2-quality-1": {
            "future_latent_state": predicted_latent,
            "constraint_violation_probability": 0.2,
            "planning_utility_delta": 0.4,
            "uncertainty": {"confidence": 0.8},
        }
    }

    _metrics, head_metrics, _inventory = svc._dynamics_evaluation_metrics(dataset, predictions)
    quality = head_metrics["future_latent_state"]["latent_v2_quality"]

    assert quality["schema"] == "territory_world_model.future_latent_state_v2_quality.v1"
    assert quality["status"] == "pass"
    assert quality["coverage"]["v2_prediction_count"] == 1
    assert quality["coverage"]["decoded_state_count"] == 1
    assert quality["coverage"]["transition_delta_count"] == 1
    assert quality["coverage"]["latent_vector_count"] == 1
    assert quality["dimension_coverage"]["missing_target_dimensions"] == []
    assert quality["missing"] == []


def test_dynamics_model_registry_report_blocks_review_only_candidate_promotion():
    svc = _build_service()
    report = svc.dynamics_model_registry_report(
        "state-registry",
        {
            "candidate_report": {
                "status": "pass",
                "candidate": {
                    "model_name": "hierarchical_neural_multi_head_dynamics",
                    "model_version": "neural_candidate_v1",
                    "model_family": "action_conditioned_hierarchical_neural_dynamics",
                    "is_scaffold_baseline": False,
                    "is_scaffold_trainer": False,
                },
                "evidence_gate": {"status": "pass"},
                "learned_parameters": {"metadata": {"training_dataset_hash": "sha256:test"}},
            },
            "readiness_report": {
                "status": "review",
                "gates": {"summary": {"blocked_gates": ["observed_temporal_support"]}},
            },
            "evaluation_report": {
                "status": "review",
                "evidence_gate": {"status": "review"},
            },
        },
    )

    assert report["schema"] == "territory_world_model.dynamics_model_registry_report.v1"
    assert report["registry_entry"]["registry_key"] == "hierarchical_neural_multi_head_dynamics:neural_candidate_v1"
    assert report["promotion_decision"] == "review_only_not_promoted"
    assert report["gates"]["readiness_gate"]["status"] == "review"
    assert report["gates"]["production_data_gate"]["status"] == "blocked"
    assert "production_observed_history" in report["missing_for_promotion"]
    assert "state_contract_version" in report["missing_registry_metadata"]
    assert report["rollback_plan"]["action"] == "keep_current_production_version"
    assert "review-only" in report["claim_boundary"]


def test_dynamics_model_registry_promotes_passed_latent_v2_candidate_with_dataset_hash_lineage():
    svc = _build_service()
    dataset = {
        "schema": "territory_world_model.dynamics_training_dataset.v1",
        "state_version_id": "state-registry",
        "project_id": "project-registry",
        "summary": {
            "example_count": 2,
            "usable_example_count": 2,
            "temporal_transition_example_count": 2,
            "loss_contract": {"transition_loss": "targets.future_latent_state"},
        },
        "examples": [
            {
                "id": "train-1",
                "split": "candidate",
                "targets": {
                    "future_latent_state": {
                        "observed_next": {"total_area_m2": 1000.0},
                    },
                },
            },
            {
                "id": "holdout-1",
                "split": "holdout",
                "provenance": {"ground_truth": True},
                "targets": {
                    "future_latent_state": {
                        "observed_next": {"total_area_m2": 1008.0},
                    },
                },
            },
        ],
    }
    latent_quality = {
        "schema": "territory_world_model.future_latent_state_v2_quality.v1",
        "status": "pass",
        "coverage": {"v2_prediction_count": 2, "prediction_count": 2},
        "dimension_coverage": {"missing_target_dimensions": []},
        "missing": [],
    }

    report = svc.dynamics_model_registry_report(
        "state-registry",
        {
            "dynamics_training_dataset": dataset,
            "candidate_report": {
                "status": "pass",
                "candidate": {
                    "model_name": "hierarchical_neural_multi_head_dynamics",
                    "model_version": "latent-v2-prod-candidate",
                    "model_family": "action_conditioned_hierarchical_neural_dynamics",
                    "is_scaffold_baseline": False,
                    "is_scaffold_trainer": False,
                },
                "evidence_gate": {"status": "pass"},
                "learned_parameters": {
                    "metadata": {
                        "state_contract_version": "state_contract_v1",
                        "training_dataset_snapshot": "iceberg://twm/dynamics_training_dataset@snapshot-42",
                        "training_run_id": "run-latent-v2-001",
                        "model_artifact_uri": "s3://gis-agent-lakehouse/artifacts/twm/models/latent-v2.pt",
                        "evaluation_report_id": "eval-latent-v2-001",
                    },
                },
            },
            "readiness_report": {"status": "pass", "gates": {"summary": {"blocked_gates": []}}},
            "evaluation_report": {
                "status": "pass",
                "evidence_gate": {"status": "pass"},
                "target_head_metrics": {
                    "future_latent_state": {
                        "latent_v2_quality": latent_quality,
                    },
                },
            },
            "production_data_gate": {"status": "pass"},
            "current_registry_key": "previous_model:v1",
        },
    )

    training_hash = report["registry_entry"]["metadata"]["training_dataset_hash"]
    assert report["promotion_decision"] == "candidate_for_registry_promotion"
    assert training_hash.startswith("sha256:")
    assert len(training_hash) == len("sha256:") + 64
    assert report["registry_entry"]["lineage"]["training_dataset_hash"] == training_hash
    assert report["registry_entry"]["lineage"]["state_contract_version"] == "state_contract_v1"
    assert report["registry_entry"]["latent_v2_quality"]["status"] == "pass"
    assert report["gates"]["latent_v2_quality_gate"]["passed"] is True
    assert report["missing_registry_metadata"] == []
    assert report["missing_for_promotion"] == []
    assert report["rollback_plan"]["action"] == "pin_candidate_with_previous_version_rollback"


def test_dynamics_model_registry_can_activate_and_rollback_persistent_versions():
    svc = _build_service()
    project, state = _save_lightweight_twm_state(svc)

    def payload_for(version: str) -> dict:
        dataset = _minimal_observed_dynamics_dataset(state.id, project.id, count=4)
        latent_quality = {
            "schema": "territory_world_model.future_latent_state_v2_quality.v1",
            "status": "pass",
            "coverage": {"v2_prediction_count": 4, "prediction_count": 4},
            "dimension_coverage": {"missing_target_dimensions": []},
            "missing": [],
        }
        return {
            "dynamics_training_dataset": dataset,
            "candidate_report": {
                "status": "pass",
                "candidate": {
                    "model_name": "hierarchical_neural_multi_head_dynamics",
                    "model_version": version,
                    "model_family": "action_conditioned_hierarchical_neural_dynamics",
                    "is_scaffold_baseline": False,
                    "is_scaffold_trainer": False,
                },
                "evidence_gate": {"status": "pass"},
                "learned_parameters": {
                    "metadata": {
                        "state_contract_version": "state_contract_v1",
                        "training_dataset_snapshot": f"iceberg://twm/dynamics_training_dataset@{version}",
                        "training_run_id": f"run-{version}",
                        "model_artifact_uri": f"s3://gis-agent-lakehouse/artifacts/twm/models/{version}.pt",
                        "evaluation_report_id": f"eval-{version}",
                    },
                },
            },
            "readiness_report": {"status": "pass", "gates": {"summary": {"blocked_gates": []}}},
            "evaluation_report": {
                "status": "pass",
                "evidence_gate": {"status": "pass"},
                "target_head_metrics": {"future_latent_state": {"latent_v2_quality": latent_quality}},
            },
            "production_data_gate": {"status": "pass"},
        }

    first = svc.activate_dynamics_model_registry_entry(state.id, payload_for("v1"))
    second = svc.activate_dynamics_model_registry_entry(state.id, payload_for("v2"))
    active_before = svc.list_dynamics_model_registry_entries(state.id, {"status": "active"})
    rollback = svc.rollback_dynamics_model_registry(state.id, {})
    active_after = svc.list_dynamics_model_registry_entries(state.id, {"status": "active"})

    assert first["schema"] == "territory_world_model.dynamics_model_registry_activation.v1"
    assert first["active_entry"]["registry_key"] == "hierarchical_neural_multi_head_dynamics:v1"
    assert first["previous_active_entry"] is None
    assert second["active_entry"]["registry_key"] == "hierarchical_neural_multi_head_dynamics:v2"
    assert second["previous_active_entry"]["registry_key"] == "hierarchical_neural_multi_head_dynamics:v1"
    assert active_before["entries"][0]["registry_key"] == "hierarchical_neural_multi_head_dynamics:v2"
    assert rollback["schema"] == "territory_world_model.dynamics_model_registry_rollback.v1"
    assert rollback["restored_entry"]["registry_key"] == "hierarchical_neural_multi_head_dynamics:v1"
    assert rollback["rolled_back_entry"]["registry_key"] == "hierarchical_neural_multi_head_dynamics:v2"
    assert active_after["entries"][0]["registry_key"] == "hierarchical_neural_multi_head_dynamics:v1"


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


def test_report_cache_hits_and_invalidates_after_rule_evaluation(monkeypatch):
    svc = _build_service()
    project = TwmProject(name="Cache invalidation project", region_code="500227")
    state_version = TwmStateVersion(
        project_id=project.id,
        object_count=1,
        relation_count=0,
        build_status="ready",
        summary={"hierarchy_tokens": {"county": ["500227"]}, "object_counts_by_role": {"parcel": 1}},
        quality_summary={"evidence_coverage": 0.8},
    )
    state_object = TwmStateObject(
        state_version_id=state_version.id,
        object_type="feature",
        object_code="PARCEL-CACHE-001",
        source_role="parcel",
        canonical_role="parcel",
        attributes={"admin_code": "500227"},
        quality_score=0.9,
    )
    svc.repository.save_state_bundle(
        StateBuildResult(
            project=project,
            state_version=state_version,
            objects=[state_object],
            relations=[],
            object_counts_by_role={"parcel": 1},
            relation_counts_by_type={},
            hierarchy_tokens={"county": ["500227"]},
            quality_summary=state_version.quality_summary,
        )
    )

    original_get_state_bundle = svc.repository.get_state_bundle
    bundle_calls = {"count": 0}

    def counted_get_state_bundle(state_version_id):
        bundle_calls["count"] += 1
        return original_get_state_bundle(state_version_id)

    monkeypatch.setattr(svc.repository, "get_state_bundle", counted_get_state_bundle)

    first = svc.state_contract_report(state_version.id, {})
    second = svc.state_contract_report(state_version.id, {})

    assert first["schema"] == "territory_world_model.state_contract_report.v1"
    assert second == first
    assert bundle_calls["count"] == 1

    def fake_evaluate_state(*_args, **_kwargs):
        return TwmRuleEvaluationResult(
            state_version_id=state_version.id,
            summary={
                "state_version_id": state_version.id,
                "rule_count": 0,
                "hit_count": 0,
                "evidence_item_count": 0,
            },
        )

    monkeypatch.setattr(svc.rule_evaluator, "evaluate_state", fake_evaluate_state)
    svc.evaluate_rules(state_version.id, {"include_default_rules": False})
    after_invalidation = svc.state_contract_report(state_version.id, {})

    assert after_invalidation["schema"] == "territory_world_model.state_contract_report.v1"
    assert bundle_calls["count"] == 3


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


def test_train_dynamics_candidate_attaches_registry_gate_with_dataset_hash_lineage():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(state_id, {"scenario": "trainer_registry_seed", "horizon": 2, "evidence_coverage": 0.72})
    dataset = _observed_dynamics_dataset(seed)

    report = svc.train_dynamics_candidate(
        state_id,
        {
            "dataset": dataset,
            "trainer": {
                "trainer_id": "trainer-registry-scaffold",
                "model_name": "hierarchical_trainable_dynamics_scaffold",
                "model_version": "registry-unit",
            },
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
            "registry_metadata": {
                "state_contract_version": "state_contract_v1",
                "training_dataset_snapshot": "iceberg://twm/dynamics_training_dataset@snapshot-train",
                "training_run_id": "run-train-registry-001",
                "model_artifact_uri": "s3://gis-agent-lakehouse/artifacts/twm/models/train-registry.pt",
                "evaluation_report_id": "eval-train-registry-001",
            },
            "production_data_gate": {"status": "pass"},
            "geofm_gate_report": {"gate_status": "review", "decision": "review_required"},
            "causal_calibration_report": {"status": "review", "method": "payload_stub"},
        },
    )

    registry = report["registry_report"]
    training_hash = registry["registry_entry"]["metadata"]["training_dataset_hash"]
    assert registry["schema"] == "territory_world_model.dynamics_model_registry_report.v1"
    assert training_hash.startswith("sha256:")
    assert registry["registry_entry"]["lineage"]["training_dataset_hash"] == training_hash
    assert registry["gates"]["latent_v2_quality_gate"]["status"] in {"pass", "review"}
    assert registry["promotion_decision"] in {"review_only_not_promoted", "blocked_scaffold_not_promoted"}
    assert "non_scaffold_candidate" in registry["missing_for_promotion"]


def test_twm_service_operations_emit_dedicated_otel_spans(monkeypatch):
    captured = _capture_twm_trace(monkeypatch)
    svc = _build_service()
    project, state = _save_lightweight_twm_state(svc)
    dataset = _minimal_observed_dynamics_dataset(state.id, project.id)

    train_report = svc.train_dynamics_candidate(
        state.id,
        {
            "dataset": dataset,
            "trainer": {
                "trainer_id": "otel-trainer",
                "model_name": "hierarchical_trainable_dynamics_scaffold",
                "model_version": "otel",
            },
            "thresholds": {
                "min_total_examples": 6,
                "min_usable_examples": 6,
                "min_observed_temporal_examples": 3,
                "min_holdout_examples": 2,
                "max_scaffold_ratio": 0.0,
                "max_review_ratio": 0.0,
            },
        },
    )
    rollout_report = svc.counterfactual_rollout(
        state.id,
        {
            "scenario": "otel_rollout",
            "horizon": 2,
            "evidence_coverage": 0.8,
            "baseline_action": {"action_type": "inspect", "target_role": "parcel"},
            "intervention_actions": [{"action_type": "protect", "target_role": "parcel"}],
        },
    )
    records = []
    for idx in range(4):
        records.append({"unit_id": f"c-{idx}", "treatment": 0, "outcome": 0.1 + idx * 0.01, "stratum": "parcel"})
        records.append({"unit_id": f"t-{idx}", "treatment": 1, "outcome": 0.2 + idx * 0.01, "stratum": "parcel"})
    calibration_report = svc.causal_calibration_report(
        state.id,
        {
            "records": records,
            "model_effect": 0.05,
            "thresholds": {"min_records": 8, "min_treated": 4, "min_control": 4},
        },
    )

    by_operation = {item["operation"]: item for item in captured}
    assert set(by_operation) >= {
        "train_dynamics_candidate",
        "counterfactual_rollout",
        "estimate_observational_treatment_effect",
    }
    train_span = by_operation["train_dynamics_candidate"]
    assert train_span["attrs"]["state_version_id"] == state.id
    assert train_span["attrs"]["backend"] == "hierarchical_trainable_dynamics_scaffold"
    assert train_span["attrs"]["sample_count"] == 6
    assert train_span["span_attrs"]["twm.gate_status"] == train_report["evidence_gate"]["status"]
    assert train_span["span_attrs"]["twm.backend_gate_status"] == train_report["backend_report"]["evidence_gate"]["status"]
    assert train_span["span_attrs"]["twm.prediction_count"] == len(train_report["predictions"])

    rollout_span = by_operation["counterfactual_rollout"]
    assert rollout_span["attrs"]["state_version_id"] == state.id
    assert rollout_span["attrs"]["backend"] == "planner"
    assert rollout_span["attrs"]["sample_count"] == 4
    assert rollout_span["span_attrs"]["twm.gate_status"] == rollout_report["evidence_gate"]["status"]
    assert rollout_span["span_attrs"]["twm.horizon"] == 2
    assert rollout_span["span_attrs"]["twm.intervention_action_count"] == 1
    assert rollout_span["span_attrs"]["twm.rollout_step_count"] == 4

    causal_span = by_operation["estimate_observational_treatment_effect"]
    assert causal_span["attrs"]["state_version_id"] == state.id
    assert causal_span["attrs"]["backend"] == "observational_causal_calibration"
    assert causal_span["attrs"]["sample_count"] == 8
    assert causal_span["span_attrs"]["twm.gate_status"] == calibration_report["evidence_gate"]["status"]


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
    assert "future_latent_state.latent_vector" in report["learned_parameters"]["architecture"]["heads"]
    assert "future_latent_state.area_total" not in report["learned_parameters"]["architecture"]["heads"]
    assert report["learned_parameters"]["latent_contract"]["dimension_count"] >= 1
    assert report["learned_parameters"]["feature_contract"]["action_mask_context_feature_names"]
    assert "action_mask_context.risk_proxy" in report["learned_parameters"]["feature_contract"]["action_mask_context_feature_names"]
    assert report["evidence_gate"]["status"] in {"pass", "review", "blocked"}


def test_neural_multi_head_dynamics_trains_future_latent_state_v2_head():
    from data_agent.territory_world_model.neural_dynamics import train_neural_multi_head_dynamics

    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    seed = svc.dynamics_training_examples(state_id, {"scenario": "latent_v2_contract", "horizon": 2, "evidence_coverage": 0.72})
    observed = _observed_dynamics_dataset(seed, count=6)
    for idx, example in enumerate(observed["examples"]):
        example["targets"]["future_latent_state"] = {
            "observed_next": {
                "total_area_m2": 1000.0,
                "total_feature_count": 10,
                "land_space_types": {
                    "agricultural_space": {"area_m2": 600.0 - idx * 3.0, "feature_count": 6, "area_delta_m2": -idx * 3.0},
                    "ecological_space": {"area_m2": 400.0 + idx * 3.0, "feature_count": 4, "area_delta_m2": idx * 3.0},
                },
            },
            "delta": {
                "total_area_delta_m2": 0.0,
                "total_abs_area_delta_m2": idx * 6.0,
                "by_land_type": {
                    "agricultural_space": {"area_delta_m2": -idx * 3.0},
                    "ecological_space": {"area_delta_m2": idx * 3.0},
                },
            },
        }

    report = train_neural_multi_head_dynamics(
        observed,
        {"trainer_type": "torch_multi_head_mlp", "is_scaffold_baseline": False},
        {"objective_contract": {"multi_head_required": ["future_latent_state"]}, "loss_components": {}},
        {"training_config": {"epochs": 2, "hidden_dim": 8, "seed": 7}},
    )

    assert report["diagnostics"]["status"] == "pass"
    heads = report["learned_parameters"]["architecture"]["heads"]
    assert "future_latent_state.latent_vector" in heads
    assert "future_latent_state.decoded_state" in heads
    assert "future_latent_state.transition_delta" in heads
    assert "future_latent_state.area_total" not in heads
    assert report["learned_parameters"]["latent_contract"]["dimension_count"] >= 8
    first_prediction = next(iter(report["predictions"].values()))
    assert first_prediction["future_latent_state"]["schema"] == "territory_world_model.predicted_latent_state.v2"
    assert first_prediction["future_latent_state"]["decoded_state"]["land_space_types"]


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
    assert "future_latent_state.latent_vector" in report["learned_parameters"]["architecture"]["heads"]
    assert "future_latent_state.area_total" not in report["learned_parameters"]["architecture"]["heads"]
    assert report["learned_parameters"]["latent_contract"]["dimension_count"] >= 1
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
                "constraint_risk_contextual_weight": 2.5,
                "risk_head_mode": "context_direct",
                "feasibility_head_mode": "context_residual",
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
    assert architecture["constraint_risk_head"] == "context_direct"
    assert set(architecture["constraint_risk_context_tokens"]) == {"action", "context", "temporal"}
    assert architecture["action_mask_feasibility_head"] == "context_residual"
    assert set(architecture["action_mask_feasibility_context_tokens"]) == {"action", "context", "temporal"}
    assert "future_latent_state.latent_vector" in architecture["heads"]
    assert "future_latent_state.area_total" not in architecture["heads"]
    assert report["learned_parameters"]["latent_contract"]["dimension_count"] >= 1
    assert report["learned_parameters"]["feature_contract"]["flat_vector_allowed"] is False
    assert "temporal" in report["learned_parameters"]["feature_contract"]["sequence_feature_names"]
    assert report["learned_parameters"]["feature_contract"]["action_mask_context_feature_names"]
    assert report["learned_parameters"]["training_config"]["constraint_risk_calibration_weight"] == 0.55
    assert report["learned_parameters"]["training_config"]["constraint_risk_contextual_weight"] == 2.5
    assert report["learned_parameters"]["training_diagnostics"]["constraint_risk_calibration_weight"] == 0.55
    assert report["learned_parameters"]["training_diagnostics"]["constraint_risk_contextual_weight"] == 2.5
    assert report["learned_parameters"]["training_diagnostics"]["constraint_risk_weight_mean"] >= 1.0
    assert report["learned_parameters"]["training_diagnostics"]["constraint_risk_weight_max"] >= 1.0
    assert report["learned_parameters"]["training_diagnostics"]["seed"] == 13
    assert report["learned_parameters"]["training_diagnostics"]["risk_head_mode"] == "context_direct"
    assert report["learned_parameters"]["training_diagnostics"]["feasibility_head_mode"] == "context_residual"
    assert report["learned_parameters"]["training_diagnostics"]["prediction_count"] >= 1
    first_prediction = next(iter(report["predictions"].values()))
    assert first_prediction["hierarchical_token_summary"]["attention_backbone"] is True
    assert first_prediction["uncertainty"]["source"] == "torch_spatiotemporal_transformer"
    assert report["backend_report"]["schema"] == "territory_world_model.dynamics_backend_report.v1"
    assert report["objective"]["schema"] == "territory_world_model.training_objective_report.v1"
    assert report["evidence_gate"]["status"] in {"pass", "review", "blocked"}


def test_trainable_graph_and_transformer_backends_report_latent_v2_heads():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})
    seed = svc.dynamics_training_examples(state_id, {"scenario": "latent_v2_backend_contract", "horizon": 2, "evidence_coverage": 0.72})
    observed = _observed_dynamics_dataset(seed, count=6)

    graph_report = svc.train_dynamics_candidate(
        state_id,
        {
            "dataset": observed,
            "trainer": {
                "trainer_id": "latent-v2-graph",
                "model_name": "hierarchical_graph_token_dynamics",
                "model_version": "unit",
                "training_method": "torch_hierarchical_graph",
            },
            "training_config": {"epochs": 2, "hidden_dim": 8, "seed": 11},
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
    transformer_report = svc.train_dynamics_candidate(
        state_id,
        {
            "dataset": observed,
            "trainer": {
                "trainer_id": "latent-v2-transformer",
                "model_name": "spatiotemporal_transformer_dynamics",
                "model_version": "unit",
                "training_method": "torch_spatiotemporal_transformer",
            },
            "training_config": {"epochs": 2, "hidden_dim": 8, "seed": 13},
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

    for report in (graph_report, transformer_report):
        if report["status"] == "blocked" and "torch_unavailable" in json.dumps(report):
            continue
        heads = report["learned_parameters"]["architecture"]["heads"]
        assert "future_latent_state.latent_vector" in heads
        assert "future_latent_state.area_total" not in heads
        assert report["learned_parameters"]["latent_contract"]["dimension_count"] >= 1
        first_prediction = next(iter(report["predictions"].values()))
        assert first_prediction["future_latent_state"]["schema"] == "territory_world_model.predicted_latent_state.v2"


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
    assert report["identification_strength"] == "observational"
    assert "not randomized" in report["identification_note"]
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


def test_scca_causal_evidence_report_accepts_external_spatial_causal_payload():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]

    report = svc.scca_causal_evidence_report(
        state_id,
        {
            "scca_result": {
                "case_id": "county_social_capital",
                "case_label": "County social capital",
                "row_count": 120,
                "column_count": 18,
                "exposure": "SocialAssoc",
                "outcome": "AveAgeDeath",
                "confounders": ["UnemployRate", "pHHinPoverty"],
                "context_columns": ["Shape_Length", "Shape_Area"],
                "credibility_decision": "strong_support",
                "evidence_grade": "core_support",
                "effect_estimates": [
                    {
                        "estimator": "baseline_adjusted_ols",
                        "coef": 0.04,
                        "p_value": 0.07,
                        "ci_lower": 0.01,
                        "ci_upper": 0.08,
                        "status": "ok",
                    },
                    {
                        "estimator": "spatial_neighbor_adjusted_ols",
                        "coef": 0.035,
                        "p_value": 0.04,
                        "neighbor_exposure_coef": 0.012,
                        "sign_stable": True,
                        "status": "ok",
                    },
                ],
                "balance_summary": [
                    {"covariate": "UnemployRate", "standardized_mean_difference": 0.12},
                    {"covariate": "pHHinPoverty", "standardized_mean_difference": -0.18},
                ],
                "spatial_diagnostics": {
                    "graph": {"method": "queen", "edge_count": 240},
                    "residual_moran": {"moran_i": 0.08, "permutation_p_value": 0.31},
                    "exposure_moran": {"moran_i": 0.16, "permutation_p_value": 0.05},
                },
            },
            "thresholds": {
                "min_row_count": 80,
                "max_p_value": 0.1,
            },
        },
    )

    assert report["schema"] == "territory_world_model.scca_causal_evidence_report.v1"
    assert report["status"] == "pass"
    assert report["boundary"]["replaces_twm_simulator"] is False
    assert report["study"]["case_id"] == "county_social_capital"
    assert report["effect"]["estimator"] == "spatial_neighbor_adjusted_ols"
    assert report["effect"]["coef"] == 0.035
    assert report["balance"]["max_abs_standardized_mean_difference"] == 0.18
    assert report["spatial_diagnostics"]["edge_count"] == 240
    assert report["evidence_gate"]["status"] == "pass"
    assert report["calibration_hint"]["can_support_twm_causal_calibration"] is True


def test_scca_causal_evidence_report_loads_scca_output_directory(tmp_path):
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]

    output_dir = tmp_path / "scca_run"
    output_dir.mkdir()
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "case_id": "chongqing_uhi",
                "row_count": 96,
                "column_count": 14,
                "exposure": "floor",
                "outcome": "LST",
                "confounders": ["rs_NDVI", "rs_NDBI"],
                "context_columns": ["centroid_x", "centroid_y"],
                "credibility_decision": "moderate_support",
                "evidence_grade": "bounded_support",
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "effect_estimates.csv").write_text(
        "\n".join(
            [
                "estimator,coef,p_value,neighbor_exposure_coef,sign_stable,status",
                "baseline_adjusted_ols,0.12,0.08,,True,ok",
                "spatial_neighbor_adjusted_ols,0.10,0.05,0.02,True,ok",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "balance_summary.csv").write_text(
        "\n".join(
            [
                "covariate,standardized_mean_difference",
                "rs_NDVI,0.11",
                "rs_NDBI,-0.19",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "spatial_diagnostics.json").write_text(
        json.dumps(
            {
                "graph": {"method": "knn", "edge_count": 128},
                "residual_moran": {"moran_i": 0.06, "permutation_p_value": 0.42},
            }
        ),
        encoding="utf-8",
    )

    report = svc.scca_causal_evidence_report(
        state_id,
        {
            "scca_output_dir": str(output_dir),
            "thresholds": {"min_row_count": 80},
        },
    )

    assert report["status"] == "pass"
    assert report["provenance"]["output_dir"] == str(output_dir)
    assert report["provenance"]["loaded_from_path"] == str(output_dir / "manifest.json")
    assert report["credibility"]["evidence_grade"] == "bounded_support"
    assert report["effect"]["coef"] == 0.1
    assert report["spatial_diagnostics"]["graph_method"] == "knn"


def test_causal_calibration_report_embeds_scca_causal_evidence_without_replacing_local_estimator():
    svc = _build_service()
    _project, state = _build_project_and_state(svc)
    state_id = state["state_version"]["id"]
    svc.ensure_default_rules()
    svc.evaluate_rules(state_id, {"include_default_rules": True})

    records = []
    for idx in range(6):
        records.append({"unit_id": f"scca-c-{idx}", "treatment": 0, "outcome": 0.10 + idx * 0.005, "stratum": "project"})
        records.append({"unit_id": f"scca-t-{idx}", "treatment": 1, "outcome": 0.20 + idx * 0.005, "stratum": "project"})

    scca = svc.scca_causal_evidence_report(
        state_id,
        {
            "scca_result": {
                "case_id": "external_scca",
                "row_count": 120,
                "credibility_decision": "strong_support",
                "evidence_grade": "core_support",
                "effect_estimates": [{"estimator": "spatial_neighbor_adjusted_ols", "coef": 0.09, "p_value": 0.03}],
                "spatial_diagnostics": {"residual_moran": {"moran_i": 0.04}},
            }
        },
    )
    report = svc.causal_calibration_report(
        state_id,
        {
            "model_effect": 0.05,
            "records": records,
            "scca_causal_evidence_report": scca,
            "thresholds": {"min_records": 10, "min_treated": 5, "min_control": 5},
        },
    )

    assert report["status"] == "pass"
    assert report["identification_strength"] == "observational"
    assert report["estimate"]["estimator"]["primary"] == "augmented_ipw_ate"
    assert report["evidence_gate"]["scca_causal_evidence"]["provided"] is True
    assert report["evidence_gate"]["scca_causal_evidence"]["status"] == "pass"
    assert report["provenance"]["scca_causal_evidence_report"]["schema"] == "territory_world_model.scca_causal_evidence_report.v1"


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
    assert calibrated["forecast"]["calibration"]["causal_calibration"]["identification_strength"] == "observational"
    assert calibrated["forecast"]["future_latent_state"]["projected"]["causal_adjustment"]["source"]["identification_strength"] == "observational"


def test_neural_dynamics_prediction_exposes_area_indicator_contract():
    from data_agent.territory_world_model.neural_dynamics import _prediction_from_outputs

    prediction = _prediction_from_outputs(
        example={"id": "contract-example", "action": {"action_type": "protect", "target_role": "parcel"}},
        area_total=1234.5,
        constraint_probability=0.24,
        utility_delta=0.31,
        confidence=0.72,
        calibrated_utility=0.28,
        action_allowed_probability=0.82,
        source="unit_test_candidate",
    )

    indicators = prediction["future_area_and_key_indicators"]
    assert indicators["schema"] == "territory_world_model.future_area_and_key_indicators.v1"
    assert indicators["projected"]["total_area_m2"] == 1234.5
    assert prediction["future_latent_state"]["schema"] == "territory_world_model.predicted_latent_state.v2"
    assert prediction["future_latent_state"]["decoded_state"]["total_area_m2"] == 1234.5
    assert prediction["future_latent_state"]["representation_boundary"] == "multi_dimensional_hierarchical_state_latent_not_full_geometry"
    assert indicators["representation_boundary"] == "derived_from_multi_dimensional_hierarchical_state_latent"


def test_latent_v2_decoder_outputs_multi_dimensional_state_contract():
    from data_agent.territory_world_model.neural_dynamics import (
        _decode_latent_vector,
        _prediction_from_outputs,
    )

    dimensions = [
        "observed_next.total_area_m2",
        "observed_next.total_feature_count",
        "observed_next.land_space_types.agricultural_space.area_m2",
        "observed_next.land_space_types.agricultural_space.feature_count",
        "observed_next.land_space_types.agricultural_space.area_delta_m2",
        "observed_next.land_space_types.ecological_space.area_m2",
        "observed_next.land_space_types.ecological_space.feature_count",
        "observed_next.land_space_types.ecological_space.area_delta_m2",
        "delta.total_area_delta_m2",
        "delta.total_abs_area_delta_m2",
        "delta.by_land_type.agricultural_space.area_delta_m2",
        "delta.by_land_type.ecological_space.area_delta_m2",
    ]
    values = [1000.0, 10.0, 580.0, 6.0, -20.0, 420.0, 4.0, 20.0, 0.0, 40.0, -20.0, 20.0]

    latent = _decode_latent_vector(dimensions, values, source="unit_test_candidate")

    assert latent["schema"] == "territory_world_model.predicted_latent_state.v2"
    assert latent["latent_head_scope"] == "multi_dimensional_hierarchical_state"
    assert latent["representation_boundary"] == "multi_dimensional_hierarchical_state_latent_not_full_geometry"
    assert latent["latent_vector"]["observed_next.total_area_m2"] == 1000.0
    assert latent["decoded_state"]["total_area_m2"] == 1000.0
    assert latent["decoded_state"]["total_feature_count"] == 10
    assert latent["decoded_state"]["land_space_types"]["agricultural_space"]["area_m2"] == 580.0
    assert latent["decoded_state"]["land_space_types"]["agricultural_space"]["feature_count"] == 6
    assert latent["decoded_state"]["land_space_types"]["agricultural_space"]["area_delta_m2"] == -20.0
    assert latent["transition_delta"]["total_abs_area_delta_m2"] == 40.0
    assert latent["transition_delta"]["by_land_type"]["ecological_space"]["area_delta_m2"] == 20.0

    prediction = _prediction_from_outputs(
        example={"id": "contract-example", "action": {"action_type": "protect", "target_role": "parcel"}},
        latent_dimensions=dimensions,
        latent_values=values,
        constraint_probability=0.24,
        utility_delta=0.31,
        confidence=0.72,
        calibrated_utility=0.28,
        action_allowed_probability=0.82,
        source="unit_test_candidate",
    )

    assert prediction["future_latent_state"]["schema"] == "territory_world_model.predicted_latent_state.v2"
    assert prediction["future_latent_state"]["decoded_state"]["total_area_m2"] == 1000.0
    assert prediction["future_area_and_key_indicators"]["projected"]["total_area_m2"] == 1000.0
    assert prediction["future_latent_state"]["representation_boundary"] != "compatibility_alias_for_future_area_and_key_indicators"


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


def test_business_scenarios_are_business_first_templates():
    svc = _build_service()
    scenarios = svc.list_business_scenarios()

    farmland = next(item for item in scenarios if item["id"] == "farmland_protection_review")
    assert farmland["decision_question"].startswith("拟建或调整项目")
    assert farmland["default_action_type"] == "protect"
    assert "永久基本农田" in farmland["required_evidence"]
    assert "合法可行备选方案" in farmland["decision_outputs"]


def test_business_scenarios_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_business_scenarios(_fake_request()))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["scenarios"][0]["decision_question"]
    assert {item["id"] for item in body["scenarios"]} >= {
        "farmland_protection_review",
        "construction_project_compliance",
        "territorial_plan_adjustment",
    }


def test_research_positioning_states_core_claims_and_falsification_conditions():
    svc = _build_service()
    positioning = svc.research_positioning()

    core_names = {item["name"] for item in positioning["core_technology"]}
    assert "Hierarchical GIS object-relation-rule-evidence state" in core_names
    assert "Action-conditioned multi-head territorial dynamics" in core_names
    dynamics_claim = next(item["claim"] for item in positioning["core_technology"] if item["name"] == "Action-conditioned multi-head territorial dynamics")
    assert "multi-dimensional hierarchical future-state latent" in dynamics_claim
    assert "full parcel geometry" in dynamics_claim
    assert positioning["unmet_need_hypotheses"]
    assert "Rule-only spatial compliance engine" in positioning["baselines_to_beat"]
    assert any("stopped" in item for item in positioning["falsification_conditions"])
    assert "synthetic fixtures" in " ".join(positioning["minimum_evaluation_plan"])


def test_research_positioning_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_research_positioning(_fake_request()))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["research_question"].startswith("Can a governance-oriented geospatial world model")


def test_roadmap_status_report_summarizes_completion_and_blockers():
    svc = _build_service()
    report = svc.roadmap_status_report()

    assert report["schema"] == "territory_world_model.roadmap_status_report.v1"
    assert report["overall_status"] == "prototype_complete_review_only"
    phase_status = {item["id"]: item["status"] for item in report["phases"]}
    assert phase_status["demo_closure"] == "complete"
    assert phase_status["trusted_poc"] == "blocked"
    assert phase_status["productionization"] == "blocked"
    assert report["data_gate"]["production_ready_observed_history_rows"] == 0
    assert any(item["id"] == "production_observed_history" for item in report["blockers"])
    assert report["next_actions"][0]["priority"] == "P0"
    assert "observed history" in report["next_actions"][0]["action"]
    assert "review-only" in report["claim_boundary"]


def test_roadmap_status_report_reflects_lineage_and_registry_gate_progress():
    svc = _build_service()
    report = svc.roadmap_status_report()
    phases = {item["id"]: item for item in report["phases"]}

    engineering = phases["engineering_scaffold"]
    assert engineering["completion_ratio"] >= 0.78
    assert any("model registry release gate" in item for item in engineering["evidence"])
    assert any("persistent model registry/version rollback" in item for item in engineering["evidence"])
    assert any("state snapshot lakehouse manifest" in item for item in engineering["evidence"])
    assert any("state snapshot lakehouse materializer" in item for item in engineering["evidence"])
    assert any("Iceberg/Sedona publish plan" in item for item in engineering["evidence"])
    assert any("Spark executor contract" in item for item in engineering["evidence"])
    assert any("spark-submit execution bundle" in item for item in engineering["evidence"])
    assert "persistent model registry/version rollback" not in engineering["remaining"]
    assert "model registry/version rollback" not in engineering["remaining"]
    assert "production-scale storage/index review" not in engineering["remaining"]
    assert "production lakehouse writer and spatial index build" not in engineering["remaining"]
    assert "Iceberg table registration and distributed spatial index build" not in engineering["remaining"]
    assert "production Spark executor and Iceberg snapshot validation" not in engineering["remaining"]
    assert "production Spark cluster wiring and external Iceberg audit" not in engineering["remaining"]
    assert "credentialed production Spark run and external Iceberg audit acceptance" in engineering["remaining"]

    data_foundation = phases["data_foundation_productization"]
    assert data_foundation["completion_ratio"] >= 0.68
    assert any("lineage and field drilldown" in item for item in data_foundation["evidence"])
    assert any("CRS remediation plan" in item for item in data_foundation["evidence"])
    assert any("authoritative production data templates" in item for item in data_foundation["evidence"])
    assert "lineage browser" not in data_foundation["remaining"]
    assert "CRS conversion workflow" not in data_foundation["remaining"]
    assert "authoritative data templates" not in data_foundation["remaining"]
    assert "production CRS conversion ETL" in data_foundation["remaining"]
    assert "production lineage ingestion templates" in data_foundation["remaining"]


def test_roadmap_status_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_roadmap_status(_fake_request()))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.roadmap_status_report.v1"
    assert body["overall_status"] == "prototype_complete_review_only"
    assert body["claim_boundary"].startswith("Current TWM is a rigorous prototype")


def test_research_claim_matrix_binds_claims_to_baselines_and_falsification():
    svc = _build_service()
    matrix = svc.research_claim_matrix()

    assert matrix["schema"] == "territory_world_model.research_claim_matrix.v1"
    assert matrix["status"] == "review"
    assert matrix["current_data_gate"]["production_ready_observed_history_rows"] == 0
    claim_ids = {item["claim_id"] for item in matrix["claims"]}
    assert {
        "C1_state_conflict_recall",
        "C2_audit_defensibility",
        "C3_action_conditioned_triage",
        "C4_standard_contract_ingestion",
    }.issubset(claim_ids)
    c1 = next(item for item in matrix["claims"] if item["claim_id"] == "C1_state_conflict_recall")
    assert c1["baseline"] == "manual_gis_overlay_checklist"
    assert c1["gate"]["claim_level"] == "prototype_scaffold"
    assert "production_observed_history" in c1["gate"]["missing"]
    assert any(metric["name"] == "hard_constraint_conflict_recall" for metric in c1["metrics"])
    baseline_ids = {item["baseline_id"] for item in matrix["baselines"]}
    assert "rule_only_spatial_compliance_engine" in baseline_ids
    assert matrix["next_experiments"][0]["priority"] == "P0"
    assert "组件" in matrix["mentor_answer"]


def test_research_claim_matrix_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_research_claim_matrix(_fake_request()))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.research_claim_matrix.v1"
    assert body["claims"][0]["gate"]["status"] == "review"
    assert any(item["baseline_id"] == "manual_gis_overlay_checklist" for item in body["baselines"])


def test_baseline_comparison_report_requires_named_baseline_evidence():
    svc = _build_service()
    report = svc.baseline_comparison_report({"claim_id": "C1_state_conflict_recall"})

    assert report["schema"] == "territory_world_model.baseline_comparison_report.v1"
    assert report["status"] == "review"
    assert report["upgrade_decision"] == "baseline_evidence_not_provided"
    assert "baseline_metrics" in report["evidence_gate"]["missing"]
    assert "comparable_metrics" in report["evidence_gate"]["missing"]
    assert report["claim"]["claim_id"] == "C1_state_conflict_recall"


def test_baseline_export_schema_defines_same_case_contract():
    svc = _build_service()
    schema = svc.baseline_export_schema()

    assert schema["schema"] == "territory_world_model.baseline_export_schema.v1"
    assert schema["same_case_join_requirements"]["minimum_overlap_ratio"] == 0.8
    assert schema["validation_api"]["endpoint"] == "POST /api/twm/baseline-export-validation-report"
    export_types = {item["export_type"]: item for item in schema["export_types"]}
    assert "manual_overlay" in export_types
    assert "rule_only_engine" in export_types
    assert "optimization_or_simulator_ranking" in export_types
    assert "case_id" in export_types["manual_overlay"]["required_columns"]
    assert "C1_state_conflict_recall" in export_types["manual_overlay"]["compatible_claims"]


def test_baseline_export_templates_define_real_sanitized_collection_contracts():
    svc = _build_service()
    templates = svc.baseline_export_templates()

    assert templates["schema"] == "territory_world_model.baseline_export_templates.v1"
    assert "real/sanitized same-case CSV collection templates" in templates["purpose"]
    by_claim = {item["claim_id"]: item for item in templates["templates"]}
    assert {"C1_state_conflict_recall", "C2_audit_defensibility", "C3_action_conditioned_triage"}.issubset(by_claim)

    c1 = by_claim["C1_state_conflict_recall"]
    assert c1["baseline_id"] == "manual_gis_overlay_checklist"
    assert c1["same_case_join_key"] == "case_id"
    assert {"case_id", "ground_truth_conflict", "detected_conflict", "evidence_linked"}.issubset(c1["headers"]["twm"])
    assert "case_id,project_id,region_code" in c1["csv_header"]["twm"]
    assert c1["sample_rows"]["twm"][0]["sanitization_level"] == "real_sanitized"
    assert c1["validation_payload_template"]["claim_id"] == "C1_state_conflict_recall"

    c2 = by_claim["C2_audit_defensibility"]
    assert {"case_id", "evidence_linked", "unsupported_recommendation", "review_task_predicted"}.issubset(c2["headers"]["baseline"])
    assert "review_task_precision" in {item["metric"] for item in c2["metric_column_map"]}

    c3 = by_claim["C3_action_conditioned_triage"]
    assert c3["same_case_join_key"] == "candidate_id"
    assert {"candidate_id", "rank", "selected", "legal_feasible", "planner_regret_against_human_oracle"}.issubset(
        c3["headers"]["twm"]
    )
    assert c3["minimum_real_data_gate"]["minimum_overlap_ratio"] == 0.8
    assert "production_policy_action_labels" in c3["minimum_real_data_gate"]["claim_gate_missing"]
    assert c3["not_for_production"] is True


def test_baseline_export_validation_passes_same_case_manual_overlay_fixture():
    svc = _build_service()
    report = svc.baseline_export_validation_report(
        {
            "claim_id": "C1_state_conflict_recall",
            "baseline_id": "manual_gis_overlay_checklist",
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv",
        }
    )

    assert report["schema"] == "territory_world_model.baseline_export_validation_report.v1"
    assert report["status"] == "pass"
    assert report["coverage"]["overlap_count"] == 10
    assert report["coverage"]["coverage_ratio"] == 1.0
    assert report["column_inventory"]["join_key"] == "case_id"
    assert report["column_inventory"]["missing_required"] == {"twm": [], "baseline": [], "claim_parser": []}
    assert "_join_ids" not in report["column_inventory"]["twm"]
    assert "hard_constraint_conflict_recall" in report["parser_compatibility"]["comparable_metrics"]
    assert report["blocking_errors"] == []


def test_baseline_export_validation_blocks_non_same_case_candidate_fixture():
    svc = _build_service()
    report = svc.baseline_export_validation_report(
        {
            "claim_id": "C3_action_conditioned_triage",
            "baseline_id": "land_use_simulator_or_optimization_only_ranking",
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_candidate_triage_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/optimization_only_candidate_triage_outputs.csv",
        }
    )

    assert report["status"] == "blocked"
    assert report["column_inventory"]["join_key"] == "candidate_id"
    assert report["coverage"]["overlap_count"] == 0
    assert "same_case_overlap_missing" in report["blocking_errors"]
    assert "planner_regret_against_human_oracle" in report["parser_compatibility"]["comparable_metrics"]
    assert any("same historical case or candidate IDs" in item for item in report["next_actions"])


def test_baseline_export_validation_passes_same_case_candidate_fixture():
    svc = _build_service()
    report = svc.baseline_export_validation_report(
        {
            "claim_id": "C3_action_conditioned_triage",
            "baseline_id": "land_use_simulator_or_optimization_only_ranking",
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_candidate_triage_same_case_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/optimization_only_candidate_triage_same_case_outputs.csv",
        }
    )

    assert report["status"] == "pass"
    assert report["column_inventory"]["join_key"] == "candidate_id"
    assert report["coverage"]["overlap_count"] == 5
    assert report["coverage"]["coverage_ratio"] == 1.0
    assert report["column_inventory"]["twm"]["synthetic_rows"] == 5
    assert "synthetic_rows_present_export_is_regression_only" in report["warnings"]
    assert {"candidate_rejection_reason_coverage", "legal_feasible_topk_precision", "planner_regret_against_human_oracle"}.issubset(
        set(report["parser_compatibility"]["comparable_metrics"])
    )


def test_baseline_export_validation_can_save_run_card():
    svc = _build_service()
    project = svc.create_project({"name": "Export validation card project", "region_code": "500227"}, username="tester")
    report = svc.baseline_export_validation_report(
        {
            "claim_id": "C3_action_conditioned_triage",
            "baseline_id": "land_use_simulator_or_optimization_only_ranking",
            "project_id": project["id"],
            "base_state_version_id": "state-demo",
            "save_run_card": True,
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_candidate_triage_same_case_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/optimization_only_candidate_triage_same_case_outputs.csv",
        }
    )

    scenario_id = report["scenario_card"]["scenario_id"]
    scenario = svc.repository.get_scenario(scenario_id)
    assert scenario is not None
    assert scenario.project_id == project["id"]
    assert scenario.base_state_version_id == "state-demo"
    assert scenario.scenario_type == "baseline_export_validation"
    assert scenario.status == "pass"
    assert scenario.metadata["kind"] == "baseline_export_validation_run_card"
    assert scenario.metadata["coverage"]["overlap_count"] == 5
    assert scenario.metadata["column_inventory"]["join_key"] == "candidate_id"
    assert scenario.metadata["not_for_production"] is True


def test_baseline_export_import_stages_csv_for_validation():
    svc = _build_service()
    csv_text = "\n".join(
        [
            "case_id,ground_truth_conflict,detected_conflict,evidence_linked,unsupported_recommendation,not_for_production,sanitization_level",
            "u001,true,true,true,false,true,synthetic_regression",
            "u002,true,false,true,false,true,synthetic_regression",
        ]
    )

    imported = svc.import_baseline_export(
        {
            "filename": "../unsafe name.csv",
            "source_role": "twm",
            "claim_id": "C1_state_conflict_recall",
            "baseline_id": "manual_gis_overlay_checklist",
            "batch_id": "unit test batch",
            "content": csv_text,
        },
        username="tester@example.com",
    )

    assert imported["schema"] == "territory_world_model.baseline_export_import.v1"
    assert imported["status"] == "pass"
    assert imported["path"].startswith("data_agent/uploads/twm_baseline_exports/tester_example.com/unit_test_batch/twm_")
    assert imported["path"].endswith("unsafe_name.csv")
    assert imported["row_count"] == 2
    assert "hard_constraint_conflict_recall" in imported["preview_metrics"]

    report = svc.baseline_export_validation_report(
        {
            "claim_id": "C1_state_conflict_recall",
            "baseline_id": "manual_gis_overlay_checklist",
            "twm_case_output_path": imported["path"],
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv",
        }
    )
    assert report["column_inventory"]["join_key"] == "case_id"
    assert "same_case_overlap_missing" in report["blocking_errors"]


def test_baseline_evidence_pipeline_blocks_comparison_when_export_not_same_case():
    svc = _build_service()
    report = svc.baseline_evidence_pipeline_report(
        {
            "claim_id": "C3_action_conditioned_triage",
            "baseline_id": "land_use_simulator_or_optimization_only_ranking",
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_candidate_triage_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/optimization_only_candidate_triage_outputs.csv",
            "save_run_card": True,
        }
    )

    assert report["schema"] == "territory_world_model.baseline_evidence_pipeline_report.v1"
    assert report["status"] == "blocked"
    assert report["pipeline_decision"] == "export_validation_blocked"
    assert report["steps"]["export_validation"]["status"] == "blocked"
    assert "same_case_overlap_missing" in report["steps"]["export_validation"]["blocking_errors"]
    assert report["steps"]["baseline_comparison"]["status"] == "skipped"
    assert report["baseline_comparison"] is None
    assert report["steps"]["baseline_comparison"]["skipped_reason"] == "export_validation_blocked"


def test_baseline_evidence_pipeline_saves_validation_and_comparison_cards():
    svc = _build_service()
    project = svc.create_project({"name": "Evidence pipeline project", "region_code": "500227"}, username="tester")
    report = svc.baseline_evidence_pipeline_report(
        {
            "claim_id": "C1_state_conflict_recall",
            "baseline_id": "manual_gis_overlay_checklist",
            "project_id": project["id"],
            "base_state_version_id": "state-demo",
            "save_run_card": True,
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv",
        }
    )

    assert report["status"] == "review"
    assert report["pipeline_decision"] == "metrics_pass_but_data_gate_blocks_upgrade"
    assert report["steps"]["export_validation"]["status"] == "pass"
    assert report["steps"]["baseline_comparison"]["status"] == "review"
    validation_card = report["steps"]["export_validation"]["scenario_card"]
    comparison_card = report["steps"]["baseline_comparison"]["scenario_card"]
    assert validation_card["scenario_type"] == "baseline_export_validation"
    assert comparison_card["scenario_type"] == "baseline_comparison"
    assert svc.repository.get_scenario(validation_card["scenario_id"]).metadata["kind"] == "baseline_export_validation_run_card"
    assert svc.repository.get_scenario(comparison_card["scenario_id"]).metadata["kind"] == "baseline_comparison_run_card"


def test_baseline_export_routes_return_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    schema_response = asyncio.run(routes.twm_baseline_export_schema(_fake_request()))
    schema_body = json.loads(schema_response.body)
    assert schema_response.status_code == 200
    assert schema_body["schema"] == "territory_world_model.baseline_export_schema.v1"

    templates_response = asyncio.run(routes.twm_baseline_export_templates(_fake_request()))
    templates_body = json.loads(templates_response.body)
    assert templates_response.status_code == 200
    assert templates_body["schema"] == "territory_world_model.baseline_export_templates.v1"
    assert {item["claim_id"] for item in templates_body["templates"]} >= {
        "C1_state_conflict_recall",
        "C2_audit_defensibility",
        "C3_action_conditioned_triage",
    }

    import_request = _fake_request(
        "POST",
        json.dumps(
            {
                "filename": "route_twm.csv",
                "source_role": "twm",
                "claim_id": "C1_state_conflict_recall",
                "baseline_id": "manual_gis_overlay_checklist",
                "batch_id": "route-test",
                "content": "case_id,ground_truth_conflict,detected_conflict,evidence_linked,unsupported_recommendation\nr001,true,true,true,false\n",
            }
        ).encode("utf-8"),
    )
    import_response = asyncio.run(routes.twm_baseline_export_import(import_request))
    import_body = json.loads(import_response.body)
    assert import_response.status_code == 200
    assert import_body["schema"] == "territory_world_model.baseline_export_import.v1"
    assert import_body["path"].endswith("twm_route_twm.csv")

    pipeline_request = _fake_request(
        "POST",
        json.dumps(
            {
                "claim_id": "C1_state_conflict_recall",
                "baseline_id": "manual_gis_overlay_checklist",
                "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv",
                "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv",
            }
        ).encode("utf-8"),
    )
    pipeline_response = asyncio.run(routes.twm_baseline_evidence_pipeline_report(pipeline_request))
    pipeline_body = json.loads(pipeline_response.body)
    assert pipeline_response.status_code == 200
    assert pipeline_body["schema"] == "territory_world_model.baseline_evidence_pipeline_report.v1"
    assert pipeline_body["steps"]["export_validation"]["status"] == "pass"

    validation_request = _fake_request(
        "POST",
        json.dumps(
            {
                "claim_id": "C1_state_conflict_recall",
                "baseline_id": "manual_gis_overlay_checklist",
                "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv",
                "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv",
            }
        ).encode("utf-8"),
    )
    validation_response = asyncio.run(routes.twm_baseline_export_validation_report(validation_request))
    validation_body = json.loads(validation_response.body)

    assert validation_response.status_code == 200
    assert validation_body["schema"] == "territory_world_model.baseline_export_validation_report.v1"
    assert validation_body["status"] == "pass"


def test_baseline_comparison_report_keeps_metrics_pass_blocked_by_data_gate():
    svc = _build_service()
    report = svc.baseline_comparison_report(
        {
            "claim_id": "C1_state_conflict_recall",
            "baseline_id": "manual_gis_overlay_checklist",
            "twm_metrics": {
                "hard_constraint_conflict_recall": 0.97,
                "missed_blocking_conflict_rate": 0.01,
                "evidence_link_completeness": 0.92,
            },
            "baseline_metrics": {
                "hard_constraint_conflict_recall": 0.91,
                "missed_blocking_conflict_rate": 0.04,
                "evidence_link_completeness": 0.8,
            },
        }
    )

    assert report["status"] == "review"
    assert report["upgrade_decision"] == "metrics_pass_but_data_gate_blocks_upgrade"
    assert report["inputs"]["provided_metric_count"] == 3
    assert report["inputs"]["passed_metric_count"] == 3
    assert report["evidence_gate"]["metrics_pass"] is True
    assert report["evidence_gate"]["claim_gate_clear"] is False
    assert "production_observed_history" in report["evidence_gate"]["missing"]


def test_baseline_comparison_report_loads_metric_files():
    svc = _build_service()
    report = svc.baseline_comparison_report(
        {
            "claim_id": "C1_state_conflict_recall",
            "baseline_id": "manual_gis_overlay_checklist",
            "twm_metrics_path": "data_agent/test_data/twm_baseline_metrics/twm_metrics.json",
            "baseline_metrics_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_metrics.csv",
        }
    )

    assert report["status"] == "review"
    assert report["upgrade_decision"] == "metrics_pass_but_data_gate_blocks_upgrade"
    assert report["inputs"]["twm_metric_count"] == 3
    assert report["inputs"]["baseline_metric_count"] == 3
    assert report["inputs"]["twm_metrics_source"].endswith("twm_metrics.json")
    assert report["inputs"]["baseline_metrics_source"].endswith("manual_overlay_metrics.csv")
    assert report["inputs"]["metric_source_errors"] == {
        "twm": None,
        "baseline": None,
        "twm_cases": None,
        "baseline_cases": None,
    }


def test_baseline_comparison_report_aggregates_case_level_outputs():
    svc = _build_service()
    report = svc.baseline_comparison_report(
        {
            "claim_id": "C1_state_conflict_recall",
            "baseline_id": "manual_gis_overlay_checklist",
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv",
        }
    )

    comparisons = {item["name"]: item for item in report["metric_comparisons"]}
    assert report["status"] == "review"
    assert report["upgrade_decision"] == "metrics_pass_but_data_gate_blocks_upgrade"
    assert report["inputs"]["twm_case_count"] == 10
    assert report["inputs"]["baseline_case_count"] == 10
    assert comparisons["hard_constraint_conflict_recall"]["twm_value"] == 1.0
    assert comparisons["hard_constraint_conflict_recall"]["baseline_value"] == 0.9
    assert comparisons["missed_blocking_conflict_rate"]["twm_value"] == 0.0
    assert comparisons["missed_blocking_conflict_rate"]["baseline_value"] == 0.1
    assert comparisons["evidence_link_completeness"]["baseline_value"] == 0.7
    assert report["inputs"]["metric_source_errors"]["twm_cases"] is None
    assert report["inputs"]["metric_source_errors"]["baseline_cases"] is None


def test_baseline_comparison_report_aggregates_audit_case_outputs():
    svc = _build_service()
    report = svc.baseline_comparison_report(
        {
            "claim_id": "C2_audit_defensibility",
            "baseline_id": "rule_only_spatial_compliance_engine",
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv",
        }
    )

    comparisons = {item["name"]: item for item in report["metric_comparisons"]}
    assert report["upgrade_decision"] == "metrics_pass_but_data_gate_blocks_upgrade"
    assert comparisons["audit_trail_completeness"]["twm_value"] == 1.0
    assert comparisons["audit_trail_completeness"]["baseline_value"] == 0.7
    assert comparisons["unsupported_recommendation_rate"]["twm_value"] == 0.0
    assert comparisons["unsupported_recommendation_rate"]["baseline_value"] == 0.1
    assert comparisons["unsupported_recommendation_rate"]["status"] == "pass"
    assert comparisons["review_task_precision"]["twm_value"] == 1.0
    assert comparisons["review_task_precision"]["baseline_value"] == 0.666667


def test_baseline_comparison_report_aggregates_candidate_triage_outputs():
    svc = _build_service()
    report = svc.baseline_comparison_report(
        {
            "claim_id": "C3_action_conditioned_triage",
            "baseline_id": "land_use_simulator_or_optimization_only_ranking",
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_candidate_triage_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/optimization_only_candidate_triage_outputs.csv",
        }
    )

    comparisons = {item["name"]: item for item in report["metric_comparisons"]}
    assert report["upgrade_decision"] == "no_metric_lift_over_baseline"
    assert comparisons["candidate_rejection_reason_coverage"]["twm_value"] == 1.0
    assert comparisons["candidate_rejection_reason_coverage"]["baseline_value"] == 0.5
    assert comparisons["legal_feasible_topk_precision"]["twm_value"] == 0.666667
    assert comparisons["legal_feasible_topk_precision"]["baseline_value"] == 0.333333
    assert comparisons["planner_regret_against_human_oracle"]["twm_value"] == 0.04
    assert comparisons["planner_regret_against_human_oracle"]["baseline_value"] == 0.162
    assert comparisons["planner_regret_against_human_oracle"]["status"] == "pass"


def test_baseline_comparison_report_can_save_scenario_run_card():
    svc = _build_service()
    project = svc.create_project({"name": "Baseline card project", "region_code": "500227"}, username="tester")
    report = svc.baseline_comparison_report(
        {
            "claim_id": "C1_state_conflict_recall",
            "baseline_id": "manual_gis_overlay_checklist",
            "project_id": project["id"],
            "base_state_version_id": "state-demo",
            "save_run_card": True,
            "twm_case_output_path": "data_agent/test_data/twm_baseline_metrics/twm_case_outputs.csv",
            "baseline_case_output_path": "data_agent/test_data/twm_baseline_metrics/manual_overlay_case_outputs.csv",
        }
    )

    scenario_id = report["scenario_card"]["scenario_id"]
    scenario = svc.repository.get_scenario(scenario_id)
    assert scenario is not None
    assert scenario.project_id == project["id"]
    assert scenario.base_state_version_id == "state-demo"
    assert scenario.scenario_type == "baseline_comparison"
    assert scenario.metadata["kind"] == "baseline_comparison_run_card"
    assert scenario.metadata["baseline_sources"]["twm_case_count"] == 10
    assert scenario.metadata["baseline_sources"]["baseline_case_count"] == 10
    assert scenario.metadata["evidence_gate"]["claim_gate_clear"] is False
    assert scenario.metadata["not_for_production"] is True


def test_baseline_comparison_report_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))
    request = _fake_request(
        "POST",
        json.dumps(
            {
                "claim_id": "C2_audit_defensibility",
                "baseline_id": "rule_only_spatial_compliance_engine",
                "twm_metrics": {"audit_trail_completeness": 0.91},
                "baseline_metrics": {"audit_trail_completeness": 0.82},
            }
        ).encode("utf-8"),
    )

    response = asyncio.run(routes.twm_baseline_comparison_report(request))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.baseline_comparison_report.v1"
    assert body["claim"]["claim_id"] == "C2_audit_defensibility"
    assert body["metric_comparisons"][0]["status"] == "pass"


def test_data_foundation_assessment_states_current_data_boundary():
    svc = _build_service()
    assessment = svc.data_foundation_assessment()

    assert assessment["schema"] == "territory_world_model.data_foundation_assessment.v1"
    assert assessment["status"] == "review"
    assert assessment["landing_readiness"]["engineering_mvp_supported"] is True
    assert assessment["landing_readiness"]["production_deployment_supported"] is False
    assert assessment["validation_snapshot"]["production_ready_observed_history_rows"] == 0
    assert assessment["validation_snapshot"]["production_policy_history_status"] == "not_provided"
    dataset_ids = {item["id"] for item in assessment["datasets"]}
    assert {
        "twm_bishan_demo",
        "twm_bishan_multi_admin_eval",
        "twm_one_map_village_standard_sample",
    }.issubset(dataset_ids)
    multi_admin = next(item for item in assessment["datasets"] if item["id"] == "twm_bishan_multi_admin_eval")
    assert multi_admin["not_for_production"] is True
    assert any(item["path"] == "tables/approval_records.csv" and item["count"] == 90 for item in multi_admin["files"])
    assert multi_admin["map_overlay_readiness"]["status"] == "ready"
    assert multi_admin["map_overlay_readiness"]["blocked_layer_count"] == 0
    assert len(multi_admin["spatial_layer_catalog"]) == 6
    parcel_layer = next(item for item in multi_admin["spatial_layer_catalog"] if item["path"] == "parcel_current.geojson")
    assert parcel_layer["feature_count"] == 21218
    assert parcel_layer["crs_diagnostic"]["status"] == "wgs84_lonlat"
    project_layer = next(item for item in multi_admin["spatial_layer_catalog"] if item["path"] == "synthetic_projects.geojson")
    project_field_names = {field["name"] for field in project_layer["property_fields"]}
    assert project_layer["property_field_count"] >= 30
    assert {"XMMC", "YDMJ", "approval_status"}.issubset(project_field_names)
    assert project_layer["sample_properties"]["XMMC"] == "璧山世界模型合成项目01"
    assert len(project_layer["sample_properties"]) <= 12
    village = next(item for item in assessment["datasets"] if item["id"] == "twm_one_map_village_standard_sample")
    assert village["map_overlay_readiness"]["status"] == "blocked"
    assert "requires_crs_conversion" in village["map_overlay_readiness"]["warning_codes"]
    assert any(item["crs_diagnostic"]["status"] == "projected_or_non_wgs84" for item in village["spatial_layer_catalog"])
    assert any(item["problem"] == "工程 MVP 与回归测试" for item in assessment["supported_problems"])
    assert any(item["claim"] == "生产级审批结论" for item in assessment["unsupported_claims"])
    assert assessment["required_next_data"][0]["priority"] == "P0"
    assert "工程和研究假设验证" in assessment["mentor_answer"]["short_answer"]


def test_data_foundation_map_preview_returns_sampled_geojson_layers():
    svc = _build_service()
    preview = svc.data_foundation_map_preview("twm_bishan_multi_admin_eval", max_features_per_layer=12)

    assert preview["schema"] == "territory_world_model.data_foundation_map_preview.v1"
    assert preview["dataset_id"] == "twm_bishan_multi_admin_eval"
    assert preview["not_for_production"] is True
    assert len(preview["center"]) == 2
    assert preview["bbox"][0] < preview["bbox"][2]
    assert preview["bbox"][1] < preview["bbox"][3]
    layer_names = {layer["name"] for layer in preview["layers"]}
    assert "parcel_current.geojson" in layer_names
    assert "synthetic_projects.geojson" in layer_names
    parcel_layer = next(layer for layer in preview["layers"] if layer["name"] == "parcel_current.geojson")
    assert parcel_layer["source_feature_count"] == 21218
    assert 1 <= parcel_layer["preview_feature_count"] <= 12
    assert parcel_layer["geojson"]["type"] == "FeatureCollection"
    assert len(parcel_layer["geojson"]["features"]) == parcel_layer["preview_feature_count"]


def test_data_foundation_map_preview_reports_wgs84_overlay_readiness():
    svc = _build_service()
    preview = svc.data_foundation_map_preview("twm_bishan_multi_admin_eval", max_features_per_layer=12)

    readiness = preview["map_overlay_readiness"]
    assert readiness["status"] == "ready"
    assert readiness["ready_layer_count"] == preview["layer_count"]
    assert readiness["blocked_layer_count"] == 0
    assert readiness["warning_codes"] == []
    for layer in preview["layers"]:
        diagnostic = layer["crs_diagnostic"]
        assert diagnostic["status"] == "wgs84_lonlat"
        assert diagnostic["coordinate_space"] == "lonlat_degrees"
        assert diagnostic["map_overlay_ready"] is True


def test_data_foundation_map_preview_blocks_projected_coordinate_layers():
    svc = _build_service()
    preview = svc.data_foundation_map_preview("twm_one_map_village_standard_sample", max_features_per_layer=4)

    readiness = preview["map_overlay_readiness"]
    assert readiness["status"] == "blocked"
    assert readiness["blocked_layer_count"] > 0
    assert "requires_crs_conversion" in readiness["warning_codes"]
    projected_layer = next(layer for layer in preview["layers"] if layer["crs_diagnostic"]["status"] == "projected_or_non_wgs84")
    assert projected_layer["crs_diagnostic"]["coordinate_space"] == "projected_or_large_numeric"
    assert projected_layer["crs_diagnostic"]["map_overlay_ready"] is False
    assert projected_layer["crs_diagnostic"]["suggested_action"] == "convert_to_wgs84_before_map_overlay"
    assert projected_layer["bbox"][0] > 1000


def test_data_foundation_map_preview_accepts_full_geojson_layers():
    svc = _build_service()
    preview = svc.data_foundation_map_preview("twm_bishan_multi_admin_eval", max_features_per_layer="all")

    parcel_layer = next(layer for layer in preview["layers"] if layer["name"] == "parcel_current.geojson")
    project_layer = next(layer for layer in preview["layers"] if layer["name"] == "synthetic_projects.geojson")

    assert preview["delivery_mode"] == "full_geojson"
    assert preview["max_features_per_layer"] is None
    assert preview["total_source_feature_count"] == 21603
    assert preview["total_preview_feature_count"] == preview["total_source_feature_count"]
    assert parcel_layer["source_feature_count"] == 21218
    assert parcel_layer["preview_feature_count"] == parcel_layer["source_feature_count"]
    assert len(parcel_layer["geojson"]["features"]) == 21218
    assert project_layer["preview_feature_count"] == project_layer["source_feature_count"]


def test_data_foundation_map_preview_filters_to_requested_layer():
    svc = _build_service()
    preview = svc.data_foundation_map_preview(
        "twm_bishan_multi_admin_eval",
        max_features_per_layer="all",
        layer_path="synthetic_projects.geojson",
    )

    assert preview["delivery_mode"] == "full_geojson"
    assert preview["layer_count"] == 1
    assert preview["total_source_feature_count"] == 90
    assert preview["total_preview_feature_count"] == 90
    assert preview["map_overlay_readiness"]["status"] == "ready"
    assert [layer["name"] for layer in preview["layers"]] == ["synthetic_projects.geojson"]
    layer = preview["layers"][0]
    assert layer["source_feature_count"] == 90
    assert layer["preview_feature_count"] == 90
    assert layer["crs_diagnostic"]["map_overlay_ready"] is True


def test_data_foundation_map_preview_route_returns_layers(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_data_foundation_map_preview(_fake_request(path_params={"dataset_id": "twm_bishan_multi_admin_eval"})))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.data_foundation_map_preview.v1"
    assert body["dataset_id"] == "twm_bishan_multi_admin_eval"
    assert any(layer["name"] == "synthetic_projects.geojson" for layer in body["layers"])


def test_data_foundation_map_preview_route_accepts_all_query(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_data_foundation_map_preview(_fake_request(
        path_params={"dataset_id": "twm_bishan_multi_admin_eval"},
        query_string=b"max_features_per_layer=all",
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["delivery_mode"] == "full_geojson"
    parcel_layer = next(layer for layer in body["layers"] if layer["name"] == "parcel_current.geojson")
    assert parcel_layer["preview_feature_count"] == 21218


def test_data_foundation_map_preview_route_accepts_layer_query(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_data_foundation_map_preview(_fake_request(
        path_params={"dataset_id": "twm_bishan_multi_admin_eval"},
        query_string=b"max_features_per_layer=all&layer=synthetic_projects.geojson",
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["delivery_mode"] == "full_geojson"
    assert body["layer_count"] == 1
    assert body["total_source_feature_count"] == 90
    assert [layer["name"] for layer in body["layers"]] == ["synthetic_projects.geojson"]


def test_data_foundation_layer_detail_returns_fields_and_sample_records():
    svc = _build_service()
    detail = svc.data_foundation_layer_detail("twm_bishan_multi_admin_eval", "synthetic_projects.geojson", sample_limit=3)

    assert detail["schema"] == "territory_world_model.data_foundation_layer_detail.v1"
    assert detail["dataset_id"] == "twm_bishan_multi_admin_eval"
    assert detail["layer_path"] == "synthetic_projects.geojson"
    assert detail["feature_count"] == 90
    assert detail["sample_record_count"] == 3
    assert "geojson" not in detail
    field_names = {field["name"] for field in detail["property_fields"]}
    assert {"XMMC", "YDMJ", "approval_status"}.issubset(field_names)
    assert detail["sample_records"][0]["properties"]["XMMC"] == "璧山世界模型合成项目01"
    assert detail["crs_diagnostic"]["map_overlay_ready"] is True


def test_data_foundation_layer_detail_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_data_foundation_layer_detail(_fake_request(
        path_params={"dataset_id": "twm_bishan_multi_admin_eval"},
        query_string=b"layer=synthetic_projects.geojson&sample_limit=2",
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.data_foundation_layer_detail.v1"
    assert body["layer_path"] == "synthetic_projects.geojson"
    assert body["sample_record_count"] == 2


def test_data_foundation_lineage_report_summarizes_sources_and_readiness():
    svc = _build_service()
    report = svc.data_foundation_lineage_report("twm_bishan_multi_admin_eval")

    assert report["schema"] == "territory_world_model.data_foundation_lineage_report.v1"
    assert report["dataset_id"] == "twm_bishan_multi_admin_eval"
    assert report["lineage_coverage"]["status"] == "review_not_for_production"
    assert report["file_count"] == 11
    assert report["spatial_layer_count"] == 6
    assert report["table_count"] == 5
    assert report["total_record_count"] == 22401
    assert "geojson" not in report

    by_path = {item["path"]: item for item in report["files"]}
    assert by_path["parcel_current.geojson"]["source_role"] == "spatial_layer"
    assert by_path["parcel_current.geojson"]["crs_diagnostic"]["map_overlay_ready"] is True
    assert by_path["tables/approval_records.csv"]["source_role"] == "auxiliary_table"
    assert by_path["tables/approval_records.csv"]["lineage_status"] == "review_not_for_production"
    gate_status = {item["id"]: item["status"] for item in report["readiness_gates"]}
    assert gate_status["production_observed_history"] == "blocked"
    assert gate_status["authoritative_source_lineage"] == "blocked"
    assert report["required_next_data"][0]["priority"] == "P0"


def test_data_foundation_lineage_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_data_foundation_lineage(_fake_request(
        path_params={"dataset_id": "twm_bishan_multi_admin_eval"},
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.data_foundation_lineage_report.v1"
    assert body["dataset_id"] == "twm_bishan_multi_admin_eval"
    assert body["file_count"] == 11


def test_data_foundation_crs_remediation_plan_flags_non_wgs84_layers():
    svc = _build_service()
    plan = svc.data_foundation_crs_remediation_plan("twm_one_map_village_standard_sample")

    assert plan["schema"] == "territory_world_model.data_foundation_crs_remediation_plan.v1"
    assert plan["dataset_id"] == "twm_one_map_village_standard_sample"
    assert plan["status"] == "action_required"
    assert plan["blocked_layer_count"] >= 1
    assert plan["target_crs"] == "EPSG:4326"
    assert "geojson" not in plan
    blocked = [item for item in plan["layers"] if item["status"] == "requires_conversion"]
    assert blocked
    assert blocked[0]["output_policy"]["suffix"] == "_wgs84.geojson"
    assert blocked[0]["conversion_steps"][0]["action"] == "identify_source_crs"
    assert any(step["action"] == "reproject_to_target_crs" for step in blocked[0]["conversion_steps"])


def test_data_foundation_crs_remediation_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_data_foundation_crs_remediation(_fake_request(
        path_params={"dataset_id": "twm_one_map_village_standard_sample"},
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.data_foundation_crs_remediation_plan.v1"
    assert body["status"] == "action_required"


def test_data_foundation_authoritative_templates_define_production_contracts():
    svc = _build_service()
    report = svc.data_foundation_authoritative_templates()

    assert report["schema"] == "territory_world_model.data_foundation_authoritative_templates.v1"
    assert report["status"] == "template_ready_review_only"
    assert report["production_deployment_supported"] is False
    assert report["template_count"] >= 5
    assert "geojson" not in report
    by_id = {item["template_id"]: item for item in report["templates"]}
    assert "parcel_current_authoritative" in by_id
    assert "approval_records_authoritative" in by_id
    assert "policy_action_history_authoritative" in by_id
    assert "geometry" in by_id["parcel_current_authoritative"]["required_fields"]
    assert "final_decision" in by_id["approval_records_authoritative"]["required_fields"]
    assert "action_allowed" in by_id["policy_action_history_authoritative"]["required_fields"]
    assert "custodian_signoff" in report["readiness_gates"][0]["id"]
    assert any("not-for-production" in item for item in report["claim_boundary_notes"])


def test_data_foundation_authoritative_templates_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_data_foundation_authoritative_templates(_fake_request()))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.data_foundation_authoritative_templates.v1"
    assert body["status"] == "template_ready_review_only"


def test_twm_frontend_exposes_roadmap_status_and_layer_detail_drilldown():
    component = Path("frontend/src/components/datapanel/TerritoryWorldModelTab.tsx").read_text()

    assert "/api/twm/roadmap-status" in component
    assert "/api/twm/data-foundation-layer-detail/" in component
    assert "/api/twm/data-foundation-lineage/" in component
    assert "/api/twm/data-foundation-crs-remediation/" in component
    assert "/api/twm/data-foundation-authoritative-templates" in component
    assert "路线图状态" in component
    assert "lineage 报告" in component
    assert "CRS 方案" in component
    assert "权威模板" in component
    assert "字段明细" in component
    assert "样例记录" in component


def test_data_foundation_assessment_route_returns_json(monkeypatch):
    svc = _build_service()
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_data_foundation_assessment(_fake_request()))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.data_foundation_assessment.v1"
    assert body["landing_readiness"]["predictive_or_causal_claim_supported"] is False
    assert body["validation_snapshot"]["synthetic_experiment"]["row_count"] >= 256


def test_twm_toolset_lists_sync_and_long_running_tools():
    from data_agent.toolsets.territory_world_model_tools import TerritoryWorldModelToolset

    toolset = TerritoryWorldModelToolset()
    tools = asyncio.run(toolset.get_tools())
    names = {tool.name for tool in tools}

    assert "twm_status" in names
    assert "twm_roadmap_status" in names
    assert "twm_data_foundation_layer_detail" in names
    assert "twm_data_foundation_lineage" in names
    assert "twm_data_foundation_crs_remediation" in names
    assert "twm_data_foundation_authoritative_templates" in names
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
    assert "twm_farmland_layout_optimization_capability" in names
    assert "twm_farmland_layout_optimization_capability_async" in names
    assert "twm_load_farmland_layout_candidates" in names
    assert "twm_load_farmland_layout_candidates_async" in names
    assert "twm_farmland_layout_optimization_beam_plan" in names
    assert "twm_farmland_layout_optimization_beam_plan_async" in names
    assert "twm_selected_plan_evaluation_bundle" in names
    assert "twm_selected_plan_evaluation_bundle_async" in names
    assert "twm_validation_report" in names
    assert "twm_validation_report_async" in names
    assert "twm_world_model_profile" in names
    assert "twm_world_model_profile_async" in names
    assert "twm_state_contract_report" in names
    assert "twm_state_contract_report_async" in names
    assert "twm_state_snapshot_lakehouse_manifest" in names
    assert "twm_state_snapshot_lakehouse_manifest_async" in names
    assert "twm_materialize_state_snapshot_lakehouse" in names
    assert "twm_materialize_state_snapshot_lakehouse_async" in names
    assert "twm_state_snapshot_lakehouse_publish_plan" in names
    assert "twm_state_snapshot_lakehouse_publish_plan_async" in names
    assert "twm_execute_state_snapshot_lakehouse_publish_plan" in names
    assert "twm_execute_state_snapshot_lakehouse_publish_plan_async" in names
    assert "twm_state_snapshot_lakehouse_spark_submit_bundle" in names
    assert "twm_state_snapshot_lakehouse_spark_submit_bundle_async" in names
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
    assert "twm_dynamics_model_registry_report" in names
    assert "twm_dynamics_model_registry_report_async" in names
    assert "twm_activate_dynamics_model_registry_entry" in names
    assert "twm_activate_dynamics_model_registry_entry_async" in names
    assert "twm_list_dynamics_model_registry_entries" in names
    assert "twm_list_dynamics_model_registry_entries_async" in names
    assert "twm_rollback_dynamics_model_registry" in names
    assert "twm_rollback_dynamics_model_registry_async" in names
    assert "twm_fit_dynamics_candidate" in names
    assert "twm_fit_dynamics_candidate_async" in names
    assert "twm_geofm_ablation_gate" in names
    assert "twm_geofm_ablation_gate_async" in names
    assert "twm_geofm_downstream_experiment_report" in names
    assert "twm_geofm_downstream_experiment_report_async" in names
    assert "twm_causal_calibration_report" in names
    assert "twm_causal_calibration_report_async" in names
    assert "twm_scca_causal_evidence_report" in names
    assert "twm_scca_causal_evidence_report_async" in names


def test_twm_roadmap_status_tool_returns_machine_readable_report(monkeypatch):
    from data_agent.toolsets import territory_world_model_tools as tools

    svc = _build_service()
    monkeypatch.setattr(tools, "get_territory_world_model_service", lambda: svc)

    payload = json.loads(tools.twm_roadmap_status())

    assert payload["schema"] == "territory_world_model.roadmap_status_report.v1"
    assert payload["overall_status"] == "prototype_complete_review_only"
    assert any(item["id"] == "trusted_poc" and item["status"] == "blocked" for item in payload["phases"])


def test_twm_data_foundation_layer_detail_tool_returns_fields(monkeypatch):
    from data_agent.toolsets import territory_world_model_tools as tools

    svc = _build_service()
    monkeypatch.setattr(tools, "get_territory_world_model_service", lambda: svc)

    payload = json.loads(tools.twm_data_foundation_layer_detail("twm_bishan_multi_admin_eval", "synthetic_projects.geojson", sample_limit="2"))

    assert payload["schema"] == "territory_world_model.data_foundation_layer_detail.v1"
    assert payload["sample_record_count"] == 2
    assert any(field["name"] == "approval_status" for field in payload["property_fields"])


def test_twm_data_foundation_lineage_tool_returns_lineage_report(monkeypatch):
    from data_agent.toolsets import territory_world_model_tools as tools

    svc = _build_service()
    monkeypatch.setattr(tools, "get_territory_world_model_service", lambda: svc)

    payload = json.loads(tools.twm_data_foundation_lineage("twm_bishan_multi_admin_eval"))

    assert payload["schema"] == "territory_world_model.data_foundation_lineage_report.v1"
    assert payload["lineage_coverage"]["status"] == "review_not_for_production"
    assert payload["file_count"] == 11


def test_twm_data_foundation_crs_remediation_tool_returns_plan(monkeypatch):
    from data_agent.toolsets import territory_world_model_tools as tools

    svc = _build_service()
    monkeypatch.setattr(tools, "get_territory_world_model_service", lambda: svc)

    payload = json.loads(tools.twm_data_foundation_crs_remediation("twm_one_map_village_standard_sample"))

    assert payload["schema"] == "territory_world_model.data_foundation_crs_remediation_plan.v1"
    assert payload["status"] == "action_required"
    assert payload["blocked_layer_count"] >= 1


def test_twm_data_foundation_authoritative_templates_tool_returns_contracts(monkeypatch):
    from data_agent.toolsets import territory_world_model_tools as tools

    svc = _build_service()
    monkeypatch.setattr(tools, "get_territory_world_model_service", lambda: svc)

    payload = json.loads(tools.twm_data_foundation_authoritative_templates())

    assert payload["schema"] == "territory_world_model.data_foundation_authoritative_templates.v1"
    assert payload["template_count"] >= 5
    assert payload["production_deployment_supported"] is False


def test_twm_dynamics_model_registry_tool_returns_gate_report(monkeypatch):
    from data_agent.toolsets import territory_world_model_tools as tools

    svc = _build_service()
    monkeypatch.setattr(tools, "get_territory_world_model_service", lambda: svc)

    payload = json.loads(tools.twm_dynamics_model_registry_report(
        "state-registry",
        json.dumps({
            "candidate_report": {
                "candidate": {"model_name": "model_a", "model_version": "v1"},
                "evidence_gate": {"status": "pass"},
            },
            "readiness_report": {"status": "review"},
            "evaluation_report": {"evidence_gate": {"status": "review"}},
        }),
    ))

    assert payload["schema"] == "territory_world_model.dynamics_model_registry_report.v1"
    assert payload["registry_entry"]["registry_key"] == "model_a:v1"
    assert payload["promotion_decision"] == "review_only_not_promoted"


def test_twm_dynamics_model_registry_routes_expose_activation_listing_and_rollback(monkeypatch):
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    activate_resp = asyncio.run(routes.twm_activate_dynamics_model_registry_entry(_fake_request(
        "POST",
        b"{}",
        path_params={"id": state.id},
    )))
    activate_body = json.loads(activate_resp.body)
    list_resp = asyncio.run(routes.twm_dynamics_model_registry_entries(_fake_request(
        "POST",
        b'{"status":"review_only"}',
        path_params={"id": state.id},
    )))
    list_body = json.loads(list_resp.body)
    rollback_resp = asyncio.run(routes.twm_rollback_dynamics_model_registry(_fake_request(
        "POST",
        b"{}",
        path_params={"id": state.id},
    )))
    rollback_body = json.loads(rollback_resp.body)

    assert activate_resp.status_code == 200
    assert activate_body["schema"] == "territory_world_model.dynamics_model_registry_activation.v1"
    assert activate_body["status"] == "review_only"
    assert list_resp.status_code == 200
    assert list_body["schema"] == "territory_world_model.dynamics_model_registry_entries.v1"
    assert list_body["entries"][0]["status"] == "review_only"
    assert rollback_resp.status_code == 200
    assert rollback_body["schema"] == "territory_world_model.dynamics_model_registry_rollback.v1"
    assert rollback_body["status"] == "blocked"
    assert "active_registry_entry" in rollback_body["missing"]


def test_twm_state_snapshot_lakehouse_manifest_route_returns_storage_contract(monkeypatch):
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_state_snapshot_lakehouse_manifest(_fake_request(
        "POST",
        b'{"lakehouse_uri":"s3://gis-agent-lakehouse","namespace":"twm_prod","include_vector_sidecar":true}',
        path_params={"id": state.id},
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.state_snapshot_lakehouse_manifest.v1"
    assert body["storage"]["table_format"] == "iceberg"
    assert body["storage"]["vector_sidecar"]["format"] == "lance"
    assert body["artifacts"]["state_objects"]["table"] == "twm_prod.state_objects"
    assert body["artifacts"]["state_objects"]["format"] == "geoparquet"


def test_twm_state_snapshot_lakehouse_materialization_route_writes_parquet(tmp_path, monkeypatch):
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_materialize_state_snapshot_lakehouse(_fake_request(
        "POST",
        json.dumps({"lakehouse_uri": tmp_path.as_uri(), "namespace": "twm_prod"}).encode("utf-8"),
        path_params={"id": state.id},
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.state_snapshot_lakehouse_materialization.v1"
    assert body["written_artifact_count"] >= 7
    assert Path(body["artifacts"]["state_objects"]["local_path"]).exists()
    assert body["readiness"]["local_parquet_written"] is True


def test_twm_state_snapshot_lakehouse_publish_plan_route_returns_iceberg_and_sedona_specs(tmp_path, monkeypatch):
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)
    materialization = svc.materialize_state_snapshot_lakehouse(
        state.id,
        {"lakehouse_uri": tmp_path.as_uri(), "namespace": "twm_prod"},
    )
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_state_snapshot_lakehouse_publish_plan(_fake_request(
        "POST",
        json.dumps({
            "materialization": materialization,
            "catalog": "prod",
            "namespace": "twm_prod",
            "warehouse_uri": "s3://gis-agent-lakehouse/warehouse/iceberg",
        }).encode("utf-8"),
        path_params={"id": state.id},
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.state_snapshot_lakehouse_publish_plan.v1"
    assert body["iceberg_publish_specs"][0]["schema"] == "territory_world_model.iceberg_artifact_publish_spec.v1"
    assert any(item["schema"] == "territory_world_model.sedona_spatial_index_job.v1" for item in body["sedona_spatial_index_specs"])
    assert body["validation_gates"]["publish_spec_gate"]["status"] == "pass"


def test_twm_state_snapshot_lakehouse_execute_route_blocks_without_executor(monkeypatch):
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_execute_state_snapshot_lakehouse_publish_plan(_fake_request(
        "POST",
        b'{"catalog":"prod","namespace":"twm_prod"}',
        path_params={"id": state.id},
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.state_snapshot_lakehouse_publish_execution.v1"
    assert body["status"] == "blocked"
    assert body["validation_gates"]["spark_executor_gate"]["missing"] == ["executor"]
    assert body["publish_plan"]["schema"] == "territory_world_model.state_snapshot_lakehouse_publish_plan.v1"


def test_twm_state_snapshot_lakehouse_spark_submit_bundle_route_returns_command(tmp_path, monkeypatch):
    svc = _build_service()
    _project, state = _save_lightweight_twm_state(svc)
    monkeypatch.setattr(routes, "get_territory_world_model_service", lambda: svc)
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: SimpleNamespace(identifier="tester", metadata={"role": "analyst"}))

    response = asyncio.run(routes.twm_state_snapshot_lakehouse_spark_submit_bundle(_fake_request(
        "POST",
        json.dumps({
            "lakehouse_uri": tmp_path.joinpath("lake").as_uri(),
            "namespace": "twm_prod",
            "catalog": "prod",
            "warehouse_uri": "s3://gis-agent-lakehouse/warehouse/iceberg",
            "output_dir": str(tmp_path / "bundle"),
            "spark_master": "local[2]",
        }).encode("utf-8"),
        path_params={"id": state.id},
    )))
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["schema"] == "territory_world_model.state_snapshot_lakehouse_spark_submit_bundle.v1"
    assert body["spark_submit"]["command"][0] == "spark-submit"
    assert Path(body["plan_path"]).exists()
    assert Path(body["executor_script"]).exists()


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

    registry_req = _fake_request(
        "POST",
        json.dumps({
            "candidate_report": {
                "candidate": {"model_name": "route_candidate", "model_version": "v1"},
                "evidence_gate": {"status": "pass"},
            },
            "readiness_report": readiness_payload,
            "evaluation_report": eval_payload,
        }).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    registry_resp = asyncio.run(routes.twm_dynamics_model_registry_report(registry_req))
    assert registry_resp.status_code == 200
    registry_payload = json.loads(registry_resp.body)
    assert registry_payload["schema"] == "territory_world_model.dynamics_model_registry_report.v1"
    assert registry_payload["registry_entry"]["registry_key"] == "route_candidate:v1"

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

    capability_req = _fake_request(
        "POST",
        json.dumps(
            {
                "candidate_actions": [
                    {"candidate_id": "route-a", "action_type": "inspect", "target_role": "project"},
                    {"candidate_id": "route-b", "action_type": "protect", "target_role": "project"},
                ]
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    capability_resp = asyncio.run(routes.twm_farmland_layout_optimization_capability(capability_req))
    assert capability_resp.status_code == 200
    capability_payload = json.loads(capability_resp.body)
    assert capability_payload["schema"] == "territory_world_model.farmland_layout_optimization_capability_report.v1"
    assert capability_payload["planner_contract"]["role"] == "consumer_and_auditor_of_candidate_layout_plans"

    candidates_req = _fake_request(
        "POST",
        json.dumps({"optimization_dir": str(OPTIMIZATION_DIR)}).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    candidates_resp = asyncio.run(routes.twm_farmland_layout_candidates(candidates_req))
    assert candidates_resp.status_code == 200
    candidates_payload = json.loads(candidates_resp.body)
    assert candidates_payload["schema"] == "territory_world_model.farmland_layout_candidate_actions_from_optimization_bundle.v1"
    assert candidates_payload["summary"]["candidate_count"] == 7

    optimization_beam_req = _fake_request(
        "POST",
        json.dumps({"optimization_dir": str(OPTIMIZATION_DIR), "evidence_coverage": 0.8}).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    optimization_beam_resp = asyncio.run(routes.twm_farmland_layout_optimization_beam_plan(optimization_beam_req))
    assert optimization_beam_resp.status_code == 200
    optimization_beam_payload = json.loads(optimization_beam_resp.body)
    assert optimization_beam_payload["schema"] == "territory_world_model.farmland_layout_optimization_beam_plan_report.v1"
    assert optimization_beam_payload["selection_audit"]["selected_from_legal_feasible_space"] is True

    selected_bundle_req = _fake_request(
        "POST",
        json.dumps({"optimization_dir": str(OPTIMIZATION_DIR), "horizon": 2, "evidence_coverage": 0.8}).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    selected_bundle_resp = asyncio.run(routes.twm_selected_plan_evaluation_bundle(selected_bundle_req))
    assert selected_bundle_resp.status_code == 200
    selected_bundle_payload = json.loads(selected_bundle_resp.body)
    assert selected_bundle_payload["schema"] == "territory_world_model.selected_plan_evaluation_bundle.v1"
    assert selected_bundle_payload["planning"]["selection_audit"]["selected_from_legal_feasible_space"] is True
    assert selected_bundle_payload["counterfactual_rollout"]["horizon"] == 2
    assert selected_bundle_payload["validation_report"]["summary"]["stage_count"] == 6

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
    assert state_contract_payload["claim_ladder"]["schema"] == "territory_world_model.claim_ladder.v1"

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

    scca_req = _fake_request(
        "POST",
        json.dumps(
            {
                "scca_result": {
                    "case_id": "route_scca",
                    "row_count": 88,
                    "credibility_decision": "strong_support",
                    "evidence_grade": "core_support",
                    "effect_estimates": [
                        {"estimator": "spatial_neighbor_adjusted_ols", "coef": 0.06, "p_value": 0.04}
                    ],
                    "spatial_diagnostics": {"residual_moran": {"moran_i": 0.02}},
                }
            }
        ).encode("utf-8"),
        path_params={"id": state["state_version"]["id"]},
    )
    scca_resp = asyncio.run(routes.twm_scca_causal_evidence_report(scca_req))
    assert scca_resp.status_code == 200
    scca_payload = json.loads(scca_resp.body)
    assert scca_payload["schema"] == "territory_world_model.scca_causal_evidence_report.v1"
    assert scca_payload["status"] == "pass"
