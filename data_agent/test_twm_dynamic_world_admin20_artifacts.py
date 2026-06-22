from __future__ import annotations

import json
from pathlib import Path

import pytest


MANIFEST = Path("data/twm_public_landcover/gee_dynamic_world/twm_dynamic_world_manifest.json")
DOWNLOAD_STATUS = Path("docs/reports/twm_gee_dynamic_world_download_status_2026-06-22.json")
BENCHMARK_REPORT = Path("docs/reports/twm_dynamic_world_admin20_benchmark_2026-06-22.json")


@pytest.mark.skipif(not MANIFEST.exists(), reason="GEE Dynamic World admin20 manifest is not available")
def test_dynamic_world_admin20_manifest_contains_real_multi_region_time_series() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected_drivers = {"srtm_elevation", "srtm_slope", "viirs_nightlight_mean"}

    assert manifest["source"]["collection"] == "GOOGLE/DYNAMICWORLD/V1"
    assert manifest["source"]["project"] == "ee-zn19860115"
    assert manifest["source"]["include_drivers"] is True
    assert set(manifest["source"]["driver_layers"]) == expected_drivers
    assert manifest["years"] == [2017, 2018, 2019, 2020, 2021, 2022, 2023]
    assert len(manifest["regions"]) == 20
    assert all(region.get("admin") for region in manifest["regions"])
    assert all(region.get("geometry") for region in manifest["regions"])
    assert all(len(region["raster_stack"]) == 7 for region in manifest["regions"])
    assert all(len(region["driver_layers"]) == 3 for region in manifest["regions"])
    assert all(
        {driver["name"] for driver in region["driver_layers"]} == expected_drivers
        for region in manifest["regions"]
    )
    assert all(frame["nodata"] == -32768 for region in manifest["regions"] for frame in region["raster_stack"])
    assert all(driver["nodata"] == -32768 for region in manifest["regions"] for driver in region["driver_layers"])
    assert sum(1 for region in manifest["regions"] for frame in region["raster_stack"] if (MANIFEST.parent / frame["path"]).exists()) == 140
    assert (
        sum(
            1
            for region in manifest["regions"]
            for driver in region["driver_layers"]
            if (MANIFEST.parent / driver["path"]).exists()
        )
        == 60
    )


@pytest.mark.skipif(not DOWNLOAD_STATUS.exists(), reason="GEE Dynamic World download status report is not available")
def test_dynamic_world_admin20_download_status_passed() -> None:
    status = json.loads(DOWNLOAD_STATUS.read_text(encoding="utf-8"))

    assert status["status"] == "pass"
    assert status["project"] == "ee-zn19860115"
    assert status["downloaded_region_count"] == 20
    assert status["downloaded_raster_count"] == 140
    assert status["downloaded_driver_count"] == 60
    assert status["failed_count"] == 0


