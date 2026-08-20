from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from data_agent.uwm.abu_dhabi_flood import (
    ExposureImpactUnit,
    FloodImpactAssessmentPolicy,
    FloodImpactAssessmentWindow,
    InundationImpactUnit,
    build_flood_impact_receipt,
    evaluate_flood_impact,
    verify_flood_impact_receipt,
)


def _inundation_units() -> tuple[InundationImpactUnit, ...]:
    return (
        InundationImpactUnit(
            overlay_unit_id="unit-a",
            maximum_depth_m=0.35,
            inundation_duration_seconds=1200.0,
            inundated_area_m2=5000.0,
            provenance_id="fixture:hydraulic-unit-a",
        ),
        InundationImpactUnit(
            overlay_unit_id="unit-b",
            maximum_depth_m=0.80,
            inundation_duration_seconds=1800.0,
            inundated_area_m2=3000.0,
            provenance_id="fixture:hydraulic-unit-b",
        ),
        InundationImpactUnit(
            overlay_unit_id="unit-c",
            maximum_depth_m=0.05,
            inundation_duration_seconds=600.0,
            inundated_area_m2=2000.0,
            provenance_id="fixture:hydraulic-unit-c",
        ),
    )


def _exposure_units() -> tuple[ExposureImpactUnit, ...]:
    return (
        ExposureImpactUnit(
            overlay_unit_id="unit-a",
            population_count=1000.0,
            critical_facility_count=2,
            road_length_m=1500.0,
            plot_count=40,
            provenance_id="fixture:exposure-unit-a",
        ),
        ExposureImpactUnit(
            overlay_unit_id="unit-b",
            population_count=600.0,
            critical_facility_count=1,
            road_length_m=800.0,
            plot_count=20,
            provenance_id="fixture:exposure-unit-b",
        ),
        ExposureImpactUnit(
            overlay_unit_id="unit-c",
            population_count=400.0,
            critical_facility_count=1,
            road_length_m=500.0,
            plot_count=15,
            provenance_id="fixture:exposure-unit-c",
        ),
    )


def _window(**changes: object) -> FloodImpactAssessmentWindow:
    values: dict[str, object] = {
        "run_id": "abu-dhabi-flood-impact-synthetic-contract",
        "window_start_seconds": 0.0,
        "window_end_seconds": 3600.0,
        "crs": "EPSG:32640",
        "overlay_method": "synthetic_partition_fixture",
        "hydraulic_result_reference_id": "fixture:hydraulic-result",
        "exposure_snapshot_reference_id": "fixture:exposure-snapshot",
        "inundation_units": _inundation_units(),
        "exposure_units": _exposure_units(),
    }
    values.update(changes)
    return FloodImpactAssessmentWindow(**values)


def test_synthetic_impact_metrics_are_deterministic():
    quality = evaluate_flood_impact(_window(), FloodImpactAssessmentPolicy())

    assert quality["passed"] is True
    assert quality["failed_checks"] == []
    assert quality["metrics"] == {
        "overlay_unit_count": 3,
        "affected_overlay_unit_count": 2,
        "severe_overlay_unit_count": 1,
        "affected_inundated_area_m2": 8000.0,
        "severe_inundated_area_m2": 3000.0,
        "affected_population_count": 1600.0,
        "severe_population_count": 600.0,
        "affected_critical_facility_count": 3,
        "severe_critical_facility_count": 1,
        "affected_road_length_m": 2300.0,
        "severe_road_length_m": 800.0,
        "affected_plot_count": 60,
        "severe_plot_count": 20,
        "maximum_depth_m": 0.8,
        "maximum_inundation_duration_seconds": 1800.0,
    }
    assert quality["admission_effect"] == "none_diagnostic_metric_contract_only"


