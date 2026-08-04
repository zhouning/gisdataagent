import copy
import json
from pathlib import Path

import pytest

from data_agent.uwm.geospatial_kernel.state_prior_admission import (
    STATE_PRIOR_ARTIFACT_SCHEMA,
    build_state_prior_admission,
    validate_state_prior_admission,
)
from data_agent.uwm.geospatial_state_prior_benchmark import (
    REQUIRED_GEOMETRY_ROUTES,
    build_uwm_geospatial_state_prior_benchmark,
    validate_uwm_geospatial_state_prior_benchmark,
    validate_uwm_geospatial_state_prior_dataset,
)
from data_agent.uwm.geospatial_state_prior_chongqing import (
    build_chongqing_pm25_state_prior_dataset,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
SCENE_PATH = (
    DATA_ROOT
    / "scene_aligned_gridded_air_quality_holdout_2026_07_06"
    / "uwm_scene_aligned_gridded_air_quality_holdout.json"
)
PANEL_PATH = (
    DATA_ROOT
    / "admin_livability_target_2024_07_2026_07_05"
    / "uwm_admin_livability_target_panel.json"
)
GRAPH_PATH = DATA_ROOT / "admin_spatial_graph_2026_07_05" / "uwm_admin_spatial_adjacency_graph.json"
OPENMETEO_WEATHER_PATH = (
    DATA_ROOT / "openmeteo_history_2024_07_01_07" / "openmeteo_historical_weather_raw.json"
)
OPENMETEO_AIR_QUALITY_PATH = (
    DATA_ROOT / "openmeteo_history_2024_07_01_07" / "openmeteo_historical_air_quality_raw.json"
)

pytestmark = pytest.mark.skipif(
    not all(
        path.is_file()
        for path in (
            SCENE_PATH,
            PANEL_PATH,
            GRAPH_PATH,
            OPENMETEO_WEATHER_PATH,
            OPENMETEO_AIR_QUALITY_PATH,
        )
    ),
    reason="requires local Chongqing public-proxy integration evidence",
)


def test_chongqing_adapter_builds_complete_public_proxy_three_geometry_dataset():
    dataset = _dataset()

    validation = validate_uwm_geospatial_state_prior_dataset(dataset)

    assert validation == {"valid": True, "errors": []}
    assert dataset["source_evidence_kind"] == "public_proxy"
    assert dataset["adapter_audit"] == {
        "scene_admin_unit_count": 36,
        "matched_panel_unit_count": 36,
        "matched_graph_node_count": 36,
        "row_count": 252,
        "route_join_key": "county_and_township",
        "complete_three_route_join": True,
        "dynamic_context_date_count": 7,
        "dynamic_context_complete": True,
    }
    assert len(dataset["rows"]) == 252
    assert dataset["target"]["source_boundary"] == (
        "public_gridded_product_not_station_observation"
    )
    assert set(dataset["geometry_routes"]) == {"raster", "admin", "graph_object"}
    assert dataset["dynamic_context"]["uses_target_values"] is False
    assert dataset["dynamic_context"]["shared_across_spatial_units"] is True
    assert set(dataset["rows"][0]["dynamic_context_features"]) == set(
        dataset["dynamic_context"]["feature_names"]
    )


def test_chongqing_public_proxy_benchmark_remains_exploratory():
    benchmark = build_uwm_geospatial_state_prior_benchmark(
        dataset=_dataset(),
        benchmark_id="chongqing-public-proxy-three-geometry-state-prior-test",
        created_at="2026-08-04T14:00:00Z",
    )

    assert validate_uwm_geospatial_state_prior_benchmark(benchmark) == {
        "valid": True,
        "errors": [],
    }
    assert benchmark["source_evidence_kind"] == "public_proxy"
    assert (
        benchmark["benchmark_protocol"]["dynamic_context_shared_by_all_primary_ridge_variants"]
        is True
    )
    assert "openmeteo_pm25_mean_ugm3" in benchmark["benchmark_protocol"]["query_context_features"]
    assert benchmark["readiness_gates"]["strict_holdout_leakage_audits_passed"] is True
    assert benchmark["readiness_gates"]["observed_holdout_evidence_present"] is False
    assert benchmark["readiness_gates"]["dynamic_context_ablation_gate_passed"] is False
    assert benchmark["readiness_gates"]["dynamic_context_sample_support_gate_passed"] is False
    assert benchmark["dynamic_context_audit"]["feature_count"] == 5
    assert benchmark["dynamic_context_audit"]["future_split_train_time_group_count"] == 5
    assert benchmark["dynamic_context_audit"]["minimum_required_train_time_groups"] == 15
    aggregate = benchmark["aggregate_results"]
    assert (
        aggregate["multi_geometry_soft_alignment_ridge"]["mean_mae"]
        > aggregate["multi_geometry_no_dynamic_context_ridge"]["mean_mae"]
    )
    assert benchmark["geospatial_state_prior_benchmark_ready"] is False
    assert benchmark["supported_claim"] == "multi_geometry_benchmark_execution_only"
    assert benchmark["claim_boundary"]["max_claim_level"] == "exploratory_only"
    assert benchmark["policy_causal_effect_claim"] is False
    assert benchmark["action_conditioned_dynamics_claim"] is False


def test_chongqing_public_proxy_benchmark_is_rejected_by_kernel_admission():
    benchmark = build_uwm_geospatial_state_prior_benchmark(
        dataset=_dataset(),
        benchmark_id="chongqing-public-proxy-kernel-admission-test",
        created_at="2026-08-04T14:10:00Z",
    )

    admission = build_state_prior_admission(
        benchmark=benchmark,
        state_prior_artifact=_candidate_artifact(benchmark),
        admission_id="chongqing-public-proxy-kernel-admission",
        created_at="2026-08-04T14:15:00Z",
    )

    assert admission["status"] == "rejected"
    assert admission["state_prior_context_ready"] is False
    assert admission["context_envelope"] is None
    assert admission["enabled_support_levels"] == []
    assert "benchmark_ready" in admission["rejection_reasons"]
    assert "observed_holdout_evidence" in admission["rejection_reasons"]
    assert "all_readiness_gates_passed" in admission["rejection_reasons"]
    assert "bounded_support_claim" in admission["rejection_reasons"]
    assert "uncertainty_calibrated" in admission["rejection_reasons"]
    assert validate_state_prior_admission(admission) == {"valid": True, "errors": []}


def test_dynamic_context_target_leakage_metadata_is_rejected():
    dataset = _dataset()
    leaked_dataset = copy.deepcopy(dataset)
    leaked_dataset["dynamic_context"]["uses_target_values"] = True

    dataset_validation = validate_uwm_geospatial_state_prior_dataset(leaked_dataset)

    assert not dataset_validation["valid"]
    assert "dynamic_context.uses_target_values must be false" in dataset_validation["errors"]

    benchmark = build_uwm_geospatial_state_prior_benchmark(
        dataset=dataset,
        benchmark_id="chongqing-dynamic-context-leakage-validation-test",
        created_at="2026-08-04T14:05:00Z",
    )
    leaked_benchmark = copy.deepcopy(benchmark)
    leaked_benchmark["dynamic_context"]["uses_target_values"] = True

    benchmark_validation = validate_uwm_geospatial_state_prior_benchmark(leaked_benchmark)

    assert not benchmark_validation["valid"]
    assert "dynamic_context.uses_target_values must be false" in benchmark_validation["errors"]


def _dataset() -> dict:
    return build_chongqing_pm25_state_prior_dataset(
        scene_aligned_holdout=_read_json(SCENE_PATH),
        admin_livability_panel=_read_json(PANEL_PATH),
        admin_spatial_graph=_read_json(GRAPH_PATH),
        dataset_id="chongqing-three-geometry-pm25-public-proxy-test",
        created_at="2026-08-04T14:00:00Z",
        evidence_refs=[
            str(SCENE_PATH.relative_to(ROOT)),
            str(PANEL_PATH.relative_to(ROOT)),
            str(GRAPH_PATH.relative_to(ROOT)),
            str(OPENMETEO_WEATHER_PATH.relative_to(ROOT)),
            str(OPENMETEO_AIR_QUALITY_PATH.relative_to(ROOT)),
        ],
        openmeteo_weather_payload=_read_json(OPENMETEO_WEATHER_PATH),
        openmeteo_air_quality_payload=_read_json(OPENMETEO_AIR_QUALITY_PATH),
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_artifact(benchmark: dict) -> dict:
    parameter_ref = "artifact://chongqing-state-prior-parameters"
    benchmark_evidence = list(benchmark["evidence_refs"])
    evidence_refs = [*benchmark_evidence, parameter_ref]
    confidence_level = benchmark["uncertainty_calibration"]["confidence_level"]
    return {
        "schema": STATE_PRIOR_ARTIFACT_SCHEMA,
        "state_prior_id": "chongqing-public-proxy-candidate-prior",
        "benchmark_id": benchmark["benchmark_id"],
        "context_ref": "artifact://chongqing-state-prior-context",
        "context_sha256": "b" * 64,
        "source_evidence_kind": "observed_holdout",
        "derivation_kind": "observed_holdout_state_reconstruction",
        "support_level": "learned_calibrated",
        "state_variables": ["daily_pm25_ugm3"],
        "evidence_refs": evidence_refs,
        "provenance": {
            "model_id": "chongqing-multi-geometry-prior-candidate",
            "model_version": "0.1",
            "parameter_ref": parameter_ref,
            "evidence_refs": [benchmark_evidence[0], parameter_ref],
        },
        "geometry_coverage": {
            "routes": list(REQUIRED_GEOMETRY_ROUTES),
            "coverage_scope": "benchmark_geometry_routes",
        },
        "uncertainty": {
            "calibrated": True,
            "representation": "two_sided_prediction_interval",
            "confidence_level": confidence_level,
        },
        "calibration": {
            "method": benchmark["uncertainty_calibration"]["method"],
            "benchmark_id": benchmark["benchmark_id"],
            "holdout_validated": True,
            "confidence_level": confidence_level,
            "evidence_refs": [benchmark_evidence[0]],
        },
        "target_leakage_audit": {
            "passed": True,
            "uses_target_values": False,
            "holdout_membership_used_for_fit": False,
        },
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "policy_causal_effect_claim": False,
        "action_conditioned_dynamics_claim": False,
        "general_geospatial_world_model_validation_claim": False,
        "empirical_policy_effect_claim": False,
    }
