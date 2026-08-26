from __future__ import annotations

from pathlib import Path

import pytest

from data_agent.uwm.abu_dhabi_flood.data_inventory import (
    INVENTORY_SCHEMA,
    build_inventory,
    render_inventory_markdown,
)

ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"


@pytest.fixture(scope="module")
def inventory() -> dict:
    pytest.importorskip("rasterio")
    if not (DATASET_ROOT / "online/weather/openmeteo_archive_abu_dhabi_20240415_20240417.json").is_file():
        pytest.skip("public stormwater data snapshot is not present in this checkout")
    return build_inventory(
        DATASET_ROOT,
        repository_root=ROOT,
        created_at="2026-08-18T00:00:00Z",
    )


def test_weather_inventory_prevents_nasa_hourly_unit_error(inventory):
    products = {item["product_id"]: item for item in inventory["weather"]["products"]}
    openmeteo = products["openmeteo_archive_point_hourly"]
    nasa_hourly = products["nasa_power_merra2_point_hourly"]
    nasa_daily = products["nasa_power_merra2_point_daily"]

    assert openmeteo["interval_count"] == 72
    assert openmeteo["total_interval_depth_mm"] == pytest.approx(67.8)
    assert nasa_hourly["source_unit"] == "mm/day"
    assert nasa_hourly["raw_value_sum_not_a_depth"] == pytest.approx(1036.17)
    assert nasa_hourly["total_interval_depth_mm"] == pytest.approx(43.17375)
    assert nasa_hourly["direct_raw_sum_forcing_forbidden"] is True
    assert nasa_daily["total_interval_depth_mm"] == pytest.approx(43.18)
    assert inventory["weather"]["observed_rainfall_available"] is False


def test_dem_inventory_records_grid_statistics_and_disagreement(inventory):
    rasters = {item["product_id"]: item for item in inventory["terrain"]["rasters"]}
    srtm = rasters["srtm_30m_clipped_epsg32640"]
    copernicus = rasters["copernicus_dem_30m_clipped_epsg32640"]
    difference = inventory["terrain"]["srtm_minus_copernicus"]

    assert (srtm["width"], srtm["height"]) == (1606, 1213)
    assert srtm["resolution"] == [30.0, 30.0]
    assert srtm["valid_pixel_percent"] == pytest.approx(100.0)
    assert srtm["minimum_m"] == pytest.approx(-69.0)
    assert copernicus["mean_m"] == pytest.approx(9.787823, abs=1e-6)
    assert difference["comparable"] is True
    assert difference["mean_difference_m"] == pytest.approx(-2.386821, abs=1e-6)
    assert difference["root_mean_square_error_m"] == pytest.approx(5.739833, abs=1e-6)
    assert difference["products_interchangeable_without_vertical_validation"] is False


def test_smartmakani_inventory_surfaces_useful_network_and_observation_limits(inventory):
    layers = {item["layer_id"]: item for item in inventory["smartmakani"]["layers"]}
    pipeline = layers[37]

    assert pipeline["feature_count"] == 213_414
    assert pipeline["target_bbox_feature_count"] == 198_263
    assert pipeline["service_extent"]["wkid"] == 32640
    assert pipeline["source_spatial_reference_wkid"] == 4326
    assert {
        "ASSET_DIAMETER",
        "INVERT_LEVEL_UP",
        "INVERT_LEVEL_DOWN",
        "Start_X",
        "Start_Y",
        "End_X",
        "End_Y",
        "OUTFALL_NAME",
    }.issubset(pipeline["hydraulic_candidate_fields_present"])
    assert pipeline["data_quality_flags"]["zero_diameter_present"] is True
    assert pipeline["data_quality_flags"]["invert_sentinel_or_outlier_present"] is True
    assert pipeline["frozen_feature_snapshot"]["record_count"] == 195_184
    assert pipeline["frozen_feature_snapshot"]["record_count_delta_from_baseline"] == -3_079
    assert pipeline["frozen_feature_snapshot"]["truncated"] is False
    assert inventory["smartmakani"]["snapshot_contains_feature_rows"] is True
    assert layers[2]["frozen_feature_snapshot"]["null_geometry_count"] == 1
    assert layers[3]["frozen_feature_snapshot"]["null_geometry_count"] == 12
    assert layers[30]["covers_target_2024_event"] is False
    assert layers[30]["incident_measure_fields"] == []
    assert inventory["smartmakani"]["mims_display_sublayer_warning"][
        "treat_as_independent_datasets"
    ] is False
    assert inventory["smartmakani"]["mims_display_sublayer_warning"][
        "frozen_object_ids_and_feature_rows_identical"
    ] is True