def test_duplicate_and_mismatched_overlay_units_are_rejected():
    inundation = _inundation_units()
    duplicate_inundation = (inundation[0], replace(inundation[1], overlay_unit_id="unit-a"))
    with pytest.raises(
        ValueError, match="flood_impact_inundation_unit_ids_must_be_unique"
    ):
        _window(inundation_units=duplicate_inundation)

    exposure = _exposure_units()
    duplicate_exposure = (exposure[0], replace(exposure[1], overlay_unit_id="unit-a"))
    with pytest.raises(
        ValueError, match="flood_impact_exposure_unit_ids_must_be_unique"
    ):
        _window(exposure_units=duplicate_exposure)

    mismatched = (exposure[0], exposure[1], replace(exposure[2], overlay_unit_id="unit-d"))
    with pytest.raises(ValueError, match="flood_impact_overlay_unit_sets_must_match"):
        _window(exposure_units=mismatched)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("maximum_depth_m", -0.1),
        ("inundation_duration_seconds", -1.0),
        ("inundated_area_m2", -1.0),
    ],
)
def test_negative_hydraulic_values_fail_closed(field: str, value: float):
    with pytest.raises(ValueError, match=f"flood_impact_{field}_invalid"):
        replace(_inundation_units()[0], **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("population_count", -1.0),
        ("critical_facility_count", -1),
        ("road_length_m", -1.0),
        ("plot_count", -1),
    ],
)
def test_negative_exposure_values_fail_closed(field: str, value: float | int):
    with pytest.raises(ValueError, match=f"flood_impact_{field}_invalid"):
        replace(_exposure_units()[0], **{field: value})


def test_window_duration_crs_overlay_and_real_evidence_fail_closed():
    too_long = replace(
        _inundation_units()[0], inundation_duration_seconds=3601.0
    )
    with pytest.raises(ValueError, match="flood_impact_duration_exceeds_window"):
        _window(inundation_units=(too_long, *_inundation_units()[1:]))
    with pytest.raises(ValueError, match="flood_impact_crs_must_be_epsg32640"):
        _window(crs="EPSG:4326")
    with pytest.raises(
        ValueError, match="flood_impact_direct_or_unapproved_overlay_forbidden"
    ):
        _window(overlay_method="direct_cross_database_id_join")
    with pytest.raises(ValueError, match="flood_impact_real_data_not_admitted"):
        _window(evidence_class="customer_rows")


@pytest.mark.parametrize(
    "flag",
    [
        "hydraulic_result_admitted",
        "common_geography_approved",
        "aggregate_impact_overlay_admitted",
        "production_admitted",
    ],
)
def test_contract_cannot_open_any_admission_flag(flag: str):
    with pytest.raises(ValueError, match="flood_impact_contract_cannot_grant_admission"):
        _window(**{flag: True})


def test_receipt_is_self_hashed_and_preserves_the_claim_boundary():
    receipt = build_flood_impact_receipt(
        _window(), FloodImpactAssessmentPolicy()
    )

    verify_flood_impact_receipt(receipt)
    assert receipt["status"] == "validated_synthetic_impact_contract_not_admitted"
    assert receipt["execution"] == {
        "actual_hydraulic_solver_result_consumed": False,
        "customer_liveability_rows_consumed": False,
        "cross_database_join_executed": False,
        "contract_only_synthetic_aggregation": True,
    }
    admission = receipt["admission"]
    assert admission["aggregate_impact_overlay_admitted"] is False
    assert admission["per_asset_identity_admitted"] is False
    assert admission["traditional_model_admitted"] is False
    assert admission["gwm_training_admitted"] is False
    assert admission["city_scale_prediction_claim_allowed"] is False


def test_receipt_hash_mismatch_is_rejected():
    receipt = build_flood_impact_receipt(
        _window(), FloodImpactAssessmentPolicy()
    )
    tampered = deepcopy(receipt)
    tampered["quality_gates"]["metrics"]["affected_population_count"] = 9999.0

    with pytest.raises(ValueError, match="flood_impact_receipt_sha256_mismatch"):
        verify_flood_impact_receipt(tampered)
