import json
from pathlib import Path

from data_agent.uwm.model_based_rl import (
    build_admin_livability_graph_observation,
    plan_with_model_based_graph_search,
)
from data_agent.uwm.offline_world_model_policy import plan_with_offline_world_model_rollouts
from data_agent.uwm.data_foundation_evidence_gate import (
    build_uwm_data_foundation_evidence_gate,
)
from data_agent.uwm.world_model_evidence_readiness import (
    build_world_model_evidence_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
ADMIN_GRAPH_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
ADMIN_PANEL_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)
MECHANISM_TABLE_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json"
)
SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json"
)
SPATIAL_CAUSAL_REGISTRY_PATH = (
    ROOT
    / "data/uwm_public_proxy/chongqing_central/spatial_causal_question_registry_2026_07_09/uwm_spatial_causal_question_registry.json"
)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_calibrated_report(
    *,
    air_quality_uncertainty_context: dict | None = None,
    spatial_causal_question_registry: dict | None = None,
) -> dict:
    graph = _load_json(ADMIN_GRAPH_PATH)
    panel = _load_json(ADMIN_PANEL_PATH)
    mechanism_table = _load_json(MECHANISM_TABLE_PATH)
    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-data-calibrated-graph-mdp-test",
        created_at="2026-07-06T19:00:00Z",
        max_units=36,
        admin_spatial_graph=graph,
    )
    kwargs = {}
    if air_quality_uncertainty_context is not None:
        kwargs["air_quality_uncertainty_context"] = air_quality_uncertainty_context
    if spatial_causal_question_registry is not None:
        kwargs["spatial_causal_question_registry"] = spatial_causal_question_registry
    return plan_with_model_based_graph_search(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "data_calibrated_heat_pollution_service_stress",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        horizon=2,
        beam_width=5,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        mechanism_table=mechanism_table,
        **kwargs,
    )


def test_data_calibrated_graph_search_uses_mechanism_table_and_beats_static():
    report = _build_calibrated_report(
        spatial_causal_question_registry=_load_json(SPATIAL_CAUSAL_REGISTRY_PATH)
    )

    assert report["schema"] == "uwm.model_based_graph_search_report.v1"
    assert report["mechanism_table_summary"]["mechanism_table_id"] == (
        "uwm-data-calibrated-mechanism-table-2026-07-06"
    )
    assert report["mechanism_table_summary"]["data_calibrated_mechanism_ready"] is True
    assert report["mechanism_table_summary"]["mechanism_source"] == (
        "data_calibrated_mechanism_table"
    )
    assert report["best_sequence"]["cumulative_reward"] > report[
        "static_single_step_baseline"
    ]["cumulative_reward"]
    assert report["advantage_over_static_single_step"] > 0
    assert report["supported_claim"] == (
        "data_calibrated_model_based_graph_search_advantage_over_static_heuristic"
    )
    assert report["empirical_superiority_claim"] is False
    assert "observed_policy_outcome_holdout_required" in report["remaining_gates"]

    best_trace = report["best_sequence"]["rollout_trace"]["simulator_trace"]
    static_trace = report["static_single_step_baseline"]["rollout_trace"][
        "simulator_trace"
    ]
    assert any(
        step["step"] == "read_data_calibrated_mechanism_table"
        and step["valid"] is True
        for step in best_trace
    )
    assert any(
        step["step"] == "apply_action_effects"
        and step["mechanism_source"] == "data_calibrated_mechanism_table"
        for step in static_trace
    )