def test_smartmakani_surface_support_remains_candidate_only(inventory):
    surface = inventory["smartmakani"]["supporting_surface_candidate"]
    summary = surface["surface_candidate_summary"]
    layers = {item["dataset_key"]: item for item in surface["layers"]}

    assert surface["available"] is True
    assert layers["contour_2017_zone40"]["record_count"] == 435_941
    assert layers["contour_2017_zone40"]["page_count"] == 436
    assert layers["bathymetry_2017"]["record_count"] == 288
    assert layers["building_survey"]["record_count"] == 151_861
    assert layers["building_survey"]["geometry"]["invalid_count"] == 2
    assert all(
        item["spatial_selection"]["returned_geometry_clipped_to_request_bbox"]
        is False
        for item in layers.values()
    )
    assert summary["vertical_datum_verified"] is False
    assert summary["returned_geometries_clipped_to_target_bbox"] is False
    assert summary["surface_patch_contract_compiled"] is False
    assert surface["admission"]["k0_opened"] is False

    clipped = inventory["smartmakani"]["target_clipped_surface_candidate"]
    clipped_layers = {item["dataset_key"]: item for item in clipped["datasets"]}
    assert clipped["available"] is True
    assert clipped_layers["contour_2017_zone40"]["source_record_count"] == 435_941
    assert clipped_layers["contour_2017_zone40"]["output_record_count"] == 427_157
    assert clipped_layers["contour_2017_zone40"][
        "dropped_after_selection_count"
    ] == 8_784
    assert clipped_layers["bathymetry_2017"]["output_record_count"] == 288
    assert clipped_layers["building_survey"]["output_record_count"] == 151_861
    assert clipped["summary"]["building_geometry_repaired_count"] == 2
    assert clipped["summary"]["output_invalid_geometry_count"] == 0
    assert clipped["summary"]["output_outside_target_count"] == 0
    assert clipped["summary"]["output_has_z_count"] == 0
    assert clipped["summary"]["vertical_datum_verified"] is False
    assert clipped["summary"]["surface_patch_contract_compiled"] is False
    assert clipped["admission"]["k0_opened"] is False


def test_runtime_catalog_and_k0_remain_evidence_gated(inventory):
    runtime = inventory["registered_makani_runtime_catalog"]
    resources = {item["physical_resource"]: item for item in runtime["key_resources"]}

    assert inventory["schema"] == INVENTORY_SCHEMA
    assert resources["layer.st_pipeline"]["estimated_record_count"] == 260_725
    assert resources["layer.st_inlet"]["estimated_record_count"] == 167_459
    assert resources["layer.st_ps_pump"]["estimated_record_count"] == 103
    assert runtime["declared_foreign_key_count"] == 0
    assert inventory["public_vs_registered_pipeline"]["counts_match"] is False
    assert inventory["public_vs_registered_pipeline"]["absolute_count_delta"] == 47_311
    assert inventory["public_vs_registered_pipeline"]["registered_target_feature_count"] == 235_842
    assert inventory["public_vs_registered_pipeline"]["target_count_delta"] == 40_658
    assert inventory["public_vs_registered_pipeline"][
        "geometry_crosswalk_candidate_count"
    ] == 156_490
    assert inventory["k0_data_gate"]["passed"] is False
    assert inventory["k0_data_gate"]["status"] == "closed_not_admitted"
    assert inventory["model_admission"] == {
        "diagnostic_only": True,
        "operator_admitted": False,
        "calibration_admitted": False,
        "city_scale_prediction_claim_allowed": False,
    }


