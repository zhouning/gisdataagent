import json
import ast
import inspect
from pathlib import Path

from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.full_admin_energy_regularized_planner import (
    UWM_FULL_ADMIN_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA,
    plan_full_admin_energy_regularized_action_sequences,
)
from data_agent.uwm.livability_data_catalog import build_uwm_livability_data_catalog
from data_agent.uwm.livability_graph_mdp_env import build_livability_graph_mdp_env
from data_agent.uwm.model_based_rl import build_admin_livability_graph_observation


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ARTIFACT_PATH = (
    DATA_ROOT
    / "energy_regularized_planner_full_admin_graph_2026_07_08/uwm_full_admin_graph_energy_regularized_planner_report.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _full_admin_env():
    panel = _read_json(
        DATA_ROOT
        / "admin_livability_target_full_admin_graph_2024_07_2026_07_08/uwm_admin_livability_target_full_admin_graph_panel.json"
    )
    admin_graph = _read_json(
        DATA_ROOT / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
    )
    geographic_similarity = _read_json(
        DATA_ROOT
        / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
    )
    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-full-admin-energy-planner-test",
        created_at="2026-07-08T19:30:00Z",
        admin_spatial_graph=admin_graph,
        geographic_similarity_kernel=geographic_similarity,
    )
    return build_livability_graph_mdp_env(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "full_admin_energy_regularized_heat_pollution_service_stress",
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
            / "data_calibrated_mechanism_table_full_admin_graph_2026_07_08/uwm_full_admin_graph_data_calibrated_mechanism_table.json"
        ),
        air_quality_uncertainty_context=_read_json(
            DATA_ROOT
            / "scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
        ),
    )


