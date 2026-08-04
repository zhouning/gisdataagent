import copy

import pytest

from data_agent.uwm.geospatial_state_prior_benchmark import (
    UWM_GEOSPATIAL_STATE_PRIOR_BENCHMARK_SCHEMA,
    UWM_GEOSPATIAL_STATE_PRIOR_DATASET_SCHEMA,
    build_uwm_geospatial_state_prior_benchmark,
    validate_uwm_geospatial_state_prior_benchmark,
    validate_uwm_geospatial_state_prior_dataset,
)


def test_state_prior_benchmark_runs_three_strict_holdouts_and_all_comparators():
    benchmark = _build_benchmark(source_evidence_kind="synthetic_fixture")

    assert benchmark["schema"] == UWM_GEOSPATIAL_STATE_PRIOR_BENCHMARK_SCHEMA
    assert set(benchmark["split_results"]) == {
        "spatial_block",
        "whole_admin",
        "future_temporal",
    }
    for result in benchmark["split_results"].values():
        assert result["leakage_audit"]["passed"] is True
        assert result["leakage_audit"]["cross_partition_group_overlap_count"] == 0
        assert result["train_count"] > result["calibration_count"] > 0
        assert result["holdout_count"] > 0
        metrics = result["method_metrics"]
        candidate_mae = metrics["multi_geometry_soft_alignment_ridge"]["mae"]
        assert candidate_mae < metrics["spatial_idw"]["mae"]
        assert candidate_mae < metrics["hard_admin_mean"]["mae"]
        assert candidate_mae < metrics["raster_only_ridge"]["mae"]
        assert candidate_mae < metrics["raster_admin_soft_alignment_ridge"]["mae"]

    gates = benchmark["readiness_gates"]
    assert gates["three_native_geometry_routes_present"] is True
    assert gates["strict_holdout_leakage_audits_passed"] is True
    assert gates["candidate_beats_required_baselines_on_every_split"] is True
    assert gates["geometry_shuffle_negative_controls_passed"] is True
    assert gates["split_conformal_coverage_passed"] is True
    assert gates["observed_holdout_evidence_present"] is False


def test_synthetic_benchmark_cannot_upgrade_beyond_execution_claim():
    benchmark = _build_benchmark(source_evidence_kind="synthetic_fixture")

    assert benchmark["geospatial_state_prior_benchmark_ready"] is False
    assert benchmark["supported_claim"] == "multi_geometry_benchmark_execution_only"
    assert benchmark["claim_boundary"]["max_claim_level"] == "exploratory_only"
    assert benchmark["policy_causal_effect_claim"] is False
    assert benchmark["action_conditioned_dynamics_claim"] is False
    assert benchmark["general_geospatial_world_model_validation_claim"] is False
    assert validate_uwm_geospatial_state_prior_benchmark(benchmark) == {
        "valid": True,
        "errors": [],
    }


def test_observed_holdout_can_support_only_bounded_state_reconstruction_claim():
    benchmark = _build_benchmark(source_evidence_kind="observed_holdout")

    assert benchmark["geospatial_state_prior_benchmark_ready"] is True
    assert benchmark["supported_claim"] == (
        "multi_geometry_state_reconstruction_advantage_under_strict_holdout"
    )
    assert benchmark["claim_boundary"]["max_claim_level"] == "bounded_support"
    assert benchmark["uncertainty_calibration"]["coverage_gate_passed"] is True
    assert validate_uwm_geospatial_state_prior_benchmark(benchmark) == {
        "valid": True,
        "errors": [],
    }


def test_dataset_contract_rejects_incomplete_geometry_route_values():
    dataset = _dataset(source_evidence_kind="synthetic_fixture")
    dataset["rows"][0]["graph_object_features"].pop("accessibility")

    validation = validate_uwm_geospatial_state_prior_dataset(dataset)

    assert not validation["valid"]
    assert any(
        "graph_object_features must match declared feature_names" in error
        for error in validation["errors"]
    )
    with pytest.raises(ValueError, match="graph_object_features"):
        build_uwm_geospatial_state_prior_benchmark(
            dataset=dataset,
            benchmark_id="invalid-state-prior-benchmark",
            created_at="2026-08-04T12:00:00Z",
        )


