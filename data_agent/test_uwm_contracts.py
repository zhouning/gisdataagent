from data_agent.uwm.contracts import (
    UWM_OBSERVATION_SCHEMA,
    UWM_PLAN_PACKAGE_SCHEMA,
    UWM_ROLLOUT_TRACE_SCHEMA,
    validate_uwm_observation,
    validate_uwm_plan_package,
    validate_uwm_rollout_trace,
)


def test_validate_uwm_observation_requires_trace_and_boundaries():
    payload = {
        "schema": UWM_OBSERVATION_SCHEMA,
        "spatial_units": [{"unit_id": "grid-001", "unit_type": "grid_500m"}],
        "object_layers": [{"role": "building", "source_dataset_id": "chongqing_buildings"}],
        "raster_features": [{"feature_id": "lst", "source_dataset_id": "modis_lst"}],
        "graph_edges": [{"edge_type": "spatial_adjacency", "source": "grid-001", "target": "grid-002"}],
        "temporal_index": {"start": "2021", "end": "2024"},
        "quality_flags": [{"level": "warning", "message": "air pollution uses public proxy"}],
        "synthetic_flags": [{"dataset_id": "uwm_air_proxy", "status": "public_proxy"}],
        "provenance": {"manifest_path": "docs/reports/uwm_data_foundation_manifest.csv"},
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "renderer_trace": [{"step": "mmfe_state_input_loaded"}],
    }

    validation = validate_uwm_observation(payload)

    assert validation["valid"], validation["errors"]
    assert payload["schema"] == UWM_OBSERVATION_SCHEMA


def test_validate_uwm_observation_rejects_missing_claim_boundary():
    payload = {"schema": UWM_OBSERVATION_SCHEMA, "spatial_units": [], "renderer_trace": []}

    validation = validate_uwm_observation(payload)

    assert not validation["valid"]
    assert "claim_boundary is required" in validation["errors"]


def test_validate_uwm_observation_rejects_incomplete_native_geometry_declaration():
    payload = {
        "schema": UWM_OBSERVATION_SCHEMA,
        "spatial_units": [],
        "object_layers": [],
        "raster_features": [
            {
                "feature_id": "downscaled_population",
                "geometry_type": "raster",
                "spatial_support": {"support_type": "grid_cell"},
                "observation_semantics": "downscaled",
            }
        ],
        "graph_edges": [],
        "temporal_index": {},
        "quality_flags": [],
        "synthetic_flags": [],
        "provenance": {},
        "claim_boundary": {"max_claim_level": "exploratory_only"},
        "renderer_trace": [],
    }

    validation = validate_uwm_observation(payload)

    assert not validation["valid"]
    assert any("uncertainty is required for downscaled" in error for error in validation["errors"])
    assert any(
        "calibration.status is required for downscaled" in error
        for error in validation["errors"]
    )


def test_validate_uwm_observation_requires_calibration_evidence_when_marked_calibrated():
    payload = {
        "schema": UWM_OBSERVATION_SCHEMA,
        "spatial_units": [],
        "object_layers": [],
        "raster_features": [
            {
                "feature_id": "interpolated_pm25",
                "geometry_type": "raster",
                "spatial_support": {"support_type": "grid_cell"},
                "observation_semantics": "interpolated",
                "uncertainty": {"representation": "prediction_interval"},
                "calibration": {"status": "calibrated", "method": "split_conformal"},
            }
        ],
        "graph_edges": [],
        "temporal_index": {},
        "quality_flags": [],
        "synthetic_flags": [],
        "provenance": {},
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "renderer_trace": [],
    }

    validation = validate_uwm_observation(payload)

    assert not validation["valid"]
    assert any("confidence_level must be" in error for error in validation["errors"])
    assert any("holdout_count must be" in error for error in validation["errors"])


def test_validate_rollout_trace_requires_action_conditioned_outputs():
    payload = {
        "schema": UWM_ROLLOUT_TRACE_SCHEMA,
        "initial_state_ref": "obs-001",
        "action_sequence": [{"action_id": "green-001", "action_type": "increase_green"}],
        "scenario": {"scenario_id": "heatwave"},
        "backend": "baseline_dynamics",
        "future_state_delta": {"changed_units": 3},
        "heat_risk_delta": -0.2,
        "air_pollution_exposure_delta": -0.1,
        "service_accessibility_delta": 0.05,
        "equity_delta": 0.08,
        "livability_delta": 0.12,
        "uncertainty_interval": {"low": 0.02, "high": 0.18},
        "evidence_grade": "exploratory_only",
        "claim_boundary": {"max_claim_level": "exploratory_only"},
        "simulator_trace": [{"step": "predict_next"}],
    }

    validation = validate_uwm_rollout_trace(payload)

    assert validation["valid"], validation["errors"]
    assert payload["schema"] == UWM_ROLLOUT_TRACE_SCHEMA


def test_validate_plan_package_requires_rollout_traces_and_rejections():
    payload = {
        "schema": UWM_PLAN_PACKAGE_SCHEMA,
        "planning_goal": "reduce_heat_and_improve_equity",
        "recommended_actions": [{"action_id": "green-001"}],
        "rejected_actions": [{"action_id": "road-001", "reason": "evidence too weak"}],
        "rollout_traces": ["rollout-001"],
        "expected_benefits": {"livability_delta": 0.12},
        "equity_effects": {"vulnerable_group_gain": 0.08},
        "risk_flags": [{"level": "warning", "message": "proxy pollution data"}],
        "evidence_grade": "bounded_support",
        "data_gaps": ["local_air_quality_station_data"],
        "human_review_required": True,
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "planner_trace": [{"step": "rank_candidates"}],
    }

    validation = validate_uwm_plan_package(payload)

    assert validation["valid"], validation["errors"]