def test_customer_postgres_audit_is_row_free_and_not_admitted(inventory):
    audit = inventory["makani_postgres_source_audit"]
    tables = {item["table"]: item for item in audit["tables"]}
    endpoint_rows = {
        item["side"]: item
        for item in audit["pipeline_endpoint_facility_probe"]["rows"]
    }

    assert audit["available"] is True
    assert audit["contains_source_rows"] is False
    assert audit["k0_status"] == "closed_not_admitted"
    assert audit["summary"]["tables_inspected"] == 18
    assert audit["summary"]["tables_without_foreign_key"] == 18
    assert tables["pipeline"]["row_count"] == 260_725
    assert tables["inlet"]["row_count"] == 167_459
    assert tables["catchbasin"]["row_count"] == 34_292
    assert tables["manholechamber"]["row_count"] == 0
    assert tables["sw_flowmeter"]["row_count"] == 0
    assert endpoint_rows["asset_before"]["matched_row_rate"] == pytest.approx(
        0.722858
    )
    assert endpoint_rows["asset_after"]["matched_row_rate"] == pytest.approx(
        0.688728
    )
    assert audit["admission"] == {
        "traditional_model_admitted": False,
        "gwm_training_admitted": False,
        "hybrid_planner_admitted": False,
        "city_scale_prediction_claim_allowed": False,
    }


def test_customer_liveability_postgres_audit_is_impact_only_and_not_admitted(inventory):
    audit = inventory["liveability_postgres_source_audit"]
    resources = {item["resource"]: item for item in audit["resources"]}

    assert audit["available"] is True
    assert audit["contains_source_rows"] is False
    assert audit["k0_status"] == "closed_not_admitted"
    assert audit["summary"]["resources_requested"] == 31
    assert audit["summary"]["resources_found"] == 31
    assert audit["summary"]["declared_foreign_key_count"] == 6
    assert resources["dim_districts"]["row_count"] == 216
    assert resources["dim_facilities"]["row_count"] == 131_915
    assert resources["dim_udm_plots"]["row_count"] == 390_613
    assert resources["fact_population"]["row_count"] == 2_953
    assert resources["nrn_road_edges"]["row_count"] == 414_546
    assert resources["fact_prioritization_runs"]["readiness_role"] == (
        "planning_run_context_candidate"
    )
    assert resources["sim_scenarios"]["row_count"] == 0
    probes = {item["child"]: item for item in audit["relationship_probes"]}
    assert probes["public.fact_prioritization_cost_outputs.run_id"][
        "matched_row_rate"
    ] == pytest.approx(1.0)
    assert audit["admission"] == {
        "traditional_model_admitted": False,
        "gwm_training_admitted": False,
        "hybrid_planner_admitted": False,
        "city_scale_prediction_claim_allowed": False,
    }


def test_cross_source_geography_audit_keeps_identity_and_k0_closed(inventory):
    audit = inventory["cross_source_geography_audit"]
    relationships = {(item["left"], item["right"]): item for item in audit["results"]}
    pipeline_district = relationships[
        (
            "makani.public.pipeline.zone_or_district_code",
            "liveability.public.dim_districts.district_id",
        )
    ]
    plot = relationships[
        (
            "makani.public.udm_plot.plotid",
            "liveability.public.dim_udm_plots.plotid",
        )
    ]

    assert audit["available"] is True
    assert audit["contains_source_rows"] is False
    assert audit["contains_source_identifier_values"] is False
    assert audit["k0_status"] == "closed_not_admitted"
    assert pipeline_district["overlapping_distinct_values"] == 0
    assert plot["overlapping_distinct_values"] == 362_746
    assert plot["left_distinct_overlap_rate"] == pytest.approx(0.912291)
    assert plot["right_distinct_overlap_rate"] == pytest.approx(0.960245)
    assert plot["identity_or_hydraulic_connectivity_established"] is False
    assert audit["admission"]["aggregate_impact_overlay_admitted"] is False
    assert audit["admission"]["per_asset_identity_admitted"] is False