def test_data_calibrated_graph_search_binds_actions_to_spatial_causal_contracts():
    registry = _load_json(SPATIAL_CAUSAL_REGISTRY_PATH)
    report = _build_calibrated_report(spatial_causal_question_registry=registry)

    binding = report["spatial_causal_contract_binding"]
    candidate_count = report["search_config"]["candidate_action_count"]
    assert binding["binding_ready"] is True
    assert binding["registry_ready"] is True
    assert binding["feasible_action_count"] == candidate_count
    assert binding["attached_action_count"] == candidate_count
    assert binding["missing_contract_action_count"] == 0
    assert binding["underidentified_policy_effect_action_count"] == candidate_count
    assert binding["identified_policy_effect_action_count"] == 0
    assert binding["policy_outcome_claim_allowed_action_count"] == 0

    for action in report["best_sequence"]["action_sequence"]:
        assert action["causal_question_id"]
        assert "do(" in action["causal_query"]
        assert action["primary_outcome"]
        assert action["identification_status"] == (
            "underidentified_for_observed_policy_effect"
        )
        assert action["required_authoritative_tables"] == [
            "policy_project_history",
            "action_constraint_cost_model",
            "observed_outcome_validation_panel",
            "causal_effect_calibration_panel",
            "human_governance_review_log",
        ]
        assert action["policy_outcome_claim_allowed"] is False
        assert action["observed_policy_outcome_superiority_claim"] is False
        assert action["empirical_superiority_claim"] is False

    static_action = report["static_single_step_baseline"]["action_sequence"][0]
    assert static_action["action_id"].startswith("static-")
    assert static_action["causal_question_id"]
    assert static_action["policy_outcome_claim_allowed"] is False

    first_transition_action = report["trajectory_dataset"]["transitions"][0]["action"]
    assert first_transition_action["causal_question_id"]
    assert first_transition_action["policy_outcome_claim_allowed"] is False


def test_graph_search_without_spatial_causal_registry_blocks_planner_advantage_claim():
    report = _build_calibrated_report()

    assert report["advantage_over_static_single_step"] > 0
    binding = report["spatial_causal_contract_binding"]
    assert binding["binding_ready"] is False
    assert binding["registry_ready"] is False
    assert binding["missing_contract_action_count"] == report["search_config"][
        "candidate_action_count"
    ]
    assert report["supported_claim"] == (
        "no_model_based_graph_search_advantage_claim_supported"
    )
    assert report["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert "spatial_causal_question_registry_binding_required" in report[
        "remaining_gates"
    ]
    assert report["observed_policy_outcome_superiority_claim"] is False
    assert report["empirical_superiority_claim"] is False


def test_data_calibrated_graph_search_uses_scene_aligned_conformal_uncertainty_for_risk_adjustment():
    scene_holdout = _load_json(SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH)
    report = _build_calibrated_report(
        air_quality_uncertainty_context=scene_holdout,
        spatial_causal_question_registry=_load_json(SPATIAL_CAUSAL_REGISTRY_PATH),
    )

    summary = report["air_quality_uncertainty_calibration_summary"]
    assert summary["source_benchmark_id"] == (
        "uwm-scene-aligned-gridded-air-quality-holdout-2026-07-06"
    )
    assert summary["method"] == "split_conformal_leave_one_train_day"
    assert summary["confidence_level"] == 0.9
    assert summary["calibration_count"] == 108
    assert summary["holdout_count"] == 144
    assert summary["uwm_interval_score"] == 5.559385
    assert summary["static_interval_score"] == 13.7
    assert summary["uwm_uncertainty_calibration_ready"] is True
    assert summary["scene_aligned_station_calibrated_air_quality_holdout_ready"] is False
    assert summary["observed_policy_outcome_superiority_claim"] is False

    risk = report["risk_adjusted_planner_evaluation"]
    assert risk["method"] == "same_conformal_pm25_uncertainty_penalty"
    assert risk["uses_same_calibrated_uncertainty_for_planner_and_static"] is True
    assert risk["pm25_scene_range_ugm3"] > 0
    assert risk["normalized_uwm_interval_score"] > 0
    assert risk["best_sequence_air_quality_dependency"] > 0
    assert risk["best_sequence_uncertainty_penalty"] > 0
    assert risk["best_sequence_risk_adjusted_reward"] < report["best_sequence"][
        "cumulative_reward"
    ]
    assert risk["static_single_step_risk_adjusted_reward"] < report[
        "static_single_step_baseline"
    ]["cumulative_reward"]
    assert risk["risk_adjusted_advantage_over_static_single_step"] > 0
    assert risk["supported_claim"] == (
        "risk_calibrated_data_calibrated_planner_replay_advantage_over_static_heuristic"
    )
    assert report["empirical_superiority_claim"] is False
    assert "observed_policy_outcome_holdout_required" in report["remaining_gates"]


