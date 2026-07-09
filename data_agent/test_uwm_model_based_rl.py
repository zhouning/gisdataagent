from data_agent.uwm.admin_spatial_graph import build_admin_spatial_adjacency_graph
from data_agent.uwm.geographic_similarity_kernel import (
    build_uwm_geographic_similarity_kernel,
)
from data_agent.uwm.model_based_rl import (
    build_admin_livability_graph_observation,
    build_graph_mdp_state,
    plan_with_model_based_graph_search,
)
from data_agent.uwm.offline_value_model import train_offline_graph_value_model


def _observation():
    return {
        "schema": "uwm.canonical_observation.v1",
        "observation_id": "uwm-graph-mdp-obs-001",
        "spatial_units": [
            {
                "unit_id": "grid-1",
                "unit_type": "grid_500m",
                "heat_risk": 0.82,
                "air_pollution_exposure": 0.72,
                "service_accessibility": 0.32,
                "equity": 0.38,
                "livability": 0.35,
            },
            {
                "unit_id": "grid-2",
                "unit_type": "grid_500m",
                "heat_risk": 0.58,
                "air_pollution_exposure": 0.46,
                "service_accessibility": 0.68,
                "equity": 0.55,
                "livability": 0.59,
            },
        ],
        "object_layers": [{"role": "buildings", "source_dataset_id": "chongqing_buildings"}],
        "raster_features": [{"role": "lst", "source_dataset_id": "modis_lst"}],
        "graph_edges": [
            {"edge_type": "grid_adjacent_to_grid", "source": "grid-1", "target": "grid-2", "weight": 1.0}
        ],
        "temporal_index": {"observation_created_at": "2026-07-05T06:45:00+00:00"},
        "quality_flags": [{"level": "info", "message": "graph mdp fixture observation"}],
        "synthetic_flags": [{"dataset_id": "modis_lst", "status": "public_proxy"}],
        "provenance": {"manifest_path": "docs/reports/uwm_data_foundation_manifest.csv"},
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "renderer_trace": [{"step": "derive_canonical_observation"}],
    }


def test_build_graph_mdp_state_exposes_nodes_edges_and_action_masks():
    state = build_graph_mdp_state(
        _observation(),
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
    )

    assert state["schema"] == "uwm.graph_mdp_state.v1"
    assert state["state_encoder"] == "graph_feature_encoder_v0"
    assert len(state["nodes"]) == 2
    assert len(state["edges"]) == 1
    assert state["graph_statistics"]["node_count"] == 2
    masked = {(action["action_type"], tuple(action["target_units"])) for action in state["available_actions"]}
    assert ("increase_green_infrastructure", ("grid-1",)) in masked
    assert ("traffic_emission_control", ("grid-1",)) in masked
    assert ("add_community_service", ("grid-1",)) in masked
    assert state["action_mask_trace"][0]["reason"] == "heat_risk_above_threshold"


def test_model_based_graph_search_exports_replay_and_beats_static_single_step_heuristic():
    report = plan_with_model_based_graph_search(
        _observation(),
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "heat_pollution_service_stress",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        horizon=2,
        beam_width=3,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
    )

    assert report["schema"] == "uwm.model_based_graph_search_report.v1"
    assert report["planner_backend"] == "graph_mdp_beam_search_v0"
    assert report["best_sequence"]["action_count"] == 2
    assert report["trajectory_dataset"]["schema"] == "uwm.graph_mdp_replay_dataset.v1"
    assert report["trajectory_dataset"]["transition_count"] > 0
    assert report["trajectory_dataset"]["transitions"][0]["tuple_keys"] == [
        "state",
        "action",
        "reward",
        "next_state_delta",
        "transition",
    ]
    assert report["best_sequence"]["cumulative_reward"] > report["static_single_step_baseline"]["cumulative_reward"]
    assert report["advantage_over_static_single_step"] > 0
    assert report["empirical_superiority_claim"] is False
    assert report["supported_claim"] == "known_effect_model_based_graph_search_advantage"
    assert "observed_policy_outcome_holdout_required" in report["remaining_gates"]