def test_registered_snapshot_and_crosswalk_remain_candidate_only(inventory):
    registered = inventory["registered_makani_spatial_snapshot"]
    crosswalk = registered["crosswalk_candidate"]
    network = registered["network_candidate"]
    readiness = registered["hybrid_readiness"]

    assert registered["available"] is True
    assert registered["record_count"] == 449_682
    assert registered["page_count"] == 101
    assert registered["privacy"]["contains_personal_fields"] is False
    assert registered["relationship_probe"]["outfall_identifier_match_count"] == 0
    assert registered["relationship_probe"]["pump_station_identifier_match_count"] == 0
    assert registered["explicit_identifier_match_available"] is False
    assert crosswalk["accepted_crosswalk_count"] == 156_490
    assert crosswalk["facility_attachment_count"] == 362_227
    assert crosswalk["within_1m_count"] == 362_042
    assert crosswalk["authoritative_identity_established"] is False
    assert crosswalk["authoritative_connectivity_established"] is False
    assert crosswalk["admitted"] is False
    assert network["pipeline_count"] == 235_842
    assert network["node_count"] == 234_900
    assert network["connected_component_count"] == 1_633
    assert network["node_facility_candidate_count"] == 193_908
    assert network["mapped_pipeline_endpoint_count"] == 362_031
    assert network["residual_unmatched_pipeline_endpoint_count"] == 109_653
    assert network["nodes_with_outfall_candidate_count"] == 216
    assert network["nodes_with_pump_candidate_count"] == 61
    assert network["source_target_node_labels_are_verified_hydraulic_direction"] is False
    assert network["outfall_or_pump_connectivity_authoritative"] is False
    assert network["nodes_are_surface_patches"] is False
    assert network["admitted"] is False
    assert network["flood_network_contract_compiled"] is False
    assert readiness["schema"] == "gwm.abu_dhabi_flood.hybrid_readiness.v1"
    assert readiness["blocker_count"] == 5
    gates = {item["gate_id"]: item for item in readiness["gates"]}
    assert gates["candidate_data_foundation"]["status"] == "candidate_ready"
    assert gates["traditional_hydraulic_baseline"]["status"] == "blocked"
    assert gates["gwm_training_panel"]["status"] == "blocked"
    assert (
        gates["hybrid_planner_contract"]["status"]
        == "contract_ready_not_executable"
    )
    assert readiness["admission"]["city_scale_prediction_claim_allowed"] is False
    assert readiness["target_clipped_surface_candidate_summary"][
        "output_record_count"
    ] == 579_306
    assert readiness["target_clipped_surface_candidate_summary"][
        "surface_patch_contract_compiled"
    ] is False


def test_compiled_pipeline_topology_remains_a_diagnostic_candidate(inventory):
    topology = inventory["smartmakani"]["pipeline_topology_candidate"]

    assert topology["available"] is True
    assert topology["pipeline_count"] == 195_184
    assert topology["node_count"] == 194_808
    assert topology["connected_component_count"] == 883
    assert topology["self_loop_count"] == 293
    assert topology["duplicate_node_pair_group_count"] == 624
    assert topology["geometry_z_both_zero_percent"] == pytest.approx(57.121485)
    assert topology["geometry_z_match_percent_of_comparable_rows"] == pytest.approx(
        37.883892,
        abs=1e-6,
    )
    assert topology["geometry_z_source_unit_or_datum_verified"] is False
    assert topology["admitted"] is False
    assert topology["flood_network_contract_compiled"] is False


