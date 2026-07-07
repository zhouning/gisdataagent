import json
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.external_observed_holdout import (
    UWM_EXTERNAL_OBSERVED_HOLDOUT_SUITE_SCHEMA,
    build_uwm_external_observed_holdout_suite,
    validate_uwm_external_observed_holdout_suite,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
OPENAQ_TEMPORAL_BENCHMARK_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json"
)
TAP_GRIDDED_TEMPORAL_BENCHMARK_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06/tap_gridded_temporal_benchmark.json"
)


def _build_real_external_suite() -> dict:
    return build_uwm_external_observed_holdout_suite(
        openaq_temporal_benchmark_path=OPENAQ_TEMPORAL_BENCHMARK_PATH,
        tap_gridded_temporal_benchmark_path=TAP_GRIDDED_TEMPORAL_BENCHMARK_PATH,
        suite_id="uwm-external-observed-holdout-suite-real-test",
        created_at="2026-07-06T13:10:00Z",
    )


def test_external_observed_holdout_suite_requires_two_real_holdouts_without_policy_claim():
    suite = _build_real_external_suite()

    assert suite["schema"] == UWM_EXTERNAL_OBSERVED_HOLDOUT_SUITE_SCHEMA
    assert validate_uwm_external_observed_holdout_suite(suite) == {
        "valid": True,
        "errors": [],
    }
    assert suite["external_observed_holdout_ready"] is True
    assert suite["external_observed_state_prediction_superiority_claim"] is True
    assert suite["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert suite["observed_policy_outcome_superiority_claim"] is False
    assert suite["empirical_superiority_claim"] is False
    assert suite["claim_boundary"]["max_claim_level"] == "bounded_support"

    openaq = suite["holdout_sources"]["openaq_station_temporal_holdout"]
    assert openaq["source_artifact_exists"] is True
    assert openaq["observation_count"] == 600
    assert openaq["holdout_count"] == 180
    assert openaq["overall_holdout_win_count"] == 150
    assert openaq["overall_holdout_win_rate"] == 0.833333
    assert openaq["best_dynamic_pm25_mae"] == 2.4
    assert openaq["best_static_pm25_mae"] == 9.466667
    assert openaq["temporal_order_negative_control_passed"] is True

    tap = suite["holdout_sources"]["tap_gridded_temporal_holdout"]
    assert tap["source_artifact_exists"] is True
    assert tap["series_count"] == 10000
    assert tap["holdout_count"] == 40000
    assert tap["best_uwm_method"] == "adaptive_online_state_update"
    assert tap["best_uwm_mae"] == 7.01169
    assert tap["best_static_baseline_mae"] == 9.309192
    assert tap["series_beats_all_traditional_static_baselines_rate"] == 0.6318
    assert tap["temporal_order_negative_control_passed"] is True

    assert "not_policy_intervention_outcome" in suite["limitations"]
    assert "openaq_not_scene_aligned_to_2024_policy_window" in suite["limitations"]
    assert "tap_gridded_product_not_station_observation" in suite["limitations"]
    supported_claims = {claim["claim"]: claim for claim in suite["supported_claims"]}
    claim = supported_claims[
        "external_observed_state_prediction_advantage_over_static_baseline_suite"
    ]
    assert claim["policy_outcome_claim"] is False
    assert claim["claim_level"] == "bounded_support"


def test_data_foundation_gate_closes_external_holdout_only_after_real_external_suite(
    tmp_path: Path,
):
    suite = _build_real_external_suite()
    suite_path = tmp_path / "uwm_external_observed_holdout_suite.json"
    suite_path.write_text(json.dumps(suite), encoding="utf-8")

    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=OPENAQ_TEMPORAL_BENCHMARK_PATH,
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
        external_observed_holdout_suite_path=suite_path,
        gate_id="uwm-data-foundation-evidence-gate-real-external-holdout-test",
        created_at="2026-07-06T13:15:00Z",
    )

    external = gate["evidence_slices"]["external_observed_holdout_suite"]
    assert external["source_artifact_exists"] is True
    assert external["external_observed_holdout_ready"] is True
    assert external["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert gate["external_observed_state_prediction_superiority_claim"] is True
    assert "external_observed_holdout_required" not in gate["remaining_gates"]
    assert "scene_aligned_station_calibrated_air_quality_holdout_required" in gate["remaining_gates"]
    assert "observed_policy_outcome_required" in gate["remaining_gates"]
    assert gate["observed_policy_outcome_superiority_claim"] is False
    assert gate["empirical_superiority_claim"] is False

    readiness = build_world_model_evidence_readiness(gate)
    external_arch = readiness["architecture_evidence"]["external_observed_holdout"]
    assert external_arch["ready"] is True
    assert external_arch["claim_level"] == "bounded_support"
    assert "collect_observed_policy_outcome_validation_data" in readiness["next_actions"]
    assert "build_scene_aligned_station_calibrated_air_quality_holdout" in readiness["next_actions"]