def test_model_based_graph_search_can_store_compact_replay_transitions():
    report = plan_with_model_based_graph_search(
        _observation(),
        action_types=[
            "increase_green_infrastructure",
            "traffic_emission_control",
            "add_community_service",
        ],
        scenario={
            "scenario_id": "heat_pollution_service_stress",
            "heat_stress_multiplier": 1.2,
            "air_pollution_stress_multiplier": 1.15,
            "vulnerability_multiplier": 1.1,
        },
        horizon=2,
        beam_width=3,
        thresholds={
            "heat_risk": 0.7,
            "air_pollution_exposure": 0.6,
            "service_accessibility": 0.5,
        },
        transition_storage="compact",
    )

    transition = report["trajectory_dataset"]["transitions"][0]
    assert report["search_config"]["transition_storage"] == "compact"
    assert "next_state_delta" not in transition
    assert transition["next_state_delta_summary"]["changed_units"] >= 1
    assert "aggregate" in transition["next_state_delta_summary"]
    assert "top_changed_units" in transition["next_state_delta_summary"]


def test_build_admin_livability_graph_observation_maps_proxy_panel_to_model_features():
    panel = {
        "schema": "uwm.admin_livability_target_panel.v1",
        "panel_id": "admin-livability-test",
        "created_at": "2026-07-05T06:55:00+00:00",
        "admin_livability_target_rows": [
            {
                "admin_unit_id": "A|one|1",
                "county": "A",
                "township": "one",
                "exposure_priority_score": 0.9,
                "service_point_count": 0.0,
                "essential_service_count": 0.0,
                "livability_need_score": 1.0,
                "score_components": {
                    "exposure_norm": 1.0,
                    "service_gap_norm": 1.0,
                    "essential_gap_norm": 1.0,
                },
            },
            {
                "admin_unit_id": "B|two|2",
                "county": "B",
                "township": "two",
                "exposure_priority_score": 0.2,
                "service_point_count": 4.0,
                "essential_service_count": 2.0,
                "livability_need_score": 0.2,
                "score_components": {
                    "exposure_norm": 0.2,
                    "service_gap_norm": 0.0,
                    "essential_gap_norm": 0.0,
                },
            },
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "limitations": ["composite_target_score_is_proxy_not_observed_livability"],
    }

    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-graph-mdp-obs-test",
        created_at="2026-07-05T07:00:00+00:00",
        max_units=2,
    )

    assert observation["schema"] == "uwm.canonical_observation.v1"
    assert len(observation["spatial_units"]) == 2
    assert observation["spatial_units"][0]["heat_risk"] == 1.0
    assert observation["spatial_units"][0]["air_pollution_exposure"] == 0.9
    assert observation["spatial_units"][0]["service_accessibility"] == 0.0
    assert observation["spatial_units"][0]["livability"] == 0.0
    assert observation["graph_edges"][0]["edge_type"] == "proxy_priority_similarity_not_spatial_adjacency"
    assert any("not true spatial adjacency" in flag["message"] for flag in observation["quality_flags"])


def test_admin_livability_graph_observation_defaults_to_full_panel_without_truncation():
    panel = {
        "schema": "uwm.admin_livability_target_panel.v1",
        "panel_id": "admin-livability-full-default-test",
        "created_at": "2026-07-08T10:05:00+00:00",
        "experiment_scope": "full_admin_graph",
        "admin_livability_target_rows": [
            {
                "admin_unit_id": f"A|unit|{index}",
                "county": "A",
                "township": f"unit-{index}",
                "exposure_priority_score": 0.9 - index * 0.1,
                "service_point_count": float(index),
                "essential_service_count": 0.0,
                "livability_need_score": 1.0 - index * 0.1,
                "score_components": {
                    "exposure_norm": 1.0 - index * 0.1,
                    "service_gap_norm": 1.0,
                    "essential_gap_norm": 1.0,
                },
            }
            for index in range(12)
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "limitations": [],
    }

    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-graph-mdp-obs-full-default-test",
        created_at="2026-07-08T10:10:00+00:00",
    )

    assert observation["experiment_scope"] == "full_admin_graph"
    assert len(observation["spatial_units"]) == 12
    assert observation["renderer_trace"][0]["source_row_count"] == 12
    assert observation["renderer_trace"][-1]["selected_unit_count"] == 12
    assert observation["renderer_trace"][-1]["selection_mode"] == "all_rows"