def test_data_calibrated_replay_can_train_learned_rollout_without_policy_claim():
    report = _build_calibrated_report(
        spatial_causal_question_registry=_load_json(SPATIAL_CAUSAL_REGISTRY_PATH)
    )
    learned = plan_with_offline_world_model_rollouts(
        report,
        model_id="data-calibrated-learned-rollout-test",
        created_at="2026-07-06T19:05:00Z",
        horizon=2,
        beam_width=5,
        holdout_stride=5,
        ridge=0.001,
        uncertainty_penalty=0.5,
    )

    assert learned["schema"] == "uwm.offline_world_model_rollout_planner_report.v1"
    assert learned["source_report_schema"] == "uwm.model_based_graph_search_report.v1"
    assert learned["holdout_metrics"]["reward_mae"] < learned["baseline_metrics"][
        "train_mean_reward_mae"
    ]
    assert learned["learned_rollout_planner"][
        "imagined_advantage_over_static_single_step"
    ] > 0
    assert learned["learned_rollout_planner"][
        "imagined_advantage_over_one_step_policy"
    ] > 0
    assert learned["supported_claim"] == (
        "learned_world_model_rollout_improves_imagined_static_and_one_step_baselines"
    )
    assert learned["empirical_superiority_claim"] is False


def test_data_foundation_gate_tracks_calibrated_planner_replay(tmp_path: Path):
    report = _build_calibrated_report(
        spatial_causal_question_registry=_load_json(SPATIAL_CAUSAL_REGISTRY_PATH)
    )
    report_path = tmp_path / "uwm_data_calibrated_graph_search.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

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
        data_calibrated_planner_replay_path=report_path,
        gate_id="uwm-data-foundation-evidence-gate-calibrated-replay-test",
        created_at="2026-07-06T19:10:00Z",
    )

    replay_slice = gate["evidence_slices"]["data_calibrated_planner_replay"]
    assert replay_slice["source_artifact_exists"] is True
    assert replay_slice["data_calibrated_planner_replay_ready"] is True
    assert replay_slice["mechanism_table_ready"] is True
    assert replay_slice["advantage_over_static_single_step"] > 0
    assert replay_slice["risk_calibrated_planner_replay_ready"] is False
    assert replay_slice["observed_policy_outcome_superiority_claim"] is False
    assert "data_calibrated_planner_replay_advantage_over_static_heuristic" in {
        claim["claim"] for claim in gate["supported_claims"]
    }

    readiness = build_world_model_evidence_readiness(gate)
    planner_arch = readiness["architecture_evidence"]["planner"]
    assert planner_arch["data_calibrated_planner_replay_ready"] is True
    assert readiness["empirical_superiority_claim"] is False


def test_data_foundation_gate_tracks_risk_calibrated_planner_replay(tmp_path: Path):
    scene_holdout = _load_json(SCENE_ALIGNED_GRIDDED_AIR_QUALITY_HOLDOUT_PATH)
    report = _build_calibrated_report(
        air_quality_uncertainty_context=scene_holdout,
        spatial_causal_question_registry=_load_json(SPATIAL_CAUSAL_REGISTRY_PATH),
    )
    report_path = tmp_path / "uwm_risk_calibrated_graph_search.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

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
        data_calibrated_planner_replay_path=report_path,
        gate_id="uwm-data-foundation-evidence-gate-risk-calibrated-replay-test",
        created_at="2026-07-06T19:15:00Z",
    )

    replay_slice = gate["evidence_slices"]["data_calibrated_planner_replay"]
    assert replay_slice["data_calibrated_planner_replay_ready"] is True
    assert replay_slice["risk_calibrated_planner_replay_ready"] is True
    assert replay_slice["air_quality_uncertainty_calibration_ready"] is True
    assert replay_slice["risk_adjusted_advantage_over_static_single_step"] > 0
    assert replay_slice["observed_policy_outcome_superiority_claim"] is False
    claims = {claim["claim"] for claim in gate["supported_claims"]}
    assert "risk_calibrated_planner_replay_advantage_over_static_heuristic" in claims

    readiness = build_world_model_evidence_readiness(gate)
    planner_arch = readiness["architecture_evidence"]["planner"]
    assert planner_arch["risk_calibrated_planner_replay_ready"] is True
    assert planner_arch["risk_calibrated_planner_advantage_over_static"] > 0
    assert readiness["empirical_superiority_claim"] is False
