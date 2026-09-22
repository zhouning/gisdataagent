"""Contract tests for the isolated Abu Dhabi phase-5 replay validation."""

from __future__ import annotations

import json

import pytest

import data_agent.abu_dhabi_flood_validation_service as validation


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _feature(depth: float = 0.4):
    return {
        "type": "Feature",
        "properties": {"cell_id": 1, "depth_m": depth},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[54.4, 24.4], [54.41, 24.4], [54.41, 24.41], [54.4, 24.4]]],
        },
    }


def _source(root, *, prescribed=100.0, actual=99.5):
    frame = {"type": "FeatureCollection", "features": [_feature()]}
    _write_json(root / "maximum_depth_wgs84.geojson", frame)
    _write_json(root / "abu_dhabi_public_citywide_2d.sww", {})
    _write_json(
        root / "temporal_snapshots/manifest.json",
        {
            "schema": "test",
            "snapshots": [
                {"index": 0, "path": "temporal_snapshots/surface_depth_t000.geojson", "time_minutes": 0},
                {"index": 1, "path": "temporal_snapshots/surface_depth_t001.geojson", "time_minutes": 30},
            ],
        },
    )
    _write_json(root / "temporal_snapshots/surface_depth_t000.geojson", frame)
    _write_json(root / "temporal_snapshots/surface_depth_t001.geojson", {**frame, "features": [_feature(0.2)]})
    _write_json(
        root / "delivery_summary.json",
        {
            "run_id": "test-historical-replay",
            "status": "completed",
            "domain": {"simulation_duration_hours": 1, "cell_size_m": 250, "active_land_cells": 1, "output_step_minutes": 30},
            "forcing": {"event_id": "test-event"},
            "surface": {"product": "Customer DTM", "source_resolution_m": [5, 5]},
            "results": {"maximum_depth_m": 0.4},
            "coupling": {
                "mode": "one_way_swmm_to_anuga",
                "prescribed_swmm_to_anuga_volume_m3": prescribed,
                "runtime": {"actual_swmm_to_anuga_volume_m3": actual},
                "mapped_node_count": 1,
                "swmm_node_count": 1,
            },
            "admission": {"numerical_validation_completed": True},
            "outputs": {"maximum_depth": "maximum_depth_wgs84.geojson", "timeline_manifest": "temporal_snapshots/manifest.json"},
        },
    )


def test_bootstrap_exposes_timeline_and_pending_observation_gate(tmp_path, monkeypatch):
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    payload = validation.historical_replay_bootstrap_payload()

    assert payload["maximum_depth"]["features"]
    assert payload["metadata"]["timeline"]["period_count"] == 2
    assert payload["metadata"]["timeline"]["time_values"] == ["0 min", "30 min"]
    assert payload["metadata"]["timeline"]["initial_time_index"] == 0
    assert payload["metadata"]["validation"]["observation_comparison"] == "pending"
    assert any(gate["gate_id"] == "observation_comparison" and gate["status"] == "pending" for gate in payload["metadata"]["validation"]["gates"])


def test_timeseries_reads_one_frame(tmp_path, monkeypatch):
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    payload = validation.historical_replay_timeseries_payload(1)

    assert payload["metadata"]["time_index"] == 1
    assert payload["metadata"]["depth_field"] == "depth_m"
    assert payload["features"][0]["properties"]["depth_m"] == 0.2


def test_bootstrap_skips_leading_dry_frames_for_map_bootstrap(tmp_path, monkeypatch):
    _source(tmp_path)
    dry = {"type": "FeatureCollection", "features": []}
    _write_json(tmp_path / "temporal_snapshots/surface_depth_t000.geojson", dry)
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    payload = validation.historical_replay_bootstrap_payload()

    assert payload["metadata"]["timeline"]["initial_time_index"] == 1


@pytest.mark.parametrize("path", ("/tmp/outside.geojson", "../outside.geojson", "nested/../../outside.geojson"))
def test_timeseries_rejects_unsafe_snapshot_path(tmp_path, monkeypatch, path):
    _source(tmp_path)
    manifest_path = tmp_path / "temporal_snapshots/manifest.json"
    _write_json(manifest_path, {"snapshots": [{"index": 0, "path": path, "time_minutes": 0}]})
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    with pytest.raises(ValueError, match="historical_replay_snapshot_path_invalid"):
        validation.historical_replay_timeseries_payload(0)


def test_missing_asset_has_stable_error(tmp_path, monkeypatch):
    _source(tmp_path)
    (tmp_path / "maximum_depth_wgs84.geojson").unlink()
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    with pytest.raises(ValueError, match="historical_replay_maximum_depth_missing"):
        validation.historical_replay_bootstrap_payload()


def test_volume_reconciliation_is_reported(tmp_path, monkeypatch):
    _source(tmp_path, prescribed=200.0, actual=198.0)
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    payload = validation.historical_replay_bootstrap_payload()
    coupling = payload["metadata"]["coupling"]

    assert coupling["relative_volume_error"] == pytest.approx(0.01)
    check = next(item for item in payload["metadata"]["validation"]["checks"] if item["check_id"] == "swmm_to_anuga_volume_reconciliation")
    assert check["passed"] is True


