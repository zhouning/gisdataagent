#!/usr/bin/env python3
"""Reproducible spatiotemporal rainfall acceptance test for Abu Dhabi.

This test deliberately separates four evidence levels:

1. a public historical rainfall proxy is converted to a five-minute profile;
2. independent spatial-zone totals and peak times are materialised;
3. the real citywide SWMM topology is rewritten and its subcatchments mapped;
4. the ANUGA runner is given the same independent zone series and its generated
   forcing script is retained for inspection.

The Open-Meteo series is a public proxy, not customer-authoritative ground
truth and not a calibrated rainfall field.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from data_agent.abu_dhabi_flood_scenario_service import (
    render_scenario_input,
    validate_scenario,
)
from data_agent.abu_dhabi_rainfall_profiles import (
    rainfall_profile_series,
    spatial_zone_values_mm_per_interval,
)
from data_agent.abu_dhabi_surface_run_service import (
    _load_runner,
    validate_surface_request,
)


DEFAULT_SWMM_INPUT = Path(os.environ.get(
    "ABU_DHABI_SWMM_INPUT",
    "input/swmm/abu_dhabi_city_full_topology.inp",
))
DEFAULT_2024_SOURCE = Path(os.environ.get(
    "ABU_DHABI_OPEN_METEO_2024_SOURCE",
    "/private/tmp/abu_openmeteo_2024_04.json",
))
DEFAULT_2026_SOURCE = Path(os.environ.get(
    "ABU_DHABI_OPEN_METEO_2026_SOURCE",
    "/private/tmp/abu_openmeteo_2026_03.json",
))
DEFAULT_OUTPUT = Path(os.environ.get(
    "ABU_DHABI_SPATIOTEMPORAL_OUTPUT",
    "雨型时空差异端到端测试_2024年4月与2026年3月",
))
OPEN_METEO_2024_URL = (
    "https://archive-api.open-meteo.com/v1/archive?latitude=24.45&longitude=54.38&"
    "start_date=2024-04-15&end_date=2024-04-17&hourly=precipitation&timezone=UTC"
)
OPEN_METEO_2026_URL = (
    "https://archive-api.open-meteo.com/v1/archive?latitude=24.45&longitude=54.38&"
    "start_date=2026-03-01&end_date=2026-03-31&hourly=precipitation&timezone=UTC"
)

# Bounds are derived from the real SWMM [COORDINATES] section.  The three
# non-overlapping strips cover every outlet coordinate and keep Al Bateen's
# approximate UTM easting (about 231-235 km) in a separately auditable zone.
MODEL_MIN_X = 227_035.0
MODEL_MAX_X = 273_901.0
MODEL_MIN_Y = 2_687_059.0
MODEL_MAX_Y = 2_723_671.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rectangle(min_x: float, max_x: float) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [[
            [min_x, MODEL_MIN_Y],
            [max_x, MODEL_MIN_Y],
            [max_x, MODEL_MAX_Y],
            [min_x, MODEL_MAX_Y],
            [min_x, MODEL_MIN_Y],
        ]],
    }


def _read_hourly_window(path: Path, start: datetime, hours: int = 72) -> list[float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    timestamps = payload.get("hourly", {}).get("time")
    precipitation = payload.get("hourly", {}).get("precipitation")
    if not isinstance(timestamps, list) or not isinstance(precipitation, list):
        raise ValueError(f"open_meteo_hourly_data_missing:{path}")
    indexed = {
        datetime.fromisoformat(str(stamp)): float(value or 0.0)
        for stamp, value in zip(timestamps, precipitation, strict=True)
    }
    values = []
    for index in range(hours):
        stamp = start + timedelta(hours=index)
        if stamp not in indexed:
            raise ValueError(f"open_meteo_hour_missing:{stamp.isoformat()}")
        value = indexed[stamp]
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"open_meteo_precipitation_invalid:{stamp.isoformat()}")
        values.append(value)
    return values


def _hourly_to_five_minute_depths(hourly_depths_mm: list[float]) -> list[float]:
    return [depth / 12.0 for depth in hourly_depths_mm for _ in range(12)]


def _shift(values: list[float], intervals: int) -> list[float]:
    if intervals == 0:
        return list(values)
    result = [0.0] * len(values)
    for index, value in enumerate(values):
        shifted = index + intervals
        if 0 <= shifted < len(values):
            result[shifted] = value
        elif value != 0.0:
            raise ValueError("nonzero_rainfall_shifted_outside_event_window")
    return result


def _zones(base_values: list[float]) -> list[dict[str, Any]]:
    return [
        {
            "zone_id": "west_coastal_later",
            "name": "西部沿海后移区",
            "crs": "EPSG:32640",
            "geometry": _rectangle(MODEL_MIN_X, 231_000.0),
            "rainfall_factor": 0.75,
            "temporal_pattern_id": "custom",
            "values_mm_per_interval": _shift(base_values, 18),
            "priority": 1,
        },
        {
            "zone_id": "al_bateen_reference",
            "name": "Al Bateen参考区",
            "crs": "EPSG:32640",
            "geometry": _rectangle(231_000.0, 239_000.0),
            "rainfall_factor": 1.0,
            "temporal_pattern_id": "custom",
            "values_mm_per_interval": list(base_values),
            "priority": 2,
        },
        {
            "zone_id": "eastern_city_earlier",
            "name": "东部城区前移区",
            "crs": "EPSG:32640",
            "geometry": _rectangle(239_000.0, MODEL_MAX_X),
            "rainfall_factor": 1.25,
            "temporal_pattern_id": "custom",
            "values_mm_per_interval": _shift(base_values, -12),
            "priority": 3,
        },
    ]


def _profile(
    event_id: str,
    start: datetime,
    base_values: list[float],
    source_url: str,
) -> dict[str, Any]:
    return {
        "profile_id": event_id,
        "name": event_id,
        "climate_zone": "zone_b",
        "source_type": "public_historical_proxy",
        "source_reference": source_url,
        "duration_minutes": len(base_values) * 5,
        "interval_minutes": 5,
        "temporal_pattern": "custom",
        "values_mm_per_interval": base_values,
        "spatial_mode": "zones",
        "zones": _zones(base_values),
        "provenance": {
            "event_start_utc": start.isoformat(),
            "claim_boundary": (
                "Open-Meteo public historical proxy at one Abu Dhabi coordinate; "
                "zone shifts and multipliers are acceptance-test assumptions, not observations."
            ),
        },
    }


def _scenario(profile: dict[str, Any], start: datetime) -> dict[str, Any]:
    return validate_scenario(
        {
            "scope": "citywide",
            "rainfallMode": "design_storm",
            "startTime": start.isoformat(),
            "durationMinutes": profile["duration_minutes"],
            "tailMinutes": 0,
            "rainfallProfile": profile,
            "spatialPattern": "zones",
            "spatialRainfallZones": profile["zones"],
            "pipeScope": "none",
            "blockagePercent": 0,
            "pipeCapacityMultiplier": 1,
            "pumpEnabled": True,
            "pumpCapacityMultiplier": 1,
            "outfallMode": "open",
            "outfallLevelM": 0,
            "outputIntervalMinutes": 60,
        }
    )


def _section_rows(path: Path, section: str) -> list[list[str]]:
    target = f"[{section.upper()}]"
    active = False
    rows: list[list[str]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.upper() == target:
                active = True
                continue
            if active and stripped.startswith("["):
                break
            if active and stripped and not stripped.startswith(";"):
                rows.append(stripped.split())
    return rows


def _zone_metrics(
    scenario: dict[str, Any],
    start: datetime,
) -> list[dict[str, Any]]:
    base = scenario["rainfall_profile"]["values_mm_per_interval"]
    result = []
    for zone in scenario["spatial_rainfall_zones"]:
        values = spatial_zone_values_mm_per_interval(
            base,
            zone,
            default_peak_position_percent=float(scenario["peak_position"]),
        )
        peak_index = max(range(len(values)), key=values.__getitem__)
        result.append(
            {
                "zone_id": zone["zone_id"],
                "rainfall_factor": zone["rainfall_factor"],
                "temporal_pattern_id": zone["temporal_pattern_id"],
                "total_depth_mm": round(sum(values), 6),
                "peak_depth_mm_per_5min": round(values[peak_index], 6),
                "peak_intensity_mm_per_hour": round(values[peak_index] * 12.0, 6),
                "peak_time_utc": (start + timedelta(minutes=5 * peak_index)).isoformat(),
                "nonzero_interval_count": sum(value > 0 for value in values),
                "values_sha256": hashlib.sha256(
                    json.dumps(values, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            }
        )
    return result


def _build_anuga_preview(
    event_dir: Path,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    profile_series, _stats = rainfall_profile_series(
        scenario["rainfall_profile"],
        start=datetime(2000, 1, 1),
        tail_minutes=0,
    )
    rainfall_values = [float(intensity) for _stamp, intensity in profile_series[:-1]]
    base_depths = [value / 12.0 for value in rainfall_values]
    spatial_zones = [
        {
            **zone,
            "rainfall_values_mm_per_hour": [
                depth * 12.0
                for depth in spatial_zone_values_mm_per_interval(
                    base_depths,
                    zone,
                    default_peak_position_percent=float(scenario["peak_position"]),
                )
            ],
        }
        for zone in scenario["spatial_rainfall_zones"]
    ]
    surface_scenario = validate_surface_request(
        {
            "solver": "anuga",
            "coupling_mode": "surface_rainfall_only",
            "rainfall_source": "custom",
            "rainfall_profile": scenario["rainfall_profile"],
            "terrain_source": "copernicus_dem_glo30",
            "cell_size_m": 500,
            "tail_minutes": 0,
            "output_interval_minutes": 60,
        }
    )
    preview_path = event_dir / "anuga_spatial_forcing_preview.py"
    runner = _load_runner()
    runner._write_model_script(
        preview_path,
        {},
        rainfall_values,
        runner.CITY_BOUNDS,
        rainfall_duration_minutes=scenario["duration_minutes"],
        spatial_zones=spatial_zones,
        default_rainfall_factor=1.0,
    )
    preview_text = preview_path.read_text(encoding="utf-8")
    return {
        "surface_request_validated": True,
        "rainfall_duration_minutes": surface_scenario["rainfall_duration_minutes"],
        "spatial_zone_count": len(surface_scenario["spatial_zones"]),
        "zone_series_lengths": {
            zone["zone_id"]: len(zone["rainfall_values_mm_per_hour"])
            for zone in spatial_zones
        },
        "zone_series_are_distinct": len(
            {
                tuple(zone["rainfall_values_mm_per_hour"])
                for zone in spatial_zones
            }
        ) == len(spatial_zones),
        "generated_script_path": str(preview_path),
        "generated_script_sha256": _sha256(preview_path),
        "generated_script_contains_zone_series": (
            "SPATIAL_ZONES =" in preview_text
            and "zone_values = zone.get(\"rainfall_values_mm_per_hour\")" in preview_text
        ),
        "numerical_run_completed": False,
        "numerical_run_note": (
            "This acceptance script proves request validation and generated independent "
            "cell-zone forcing. Full 72-hour ANUGA integration is a separate heavy run."
        ),
    }


def _run_event(
    *,
    event_id: str,
    start: datetime,
    hourly_values: list[float],
    source_path: Path,
    source_url: str,
    base_swmm: Path,
    output_root: Path,
) -> dict[str, Any]:
    base_values = _hourly_to_five_minute_depths(hourly_values)
    profile = _profile(event_id, start, base_values, source_url)
    scenario = _scenario(profile, start)
    event_dir = output_root / event_id
    event_dir.mkdir(parents=True, exist_ok=True)
    scenario_path = event_dir / "scenario.json"
    scenario_path.write_text(
        json.dumps(scenario, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    swmm_input = event_dir / "scenario_citywide_spatiotemporal.inp"
    rewrite = render_scenario_input(base_swmm, swmm_input, scenario)
    assignment_counts = Counter(
        row[1]
        for row in _section_rows(swmm_input, "SUBCATCHMENTS")
        if len(row) >= 2
    )
    zone_metrics = _zone_metrics(scenario, start)
    peak_times = {item["peak_time_utc"] for item in zone_metrics}
    totals = {item["total_depth_mm"] for item in zone_metrics}
    mapping = rewrite["spatial_mapping"]
    expected_gages = set(mapping.get("zone_gages", {}).values())
    mapped_by_gage = {
        gage: assignment_counts.get(gage, 0)
        for gage in sorted(expected_gages)
    }
    anuga = _build_anuga_preview(event_dir, scenario)
    checks = {
        "public_proxy_has_72_hour_window": len(hourly_values) == 72,
        "five_minute_profile_has_864_intervals": len(base_values) == 864,
        "base_total_matches_hourly_total": math.isclose(
            sum(base_values), sum(hourly_values), rel_tol=0, abs_tol=1e-9
        ),
        "three_zone_peak_times_are_distinct": len(peak_times) == 3,
        "three_zone_totals_are_distinct": len(totals) == 3,
        "swmm_spatial_mapping_applied": mapping.get("applied") is True,
        "swmm_used_outlet_coordinate_fallback": (
            mapping.get("spatial_reference_method") == "subcatchment_outlet_coordinate"
        ),
        "all_real_subcatchments_mapped": (
            mapping.get("mapped_subcatchment_count")
            == mapping.get("total_subcatchment_centroid_count")
        ),
        "every_zone_received_real_subcatchments": all(
            count > 0 for count in mapped_by_gage.values()
        ),
        "anuga_request_and_zone_forcing_generated": (
            anuga["surface_request_validated"]
            and anuga["zone_series_are_distinct"]
            and anuga["generated_script_contains_zone_series"]
        ),
    }
    return {
        "event_id": event_id,
        "event_start_utc": start.isoformat(),
        "event_end_utc": (start + timedelta(hours=72)).isoformat(),
        "source": {
            "provider": "Open-Meteo historical archive",
            "url": source_url,
            "local_path": str(source_path),
            "sha256": _sha256(source_path),
            "evidence_class": "public_proxy",
            "ground_truth": False,
        },
        "base_rainfall": {
            "total_depth_mm": round(sum(hourly_values), 6),
            "maximum_hourly_depth_mm": round(max(hourly_values), 6),
            "maximum_hour_start_utc": (
                start + timedelta(hours=max(range(72), key=hourly_values.__getitem__))
            ).isoformat(),
            "duration_hours": 72,
            "five_minute_interval_count": len(base_values),
        },
        "zone_metrics": zone_metrics,
        "swmm": {
            "base_input": str(base_swmm),
            "base_input_sha256": _sha256(base_swmm),
            "generated_input": str(swmm_input),
            "generated_input_size_bytes": swmm_input.stat().st_size,
            "generated_input_sha256": _sha256(swmm_input),
            "spatial_application": rewrite["spatial_application"],
            "spatial_mapping": mapping,
            "subcatchment_assignment_counts": dict(sorted(assignment_counts.items())),
            "mapped_zone_gage_counts": mapped_by_gage,
            "numerical_run_completed": False,
        },
        "anuga": anuga,
        "checks": checks,
        "passed": all(checks.values()),
        "claim_boundary": (
            "Public-proxy reconstruction and solver-input acceptance evidence only. "
            "It is not customer-authoritative historical reconstruction, calibration, "
            "ground-truth validation, or an engineering-admitted prediction."
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 阿布扎比雨型时空差异端到端验收",
        "",
        f"- 总体状态：{'通过' if report['passed'] else '未通过'}",
        "- 历史降雨证据：Open-Meteo 单点公开代理，不是客户权威雨量站、雷达 QPE 或 ground truth。",
        "- 空间差异：真实全市 SWMM 子汇水区按出口节点坐标映射到三个区域。",
        "- 时间差异：西部后移 90 分钟、Al Bateen 保持公开代理时序、东部前移 60 分钟。",
        "- 二维状态：已验证 ANUGA 请求并生成逐区独立强迫脚本；本脚本不宣称完成 72 小时二维积分。",
        "",
    ]
    for event in report["events"]:
        lines.extend(
            [
                f"## {event['event_id']}",
                "",
                f"- 基准累计雨量：{event['base_rainfall']['total_depth_mm']:.2f} mm",
                f"- 最大小时雨量：{event['base_rainfall']['maximum_hourly_depth_mm']:.2f} mm",
                f"- 基准峰值小时：{event['base_rainfall']['maximum_hour_start_utc']}",
                f"- SWMM 空间映射：{event['swmm']['spatial_application']}",
                f"- 已映射子汇水区：{event['swmm']['spatial_mapping']['mapped_subcatchment_count']}",
                f"- 未映射子汇水区：{event['swmm']['spatial_mapping']['unmapped_subcatchment_count']}",
                "",
                "| 区域 | 累计雨量(mm) | 峰值强度(mm/h) | 峰值时间(UTC) |",
                "|---|---:|---:|---|",
            ]
        )
        for zone in event["zone_metrics"]:
            lines.append(
                f"| {zone['zone_id']} | {zone['total_depth_mm']:.2f} | "
                f"{zone['peak_intensity_mm_per_hour']:.2f} | {zone['peak_time_utc']} |"
            )
        lines.extend(["", "验收检查："])
        for key, passed in event["checks"].items():
            lines.append(f"- [{'x' if passed else ' '}] {key}")
        lines.append("")
    lines.extend(
        [
            "## 尚不能据此宣称的内容",
            "",
            "- 尚未用客户权威站点/雷达时空场还原真实降雨分布。",
            "- 尚未用 2024 年 4 月客户 ground truth 做水深/范围/时序验证。",
            "- 尚未在本验收脚本中完成两个 72 小时事件的 SWMM 和 ANUGA 全程数值积分。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--swmm-input", type=Path, default=DEFAULT_SWMM_INPUT)
    parser.add_argument("--source-2024", type=Path, default=DEFAULT_2024_SOURCE)
    parser.add_argument("--source-2026", type=Path, default=DEFAULT_2026_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    base_swmm = args.swmm_input.expanduser().resolve()
    source_2024 = args.source_2024.expanduser().resolve()
    source_2026 = args.source_2026.expanduser().resolve()
    output = args.output.expanduser().resolve()
    for required in (base_swmm, source_2024, source_2026):
        if not required.is_file():
            raise FileNotFoundError(required)
    output.mkdir(parents=True, exist_ok=True)

    start_2024 = datetime(2024, 4, 15)
    start_2026 = datetime(2026, 3, 25)
    events = [
        _run_event(
            event_id="2024-04-15_to_2024-04-17_public_proxy",
            start=start_2024,
            hourly_values=_read_hourly_window(source_2024, start_2024),
            source_path=source_2024,
            source_url=OPEN_METEO_2024_URL,
            base_swmm=base_swmm,
            output_root=output,
        ),
        _run_event(
            event_id="2026-03-25_to_2026-03-27_public_proxy",
            start=start_2026,
            hourly_values=_read_hourly_window(source_2026, start_2026),
            source_path=source_2026,
            source_url=OPEN_METEO_2026_URL,
            base_swmm=base_swmm,
            output_root=output,
        ),
    ]
    report = {
        "schema": "gwm.abu_dhabi_spatiotemporal_rainfall_acceptance.v1",
        "generated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "test_type": "real_citywide_input_chain_acceptance",
        "events": events,
        "passed": all(event["passed"] for event in events),
        "evidence_levels": {
            "unit_tests": "separate pytest suite",
            "real_swmm_input_generation": "completed by this report",
            "real_swmm_numerical_run": "not completed by this report",
            "anuga_spatial_forcing_generation": "completed by this report",
            "real_anuga_72h_numerical_run": "not completed by this report",
        },
    }
    report_path = output / "验收报告.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path = output / "验收结论.md"
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({
        "passed": report["passed"],
        "report": str(report_path),
        "markdown": str(markdown_path),
        "events": [
            {
                "event_id": event["event_id"],
                "base_total_depth_mm": event["base_rainfall"]["total_depth_mm"],
                "mapped_subcatchments": event["swmm"]["spatial_mapping"]["mapped_subcatchment_count"],
                "unmapped_subcatchments": event["swmm"]["spatial_mapping"]["unmapped_subcatchment_count"],
                "zone_metrics": event["zone_metrics"],
            }
            for event in events
        ],
    }, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