def test_full_admin_energy_regularized_planner_uses_full_graph_and_beats_static():
    report = plan_full_admin_energy_regularized_action_sequences(
        _full_admin_env(),
        graph_drl_training_report=_read_json(
            DATA_ROOT
            / "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json"
        ),
        geographic_similarity_kernel=_read_json(
            DATA_ROOT
            / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
        ),
        report_id="uwm-full-admin-energy-regularized-planner-test",
        created_at="2026-07-08T19:35:00Z",
        top_k_per_step=16,
        energy_weight=0.00035,
        ood_penalty_weight=0.00055,
    )

    assert report["schema"] == UWM_FULL_ADMIN_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA
    assert report["experiment_scope"] == "full_admin_graph"
    assert report["full_data_guard"]["passed"] is True
    assert report["full_data_guard"]["graph_node_count"] == 1017
    assert report["full_data_guard"]["graph_edge_count"] == 7932
    assert report["full_data_guard"]["available_action_count"] == 1137
    assert report["full_data_guard"]["geographic_similarity_edge_count"] == 5085
    assert report["full_data_guard"]["non_adjacent_similarity_edge_count"] == 4835

    summary = report["real_data_graph_mdp_summary"]
    assert summary["real_data_graph_node_count"] == 1017
    assert summary["real_data_graph_edge_count"] == 7932
    assert summary["real_data_available_action_count"] == 1137

    search = report["search_config"]
    assert search["candidate_action_count"] == 1137
    assert search["top_k_per_step"] == 16
    assert search["evaluated_sequence_count"] > 1000
    assert search["evaluated_sequence_count"] < 1137 * 1136

    prior = report["behavior_prior"]
    assert prior["action_count"] == 1137
    assert prior["source"] == (
        "full_admin_graph_available_actions_boundary_and_similarity_edges"
    )
    assert prior["observed_intervention_log_prior"] is False
    assert prior["energy_threshold"] > 0

    selected = report["selected_sequence"]
    static = report["traditional_static_baseline"]
    assert selected["action_count"] == 2
    assert selected["raw_cumulative_reward"] > static["cumulative_reward"]
    assert selected["advantage_over_traditional_static"] > 0
    assert selected["mean_behavior_energy"] <= prior["energy_threshold"]
    assert selected["ood_action_drift"] <= 0.0

    alignment = report["search_value_alignment"]
    assert alignment["graph_dqn_report_available"] is True
    assert alignment["graph_dqn_training_sample_count"] == 1248
    assert alignment["graph_dqn_q_return_mae"] == 0.0000954
    assert alignment["graph_dqn_train_mean_return_mae"] == 0.000994236
    assert alignment["search_value_alignment_ready"] is True

    assert report["supported_claim"] == (
        "full_admin_energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static"
    )
    assert report["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False
    assert "observed_policy_outcome_holdout_required" in report["remaining_gates"]
    assert "historical_policy_intervention_log_required" in report["remaining_gates"]


def test_full_admin_energy_regularized_planner_artifact_is_full_scope():
    report = _read_json(ARTIFACT_PATH)

    assert report["schema"] == UWM_FULL_ADMIN_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA
    assert report["experiment_scope"] == "full_admin_graph"
    assert report["full_admin_energy_regularized_planner_ready"] is True
    assert report["full_data_guard"]["passed"] is True
    assert report["full_data_guard"]["graph_node_count"] == 1017
    assert report["full_data_guard"]["graph_edge_count"] == 7932
    assert report["search_config"]["candidate_action_count"] == 1137
    assert report["selected_sequence"]["advantage_over_traditional_static"] > 0
    assert report["conservative_search_audit"]["planner_exploitation_guard_passed"] is True
    assert report["search_value_alignment"]["search_value_alignment_ready"] is True
    assert report["observed_policy_outcome_superiority_claim"] is False


def test_catalog_and_gate_track_full_admin_energy_regularized_planner(tmp_path: Path):
    report = plan_full_admin_energy_regularized_action_sequences(
        _full_admin_env(),
        graph_drl_training_report=_read_json(
            DATA_ROOT
            / "livability_graph_drl_training_full_admin_graph_2026_07_08/uwm_full_admin_graph_livability_graph_drl_training_report.json"
        ),
        geographic_similarity_kernel=_read_json(
            DATA_ROOT
            / "geographic_similarity_kernel_2026_07_08/uwm_geographic_similarity_kernel.json"
        ),
        report_id="uwm-full-admin-energy-regularized-planner-gate-test",
        created_at="2026-07-08T19:40:00Z",
        top_k_per_step=16,
    )
    report_path = tmp_path / "uwm_full_admin_graph_energy_regularized_planner.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

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
        full_admin_energy_regularized_planner_report_path=report_path,
        gate_id="uwm-full-admin-energy-regularized-planner-gate-test",
        created_at="2026-07-08T19:45:00Z",
    )
    slice_ = gate["evidence_slices"]["full_admin_energy_regularized_planner"]
    assert slice_["source_artifact_exists"] is True
    assert slice_["full_admin_energy_regularized_planner_ready"] is True
    assert slice_["graph_node_count"] == 1017
    assert slice_["graph_edge_count"] == 7932
    assert slice_["available_action_count"] == 1137
    assert slice_["geographic_similarity_edge_count"] == 5085
    assert slice_["evaluated_sequence_count"] > 1000
    assert slice_["advantage_over_traditional_static"] > 0
    assert slice_["planner_exploitation_guard_passed"] is True
    assert slice_["search_value_alignment_ready"] is True
    assert slice_["observed_policy_outcome_superiority_claim"] is False

    claims = {claim["claim"] for claim in gate["supported_claims"]}
    assert (
        "full_admin_energy_regularized_model_based_action_sequence_planner_advantage_over_traditional_static"
        in claims
    )

    catalog = build_uwm_livability_data_catalog(
        data_root=DATA_ROOT,
        catalog_id="uwm-full-admin-energy-regularized-planner-catalog-test",
        created_at="2026-07-08T19:50:00Z",
    )
    assets_by_id = {asset["asset_id"]: asset for asset in catalog["assets"]}
    asset = assets_by_id["full_admin_energy_regularized_planner_report"]
    assert asset["exists"] is True
    assert asset["schema"] == UWM_FULL_ADMIN_ENERGY_REGULARIZED_ACTION_SEQUENCE_PLANNER_SCHEMA
    assert asset["experiment_scope"] == "full_admin_graph"
    assert asset["full_admin_energy_regularized_planner_ready"] is True
    assert asset["graph_node_count"] == 1017
    assert asset["graph_edge_count"] == 7932
    assert asset["available_action_count"] == 1137
    assert (
        catalog["full_data_readiness"][
            "full_admin_energy_regularized_planner_completed"
        ]
        is True
    )


def test_data_foundation_gate_builder_wires_full_admin_energy_planner_artifact():
    import scripts.build_uwm_data_foundation_evidence_gate as builder

    assert builder.FULL_ADMIN_ENERGY_REGULARIZED_PLANNER_REPORT_PATH.exists()

    tree = ast.parse(inspect.getsource(builder.main))
    build_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "build_uwm_data_foundation_evidence_gate"
    ]
    assert len(build_calls) == 1
    keyword_names = {keyword.arg for keyword in build_calls[0].keywords}
    assert "full_admin_energy_regularized_planner_report_path" in keyword_names

    source = inspect.getsource(builder.main)
    assert "full_admin_energy_regularized_planner_ready" in source
    assert "full_admin_energy_regularized_planner_advantage" in source
