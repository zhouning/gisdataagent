import pytest

from data_agent.uwm.contracts import validate_uwm_rollout_trace
from data_agent.uwm.simulator import simulate_livability_rollout


def _canonical_observation():
    return {
        "schema": "uwm.canonical_observation.v1",
        "observation_id": "uwm-obs-sim-001",
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
                "heat_risk": 0.60,
                "air_pollution_exposure": 0.52,
                "service_accessibility": 0.44,
                "equity": 0.50,
                "livability": 0.46,
            },
        ],
        "object_layers": [{"role": "buildings", "source_dataset_id": "chongqing_buildings"}],
        "raster_features": [{"role": "lst", "source_dataset_id": "modis_lst"}],
        "graph_edges": [
            {"edge_type": "grid_adjacent_to_grid", "source": "grid-1", "target": "grid-2", "weight": 1.0}
        ],
        "temporal_index": {"observation_created_at": "2026-07-04T01:00:00+00:00"},
        "quality_flags": [{"level": "info", "message": "fixture observation"}],
        "synthetic_flags": [{"dataset_id": "modis_lst", "status": "public_proxy"}],
        "provenance": {"manifest_path": "docs/reports/uwm_data_foundation_manifest.csv"},
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "renderer_trace": [{"step": "derive_canonical_observation"}],
    }


def test_simulator_rollout_is_action_conditioned_and_contract_valid():
    observation = _canonical_observation()
    action_sequence = [
        {
            "action_id": "green-grid-1",
            "action_type": "increase_green_infrastructure",
            "target_units": ["grid-1"],
            "intensity": 0.5,
        }
    ]
    scenario = {"scenario_id": "heatwave_day", "heat_stress_multiplier": 1.2}

    rollout = simulate_livability_rollout(observation, action_sequence, scenario=scenario)
    validation = validate_uwm_rollout_trace(rollout)

    assert validation["valid"], validation["errors"]
    assert rollout["backend"] == "mechanistic_urban_livability_v0"
    assert rollout["initial_state_ref"] == "uwm-obs-sim-001"
    assert rollout["action_sequence"] == action_sequence
    assert rollout["scenario"] == scenario
    assert rollout["future_state_delta"]["per_unit"]["grid-1"]["heat_risk_delta"] < 0
    assert rollout["future_state_delta"]["per_unit"]["grid-2"]["heat_risk_delta"] < 0
    assert abs(rollout["future_state_delta"]["per_unit"]["grid-1"]["heat_risk_delta"]) > abs(
        rollout["future_state_delta"]["per_unit"]["grid-2"]["heat_risk_delta"]
    )
    assert rollout["livability_delta"] > 0
    assert rollout["uncertainty_interval"]["low"] <= rollout["livability_delta"] <= rollout["uncertainty_interval"]["high"]
    assert rollout["simulator_trace"][0]["step"] == "validate_observation_contract"
    assert any(step["step"] == "apply_action_effects" for step in rollout["simulator_trace"])


def test_simulator_marks_invalid_observation_not_for_claim():
    observation = {"schema": "uwm.canonical_observation.v1", "spatial_units": []}

    rollout = simulate_livability_rollout(
        observation,
        [{"action_id": "green-grid-1", "action_type": "increase_green_infrastructure"}],
        scenario={"scenario_id": "invalid_input_smoke"},
    )
    validation = validate_uwm_rollout_trace(rollout)

    assert validation["valid"], validation["errors"]
    assert rollout["evidence_grade"] == "not_for_claim"
    assert rollout["claim_boundary"]["max_claim_level"] == "not_for_claim"
    assert rollout["livability_delta"] == 0.0
    assert rollout["future_state_delta"]["changed_units"] == 0
    assert rollout["simulator_trace"][0]["valid"] is False


def test_simulator_rejects_missing_action_sequence():
    with pytest.raises(ValueError, match="action_sequence must not be empty"):
        simulate_livability_rollout(
            _canonical_observation(),
            [],
            scenario={"scenario_id": "missing_action"},
        )


def test_simulator_consumes_scene_state_air_pollution_stress_multiplier():
    observation = _canonical_observation()
    action = [
        {
            "action_id": "lez-grid-1",
            "action_type": "traffic_emission_control",
            "target_units": ["grid-1"],
            "intensity": 0.5,
        }
    ]

    normal = simulate_livability_rollout(
        observation,
        action,
        scenario={"scenario_id": "normal_air", "air_pollution_stress_multiplier": 1.0},
    )
    stressed = simulate_livability_rollout(
        observation,
        action,
        scenario={
            "scenario_id": "stressed_air",
            "source_scene_state_id": "uwm-scene-openmeteo-ghsl-2024-07",
            "air_pollution_stress_multiplier": 1.4,
            "vulnerability_multiplier": 1.2,
        },
    )

    assert stressed["air_pollution_exposure_delta"] < normal["air_pollution_exposure_delta"]
    assert stressed["equity_delta"] > normal["equity_delta"]
    assert stressed["livability_delta"] > normal["livability_delta"]
    assert any(
        step["step"] == "read_scene_state_controls"
        and step["source_scene_state_id"] == "uwm-scene-openmeteo-ghsl-2024-07"
        for step in stressed["simulator_trace"]
    )
