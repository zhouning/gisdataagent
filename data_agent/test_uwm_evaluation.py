from data_agent.uwm.evaluation import evaluate_dynamic_advantage_over_static_baseline


def _observation():
    return {
        "schema": "uwm.canonical_observation.v1",
        "observation_id": "uwm-eval-obs-001",
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


def _baseline_records():
    return [
        {"unit_id": "grid-1", "heat": 0.82, "pollution": 0.72, "service_access": 0.32, "equity": 0.38},
        {"unit_id": "grid-2", "heat": 0.60, "pollution": 0.52, "service_access": 0.44, "equity": 0.50},
    ]


def _indicators():
    return {
        "heat": {"weight": 0.30, "direction": "negative"},
        "pollution": {"weight": 0.25, "direction": "negative"},
        "service_access": {"weight": 0.25, "direction": "positive"},
        "equity": {"weight": 0.20, "direction": "positive"},
    }


def test_evaluation_proves_known_effect_dynamic_advantage_without_empirical_overclaim():
    report = evaluate_dynamic_advantage_over_static_baseline(
        observation=_observation(),
        baseline_records=_baseline_records(),
        indicators=_indicators(),
        action_sequence=[
            {
                "action_id": "green-grid-1",
                "action_type": "increase_green_infrastructure",
                "target_units": ["grid-1"],
                "intensity": 0.5,
            }
        ],
        scenario={"scenario_id": "heatwave_day", "heat_stress_multiplier": 1.2},
    )

    assert report["schema"] == "uwm.dynamic_advantage_evaluation.v1"
    assert report["traditional_baseline"]["method"] == "static_weighted_indicator_overlay"
    assert report["traditional_baseline"]["action_response_delta"] == 0.0
    assert report["world_model"]["action_response_delta"] > 0.0
    assert report["checks"]["dynamic_action_response"]["passed"] is True
    assert report["checks"]["negative_control_stability"]["passed"] is True
    assert report["checks"]["trace_completeness"]["passed"] is True
    assert report["architectural_superiority_over_static_baseline"] is True
    assert report["empirical_superiority_claim"] is False
    assert report["supported_claim"] == "known_effect_dynamic_advantage_over_static_baseline"
    assert "holdout_observed_outcomes_required" in report["remaining_gates"]


def test_evaluation_downgrades_claim_when_rollout_is_not_for_claim():
    observation = _observation()
    observation["synthetic_flags"] = [{"dataset_id": "synthetic_air", "status": "synthetic"}]
    observation["claim_boundary"] = {"max_claim_level": "exploratory_only"}

    report = evaluate_dynamic_advantage_over_static_baseline(
        observation=observation,
        baseline_records=_baseline_records(),
        indicators=_indicators(),
        action_sequence=[
            {
                "action_id": "green-grid-1",
                "action_type": "increase_green_infrastructure",
                "target_units": ["grid-1"],
                "intensity": 0.5,
            }
        ],
        scenario={"scenario_id": "synthetic_smoke"},
    )

    assert report["world_model"]["evidence_grade"] == "exploratory_only"
    assert report["architectural_superiority_over_static_baseline"] is True
    assert report["empirical_superiority_claim"] is False
    assert report["claim_boundary"]["max_claim_level"] == "exploratory_only"
    assert report["supported_claim"] == "exploratory_known_effect_dynamic_advantage_only"
