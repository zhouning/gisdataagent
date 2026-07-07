import json
from pathlib import Path

import pytest

from data_agent.uwm.causal_policy_evidence import (
    UWM_CAUSAL_POLICY_EVIDENCE_GATE_SCHEMA,
    build_uwm_causal_policy_evidence_gate,
    validate_uwm_causal_policy_evidence_gate,
)
from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
PAPER6_RESULTS_ROOT = (
    ROOT.parent
    / "paper6-spatial-causal-inference/paper/ijgis_submission_20260605/07_results"
)


def _require_paper6_results_root() -> Path:
    if not PAPER6_RESULTS_ROOT.exists():
        pytest.skip(f"paper6 real result artifacts are missing: {PAPER6_RESULTS_ROOT}")
    return PAPER6_RESULTS_ROOT


def _build_real_paper6_gate() -> dict:
    return build_uwm_causal_policy_evidence_gate(
        paper6_results_root=_require_paper6_results_root(),
        gate_id="uwm-causal-policy-evidence-real-paper6-test",
        created_at="2026-07-06T11:40:00Z",
    )


def test_causal_policy_evidence_gate_reads_paper6_real_artifacts_without_policy_claim():
    gate = _build_real_paper6_gate()

    assert gate["schema"] == UWM_CAUSAL_POLICY_EVIDENCE_GATE_SCHEMA
    assert validate_uwm_causal_policy_evidence_gate(gate) == {
        "valid": True,
        "errors": [],
    }
    assert gate["algorithmic_causal_diagnostic_ready"] is True
    assert gate["observed_local_policy_outcome_ready"] is False
    assert gate["observed_policy_outcome_superiority_claim"] is False
    assert gate["empirical_superiority_claim"] is False
    assert gate["claim_boundary"]["max_claim_level"] == "bounded_support"

    arcgis = gate["evidence_slices"]["arcgis_sci_plus_county"]
    assert arcgis["source_artifact_exists"] is True
    assert arcgis["study"] == "county_social_capital_longevity_validation"
    assert arcgis["input_rows"] == 3108
    assert arcgis["trimmed_rows"] == 3044
    assert arcgis["erf_grid_count"] == 200
    assert arcgis["arcgis_native_parity_ready"] is True
    assert arcgis["arcgis_version"] == "3.7"
    assert arcgis["tested_mode"] == "REGRESSION propensity scores + MATCHING balance + PLUG_IN bandwidth + NO_CI"
    assert arcgis["arcgis_erf_response_mae"] == pytest.approx(0.015153286175193017)
    assert arcgis["sample_parity"]["arcgis_final_n"] == 3044
    assert arcgis["sample_parity"]["open_final_n"] == 3044
    assert arcgis["parameter_parity"]["arcgis_selected_num_bins"] == 25
    assert arcgis["parameter_parity"]["open_selected_num_bins"] == 25
    assert arcgis["selected_passes_balance_threshold"] is True
    assert arcgis["provenance_field_count"] == 19
    assert "UnemployRate" in arcgis["unresolved_fields"]
    assert arcgis["spatial_risk_status"] == "unavailable"

    scca = gate["evidence_slices"]["scca_county_social_capital"]
    assert scca["source_artifact_exists"] is True
    assert scca["decision"] == "strong_support"
    assert scca["leave_group_sign_stable"] is True
    assert scca["estimator_statuses"]["baseline_adjusted_ols"] == "ok"
    assert scca["estimator_statuses"]["generalized_propensity_erf"] == "ok"

    chongqing = gate["evidence_slices"]["chongqing_uhi_analysis"]
    assert chongqing["source_artifact_exists"] is True
    assert chongqing["study"] == "Building density -> UHI in Chongqing"
    assert chongqing["sample_size"] == 5000
    assert chongqing["buildings_total"] == 107035
    assert chongqing["balance_interpretation"] == "credible_balance"
    assert chongqing["outcome_product"] == "MODIS MOD11A2 summer LST (~1 km)"

    assert "not_observed_intervention_outcome" in gate["limitations"]
    assert "third_party_county_demo_data_not_chongqing_policy_outcome" in gate["limitations"]
    assert "provided_chongqing_analysis_sample_not_policy_intervention" in gate["limitations"]
    supported_claims = {claim["claim"]: claim for claim in gate["supported_claims"]}
    diagnostic_claim = supported_claims[
        "paper6_arcgis_sci_plus_real_artifact_causal_diagnostic_ready"
    ]
    assert diagnostic_claim["policy_outcome_claim"] is False
    assert diagnostic_claim["claim_level"] == "bounded_support"


def test_data_foundation_gate_uses_real_paper6_causal_diagnostic_but_keeps_outcome_gate(
    tmp_path: Path,
):
    causal_gate = _build_real_paper6_gate()
    causal_gate_path = tmp_path / "uwm_causal_policy_evidence_gate.json"
    causal_gate_path.write_text(json.dumps(causal_gate), encoding="utf-8")

    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json",
        tap_external_dynamics_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        learned_rollout_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=ROOT
        / "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        causal_policy_evidence_path=causal_gate_path,
        gate_id="uwm-data-foundation-evidence-gate-real-causal-test",
        created_at="2026-07-06T11:45:00Z",
    )

    causal = gate["evidence_slices"]["causal_policy_effect_validation"]
    assert causal["source_artifact_exists"] is True
    assert causal["algorithmic_causal_diagnostic_ready"] is True
    assert causal["observed_local_policy_outcome_ready"] is False
    assert "causal_policy_effect_validation_required" not in gate["remaining_gates"]
    assert "observed_policy_outcome_required" in gate["remaining_gates"]
    assert gate["observed_policy_outcome_superiority_claim"] is False
    assert gate["empirical_superiority_claim"] is False
    assert any(
        claim["claim"] == "paper6_arcgis_sci_plus_real_artifact_causal_diagnostic_ready"
        and claim["policy_outcome_claim"] is False
        for claim in gate["supported_claims"]
    )

    readiness = build_world_model_evidence_readiness(gate)
    causal_arch = readiness["architecture_evidence"]["causal_policy_evidence"]
    policy_eval = readiness["architecture_evidence"]["policy_outcome_evaluator"]
    assert causal_arch["ready"] is True
    assert causal_arch["claim_level"] == "bounded_support"
    assert policy_eval["ready"] is False
    assert policy_eval["causal_policy_diagnostic_ready"] is True
    assert "design_causal_policy_effect_validation" not in readiness["next_actions"]
    assert "collect_observed_policy_outcome_validation_data" in readiness["next_actions"]