def test_artifacts_are_hashed_and_report_keeps_claim_boundary(inventory):
    assert inventory["artifacts"]
    assert all(len(item["sha256"]) == 64 for item in inventory["artifacts"])
    assert all(item["size_bytes"] > 0 for item in inventory["artifacts"])
    public_pages = [
        item
        for item in inventory["artifacts"]
        if item["origin"] == "downloaded_public_arcgis_feature_snapshot"
    ]
    assert len(public_pages) == 202
    assert all(item["contains_source_rows"] is True for item in public_pages)
    assert all(item["public_feature_rows"] is True for item in public_pages)
    assert all(item["contains_personal_fields"] is False for item in public_pages)
    assert all(
        item["calibration_admission"] == "not_admitted_for_calibration"
        for item in public_pages
    )
    surface_pages = [
        item
        for item in inventory["artifacts"]
        if item["origin"] == "downloaded_public_surface_support_snapshot"
    ]
    assert len(surface_pages) == 589
    assert all(item["contains_source_rows"] is True for item in surface_pages)
    assert all(item["public_feature_rows"] is True for item in surface_pages)
    assert all(item["contains_personal_fields"] is False for item in surface_pages)
    assert all(
        item["calibration_admission"] == "not_admitted_for_calibration"
        for item in surface_pages
    )
    clipped_pages = [
        item
        for item in inventory["artifacts"]
        if item["origin"] == "derived_target_clipped_surface_candidate"
    ]
    assert len(clipped_pages) == 589
    assert all(item["contains_source_rows"] is True for item in clipped_pages)
    assert all(item["public_feature_rows"] is True for item in clipped_pages)
    assert all(item["contains_raw_asset_identifiers"] is True for item in clipped_pages)
    assert all(item["contains_personal_fields"] is False for item in clipped_pages)
    clipped_controls = [
        item
        for item in inventory["artifacts"]
        if item["origin"] == "derived_target_clipped_surface_candidate_control"
    ]
    assert len(clipped_controls) == 4
    assert all(item["contains_source_rows"] is False for item in clipped_controls)
    registered_pages = [
        item
        for item in inventory["artifacts"]
        if item["origin"] == "registered_makani_field_minimized_feature_snapshot"
    ]
    assert len(registered_pages) == 101
    assert all(item["contains_source_rows"] is True for item in registered_pages)
    assert all(item["contains_personal_fields"] is False for item in registered_pages)
    readiness_artifacts = [
        item
        for item in inventory["artifacts"]
        if item["origin"] == "derived_abu_dhabi_hybrid_readiness_audit"
    ]
    assert len(readiness_artifacts) == 1
    assert readiness_artifacts[0]["contains_source_rows"] is False
    assert readiness_artifacts[0]["contains_raw_asset_identifiers"] is False
    derived_rows = [
        item
        for item in inventory["artifacts"]
        if item["origin"] == "derived_local_hydraulic_candidate"
        and item["contains_source_rows"]
    ]
    assert {Path(item["path"]).suffix for item in derived_rows} == {".parquet", ".gpkg"}
    downloaded = [
        item
        for item in inventory["artifacts"]
        if item["origin"].startswith("downloaded_public")
        or item["origin"].startswith("anonymous_arcgis")
    ]
    assert downloaded
    assert all(item.get("source_url", "").startswith("https://") for item in downloaded)

    report = render_inventory_markdown(inventory)
    assert "K0 closed" in report
    assert "195,184" in report
    assert "198,263" in report
    assert "883" in report
    assert "禁止作为模型强迫" in report
    assert "不能互相替代" in report
    assert "449,682" in report
    assert "156,490" in report
    assert "362,227" in report
    assert "234,900" in report
    assert "193,908" in report
    assert "109,653" in report
    assert "contract_ready_not_executable" in report
    assert "liveability_data_20260730.public" in report
    assert "414,546" in report
    assert "impact/exposure" in report
    assert "362,746" in report
    assert "91.23%" in report
    assert "per_asset_identity_admitted=false" in report
    assert "234,664" in report
    assert "2,248" in report
    assert "435,941" in report
    assert "151,861" in report
    assert "427,157" in report
    assert "8,784" in report
    assert "完整几何" in report
    assert "2` 个无效几何" in report