@pytest.mark.skipif(not BENCHMARK_REPORT.exists(), reason="TWM Dynamic World admin20 benchmark report is not available")
def test_dynamic_world_admin20_benchmark_report_has_forecast_and_oracle_results() -> None:
    report = json.loads(BENCHMARK_REPORT.read_text(encoding="utf-8"))
    summary = report["summary"]["aggregate_by_candidate"]
    component_rows = {
        row["component"]: row for row in report["summary"]["aggregate_component_diagnostics"]["rows"]
    }

    assert report["status"] == "pass"
    assert report["source"]["declared_source"]["include_drivers"] is True
    assert report["source"]["declared_source"]["driver_layers"] == [
        "srtm_elevation",
        "srtm_slope",
        "viirs_nightlight_mean",
    ]
    assert report["data_profile"]["region_count"] == 20
    assert report["data_profile"]["case_count"] == 100
    assert all(len(region["driver_layers"]) == 3 for region in report["data_profile"]["regions"])
    assert summary["twm_independent_transition_forecast_demand"]["mean_change_fom"] > summary["markov_transition_projection"]["mean_change_fom"]
    assert summary["twm_hierarchical_transition_forecast_demand"]["mean_change_fom"] > summary["markov_transition_projection"]["mean_change_fom"]
    assert summary["twm_calibrated_hierarchical_transition_forecast_demand"]["mean_change_fom"] > summary["markov_transition_projection"]["mean_change_fom"]
    assert summary["twm_cross_region_smoothed_transition_forecast_demand"]["mean_change_fom"] > summary["markov_transition_projection"]["mean_change_fom"]
    assert summary["twm_independent_transition_forecast_demand"]["mean_change_fom"] > summary["twm_ablation_no_neighborhood_forecast_demand"]["mean_change_fom"]
    assert summary["twm_independent_transition_forecast_demand"]["mean_change_fom"] >= summary["twm_cross_region_smoothed_transition_forecast_demand"]["mean_change_fom"]
    assert summary["twm_ablation_no_drivers_forecast_demand"]["mean_change_fom"] >= summary["twm_independent_transition_forecast_demand"]["mean_change_fom"]
    assert summary["twm_independent_transition_forecast_demand"]["total_target_demand_abs_error"] == 0
    assert summary["twm_hierarchical_transition_forecast_demand"]["total_target_demand_abs_error"] == 0
    assert summary["twm_calibrated_hierarchical_transition_forecast_demand"]["total_target_demand_abs_error"] == 0
    assert summary["twm_cross_region_smoothed_transition_forecast_demand"]["total_target_demand_abs_error"] == 0
    assert summary["twm_independent_transition_oracle_demand"]["total_oracle_demand_abs_error"] == 0
    assert summary["twm_ablation_no_demand_projection"]["total_target_demand_abs_error"] > 0
    assert component_rows["transition_surface_vs_markov"]["change_fom_delta_full_minus_comparison"] > 0
    assert component_rows["hierarchical_pooling_candidate"]["change_fom_delta_full_minus_comparison"] >= 0
    assert component_rows["calibrated_hierarchical_pooling_candidate"]["change_fom_delta_full_minus_comparison"] >= 0
    assert (
        component_rows["calibrated_hierarchical_pooling_candidate"]["change_fom_delta_full_minus_comparison"]
        < component_rows["hierarchical_pooling_candidate"]["change_fom_delta_full_minus_comparison"]
    )
    assert component_rows["cross_region_transition_smoothing_candidate"]["change_fom_delta_full_minus_comparison"] >= 0
    assert component_rows["neighborhood_context"]["change_fom_delta_full_minus_comparison"] > 0
    assert component_rows["external_drivers"]["change_fom_delta_full_minus_comparison"] <= 0
    assert component_rows["demand_projection_constraint"]["target_demand_abs_error_delta_full_minus_comparison"] < 0

    diagnostics = report["summary"]["training_diagnostics_by_candidate"]["twm_independent_transition_forecast_demand"]
    assert diagnostics["case_count"] == 100
    assert diagnostics["source_class_count"] == 900
    assert diagnostics["fitted_source_class_count"] > 0
    assert diagnostics["fallback_source_class_count"] > 0
    assert sum(diagnostics["solver_counts"].values()) == diagnostics["fitted_source_class_count"]
    assert diagnostics["source_status_counts"]["fit"] == diagnostics["fitted_source_class_count"]
    assert diagnostics["source_status_counts"]["fallback_global_prior"] == diagnostics["fallback_source_class_count"]

    hierarchical = report["summary"]["training_diagnostics_by_candidate"]["twm_hierarchical_transition_forecast_demand"]
    assert hierarchical["case_count"] == 100
    assert hierarchical["source_class_count"] == 900
    assert hierarchical["fitted_source_class_count"] == diagnostics["fitted_source_class_count"]
    assert hierarchical["pooled_fallback_source_class_count"] == diagnostics["fallback_source_class_count"]
    assert hierarchical["hard_fallback_source_class_count"] == 0
    assert hierarchical["local_or_pooled_model_source_class_count"] == hierarchical["source_class_count"]
    assert hierarchical["source_status_counts"]["pooled_fallback"] == hierarchical["pooled_fallback_source_class_count"]
    assert hierarchical["mean_pooled_fallback_weight"] == 1.0

    calibrated = report["summary"]["training_diagnostics_by_candidate"]["twm_calibrated_hierarchical_transition_forecast_demand"]
    assert calibrated["case_count"] == 100
    assert calibrated["source_class_count"] == 900
    assert calibrated["fitted_source_class_count"] == diagnostics["fitted_source_class_count"]
    assert calibrated["pooled_fallback_source_class_count"] == diagnostics["fallback_source_class_count"]
    assert calibrated["hard_fallback_source_class_count"] == 0
    assert calibrated["local_or_pooled_model_source_class_count"] == calibrated["source_class_count"]
    assert 0.0 < calibrated["mean_pooled_fallback_weight"] < hierarchical["mean_pooled_fallback_weight"]
    assert calibrated["source_status_counts"]["pooled_fallback"] == calibrated["pooled_fallback_source_class_count"]

    cross_region = report["summary"]["training_diagnostics_by_candidate"]["twm_cross_region_smoothed_transition_forecast_demand"]
    assert cross_region["case_count"] == 100
    assert cross_region["source_class_count"] == 900
    assert cross_region["fitted_source_class_count"] == 0
    assert cross_region["cross_region_supported_source_class_count"] == cross_region["source_class_count"]
    assert 0 < cross_region["cross_region_smoothed_source_class_count"] < cross_region["source_class_count"]
    assert cross_region["cross_region_supported_source_class_rate"] == 1.0
    assert 0.0 < cross_region["cross_region_smoothed_source_class_rate"] < 1.0
    assert 0.0 < cross_region["mean_smoothing_weight"] < 0.35
    assert cross_region["source_status_counts"]["cross_region_smoothed"] == cross_region["cross_region_smoothed_source_class_count"]
