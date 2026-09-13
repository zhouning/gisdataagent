import json
from pathlib import Path

from data_agent.uwm.full_admin_service_surface_quality import (
    UWM_FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_SCHEMA,
    build_full_admin_service_surface_quality_audit,
    validate_full_admin_service_surface_quality_audit,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
SURFACE_PATH = (
    DATA_ROOT
    / "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json"
)
AUDIT_PATH = (
    DATA_ROOT
    / "full_admin_service_surface_quality_audit_2026_07_08/uwm_full_admin_service_surface_quality_audit.json"
)


def _surface_for_unit_test() -> dict:
    rows = []
    road_pattern = [2, 8, 3, 7, 4, 9, 1, 6, 5, 10, 2, 7]
    for index in range(12):
        nonessential = float(index + 1)
        road = float(road_pattern[index])
        rows.append(
            {
                "admin_unit_id": f"unit-{index}",
                "county": "A",
                "township": f"T{index}",
                "food_retail_count": nonessential,
                "finance_count": nonessential * 0.2,
                "mobility_transport_count": nonessential * 0.3,
                "civic_public_count": nonessential * 0.1,
                "recreation_count": nonessential * 0.4,
                "lodging_count": 0,
                "other_service_count": nonessential * 0.5,
                "essential_service_count": 4.0 + 2.0 * nonessential,
                "estimated_nearest_essential_travel_time_min": max(
                    0.2,
                    8.0 - 0.35 * road - 0.15 * nonessential,
                ),
                "road_segment_count": road,
                "road_length_km": road * 1.5,
                "mean_road_speed_kmh": 25.0 + index,
                "service_accessibility_score": min(1.0, 0.05 * index),
                "service_gap_score": max(0.0, 1.0 - 0.05 * index),
                "service_coverage_status": "covered_by_full_local_surface",
            }
        )
    return {
        "schema": "uwm.full_admin_service_accessibility_surface.v1",
        "surface_id": "unit-full-admin-service-surface",
        "created_at": "2026-07-08T16:30:00Z",
        "experiment_scope": "full_admin_graph",
        "source_feature_counts": {
            "admin_units": 12,
            "poi_points": 120,
            "roads": 12,
        },
        "admin_unit_count": 12,
        "coverage": {
            "service_missing_admin_count": 0,
            "admin_units_with_accessibility_score": 12,
            "admin_units_with_road_context": 12,
        },
        "admin_service_rows": rows,
        "supported_claim": (
            "full_admin_service_accessibility_surface_covers_all_admin_units_from_local_poi_and_road_assets"
        ),
        "claim_boundary": {"max_claim_level": "bounded_support"},
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
    }


def test_full_admin_service_surface_quality_audit_validates_proxy_coherence_without_policy_claim():
    audit = build_full_admin_service_surface_quality_audit(
        service_surface=_surface_for_unit_test(),
        audit_id="unit-full-admin-service-surface-quality-audit",
        created_at="2026-07-08T16:45:00Z",
    )

    validation = validate_full_admin_service_surface_quality_audit(audit)
    assert validation["valid"], validation["errors"]
    assert audit["schema"] == UWM_FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_SCHEMA
    assert audit["admin_unit_count"] == 12
    assert audit["endpoint_count"] == 2
    assert audit["full_admin_service_surface_quality_audit_ready"] is True
    assert audit["observed_trip_time_claim"] is False
    assert audit["observed_policy_outcome_superiority_claim"] is False
    assert audit["empirical_superiority_claim"] is False

    endpoints = {
        item["endpoint_id"]: item for item in audit["endpoint_evaluations"]
    }
    assert endpoints["essential_service_count_proxy"]["holdout_admin_unit_count"] == 12
    assert endpoints["essential_service_count_proxy"]["model_mae"] < endpoints[
        "essential_service_count_proxy"
    ]["best_baseline_mae"]
    assert endpoints["estimated_nearest_essential_travel_time_proxy"][
        "target_rotation_negative_control_mae"
    ] > endpoints["estimated_nearest_essential_travel_time_proxy"]["model_mae"]


def test_full_admin_service_surface_quality_audit_artifact_uses_all_surface_rows():
    assert AUDIT_PATH.exists()
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))

    validation = validate_full_admin_service_surface_quality_audit(audit)
    assert validation["valid"], validation["errors"]
    assert audit["schema"] == UWM_FULL_ADMIN_SERVICE_SURFACE_QUALITY_AUDIT_SCHEMA
    assert audit["source_surface_path"].endswith(
        "full_admin_service_accessibility_surface_2026_07_08/uwm_full_admin_service_accessibility_surface.json"
    )
    assert audit["admin_unit_count"] == 1017
    assert audit["source_feature_counts"]["admin_units"] == 1017
    assert audit["source_feature_counts"]["poi_points"] == 1194351
    assert audit["source_feature_counts"]["roads"] == 50366
    assert audit["coverage"]["service_missing_admin_count"] == 0
    assert audit["endpoint_count"] == 2
    assert audit["full_admin_service_surface_quality_audit_ready"] is True

    endpoints = {item["endpoint_id"]: item for item in audit["endpoint_evaluations"]}
    essential = endpoints["essential_service_count_proxy"]
    travel = endpoints["estimated_nearest_essential_travel_time_proxy"]
    assert essential["holdout_admin_unit_count"] == 1017
    assert essential["model_mae"] < essential["best_baseline_mae"]
    assert essential["mae_reduction_vs_best_baseline"] > 40
    assert essential["target_rotation_negative_control_passed"] is True
    assert travel["holdout_admin_unit_count"] == 1017
    assert travel["model_mae"] < travel["best_baseline_mae"]
    assert travel["target_rotation_negative_control_passed"] is True
    assert audit["supported_claim"] == (
        "full_admin_service_surface_proxy_quality_beats_static_and_negative_controls"
    )
    assert audit["observed_trip_time_claim"] is False
    assert audit["observed_policy_outcome_superiority_claim"] is False
    assert audit["empirical_superiority_claim"] is False
