import json
from pathlib import Path

from data_agent.uwm.energy_regularized_planner import (
    UWM_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA,
    plan_with_energy_regularized_action_sequences,
)
from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.livability_graph_mdp_env import build_livability_graph_mdp_env
from data_agent.uwm.model_based_rl import build_admin_livability_graph_observation
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _real_data_env():
    observation = build_admin_livability_graph_observation(
        _read_json(
            DATA_ROOT
            / "admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
        ),
        observation_id="admin-livability-energy-planner-real-data-test",
        created_at="2026-07-07T21:00:00Z",
        max_units=36,
        admin_spatial_graph=_read_json(
            DATA_ROOT
            / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
        ),
    )
    return build_livability_graph_mdp_env(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "energy_regularized_heat_pollution_service_stress",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        horizon=2,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        mechanism_table=_read_json(
            DATA_ROOT
            / "data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json"
        ),
        spatial_spillover_kernel=_read_json(
            DATA_ROOT
            / "data_calibrated_spatial_spillover_kernel_2026_07_07/uwm_data_calibrated_spatial_spillover_kernel.json"
        ),
        air_quality_uncertainty_context=_read_json(
            DATA_ROOT
            / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
        ),
    )


def test_energy_regularized_planner_uses_real_graph_mdp_and_beats_static_baseline():
    report = plan_with_energy_regularized_action_sequences(
        _real_data_env(),
        graph_drl_training_report=_read_json(
            DATA_ROOT
            / "livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json"
        ),
        report_id="uwm-energy-regularized-planner-real-data-test",
        created_at="2026-07-07T21:05:00Z",
        top_k_per_step=12,
        energy_weight=0.00035,
        ood_penalty_weight=0.00055,
    )

    assert report["schema"] == UWM_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA
    assert report["planner_algorithm"]["algorithm"] == (
        "energy_regularized_model_based_action_sequence_planner"
    )
    assert report["planner_algorithm"]["uses_behavior_prior_energy"] is True
    assert report["planner_algorithm"]["uses_ood_action_drift_guard"] is True
    assert report["planner_algorithm"]["is_model_based"] is True

    data = report["real_data_graph_mdp_summary"]
    assert data["real_data_graph_node_count"] == 36
    assert data["real_data_graph_edge_count"] == 96
    assert data["real_data_available_action_count"] == 60
    assert data["spatial_spillover_directional_edge_count"] == 227

    selected = report["selected_sequence"]
    static = report["traditional_static_baseline"]
    assert selected["action_count"] == 2
    assert selected["raw_cumulative_reward"] > static["cumulative_reward"]
    assert selected["advantage_over_traditional_static"] > 0
    assert selected["mean_behavior_energy"] <= report["behavior_prior"]["energy_threshold"]
    assert selected["ood_action_drift"] <= 0.0

    audit = report["conservative_search_audit"]
    assert audit["evaluated_sequence_count"] > 100
    assert audit["raw_best_sequence_raw_reward"] >= selected["raw_cumulative_reward"]
    assert audit["selected_sequence_energy"] <= audit["energy_threshold"]
    assert audit["planner_exploitation_guard_passed"] is True

    alignment = report["search_value_alignment"]
    assert alignment["graph_dqn_report_available"] is True
    assert alignment["graph_dqn_holdout_win_rate_vs_train_mean"] > 0.9
    assert alignment["selected_sequence_reward_beats_traditional_static"] is True
    assert alignment["search_value_alignment_ready"] is True

    assert report["supported_claim"] == (
        "energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static"
    )
    assert report["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False
    assert "observed_policy_outcome_holdout_required" in report["remaining_gates"]


def test_evidence_gate_tracks_energy_regularized_planner_without_policy_outcome_claim():
    gate = build_uwm_data_foundation_evidence_gate(
        manifest_path=ROOT / "docs/reports/uwm_data_foundation_manifest.csv",
        openaq_temporal_benchmark_path=DATA_ROOT
        / "openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json",
        tap_external_dynamics_path=DATA_ROOT
        / "tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json",
        learned_rollout_path=DATA_ROOT
        / "model_based_rl_graph_search_2026_07_05/uwm_offline_world_model_rollout_planner_admin_livability_spatial_graph_proxy.json",
        livability_intervention_package_path=DATA_ROOT
        / "model_based_rl_graph_search_2026_07_05/uwm_livability_intervention_package_admin_livability_spatial_graph.json",
        local_planning_inventory_path=DATA_ROOT
        / "local_planning_zip_audit_2026_07_05/uwm_local_planning_zip_inventory.csv",
        admin_spatial_graph_path=DATA_ROOT
        / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json",
        data_calibrated_planner_replay_path=DATA_ROOT
        / "data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json",
        livability_graph_drl_training_report_path=DATA_ROOT
        / "livability_graph_drl_training_2026_07_07/uwm_livability_graph_drl_training_report.json",
        energy_regularized_planner_report_path=DATA_ROOT
        / "energy_regularized_planner_2026_07_07/uwm_energy_regularized_planner_report.json",
        gate_id="uwm-data-foundation-energy-planner-gate-test",
        created_at="2026-07-07T21:10:00Z",
    )

    planner = gate["evidence_slices"]["energy_regularized_planner"]
    assert planner["energy_regularized_planner_ready"] is True
    assert planner["evaluated_sequence_count"] == 756
    assert planner["advantage_over_traditional_static"] > 0
    assert planner["selected_sequence_energy"] <= planner["energy_threshold"]
    assert planner["selected_sequence_ood_action_drift"] <= 0.0
    assert planner["planner_exploitation_guard_passed"] is True
    assert planner["search_value_alignment_ready"] is True
    assert planner["observed_policy_outcome_superiority_claim"] is False
    assert "energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static" in {
        claim["claim"] for claim in gate["supported_claims"]
    }

    readiness = build_world_model_evidence_readiness(gate)
    planner_evidence = readiness["architecture_evidence"]["planner"]
    assert planner_evidence["energy_regularized_planner_ready"] is True
    assert planner_evidence["energy_regularized_exploitation_guard_passed"] is True
    assert planner_evidence["energy_regularized_search_value_alignment_ready"] is True
    assert readiness["empirical_superiority_claim"] is False
