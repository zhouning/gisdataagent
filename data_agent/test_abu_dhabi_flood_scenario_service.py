"""Contract tests for the interactive Abu Dhabi SWMM scenario service."""

from __future__ import annotations

from datetime import datetime

import pytest

import data_agent.abu_dhabi_flood_scenario_service as scenario_service
from data_agent.abu_dhabi_flood_scenario_service import (
    _rainfall_series,
    _parse_node_hydraulic_results,
    render_scenario_input,
    validate_scenario,
)


def _scenario(**overrides):
    value = {
        "scope": "partition",
        "partition": "0",
        "rainfallMode": "design_storm",
        "startTime": "2024-04-16T00:00",
        "durationMinutes": 30,
        "tailMinutes": 30,
        "totalDepthMm": 12,
        "rainfallPattern": "uniform",
        "peakPosition": 40,
        "spatialPattern": "uniform",
        "pipeScope": "none",
        "blockagePercent": 0,
        "pipeCapacityMultiplier": 1,
        "pumpEnabled": True,
        "pumpCapacityMultiplier": 1,
        "outfallMode": "open",
        "outfallLevelM": 0,
        "outputIntervalMinutes": 5,
    }
    value.update(overrides)
    return value


def test_design_storm_depth_is_conserved():
    scenario = validate_scenario(_scenario())
    series, stats = _rainfall_series(scenario)
    depth_mm = sum(intensity / 12 for _, intensity in series if intensity > 0)
    assert abs(depth_mm - 12.0) < 1e-8
    assert stats["generated_intervals"] == 6
    assert scenario["partitions"] == [0]


def test_render_scenario_input_rebinds_all_subcatchment_rain_gages(tmp_path):
    base = tmp_path / "base.inp"
    base.write_text(
        """[OPTIONS]\nSTART_DATE  01/01/2020\nSTART_TIME  00:00:00\nREPORT_START_DATE  01/01/2020\nREPORT_START_TIME  00:00:00\nEND_DATE  01/01/2020\nEND_TIME  01:00:00\nREPORT_STEP  00:05:00\nWET_STEP  00:05:00\nROUTING_STEP  00:05:00\n\n[RAINGAGES]\nRG_PUBLIC  INTENSITY  00:05  1.0  TIMESERIES  TS_PUBLIC\nRG_LEGACY  INTENSITY  00:05  1.0  TIMESERIES  TS_LEGACY\n\n[SUBCATCHMENTS]\nS_PUBLIC  RG_PUBLIC  J1  1  80  100  0.5  0\nS_LEGACY  RG_LEGACY  J1  1  80  100  0.5  0\nS_NONE  -  J1  1  80  100  0.5  0\n\n[TIMESERIES]\nTS_PUBLIC  00:00  0\n\n[OUTFALLS]\nO1  0  FREE\n\n[XSECTIONS]\nC1  CIRCULAR  0.15  0  0  0  1\n""",
        encoding="utf-8",
    )
    output = tmp_path / "scenario.inp"
    scenario = validate_scenario(_scenario())
    render_scenario_input(base, output, scenario)
    text = output.read_text(encoding="utf-8")
    assert "S_PUBLIC  RG_INTERACTIVE" in text
    assert "S_LEGACY  RG_INTERACTIVE" in text
    assert "S_NONE  -  J1" in text


@pytest.mark.parametrize(
    ("return_period", "expected_depth"),
    [(2, 11.31), (5, 25.29), (10, 28.71), (25, 40.35), (50, 51.48), (100, 60.33)],
)
def test_official_zone_b_180_minute_storm_conserves_published_depth(return_period, expected_depth):
    scenario = validate_scenario(
        _scenario(
            durationMinutes=180,
            tailMinutes=180,
            totalDepthMm=expected_depth,
            rainfallPattern="official_zone_b_ddf_abm",
            returnPeriodYears=return_period,
        )
    )
    series, stats = _rainfall_series(scenario)
    rain = series[:36]
    assert sum(intensity / 12.0 for _, intensity in rain) == pytest.approx(expected_depth)
    assert len(rain) == 36
    assert stats["source_authority"] == "official_publication_user_supplied_extract"
    assert stats["return_period_years"] == return_period
    assert stats["published_total_depth_mm"] == expected_depth
    assert stats["peak_position_source"].startswith("scenario_assumption")


