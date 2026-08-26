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
    assert payload["metadata"]["node_map_filter"] == "none"