def test_validator_rejects_forged_ready_claim_from_synthetic_evidence():
    benchmark = _build_benchmark(source_evidence_kind="synthetic_fixture")
    forged = copy.deepcopy(benchmark)
    forged["geospatial_state_prior_benchmark_ready"] = True
    forged["supported_claim"] = "multi_geometry_state_reconstruction_advantage_under_strict_holdout"
    forged["claim_boundary"]["max_claim_level"] = "bounded_support"

    validation = validate_uwm_geospatial_state_prior_benchmark(forged)

    assert not validation["valid"]
    assert "ready benchmark requires every readiness gate" in validation["errors"]
    assert "ready benchmark requires observed_holdout evidence" in validation["errors"]


def _build_benchmark(*, source_evidence_kind: str) -> dict:
    return build_uwm_geospatial_state_prior_benchmark(
        dataset=_dataset(source_evidence_kind=source_evidence_kind),
        benchmark_id=f"state-prior-{source_evidence_kind}-fixture",
        created_at="2026-08-04T12:00:00Z",
        confidence_level=0.9,
        coverage_tolerance=0.05,
        ridge=0.0,
        idw_neighbors=8,
    )


def _dataset(*, source_evidence_kind: str) -> dict:
    rows = []
    for time_index in range(8):
        for x_index in range(8):
            for y_index in range(4):
                admin_index = (3 * x_index + 5 * y_index) % 10
                temperature = 0.4 * x_index + 0.2 * y_index + 0.7 * time_index
                vegetation = ((x_index * y_index + time_index) % 7) / 7.0
                income = 0.3 + 0.8 * admin_index
                density = (admin_index**2) / 100.0
                degree = float((x_index + 1) * (y_index + 1)) / 10.0
                accessibility = ((x_index + 1) ** 2 + 3 * y_index) / 100.0
                target = (
                    3.0 * temperature
                    - 1.5 * vegetation
                    + 2.4 * income
                    - 0.8 * density
                    + 1.1 * degree
                    + 2.2 * accessibility
                )
                rows.append(
                    {
                        "sample_id": f"t{time_index}-x{x_index}-y{y_index}",
                        "x": float(x_index),
                        "y": float(y_index),
                        "time_id": f"2026-{time_index + 1:02d}",
                        "admin_unit_id": f"admin-{admin_index}",
                        "target": target,
                        "raster_features": {
                            "temperature": temperature,
                            "vegetation": vegetation,
                        },
                        "admin_features": {
                            "income": income,
                            "density": density,
                        },
                        "graph_object_features": {
                            "degree": degree,
                            "accessibility": accessibility,
                        },
                    }
                )
    evidence_refs = (
        ["fixture://observed-holdout-evidence"]
        if source_evidence_kind == "observed_holdout"
        else []
    )
    return {
        "schema": UWM_GEOSPATIAL_STATE_PRIOR_DATASET_SCHEMA,
        "dataset_id": f"three-geometry-{source_evidence_kind}-fixture",
        "source_evidence_kind": source_evidence_kind,
        "source_dataset_ids": ["fixture-raster", "fixture-admin", "fixture-graph"],
        "evidence_refs": evidence_refs,
        "target": {
            "name": "fixture_state",
            "geometry_type": "point",
            "spatial_support": {"support_type": "grid_cell"},
            "observation_semantics": "observed",
        },
        "geometry_routes": {
            "raster": {
                "geometry_type": "raster",
                "spatial_support": {"support_type": "grid_cell"},
                "feature_names": ["temperature", "vegetation"],
            },
            "admin": {
                "geometry_type": "polygon",
                "spatial_support": {"support_type": "admin_unit"},
                "feature_names": ["income", "density"],
            },
            "graph_object": {
                "geometry_type": "network",
                "spatial_support": {"support_type": "network_node"},
                "feature_names": ["degree", "accessibility"],
            },
        },
        "rows": rows,
    }