def test_official_zone_b_storm_rejects_wrong_duration_or_depth():
    with pytest.raises(ValueError, match="official_zone_b_ddf_requires_180_minute_duration"):
        validate_scenario(
            _scenario(
                durationMinutes=120,
                totalDepthMm=25.29,
                rainfallPattern="official_zone_b_ddf_abm",
                returnPeriodYears=5,
            )
        )
    with pytest.raises(ValueError, match="official_zone_b_total_depth_mismatch"):
        validate_scenario(
            _scenario(
                durationMinutes=180,
                totalDepthMm=99,
                rainfallPattern="official_zone_b_ddf_abm",
                returnPeriodYears=5,
            )
        )


def test_design_storm_batch_catalog_strips_private_paths_and_reports_non_monotonic_checks(tmp_path, monkeypatch):
    batch_root = tmp_path / "batches" / "batch-1"
    batch_root.mkdir(parents=True)
    runs = []
    for index, return_period in enumerate((2, 5, 10, 25, 50, 100), start=1):
        runs.append(
            {
                "return_period_years": return_period,
                "published_180_minute_depth_mm": float(index),
                "published_180_minute_mean_intensity_mm_per_hour": float(index),
                "status": "completed_with_warnings",
                "run_id": f"run-{return_period}",
                "rainfall_stats": {},
                "hydraulic_summary": {
                    "flooding_loss_million_litres": float(index),
                    "external_outflow_million_litres": float(7 - index),
                },
                "node_summary": {
                    "nodes_depth_ge_0_05_m": index,
                    "nodes_depth_ge_0_15_m": index,
                    "nodes_depth_ge_0_30_m": index,
                    "nodes_depth_ge_0_50_m": index,
                    "nodes_depth_ge_1_00_m": index,
                    "nodes_with_overflow": 7 - index,
                },
                "strict_quality_gates": {"passed": False},
                "artifacts": {"native_report": "/private/customer/report.rpt"},
            }
        )
    (batch_root / "batch_manifest.json").write_text(
        __import__("json").dumps(
            {
                "schema": "test",
                "batch_id": "batch-1",
                "status": "completed_with_quality_warnings",
                "finished_at": "2026-08-26T00:00:00Z",
                "runs": runs,
                "claim_boundary": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ABU_DHABI_SWMM_INTERACTIVE_RUN_ROOT", str(tmp_path))
    catalog = scenario_service.latest_zone_b_design_storm_batch()
    assert catalog["comparison_checks"]["flooding_loss_non_decreasing"] is True
    assert catalog["comparison_checks"]["external_outflow_non_decreasing"] is False
    assert catalog["comparison_checks"]["engineering_comparison_admitted"] is False
    assert "artifacts" not in catalog["runs"][0]


def test_citywide_scope_uses_one_topology_preserving_job():
    scenario = validate_scenario(_scenario(scope="citywide"))
    assert scenario["partitions"] == ["full_city"]


def test_full_city_input_uses_configured_input_root(monkeypatch, tmp_path):
    configured_root = tmp_path / "configured-inputs"
    monkeypatch.setenv("ABU_DHABI_SWMM_INPUT_ROOT", str(configured_root))

    assert scenario_service._full_city_input() == (
        configured_root / "abu_dhabi_city_full_topology.inp"
    )


def test_full_city_input_accepts_explicit_file_override(monkeypatch, tmp_path):
    configured_input = tmp_path / "citywide-v2.inp"
    monkeypatch.setenv("ABU_DHABI_SWMM_FULL_CITY_INPUT", str(configured_input))

    assert scenario_service._full_city_input(tmp_path / "ignored-root") == configured_input


def test_historical_event_requires_authoritative_timeseries():
    with pytest.raises(ValueError, match="historical_event_requires_authoritative_timeseries"):
        validate_scenario(_scenario(rainfallMode="historical_event"))


def test_online_public_mode_is_distinct_from_design_storm(monkeypatch):
    scenario = validate_scenario(_scenario(rainfallMode="online_public", durationMinutes=90, totalDepthMm=999))
    assert scenario["total_depth_mm"] is None
    assert scenario["public_rainfall_source"] == "open_meteo_archive"
    monkeypatch.setattr(
        scenario_service,
        "_read_open_meteo_precipitation",
        lambda value: (
            {
                datetime(2024, 4, 16, 0, 0): 12.0,
                datetime(2024, 4, 16, 1, 0): 6.0,
            },
            "https://archive-api.open-meteo.com/v1/archive?test=1",
            {"latitude": 24.43, "longitude": 54.365, "timezone": "GMT", "elevation": 6.0},
        ),
    )
    series, stats = _rainfall_series(scenario)
    assert stats["source"] == "online_public_open_meteo"
    assert stats["source_authority"] == "public_proxy"
    assert stats["native_interval_minutes"] == 60
    assert stats["resolved_location"]["latitude"] == pytest.approx(24.43)
    assert stats["generated_total_depth_mm"] == pytest.approx(15.0)
    assert [value for _, value in series[:6]] == [12.0] * 6


def test_public_ncei_station_event_reads_controlled_forcing_and_preserves_station_constraint(monkeypatch, tmp_path):
    root = tmp_path / "ncei"
    forcing = root / "registered_swmm_station_constrained_diagnostic"
    forcing.mkdir(parents=True)
    lines = ["[TIMESERIES]"]
    from datetime import timedelta
    start = datetime(2024, 4, 15)
    for index in range(73):
        stamp = start + timedelta(hours=index)
        lines.append(f"TS_PUBLIC  {stamp:%m/%d/%Y}  {stamp:%H:%M}  {1.0 if index == 12 else 0.0}")
    (forcing / "registered_subnetwork_omad_station_constrained.inp").write_text("\n".join(lines), encoding="utf-8")
    (root / "ncei_april_2024_station_event_constraints.json").write_text(
        __import__("json").dumps({"stations": [{"call_sign": "OMAD", "station_id": "41216099999", "metadata": {"LATITUDE": "24.4", "LONGITUDE": "54.4"}, "records": [{"rain_mm": 6.0}]}]}),
        encoding="utf-8",
    )
    (forcing / "omad_summary.json").write_text(
        __import__("json").dumps({"forcing_total_mm": 6.0}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ABU_DHABI_PUBLIC_NCEI_ROOT", str(root))
    scenario = validate_scenario(_scenario(scope="citywide", rainfallMode="public_station_event", publicStation="OMAD", startTime="2024-04-15T00:00", durationMinutes=4320, tailMinutes=0))
    series, stats = _rainfall_series(scenario)
    assert len(series) == 865
    assert stats["station"] == "OMAD"
    assert stats["anchor_total_depth_mm"] == 6.0
    assert stats["generated_total_depth_mm"] == pytest.approx(1.0)


def test_input_rewriter_rebinds_rain_gage_and_applies_outfall_and_pipe_action(tmp_path):
    source = tmp_path / "base.inp"
    source.write_text(
        """[OPTIONS]\nSTART_DATE  04/15/2024\nSTART_TIME  00:00:00\nEND_DATE  04/18/2024\nEND_TIME  06:00:00\nREPORT_STEP  00:15:00\nWET_STEP  00:05:00\nROUTING_STEP  00:05:00\n[RAINGAGES]\nRG_PUBLIC  INTENSITY  01:00  1.0  TIMESERIES  TS_PUBLIC\n[SUBCATCHMENTS]\ns_1  RG_PUBLIC  n_1  1  80  30  0.5  0\n[TIMESERIES]\nTS_PUBLIC  04/15/2024  00:00  0\n[OUTFALLS]\nn_2  0.0  FREE  NO\n[XSECTIONS]\nc_1  CIRCULAR  1.0  0  0  0  1\n""",
        encoding="utf-8",
    )
    destination = tmp_path / "scenario.inp"
    scenario = validate_scenario(_scenario(pipeScope="selected_zone", blockagePercent=20, pipeCapacityMultiplier=0.8, outfallMode="fixed_level", outfallLevelM=1.2))
    rewrite = render_scenario_input(source, destination, scenario)
    text = destination.read_text(encoding="utf-8")
    assert "RG_INTERACTIVE" in text
    assert "FIXED  1.200" in text
    assert "TS_INTERACTIVE" in text
    assert rewrite["modified_xsection_count"] == 1
    assert "CIRCULAR  0.845897" in text


def test_native_report_node_sections_are_parsed_for_map_results(tmp_path):
    report = tmp_path / "scenario.rpt"
    report.write_text(
        """Node Depth Summary
  n_demo JUNCTION 0.12 0.80 4.20 0 01:10 0.80
  n_out OUTFALL 0.00 0.10 1.20 0 00:50 0.10
Node Inflow Summary
Node Flooding Summary
  n_demo 0.50 0.025 0 01:20 0.012 0.004
Node Outflow Summary
""",
        encoding="utf-8",
    )
    parsed = _parse_node_hydraulic_results(report)
    assert parsed["n_demo"]["max_water_depth_m"] == pytest.approx(0.8)
    assert parsed["n_demo"]["max_overflow_or_flooding_m3s"] == pytest.approx(0.025)
    assert parsed["n_demo"]["total_flood_volume_million_litres"] == pytest.approx(0.012)
    assert parsed["n_out"]["max_water_depth_m"] == pytest.approx(0.1)


def test_map_bootstrap_returns_timeline_without_serializing_node_features(monkeypatch):
    monkeypatch.setattr(
        scenario_service,
        "public_run",
        lambda run_id: {
            "run_id": run_id,
            "status": "completed_with_warnings",
            "scenario": {"rainfall_mode": "design_storm", "rainfall_stats": {"source_label": "test DDF"}},
        },
    )
    monkeypatch.setattr(
        scenario_service,
        "_scenario_timeline",
        lambda run_id, run: {
            "available": True,
            "period_count": 7,
            "time_values": ["t0"],
            "elapsed_minutes": [0],
            "total_node_count": 146_823,
        },
    )

    payload = scenario_service.scenario_map_bootstrap_payload("run-100")

    assert payload["features"] == []
    assert payload["metadata"]["bootstrap_only"] is True
    assert payload["metadata"]["total_node_result_count"] == 146_823
    assert payload["metadata"]["map_node_filter"] == "none"


def test_map_node_coverage_contract_separates_result_nodes_from_renderable_geometry():
    metadata = scenario_service._map_node_coverage_metadata(146_823, 138_831)

    assert metadata["total_node_result_count"] == 146_823
    assert metadata["node_feature_count"] == 138_831
    assert metadata["missing_geometry_count"] == 7_992
    assert metadata["geometry_coverage_fraction"] == pytest.approx(138_831 / 146_823)
    assert metadata["map_node_completeness"] == "partial_geometry_coverage"
    assert metadata["node_value_filter"] == "none_including_zero_values_for_mapped_nodes"
    assert metadata["node_map_filter"] == "none"


def test_timeseries_map_returns_every_native_out_node_including_zero_values(monkeypatch, tmp_path):
    run = {
        "status": "completed_with_warnings",
        "scenario": {"partitions": ["full_city"], "rainfall_stats": {}},
        "partitions": [{"partition_id": "full_city", "status": "completed_quality_warning"}],
    }
    monkeypatch.setattr(scenario_service, "public_run", lambda run_id: run)
    monkeypatch.setattr(
        scenario_service,
        "_scenario_timeline",
        lambda run_id, value: {
            "available": True,
            "period_count": 1,
            "time_values": ["2024-04-16T00:00:00"],
            "elapsed_minutes": [0],
            "total_node_count": 3,
        },
    )
    monkeypatch.setattr(scenario_service, "_partition_out_path", lambda run_id, partition_id: tmp_path / "test.out")
    monkeypatch.setattr(
        scenario_service,
        "_swmm_out_header",
        lambda path: {"period_count": 1, "node_names": ["n_zero", "n_depth", "n_overflow"]},
    )
    monkeypatch.setattr(
        scenario_service,
        "read_node_period",
        lambda path, header, index: {
            "timestamp": "2024-04-16T00:00:00",
            "elapsed_minutes": 0,
            "nodes": [
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.08, 0.08, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.02],
            ],
        },
    )
    monkeypatch.setattr(
        scenario_service,
        "_node_geometry_index",
        lambda: {
            node_id: {"type": "Point", "coordinates": [54.0 + index, 24.0]}
            for index, node_id in enumerate(("n_zero", "n_depth", "n_overflow"))
        },
    )

    payload = scenario_service.scenario_map_timeseries_payload("run-full", 0)

    assert [feature["properties"]["node_id"] for feature in payload["features"]] == [
        "n_zero",
        "n_depth",
        "n_overflow",
    ]
    assert payload["metadata"]["node_feature_count"] == 3
    assert payload["metadata"]["affected_node_count"] == 2
    assert payload["metadata"]["missing_geometry_count"] == 0
    assert payload["metadata"]["map_node_completeness"] == "complete_geometry_coverage"
    assert payload["metadata"]["node_map_filter"] == "none"


def test_timeseries_columns_preserve_every_node_without_geojson_repetition(monkeypatch, tmp_path):
    run = {
        "status": "completed_with_warnings",
        "scenario": {"partitions": ["full_city"], "rainfall_stats": {}},
        "partitions": [{"partition_id": "full_city", "status": "completed_quality_warning"}],
    }
    monkeypatch.setattr(scenario_service, "public_run", lambda run_id: run)
    monkeypatch.setattr(
        scenario_service,
        "_scenario_timeline",
        lambda run_id, value: {
            "available": True,
            "period_count": 1,
            "time_values": ["2024-04-16T00:00:00"],
            "elapsed_minutes": [0],
            "total_node_count": 3,
        },
    )
    monkeypatch.setattr(scenario_service, "_partition_out_path", lambda run_id, partition_id: tmp_path / "test.out")
    monkeypatch.setattr(
        scenario_service,
        "_swmm_out_header",
        lambda path: {"period_count": 1, "node_names": ["n_zero", "n_depth", "n_overflow"]},
    )
    monkeypatch.setattr(
        scenario_service,
        "read_node_period",
        lambda path, header, index: {
            "timestamp": "2024-04-16T00:00:00",
            "elapsed_minutes": 0,
            "nodes": [
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.08, 0.08, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.02],
            ],
        },
    )
    monkeypatch.setattr(
        scenario_service,
        "_node_geometry_index",
        lambda: {
            node_id: {"type": "Point", "coordinates": [54.0 + index, 24.0]}
            for index, node_id in enumerate(("n_zero", "n_depth", "n_overflow"))
        },
    )

    payload = scenario_service.scenario_map_timeseries_columns_payload("run-full", 0)

    assert payload["format"] == "swmm-node-columns-v1"
    assert payload["node_ids"] == ["n_zero", "n_depth", "n_overflow"]
    assert payload["partition_labels"] == ["全市连续网络"]
    assert payload["coordinates"] == [54.0, 24.0, 55.0, 24.0, 56.0, 24.0]
    assert payload["values"][6] == pytest.approx(0.08)
    assert payload["values"][-1] == pytest.approx(0.02)
    assert payload["overflow_node_indexes"] == [2]
    assert payload["metadata"]["node_feature_count"] == 3
    assert payload["metadata"]["affected_node_count"] == 2
    assert payload["metadata"]["missing_geometry_count"] == 0
    assert payload["metadata"]["map_node_completeness"] == "complete_geometry_coverage"
    assert "features" not in payload


def test_customer_dtm_diagnostic_bootstrap_and_timeseries_are_private_derived_results(
    monkeypatch, tmp_path
):
    root = tmp_path / "diagnostic"
    (root / "results").mkdir(parents=True)
    (root / "temporal_snapshots").mkdir()
    maximum = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[54, 24], [54.001, 24], [54.001, 24.001], [54, 24.001], [54, 24]]]},
                "properties": {"cell_id": 1, "maximum_depth_m": 0.12},
            }
        ],
    }
    snapshot = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": maximum["features"][0]["geometry"],
                "properties": {"cell_id": 1, "time_hours": 1.0, "depth_m": 0.08},
            }
        ],
    }
    (root / "results" / "dtm5m_customer_maximum_depth_wgs84.geojson").write_text(
        __import__("json").dumps(maximum), encoding="utf-8"
    )
    (root / "results" / "delivery_summary.json").write_text(
        __import__("json").dumps(
            {
                "source": {"raster_name": "dtm_5M.tif", "evidence_class": "customer_unverified", "resolution_m": [5, 5]},
                "model": {"domain_bounds_epsg32640": [1, 2, 3, 4], "domain_area_m2": 4, "triangle_count": 1, "forcing_total_mm": 59.8, "swmm_overflow_exchange_m3": 0},
                "results": {"maximum_depth_m": 0.12, "maximum_depth_footprint_ge_0_05m_m2": 100},
            }
        ), encoding="utf-8"
    )
    (root / "temporal_snapshots" / "t0.geojson").write_text(
        __import__("json").dumps(snapshot), encoding="utf-8"
    )
    (root / "temporal_snapshots" / "manifest.json").write_text(
        __import__("json").dumps({"snapshots": [{"time_seconds": 3600, "time_hours": 1, "path": "temporal_snapshots/t0.geojson"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ABU_DHABI_DTM_DIAGNOSTIC_ROOT", str(root))
    bootstrap = scenario_service.dtm_diagnostic_bootstrap_payload()
    assert bootstrap["metadata"]["surface_product"] == "dtm_5M.tif"
    assert bootstrap["metadata"]["timeline"]["period_count"] == 1
    assert bootstrap["features"] == []
    frame = scenario_service.dtm_diagnostic_timeseries_payload(0)
    assert frame["metadata"]["time_index"] == 0
    assert frame["features"][0]["properties"]["depth_m"] == 0.08


def test_public_citywide_2d_exposes_land_water_mask_and_land_cell_timeline(
    monkeypatch, tmp_path
):
    root = tmp_path / "public-citywide-2d"
    snapshots = root / "temporal_snapshots"
    snapshots.mkdir(parents=True)
    maximum = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[54, 24], [54.1, 24], [54.1, 24.1], [54, 24.1], [54, 24]]],
                },
                "properties": {
                    "cell_id": 1,
                    "maximum_depth_m": 0.2,
                    "land_fraction": 0.95,
                    "permanent_water_fraction": 0.05,
                },
            }
        ],
    }
    frame = {
        "type": "FeatureCollection",
        "features": [
            {
                **maximum["features"][0],
                "properties": {
                    "cell_id": 1,
                    "depth_m": 0.1,
                    "land_fraction": 0.95,
                    "permanent_water_fraction": 0.05,
                },
            }
        ],
    }
    (root / "maximum_depth_wgs84.geojson").write_text(
        __import__("json").dumps(maximum), encoding="utf-8"
    )
    (root / "delivery_summary.json").write_text(
        __import__("json").dumps(
            {
                "solver": "ANUGA 2D",
                "status": "completed_public_copernicus_citywide_2d_prototype_not_calibrated",
                "surface": {
                    "product": "Copernicus DEM GLO-30 public proxy",
                    "source_resolution_m": [30, 30],
                },
                "domain": {
                    "cell_size_m": 250,
                    "rectangular_cells": 100,
                    "active_land_cells": 65,
                    "excluded_permanent_water_cells": 35,
                    "output_step_minutes": 30,
                },
                "land_water_treatment": {
                    "product": "ESA WorldCover 2021 v200",
                    "permanent_water_class": 80,
                    "water_cell_fraction_threshold": 0.5,
                    "source_coverage_threshold": 0.999,
                    "source_covered_cells": 90,
                    "source_uncovered_cells_excluded": 10,
                    "rainfall_applied_to": "active_land_cells_only",
                    "permanent_water_output_policy": "excluded_from_inland_flood_layers_and_statistics",
                    "sea_boundary_level_m": 0,
                    "claim_boundary": "public land-cover proxy",
                },
                "results": {"maximum_depth_m": 0.2},
            }
        ),
        encoding="utf-8",
    )
    (snapshots / "t0.geojson").write_text(
        __import__("json").dumps({"type": "FeatureCollection", "features": []}),
        encoding="utf-8",
    )
    (snapshots / "t1.geojson").write_text(
        __import__("json").dumps(frame), encoding="utf-8"
    )
    (snapshots / "manifest.json").write_text(
        __import__("json").dumps(
            {
                "snapshots": [
                    {"time_seconds": 0, "time_minutes": 0, "path": "temporal_snapshots/t0.geojson"},
                    {"time_seconds": 1800, "time_minutes": 30, "path": "temporal_snapshots/t1.geojson"},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ABU_DHABI_PUBLIC_CITYWIDE_2D_ROOT", str(root))

    bootstrap = scenario_service.public_citywide_2d_bootstrap_payload()
    assert bootstrap["metadata"]["land_water_mask"]["applied"] is True
    assert bootstrap["metadata"]["land_water_mask"]["excluded_permanent_water_cells"] == 35
    assert bootstrap["metadata"]["land_water_mask"]["source_coverage_threshold"] == 0.999
    assert bootstrap["metadata"]["land_water_mask"]["source_uncovered_cells_excluded"] == 10
    assert bootstrap["metadata"]["timeline"]["total_cell_count"] == 65
    assert bootstrap["metadata"]["timeline"]["initial_time_index"] == 1
    assert bootstrap["metadata"]["model_configuration"] == {
        "execution_mode": "registered_precomputed_result",
        "solver": "ANUGA 2D",
        "solver_chain": "EPA SWMM 5.2.4 native OUT -> ANUGA 2D",
        "terrain_source": "copernicus_dem_glo30",
        "terrain_product": "Copernicus DEM GLO-30 public proxy",
        "terrain_source_resolution_m": [30, 30],
        "model_cell_size_m": 250,
        "forcing_source": None,
        "forcing_duration_minutes": None,
        "forcing_interval_minutes": None,
        "forcing_peak_position_percent": None,
        "simulation_duration_minutes": None,
        "tail_minutes": None,
        "output_interval_minutes": 30,
        "coupling_mode": "one_way_swmm_to_anuga",
        "exchange_quantity": None,
        "dynamic_head_feedback": False,
        "sea_boundary_condition": None,
        "sea_boundary_level_m": 0,
        "water_cell_fraction_threshold": 0.5,
        "editable_parameters": ["return_period_years"],
        "frozen_parameter_reason": (
            "The current web contract selects an audited registered result. "
            "Changing mesh, boundary, coupling, roughness, or time-step settings "
            "requires a new ANUGA run and a new run receipt."
        ),
    }
    assert "WorldCover" in bootstrap["metadata"]["claim_boundary"]

    assert scenario_service.public_citywide_2d_timeseries_payload(0)["features"] == []
    result_frame = scenario_service.public_citywide_2d_timeseries_payload(1)
    assert result_frame["metadata"]["permanent_water_cells_excluded"] is True
    assert result_frame["features"][0]["properties"]["land_fraction"] == 0.95


def test_periodless_citywide_2d_request_defaults_to_available_100_year_customer_product(
    monkeypatch, tmp_path
):
    root = tmp_path / "customer-citywide"
    period = root / "rp100" / "temporal_snapshots"
    period.mkdir(parents=True)
    maximum = {"type": "FeatureCollection", "features": []}
    (root / "rp100" / "maximum_depth_wgs84.geojson").write_text(
        __import__("json").dumps(maximum), encoding="utf-8"
    )
    (root / "rp100" / "delivery_summary.json").write_text(
        __import__("json").dumps(
            {
                "solver": "ANUGA 2D",
                "status": "completed_customer_dtm_citywide_2d_validation",
                "surface": {
                    "product": "Customer AUH_DTM_5m_Z40",
                    "evidence_class": "customer_dtm_5m",
                    "source_resolution_m": [5, 5],
                },
                "domain": {"active_land_cells": 0, "output_step_minutes": 30},
                "forcing": {"return_period_years": 100},
            }
        ), encoding="utf-8"
    )
    (period / "manifest.json").write_text(
        __import__("json").dumps(
            {"snapshots": [{"time_seconds": 0, "time_minutes": 0, "path": "temporal_snapshots/t0.geojson"}]}
        ), encoding="utf-8"
    )
    (period / "t0.geojson").write_text(__import__("json").dumps(maximum), encoding="utf-8")
    monkeypatch.setenv("ABU_DHABI_CUSTOMER_CITYWIDE_2D_ROOT", str(root))
    monkeypatch.delenv("ABU_DHABI_PUBLIC_CITYWIDE_2D_ROOT", raising=False)

    payload = scenario_service.public_citywide_2d_bootstrap_payload()
    assert payload["metadata"]["return_period_years"] == 100
    assert payload["metadata"]["surface_source_class"] == "customer_authoritative"
    assert payload["metadata"]["source_resolution_m"] == [5, 5]


def test_citywide_2d_bidirectional_validation_is_exposed_as_separate_result_source(
    monkeypatch, tmp_path
):
    root = tmp_path / "bidirectional"
    snapshots = root / "temporal_snapshots"
    snapshots.mkdir(parents=True)
    maximum = {"type": "FeatureCollection", "features": []}
    (root / "maximum_depth_wgs84.geojson").write_text(
        __import__("json").dumps(maximum), encoding="utf-8"
    )
    (root / "delivery_summary.json").write_text(
        __import__("json").dumps(
            {
                "status": "completed_customer_dtm_citywide_synchronous_bidirectional_2d_validation",
                "run_id": "bidirectional-run-001",
                "solver": "EPA SWMM 5.2.4 + ANUGA 2D synchronous coupling",
                "surface": {
                    "product": "Customer DTM + synchronous bidirectional coupling",
                    "evidence_class": "customer_dtm_customer_swmm_synchronous_bidirectional_coupling",
                    "source_resolution_m": [5, 5],
                },
                "domain": {
                    "active_land_cells": 10,
                    "cell_size_m": 250,
                    "simulation_duration_minutes": 180,
                    "output_step_minutes": 5,
                },
                "forcing": {
                    "return_period_years": 100,
                    "configured_storm_duration_minutes": 180,
                },
                "coupling": {
                    "mode": "synchronous_two_way_swmm_anuga_surface_exchange",
                    "quality_passed": True,
                    "window_count": 36,
                    "exchange_window_seconds": 300,
                    "interface_count": 141840,
                    "total_swmm_to_anuga_m3": 100.0,
                    "total_anuga_to_swmm_m3": 25.0,
                },
                "results": {"maximum_depth_m": 1.2},
            }
        ),
        encoding="utf-8",
    )
    (snapshots / "manifest.json").write_text(
        __import__("json").dumps(
            {
                "snapshots": [
                    {
                        "time_seconds": 0,
                        "time_minutes": 0,
                        "path": "temporal_snapshots/t0.geojson",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (snapshots / "t0.geojson").write_text(
        __import__("json").dumps(maximum), encoding="utf-8"
    )
    monkeypatch.setenv("ABU_DHABI_CUSTOMER_BIDIRECTIONAL_2D_ROOT", str(root))

    payload = scenario_service.public_citywide_2d_bootstrap_payload(
        100, "bidirectional_validation"
    )

    assert payload["metadata"]["result_variant"] == "bidirectional_validation"
    assert payload["metadata"]["timeline"]["run_id"] == "bidirectional-run-001"
    assert "result_source=bidirectional_validation" in payload["metadata"]["timeline"]["endpoint"]
    assert payload["metadata"]["model_configuration"]["dynamic_head_feedback"] is True
    assert payload["metadata"]["coupling_summary"]["window_count"] == 36
    assert payload["metadata"]["coupling_summary"]["total_anuga_to_swmm_m3"] == 25.0

    frame = scenario_service.public_citywide_2d_timeseries_payload(
        0, 100, "bidirectional_validation"
    )
    assert frame["metadata"]["result_variant"] == "bidirectional_validation"
    assert frame["metadata"]["coupling_mode"] == "synchronous_two_way_swmm_anuga_surface_exchange"