def test_swmm_strict_quality_gate_is_exposed_without_blocking_assets(tmp_path, monkeypatch):
    _source(tmp_path)
    receipt = tmp_path.parent / "swmm/swmm_execution_receipt.json"
    _write_json(
        receipt,
        {
            "status": "completed_numerical_quality_failed_not_admitted",
            "strict_quality_gates": {
                "admission_effect": "none_diagnostic_quality_only",
                "checks": [
                    {"check_id": "report_contains_no_swmm_errors", "observed": 0, "passed": True, "threshold_or_required": 0},
                    {"check_id": "nonconverging_steps_within_threshold", "observed": 98.79, "passed": False, "threshold_or_required": 0.0},
                ],
                "passed": False,
            },
        },
    )
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    payload = validation.historical_replay_bootstrap_payload()
    quality = payload["metadata"]["validation"]["swmm_quality"]

    assert quality["status"] == "failed"
    assert quality["failed_checks"] == ["nonconverging_steps_within_threshold"]
    assert payload["metadata"]["validation"]["status"] == "artifacts_complete_swmm_quality_gate_failed"
    assert any(gate["gate_id"] == "swmm_numerical_quality" and gate["status"] == "failed" for gate in payload["metadata"]["validation"]["gates"])


def test_phase5_report_is_path_safe_and_includes_five_stage_delivery(tmp_path, monkeypatch):
    _source(tmp_path)
    receipt = tmp_path.parent / "swmm/swmm_execution_receipt.json"
    _write_json(
        receipt,
        {
            "strict_quality_gates": {
                "checks": [{"check_id": "nonconverging_steps_within_threshold", "observed": 98.79, "passed": False}],
                "passed": False,
            },
        },
    )
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    report = validation.historical_replay_report_payload()
    html = validation.historical_replay_report_html()

    assert report["title"].startswith("Abu Dhabi Urban Pluvial Flood")
    assert len(report["phases"]) == 5
    assert report["validation"]["swmm_quality"]["status"] == "failed"
    assert "2024 April Historical Replay and Delivery Report" in html
    assert "Maximum surface-water depth (citywide land grid)" in html
    assert "nonconverging_steps_within_threshold" in html
    assert str(tmp_path) not in html


def test_phase5_report_uses_single_language_and_model_window_for_visuals(tmp_path, monkeypatch):
    _source(tmp_path)
    summary_path = tmp_path / "delivery_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["forcing"] = {"event_id": "test-event", "simulation_window_minutes": 2880, "native_interval_minutes": 5}
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    swmm_dir = tmp_path.parent / "swmm"
    swmm_dir.mkdir(parents=True, exist_ok=True)
    # A sibling fixture may have left an execution receipt in the shared
    # pytest temporary parent; this test focuses on language/window behavior.
    (swmm_dir / "swmm_execution_receipt.json").unlink(missing_ok=True)
    # Include one row beyond the 48-hour model window. It must not stretch the
    # report rainfall axis into a multi-day chart.
    (swmm_dir / "historical_replay.inp").write_text(
        "[TIMESERIES]\n"
        "TS_INTERACTIVE  04/15/2024  16:00  0.0\n"
        "TS_INTERACTIVE  04/15/2024  16:05  12.0\n"
        "TS_INTERACTIVE  04/17/2024  16:00  8.0\n"
        "TS_INTERACTIVE  04/18/2024  16:00  99.0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    zh = validation.historical_replay_report_html("zh")
    en = validation.historical_replay_report_html("en")

    assert "2880 分钟" in zh
    assert "34560" not in zh
    assert "不收敛步数超过阈值" not in zh  # no quality receipt in this fixture
    assert "Generating the phase" not in zh
    assert not any("\u3400" <= char <= "\u9fff" for char in en)
    assert "Maximum surface-water depth (citywide land grid)" in en
    assert "Maximum surface-water depth (citywide land grid)" not in zh
    assert "时间（分钟）（分钟）" not in zh
    assert "Time (min)" in en


def test_phase5_chinese_report_uses_localized_prose_and_explanatory_visuals(tmp_path, monkeypatch):
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    html = validation.historical_replay_report_html("zh-CN")

    # Technical file names and model acronyms are intentionally retained as
    # machine-facing identifiers, but prose and chart annotations must not
    # fall back to English labels.
    assert "Maximum surface-water depth overview" not in html
    assert "Sampled maximum surface-water depth map" not in html
    assert "Sampled rendering" not in html
    assert "积水单元" in html
    assert "峰值" in html
    assert "平方千米" in html
    assert "空白 = 无积水、永久水体或未写入最大深度资产" in html
    assert "陆域网格" in html
    assert html.count("maximum_depth_wgs84.geojson") == 1


def test_phase5_report_map_declares_blank_area_and_keeps_english_consistent(tmp_path, monkeypatch):
    _source(tmp_path)
    monkeypatch.setenv("ABU_DHABI_HISTORICAL_REPLAY_2D_ROOT", str(tmp_path))

    html = validation.historical_replay_report_html("en-US")

    assert "Maximum surface-water depth (citywide land grid) — wet-cell result" in html
    assert "Colour = wet result; blank = dry / permanent water / not written" in html
    assert "Blank = dry, permanent water or not in maximum-depth asset" in html
    assert not any("\u3400" <= char <= "\u9fff" for char in html)
