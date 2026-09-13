import json
from pathlib import Path

from data_agent.uwm.model_based_rl import (
    build_admin_livability_graph_observation,
    plan_with_model_based_graph_search,
)
from data_agent.uwm.simulator import simulate_livability_rollout
from data_agent.uwm.spatial_spillover_kernel import (
    UWM_DATA_CALIBRATED_SPATIAL_SPILLOVER_KERNEL_SCHEMA,
    build_uwm_data_calibrated_spatial_spillover_kernel,
    validate_uwm_data_calibrated_spatial_spillover_kernel,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
ADMIN_GRAPH_PATH = (
    DATA_ROOT
    / "admin_spatial_graph_2026_07_05/uwm_admin_spatial_adjacency_graph.json"
)
ADMIN_PANEL_PATH = (
    DATA_ROOT
    / "admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _build_kernel() -> dict:
    return build_uwm_data_calibrated_spatial_spillover_kernel(
        admin_spatial_graph=_read_json(ADMIN_GRAPH_PATH),
        admin_livability_panel=_read_json(ADMIN_PANEL_PATH),
        kernel_id="uwm-data-calibrated-spatial-spillover-kernel-real-test",
        created_at="2026-07-07T18:10:00Z",
    )


def test_spatial_spillover_kernel_uses_real_admin_boundary_and_livability_panel():
    kernel = _build_kernel()

    assert kernel["schema"] == UWM_DATA_CALIBRATED_SPATIAL_SPILLOVER_KERNEL_SCHEMA
    assert validate_uwm_data_calibrated_spatial_spillover_kernel(kernel) == {
        "valid": True,
        "errors": [],
    }
    assert kernel["data_calibrated_spatial_spillover_kernel_ready"] is True
    assert kernel["source_dataset_ids"] == [
        "chongqing_township_admin_units_local",
        "admin_livability_target_panel_2024_07",
    ]
    assert kernel["calibration_features"]["uses_shared_boundary_length"] is True
    assert kernel["calibration_features"]["uses_admin_livability_need"] is True
    assert kernel["calibration_features"]["uses_admin_exposure_priority"] is True
    assert kernel["summary"]["panel_unit_count"] == 36
    assert kernel["summary"]["kernel_source_unit_count"] >= 30
    assert kernel["summary"]["directional_edge_count"] > 100
    assert kernel["summary"]["max_spillover_factor"] > kernel["summary"]["min_spillover_factor"]
    assert kernel["observed_policy_outcome_superiority_claim"] is False


def test_simulator_consumes_spatial_spillover_kernel_with_explainable_neighbor_effects():
    panel = _read_json(ADMIN_PANEL_PATH)
    graph = _read_json(ADMIN_GRAPH_PATH)
    kernel = _build_kernel()
    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-spatial-kernel-sim-test",
        created_at="2026-07-07T18:15:00Z",
        max_units=12,
        admin_spatial_graph=graph,
    )
    target_unit = "九龙坡区|九龙镇|77"

    rollout = simulate_livability_rollout(
        observation,
        [
            {
                "action_id": "kernel-green-jiulong",
                "action_type": "increase_green_infrastructure",
                "target_units": [target_unit],
                "intensity": 1.0,
            }
        ],
        scenario={
            "scenario_id": "data_calibrated_spatial_spillover_test",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        spatial_spillover_kernel=kernel,
    )

    per_unit = rollout["future_state_delta"]["per_unit"]
    benefited_neighbors = [
        unit_id
        for unit_id, delta in per_unit.items()
        if unit_id != target_unit and delta["livability_delta"] > 0.0
    ]
    assert benefited_neighbors
    assert any(
        step["step"] == "read_data_calibrated_spatial_spillover_kernel"
        and step["kernel_id"] == kernel["kernel_id"]
        and step["valid"] is True
        for step in rollout["simulator_trace"]
    )
    spillover_steps = [
        step
        for step in rollout["simulator_trace"]
        if step["step"] == "apply_spatial_spillover_kernel"
    ]
    assert spillover_steps
    assert spillover_steps[0]["mechanism_source"] == "data_calibrated_spatial_spillover_kernel"
    assert spillover_steps[0]["neighbor_count"] > 0
    assert spillover_steps[0]["total_spillover_factor"] > 0.0
    assert rollout["claim_boundary"]["max_claim_level"] == "bounded_support"


def test_model_based_planner_replay_records_spatial_kernel_transition_sources():
    panel = _read_json(ADMIN_PANEL_PATH)
    graph = _read_json(ADMIN_GRAPH_PATH)
    kernel = _build_kernel()
    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-livability-spatial-kernel-planner-test",
        created_at="2026-07-07T18:20:00Z",
        max_units=12,
        admin_spatial_graph=graph,
    )

    report = plan_with_model_based_graph_search(
        observation,
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "data_calibrated_spatial_kernel_planning",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        horizon=2,
        beam_width=4,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        spatial_spillover_kernel=kernel,
    )

    assert report["spatial_spillover_kernel_summary"]["kernel_id"] == kernel["kernel_id"]
    assert report["spatial_spillover_kernel_summary"][
        "data_calibrated_spatial_spillover_kernel_ready"
    ] is True
    assert report["best_sequence"]["action_count"] == 2
    assert report["advantage_over_static_single_step"] > 0.0
    assert any(
        "data_calibrated_spatial_spillover_kernel" in transition["transition"][
            "simulator_mechanism_sources"
        ]
        for transition in report["trajectory_dataset"]["transitions"]
    )
    assert report["observed_policy_outcome_superiority_claim"] is False
