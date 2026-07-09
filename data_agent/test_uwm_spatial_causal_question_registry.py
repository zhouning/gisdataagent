import json
from pathlib import Path

from data_agent.uwm.spatial_causal_question_registry import (
    UWM_SPATIAL_CAUSAL_QUESTION_REGISTRY_SCHEMA,
    build_uwm_spatial_causal_question_registry,
    validate_uwm_spatial_causal_question_registry,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_registry() -> dict:
    return build_uwm_spatial_causal_question_registry(
        registry_id="uwm-spatial-causal-question-registry-test",
        created_at="2026-07-09T09:15:00Z",
        production_action_catalog=_read_json(
            DATA_ROOT
            / "production_action_catalog_2026_07_08/uwm_production_action_catalog.json"
        ),
        governance_data_contract=_read_json(
            DATA_ROOT
            / "production_governance_data_contract_2026_07_08/uwm_production_governance_data_contract.json"
        ),
        causal_policy_evidence_gate=_read_json(
            DATA_ROOT
            / "causal_policy_evidence_2026_07_06/uwm_causal_policy_evidence_gate.json"
        ),
        data_foundation_evidence_gate=_read_json(
            DATA_ROOT
            / "data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json"
        ),
    )


def test_spatial_causal_question_registry_defines_do_queries_without_policy_claims():
    registry = _build_registry()

    assert registry["schema"] == UWM_SPATIAL_CAUSAL_QUESTION_REGISTRY_SCHEMA
    assert registry["experiment_scope"] == "full_admin_graph"
    assert registry["registry_ready"] is True
    assert registry["algorithmic_causal_diagnostic_ready"] is True
    assert registry["observed_outcome_panel_ready"] is False
    assert registry["causal_effect_calibration_ready"] is False
    assert registry["planner_governance_binding_ready"] is False
    assert registry["observed_policy_outcome_superiority_claim"] is False
    assert registry["empirical_superiority_claim"] is False
    assert registry["production_readiness_claim"] is False
    assert validate_uwm_spatial_causal_question_registry(registry) == {
        "valid": True,
        "errors": [],
    }

    summary = registry["summary"]
    assert summary["production_action_type_count"] == 57
    assert summary["currently_bound_action_type_count"] == 3
    assert summary["currently_bound_feasible_action_count"] == 1137
    assert summary["active_causal_question_count"] == 3
    assert summary["authoritative_required_table_count"] == 5
    assert summary["ready_authoritative_table_count"] == 0
    assert summary["identified_policy_effect_question_count"] == 0
    assert summary["underidentified_policy_effect_question_count"] == 3

    questions = {
        question["action_type"]: question
        for question in registry["causal_question_contracts"]
    }
    assert set(questions) == {
        "increase_green_infrastructure",
        "traffic_emission_control",
        "add_community_service",
    }

    green = questions["increase_green_infrastructure"]
    assert green["query_type"] == "intervention_effect"
    assert green["causal_query"] == (
        "P(heat_risk, livability | do(increase_green_infrastructure), spatial_context)"
    )
    assert green["treatment"]["action_type"] == "increase_green_infrastructure"
    assert green["outcomes"]["primary_outcome"] == "heat_risk"
    assert "livability" in green["outcomes"]["secondary_outcomes"]
    assert "baseline_heat_risk" in green["adjustment_set"]["confounders"]
    assert "green_accessibility_change" in green["mechanism_path"]["mediators"]
    assert green["estimand_contract"]["target_estimand"] == "ATT_on_eligible_admin_units"
    assert green["identification"]["status"] == "underidentified_for_observed_policy_effect"
    assert green["identification"]["allowed_current_query_level"] == (
        "conditional_simulation_with_algorithmic_causal_diagnostic"
    )
    assert green["required_authoritative_tables"] == [
        "policy_project_history",
        "action_constraint_cost_model",
        "observed_outcome_validation_panel",
        "causal_effect_calibration_panel",
        "human_governance_review_log",
    ]
    assert "negative_control_no_effect_on_unrelated_outcome" in green[
        "testable_implications"
    ]
    assert green["policy_outcome_claim_allowed"] is False

    air = questions["traffic_emission_control"]
    assert air["outcomes"]["primary_outcome"] == "air_pollution_exposure"
    assert "meteorology" in air["adjustment_set"]["confounders"]
    assert "traffic_emission_intensity_change" in air["mechanism_path"]["mediators"]

    service = questions["add_community_service"]
    assert service["outcomes"]["primary_outcome"] == "service_accessibility"
    assert "population_need" in service["adjustment_set"]["confounders"]
    assert "service_capacity_change" in service["mechanism_path"]["mediators"]

    assert registry["claim_boundary"]["max_claim_level"] == (
        "spatial_causal_question_contract_only"
    )
    assert "observed_policy_outcome_validation_panel_required" in registry[
        "remaining_gates"
    ]


def test_spatial_causal_question_registry_validation_rejects_overclaims():
    registry = _build_registry()
    registry["observed_policy_outcome_superiority_claim"] = True
    registry["causal_question_contracts"][0]["policy_outcome_claim_allowed"] = True
    registry["causal_question_contracts"][0]["identification"]["status"] = "identified"

    validation = validate_uwm_spatial_causal_question_registry(registry)

    assert validation["valid"] is False
    assert "observed_policy_outcome_superiority_claim_must_be_false" in validation[
        "errors"
    ]
    assert "question_policy_outcome_claim_must_be_false" in validation["errors"]
    assert "identified_status_requires_observed_outcome_and_calibration" in validation[
        "errors"
    ]


def test_spatial_causal_question_registry_artifact_is_rebuilt_with_no_fake_rows():
    registry = _read_json(ARTIFACT_PATH)

    assert registry["schema"] == UWM_SPATIAL_CAUSAL_QUESTION_REGISTRY_SCHEMA
    assert registry["summary"]["active_causal_question_count"] == 3
    assert registry["summary"]["currently_bound_feasible_action_count"] == 1137
    assert registry["summary"]["ready_authoritative_table_count"] == 0
    assert registry["summary"]["identified_policy_effect_question_count"] == 0
    assert registry["observed_policy_outcome_superiority_claim"] is False
    assert registry["empirical_superiority_claim"] is False