def test_build_admin_spatial_adjacency_graph_from_touching_admin_polygons():
    graph = build_admin_spatial_adjacency_graph(
        admin_features=[
            _admin_feature(
                "A|one|1",
                "A",
                "one",
                [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
            ),
            _admin_feature(
                "B|two|2",
                "B",
                "two",
                [(1, 0), (2, 0), (2, 1), (1, 1), (1, 0)],
            ),
            _admin_feature(
                "C|three|3",
                "C",
                "three",
                [(3, 0), (4, 0), (4, 1), (3, 1), (3, 0)],
            ),
        ],
        graph_id="admin-spatial-graph-test",
        created_at="2026-07-05T08:00:00+00:00",
    )

    assert graph["schema"] == "uwm.admin_spatial_adjacency_graph.v1"
    assert graph["summary"]["source_feature_count"] == 3
    assert graph["summary"]["node_count"] == 3
    assert graph["summary"]["edge_count"] == 1
    assert graph["nodes"][0]["unit_id"] == "A|one|1"
    assert graph["edges"][0]["edge_type"] == "admin_boundary_adjacency"
    assert graph["edges"][0]["source"] == "A|one|1"
    assert graph["edges"][0]["target"] == "B|two|2"
    assert graph["edges"][0]["shared_boundary_length_degrees"] > 0
    assert graph["claim_boundary"]["max_claim_level"] == "bounded_support"


def test_admin_livability_observation_uses_spatial_adjacency_graph_when_available():
    graph = build_admin_spatial_adjacency_graph(
        admin_features=[
            _admin_feature(
                "A|one|1",
                "A",
                "one",
                [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
            ),
            _admin_feature(
                "B|two|2",
                "B",
                "two",
                [(1, 0), (2, 0), (2, 1), (1, 1), (1, 0)],
            ),
        ],
        graph_id="admin-spatial-graph-test",
        created_at="2026-07-05T08:00:00+00:00",
    )
    panel = {
        "schema": "uwm.admin_livability_target_panel.v1",
        "panel_id": "admin-livability-spatial-test",
        "created_at": "2026-07-05T08:01:00+00:00",
        "admin_livability_target_rows": [
            {
                "admin_unit_id": "A|one|1",
                "county": "A",
                "township": "one",
                "exposure_priority_score": 0.9,
                "service_point_count": 0.0,
                "essential_service_count": 0.0,
                "livability_need_score": 1.0,
                "score_components": {
                    "exposure_norm": 1.0,
                    "service_gap_norm": 1.0,
                    "essential_gap_norm": 1.0,
                },
            },
            {
                "admin_unit_id": "B|two|2",
                "county": "B",
                "township": "two",
                "exposure_priority_score": 0.8,
                "service_point_count": 0.0,
                "essential_service_count": 0.0,
                "livability_need_score": 0.9,
                "score_components": {
                    "exposure_norm": 0.9,
                    "service_gap_norm": 1.0,
                    "essential_gap_norm": 1.0,
                },
            },
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
    }

    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-graph-mdp-obs-spatial-test",
        created_at="2026-07-05T08:05:00+00:00",
        max_units=2,
        admin_spatial_graph=graph,
    )

    assert observation["graph_edges"][0]["edge_type"] == "admin_boundary_adjacency"
    assert observation["graph_edges"][0]["source"] == "A|one|1"
    assert observation["graph_edges"][0]["target"] == "B|two|2"
    assert observation["renderer_trace"][-1]["step"] == "derive_admin_spatial_adjacency_subgraph"
    assert observation["renderer_trace"][-1]["selected_spatial_edge_count"] == 1
    assert not any("not true spatial adjacency" in flag["message"] for flag in observation["quality_flags"])


def test_admin_livability_observation_adds_geographic_similarity_edges_when_available():
    panel = {
        "schema": "uwm.admin_livability_target_panel.v1",
        "panel_id": "admin-livability-similarity-test",
        "created_at": "2026-07-08T15:10:00+00:00",
        "admin_livability_target_rows": [
            _similarity_panel_row("A|one|1", "A", need=0.9, exposure=0.8, service=0.2),
            _similarity_panel_row("B|two|2", "B", need=0.88, exposure=0.79, service=0.22),
            _similarity_panel_row("C|three|3", "C", need=0.2, exposure=0.1, service=0.9),
        ],
        "claim_boundary": {"max_claim_level": "bounded_support"},
    }
    graph = build_admin_spatial_adjacency_graph(
        admin_features=[
            _admin_feature(
                "A|one|1",
                "A",
                "one",
                [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
            ),
            _admin_feature(
                "C|three|3",
                "C",
                "three",
                [(1, 0), (2, 0), (2, 1), (1, 1), (1, 0)],
            ),
            _admin_feature(
                "B|two|2",
                "B",
                "two",
                [(4, 0), (5, 0), (5, 1), (4, 1), (4, 0)],
            ),
        ],
        graph_id="admin-spatial-similarity-graph-test",
        created_at="2026-07-08T15:11:00+00:00",
    )
    kernel = build_uwm_geographic_similarity_kernel(
        admin_livability_panel=panel,
        admin_spatial_graph=graph,
        kernel_id="uwm-geographic-similarity-observation-test",
        created_at="2026-07-08T15:12:00Z",
        top_k=1,
    )

    observation = build_admin_livability_graph_observation(
        panel,
        observation_id="admin-graph-mdp-obs-geographic-similarity-test",
        created_at="2026-07-08T15:13:00+00:00",
        admin_spatial_graph=graph,
        geographic_similarity_kernel=kernel,
    )
    state = build_graph_mdp_state(
        observation,
        action_types=["increase_green_infrastructure"],
        thresholds={"heat_risk": 0.7},
    )

    edge_types = {edge["edge_type"] for edge in observation["graph_edges"]}
    assert "admin_boundary_adjacency" in edge_types
    assert "geographic_configuration_similarity" in edge_types
    assert any(
        edge["source"] == "A|one|1"
        and edge["target"] == "B|two|2"
        and edge["boundary_adjacent"] is False
        for edge in observation["graph_edges"]
    )
    assert state["graph_statistics"]["edge_count"] == len(observation["graph_edges"])
    assert observation["renderer_trace"][-1]["step"] == (
        "append_geographic_configuration_similarity_edges"
    )
    assert observation["renderer_trace"][-1]["selected_similarity_edge_count"] > 0


def test_train_offline_graph_value_model_learns_from_replay_without_empirical_claim():
    report = _offline_value_report_fixture()

    value_report = train_offline_graph_value_model(
        report,
        model_id="offline-value-test",
        created_at="2026-07-05T09:10:00+00:00",
        holdout_stride=4,
        ridge=0.001,
    )

    assert value_report["schema"] == "uwm.offline_graph_value_model_report.v1"
    assert value_report["source_replay_transition_count"] == 8
    assert value_report["training_summary"]["train_count"] > 0
    assert value_report["training_summary"]["holdout_count"] > 0
    assert value_report["holdout_metrics"]["mae"] < value_report["baseline_metrics"]["train_mean_mae"]
    assert value_report["supported_claim"] == "offline_replay_value_model_beats_train_mean_baseline"
    assert value_report["empirical_superiority_claim"] is False
    assert value_report["candidate_value_ranking"][0]["action_id"] == "increase_green_infrastructure-unit-hot"
    assert "observed_policy_outcome_holdout_required" in value_report["remaining_gates"]


def _admin_feature(
    admin_unit_id: str,
    county: str,
    township: str,
    coordinates: list[tuple[float, float]],
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "admin_unit_id": admin_unit_id,
            "county": county,
            "township": township,
        },
        "geometry": {
            "type": "Polygon",
            "coordinates": [[list(point) for point in coordinates]],
        },
    }


def _similarity_panel_row(
    unit_id: str,
    county: str,
    *,
    need: float,
    exposure: float,
    service: float,
) -> dict:
    return {
        "admin_unit_id": unit_id,
        "county": county,
        "township": unit_id.split("|")[1],
        "exposure_priority_score": exposure,
        "service_point_count": service * 100.0,
        "essential_service_count": service * 10.0,
        "service_accessibility_score": service,
        "service_gap_score": 1.0 - service,
        "nearest_essential_service_distance_m": (1.0 - service) * 1000.0,
        "estimated_nearest_essential_travel_time_min": (1.0 - service) * 8.0,
        "road_segment_count": service * 100.0,
        "road_length_km": service * 80.0,
        "mean_road_speed_kmh": 40.0,
        "livability_need_score": need,
        "score_components": {
            "exposure_norm": exposure,
            "service_gap_norm": 1.0 - service,
            "essential_gap_norm": 1.0 - service,
        },
    }


def _offline_value_report_fixture() -> dict:
    graph_state = {
        "schema": "uwm.graph_mdp_state.v1",
        "state_id": "offline-value-state",
        "nodes": [
            {
                "unit_id": "unit-hot",
                "features": {
                    "heat_risk": 0.95,
                    "air_pollution_exposure": 0.40,
                    "service_accessibility": 0.80,
                    "equity": 0.70,
                    "livability": 0.20,
                },
            },
            {
                "unit_id": "unit-air",
                "features": {
                    "heat_risk": 0.30,
                    "air_pollution_exposure": 0.90,
                    "service_accessibility": 0.75,
                    "equity": 0.40,
                    "livability": 0.35,
                },
            },
            {
                "unit_id": "unit-service",
                "features": {
                    "heat_risk": 0.40,
                    "air_pollution_exposure": 0.30,
                    "service_accessibility": 0.10,
                    "equity": 0.55,
                    "livability": 0.25,
                },
            },
        ],
        "edges": [
            {"source": "unit-hot", "target": "unit-air", "weight": 1.0},
            {"source": "unit-air", "target": "unit-service", "weight": 1.0},
        ],
        "graph_statistics": {"node_count": 3, "edge_count": 2, "available_action_count": 8},
        "available_actions": [
            {
                "action_id": "increase_green_infrastructure-unit-hot",
                "action_type": "increase_green_infrastructure",
                "target_units": ["unit-hot"],
                "intensity": 1.0,
            },
            {
                "action_id": "increase_green_infrastructure-unit-air",
                "action_type": "increase_green_infrastructure",
                "target_units": ["unit-air"],
                "intensity": 1.0,
            },
            {
                "action_id": "traffic_emission_control-unit-air",
                "action_type": "traffic_emission_control",
                "target_units": ["unit-air"],
                "intensity": 1.0,
            },
            {
                "action_id": "add_community_service-unit-service",
                "action_type": "add_community_service",
                "target_units": ["unit-service"],
                "intensity": 1.0,
            },
        ],
    }
    rewards = [
        ("increase_green_infrastructure", "unit-hot", 0.31),
        ("increase_green_infrastructure", "unit-air", 0.06),
        ("traffic_emission_control", "unit-air", 0.24),
        ("add_community_service", "unit-service", 0.20),
        ("increase_green_infrastructure", "unit-hot", 0.30),
        ("traffic_emission_control", "unit-air", 0.23),
        ("add_community_service", "unit-service", 0.19),
        ("increase_green_infrastructure", "unit-air", 0.05),
    ]
    transitions = []
    for index, (action_type, unit_id, reward) in enumerate(rewards):
        transitions.append(
            {
                "action": {
                    "action_id": f"{action_type}-{unit_id}",
                    "action_type": action_type,
                    "target_units": [unit_id],
                    "intensity": 1.0,
                },
                "reward": reward,
                "transition": {
                    "step_index": index % 2,
                    "cumulative_reward": reward,
                },
            }
        )
    return {
        "schema": "uwm.model_based_graph_search_report.v1",
        "graph_mdp_state": graph_state,
        "trajectory_dataset": {
            "schema": "uwm.graph_mdp_replay_dataset.v1",
            "transition_count": len(transitions),
            "transitions": transitions,
        },
    }
