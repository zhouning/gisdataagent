"""Interactive, diagnostic-only EPA SWMM scenarios for Abu Dhabi.

The service deliberately keeps customer inputs outside the repository.  It
copies the registered city partition inputs into a private run directory,
rewrites only scenario controls, invokes the existing isolated SWMM adapter,
and returns auditable partition-level summaries.  It does not grant model
admission or make an engineering prediction claim.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .abu_dhabi_zone_b_design_storm import (
    SUPPORTED_RETURN_PERIODS,
    official_depth_mm,
    zone_b_180_minute_hyetograph,
)
from .uwm.abu_dhabi_flood.swmm_adapter import evaluate_swmm_quality, execute_swmm
from .uwm.abu_dhabi_flood.swmm_out_parser import (
    read_node_period,
    read_swmm_out_header,
    timeline_from_header,
)
from .uwm.abu_dhabi_flood.traditional_solver import (
    TraditionalSolverExecutionError,
    TraditionalSolverQualityPolicy,
    TraditionalSolverRunRequest,
)


DEFAULT_PRIVATE_ROOT = (
    Path.home() / ".local/share/gisdataagent/private/abu_dhabi_stormwater"
)
DEFAULT_INPUT_ROOT = DEFAULT_PRIVATE_ROOT / "customer_city_swmm_full_diagnostic_20260825"
DEFAULT_FULL_CITY_INPUT = DEFAULT_INPUT_ROOT / "abu_dhabi_city_full_topology.inp"
DEFAULT_RUN_ROOT = DEFAULT_PRIVATE_ROOT / "customer_interactive_swmm_runs"
DEFAULT_EXECUTABLE = Path(__file__).resolve().parents[1] / (
    "external_models/swmm-5.2.4/build-local/bin/runswmm"
)
DEFAULT_NODE_GEOMETRY = DEFAULT_PRIVATE_ROOT / "customer_city_swmm_spatial_results_20260824" / "abu_dhabi_city_swmm_node_results.geojson"
SWMM_SCENARIO_SCHEMA = "gwm.abu_dhabi_flood.interactive_swmm_scenario.v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_FLOAT = r"[-+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[Ee][-+]?[0-9]+)?"
_MAX_PARTITIONS = 30
_STEP_MINUTES = 5
_PUBLIC_RAINFALL_SOURCE = "open_meteo_archive"
_PUBLIC_RAINFALL_SOURCE_URL = "https://archive-api.open-meteo.com/v1/archive"
_ABU_DHABI_LATITUDE = 24.4539
_ABU_DHABI_LONGITUDE = 54.3773

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="abu-swmm")
_RUNS: dict[str, dict[str, Any]] = {}
_RUN_LOCK = threading.RLock()


def _configured_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else default


def _private_input_root() -> Path:
    return _configured_path("ABU_DHABI_SWMM_INPUT_ROOT", DEFAULT_INPUT_ROOT)


def _private_run_root() -> Path:
    return _configured_path("ABU_DHABI_SWMM_INTERACTIVE_RUN_ROOT", DEFAULT_RUN_ROOT)


def _executable() -> Path:
    return _configured_path("ABU_DHABI_SWMM_EXECUTABLE", DEFAULT_EXECUTABLE)


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _as_number(value: Any, name: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name}_invalid")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ValueError(f"{name}_below_minimum")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name}_above_maximum")
    return number


def _parse_start(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("start_time_required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("start_time_invalid") from error
    # SWMM input has no timezone field.  Accept an offset but bind the
    # resulting wall-clock instant to UTC for a deterministic receipt.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    parsed = parsed.replace(second=0, microsecond=0)
    if parsed.minute % _STEP_MINUTES:
        raise ValueError("start_time_must_align_to_5_minutes")
    return parsed


def validate_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("scenario_payload_invalid")
    scope = payload.get("scope", "citywide")
    if scope not in {"citywide", "partition"}:
        raise ValueError("scope_invalid")
    partition_value = payload.get("partition", "all")
    if scope == "partition":
        try:
            partition_id = int(str(partition_value))
        except (TypeError, ValueError) as error:
            raise ValueError("partition_invalid") from error
        if not 0 <= partition_id < _MAX_PARTITIONS:
            # The UI labels partitions 01-30; accepting both 0-based and
            # 1-based labels keeps the API explicit while avoiding surprises.
            if 1 <= partition_id <= _MAX_PARTITIONS:
                partition_id -= 1
            else:
                raise ValueError("partition_invalid")
        partitions = [partition_id]
    else:
        # Citywide scenarios run one topology-preserving SWMM model.  The
        # former 30 entries were independent graph chunks and could not be
        # presented as a citywide hydraulic result.
        partitions = ["full_city"]
        partition_id = None
    rainfall_mode = payload.get("rainfallMode", payload.get("rainfall_mode", "design_storm"))
    if rainfall_mode not in {"design_storm", "online_public", "historical_event"}:
        raise ValueError("rainfall_mode_invalid")
    if rainfall_mode == "historical_event":
        raise ValueError("historical_event_requires_authoritative_timeseries")
    duration = _as_number(payload.get("durationMinutes", payload.get("duration_minutes")), "duration_minutes", minimum=5, maximum=4320)
    tail = _as_number(payload.get("tailMinutes", payload.get("tail_minutes", 0)), "tail_minutes", minimum=0, maximum=1440)
    if duration % _STEP_MINUTES or tail % _STEP_MINUTES:
        raise ValueError("duration_and_tail_must_be_multiples_of_5_minutes")
    if duration + tail > 4320:
        raise ValueError("total_simulation_window_exceeds_72_hours")
    pattern = payload.get("rainfallPattern", payload.get("rainfall_pattern", "uniform"))
    if pattern not in {"uniform", "front_loaded", "alternating_block", "official_zone_b_ddf_abm"}:
        raise ValueError("rainfall_pattern_invalid")
    return_period_value = payload.get("returnPeriodYears", payload.get("return_period_years"))
    return_period: int | None = None
    if rainfall_mode == "design_storm" and pattern == "official_zone_b_ddf_abm":
        if isinstance(return_period_value, bool):
            raise ValueError("return_period_years_invalid")
        try:
            return_period = int(return_period_value)
        except (TypeError, ValueError) as error:
            raise ValueError("return_period_years_required") from error
        if return_period not in SUPPORTED_RETURN_PERIODS:
            raise ValueError("return_period_years_not_supported")
        if duration != 180:
            raise ValueError("official_zone_b_ddf_requires_180_minute_duration")
        depth = official_depth_mm(return_period, 180)
        depth_value = payload.get("totalDepthMm", payload.get("total_depth_mm"))
        if depth_value is not None:
            supplied_depth = _as_number(depth_value, "total_depth_mm", minimum=0.001, maximum=1000)
            if not math.isclose(supplied_depth, depth, abs_tol=0.011):
                raise ValueError("official_zone_b_total_depth_mismatch")
    else:
        depth_value = payload.get("totalDepthMm", payload.get("total_depth_mm"))
        depth = (
            _as_number(depth_value, "total_depth_mm", minimum=0.001, maximum=1000)
            if rainfall_mode == "design_storm"
            else None
        )
    peak = _as_number(payload.get("peakPosition", payload.get("peak_position", 40)), "peak_position", minimum=0, maximum=100)
    spatial = payload.get("spatialPattern", payload.get("spatial_pattern", "uniform"))
    if spatial not in {"uniform", "zonal"}:
        raise ValueError("spatial_pattern_invalid")
    pipe_scope = payload.get("pipeScope", payload.get("pipe_scope", "none"))
    if pipe_scope not in {"none", "priority_corridor", "selected_zone"}:
        raise ValueError("pipe_scope_invalid")
    blockage = _as_number(payload.get("blockagePercent", payload.get("blockage_percent", 0)), "blockage_percent", minimum=0, maximum=90)
    capacity = _as_number(payload.get("pipeCapacityMultiplier", payload.get("pipe_capacity_multiplier", 1)), "pipe_capacity_multiplier", minimum=0.1, maximum=1.5)
    pump_enabled = bool(payload.get("pumpEnabled", payload.get("pump_enabled", True)))
    pump_capacity = _as_number(payload.get("pumpCapacityMultiplier", payload.get("pump_capacity_multiplier", 1)), "pump_capacity_multiplier", minimum=0, maximum=1.5)
    outfall_mode = payload.get("outfallMode", payload.get("outfall_mode", "open"))
    if outfall_mode not in {"open", "fixed_level"}:
        raise ValueError("outfall_mode_invalid")
    outfall_level = _as_number(payload.get("outfallLevelM", payload.get("outfall_level_m", 0)), "outfall_level_m", minimum=-100, maximum=100)
    report_step = int(_as_number(payload.get("outputIntervalMinutes", payload.get("output_interval_minutes", 5)), "output_interval_minutes", minimum=5, maximum=60))
    if report_step % 5:
        raise ValueError("output_interval_must_be_a_multiple_of_5_minutes")
    start = _parse_start(payload.get("startTime", payload.get("start_time")))
    public_source = payload.get("publicRainfallSource", payload.get("public_rainfall_source", _PUBLIC_RAINFALL_SOURCE))
    if rainfall_mode == "online_public" and public_source != _PUBLIC_RAINFALL_SOURCE:
        raise ValueError("public_rainfall_source_invalid")
    latitude = _as_number(
        payload.get("publicLatitude", payload.get("public_latitude", _ABU_DHABI_LATITUDE)),
        "public_latitude",
        minimum=-90,
        maximum=90,
    )
    longitude = _as_number(
        payload.get("publicLongitude", payload.get("public_longitude", _ABU_DHABI_LONGITUDE)),
        "public_longitude",
        minimum=-180,
        maximum=180,
    )
    return {
        "schema": SWMM_SCENARIO_SCHEMA,
        "scope": scope,
        "partition": partition_id,
        "partitions": partitions,
        "rainfall_mode": rainfall_mode,
        "public_rainfall_source": public_source if rainfall_mode == "online_public" else None,
        "public_latitude": latitude,
        "public_longitude": longitude,
        "start_time": start.isoformat(timespec="minutes"),
        "duration_minutes": int(duration),
        "tail_minutes": int(tail),
        "total_depth_mm": depth,
        "rainfall_pattern": pattern,
        "return_period_years": return_period,
        "peak_position": peak,
        "spatial_pattern": spatial,
        "pipe_scope": pipe_scope,
        "blockage_percent": blockage,
        "pipe_capacity_multiplier": capacity,
        "pump_enabled": pump_enabled,
        "pump_capacity_multiplier": pump_capacity,
        "outfall_mode": outfall_mode,
        "outfall_level_m": outfall_level,
        "output_interval_minutes": report_step,
    }


def _design_rainfall_series(scenario: dict[str, Any]) -> tuple[list[tuple[datetime, float]], dict[str, Any]]:
    if scenario["rainfall_pattern"] == "official_zone_b_ddf_abm":
        return zone_b_180_minute_hyetograph(
            int(scenario["return_period_years"]),
            start=datetime.fromisoformat(scenario["start_time"]),
            peak_position_percent=float(scenario["peak_position"]),
            tail_minutes=int(scenario["tail_minutes"]),
        )
    count = int(scenario["duration_minutes"] // _STEP_MINUTES)
    peak_position = float(scenario["peak_position"]) / 100.0
    raw: list[float] = []
    for index in range(count):
        x = (index + 0.5) / count
        if scenario["rainfall_pattern"] == "uniform":
            weight = 1.0
        elif scenario["rainfall_pattern"] == "front_loaded":
            weight = max(0.15, 2.0 - 1.5 * x)
        else:
            distance = abs(x - peak_position)
            weight = max(0.12, 1.9 - distance * 4.0)
        raw.append(weight)
    total = float(scenario["total_depth_mm"])
    depths = [total * value / sum(raw) for value in raw]
    start = datetime.fromisoformat(scenario["start_time"])
    values = [(start + timedelta(minutes=index * _STEP_MINUTES), depth * 12.0) for index, depth in enumerate(depths)]
    end_of_rain = start + timedelta(minutes=int(scenario["duration_minutes"]))
    simulation_end = end_of_rain + timedelta(minutes=int(scenario["tail_minutes"]))
    values.extend([(end_of_rain, 0.0), (simulation_end, 0.0)])
    return values, {
        "source": "parameterized_design_storm",
        "source_label": "参数化设计暴雨",
        "source_authority": "model_parameter",
        "source_url": None,
        "native_interval_minutes": _STEP_MINUTES,
        "resampling_method": "none",
        "generated_intervals": float(count),
        "generated_total_depth_mm": float(sum(depths)),
        "peak_intensity_mm_per_hour": float(max(value for _, value in values)),
    }


def _read_open_meteo_precipitation(
    scenario: dict[str, Any],
) -> tuple[dict[datetime, float], str, dict[str, Any]]:
    start = datetime.fromisoformat(scenario["start_time"])
    end = start + timedelta(minutes=int(scenario["duration_minutes"]) - _STEP_MINUTES)
    query = urlencode(
        {
            "latitude": f"{float(scenario['public_latitude']):.6f}",
            "longitude": f"{float(scenario['public_longitude']):.6f}",
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
            "hourly": "precipitation",
            "timezone": "UTC",
        }
    )
    url = f"{_PUBLIC_RAINFALL_SOURCE_URL}?{query}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "GISDataAgent-AbuDhabiFloodPrototype/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        raise ValueError("online_public_rainfall_fetch_failed") from error
    hourly = payload.get("hourly") if isinstance(payload, dict) else None
    times = hourly.get("time") if isinstance(hourly, dict) else None
    values = hourly.get("precipitation") if isinstance(hourly, dict) else None
    if not isinstance(times, list) or not isinstance(values, list) or len(times) != len(values) or not times:
        raise ValueError("online_public_rainfall_payload_invalid")
    result: dict[datetime, float] = {}
    for timestamp, value in zip(times, values, strict=True):
        try:
            stamp = datetime.fromisoformat(str(timestamp)).replace(tzinfo=None)
            if value is None:
                raise ValueError("online_public_rainfall_value_missing")
            amount = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError("online_public_rainfall_payload_invalid") from error
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("online_public_rainfall_value_invalid")
        result[stamp] = amount
    resolved_location = {
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "timezone": payload.get("timezone"),
        "elevation": payload.get("elevation"),
    }
    return result, url, resolved_location


def _online_public_rainfall_series(scenario: dict[str, Any]) -> tuple[list[tuple[datetime, float]], dict[str, Any]]:
    hourly, source_url, resolved_location = _read_open_meteo_precipitation(scenario)
    start = datetime.fromisoformat(scenario["start_time"])
    count = int(scenario["duration_minutes"] // _STEP_MINUTES)
    values: list[tuple[datetime, float]] = []
    for index in range(count):
        stamp = start + timedelta(minutes=index * _STEP_MINUTES)
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        # Open-Meteo precipitation is the hourly accumulated depth in mm.
        # SWMM receives the equivalent constant hourly intensity for each of
        # the six five-minute routing intervals in that hour.
        if hour not in hourly:
            raise ValueError("online_public_rainfall_window_incomplete")
        intensity_mm_per_hour = float(hourly[hour])
        values.append((stamp, intensity_mm_per_hour))
    end_of_rain = start + timedelta(minutes=int(scenario["duration_minutes"]))
    simulation_end = end_of_rain + timedelta(minutes=int(scenario["tail_minutes"]))
    values.extend([(end_of_rain, 0.0), (simulation_end, 0.0)])
    total_depth = sum(value * _STEP_MINUTES / 60.0 for _, value in values[:count])
    return values, {
        "source": "online_public_open_meteo",
        "source_label": "在线公开来源降雨数据（Open-Meteo）",
        "source_authority": "public_proxy",
        "source_url": source_url,
        "provider": "Open-Meteo Archive API",
        "requested_latitude": float(scenario["public_latitude"]),
        "requested_longitude": float(scenario["public_longitude"]),
        "resolved_location": resolved_location,
        "native_interval_minutes": 60,
        "resampling_method": "hourly_accumulated_depth_to_constant_5_minute_intensity",
        "generated_intervals": float(count),
        "generated_total_depth_mm": float(total_depth),
        "peak_intensity_mm_per_hour": float(max((value for _, value in values[:count]), default=0.0)),
    }


def _rainfall_series(scenario: dict[str, Any]) -> tuple[list[tuple[datetime, float]], dict[str, Any]]:
    mode = scenario.get("rainfall_mode", "design_storm")
    if mode == "design_storm":
        return _design_rainfall_series(scenario)
    if mode == "online_public":
        return _online_public_rainfall_series(scenario)
    raise ValueError("historical_event_requires_authoritative_timeseries")


def _section_indexes(lines: list[str]) -> dict[str, tuple[int, int]]:
    starts = [(index, line.strip().upper()) for index, line in enumerate(lines) if line.strip().startswith("[") and line.strip().endswith("]")]
    result: dict[str, tuple[int, int]] = {}
    for position, (index, name) in enumerate(starts):
        result[name] = (index, starts[position + 1][0] if position + 1 < len(starts) else len(lines))
    return result


def _replace_option(lines: list[str], begin: int, end: int, key: str, value: str) -> None:
    pattern = re.compile(rf"^(\s*){re.escape(key)}\b", re.IGNORECASE)
    for index in range(begin + 1, end):
        if pattern.match(lines[index]) and not lines[index].lstrip().startswith(";"):
            lines[index] = f"{key}  {value}"
            return
    lines.insert(end, f"{key}  {value}")


def _replace_section(lines: list[str], section: str, content: list[str]) -> None:
    sections = _section_indexes(lines)
    if section not in sections:
        raise ValueError(f"swmm_section_missing:{section}")
    begin, end = sections[section]
    lines[begin + 1:end] = content


def render_scenario_input(
    base: Path,
    output: Path,
    scenario: dict[str, Any],
    rainfall_series: list[tuple[datetime, float]] | None = None,
) -> dict[str, Any]:
    text = base.read_text(encoding="utf-8")
    lines = text.splitlines()
    sections = _section_indexes(lines)
    rainfall, rainfall_stats = (
        (rainfall_series, scenario.get("rainfall_stats", {}))
        if rainfall_series is not None
        else _rainfall_series(scenario)
    )
    start = datetime.fromisoformat(scenario["start_time"])
    simulation_end = start + timedelta(minutes=scenario["duration_minutes"] + scenario["tail_minutes"])
    _replace_option(lines, *sections["[OPTIONS]"], "START_DATE", start.strftime("%m/%d/%Y"))
    _replace_option(lines, *sections["[OPTIONS]"], "START_TIME", start.strftime("%H:%M:%S"))
    _replace_option(lines, *sections["[OPTIONS]"], "REPORT_START_DATE", start.strftime("%m/%d/%Y"))
    _replace_option(lines, *sections["[OPTIONS]"], "REPORT_START_TIME", start.strftime("%H:%M:%S"))
    _replace_option(lines, *sections["[OPTIONS]"], "END_DATE", simulation_end.strftime("%m/%d/%Y"))
    _replace_option(lines, *sections["[OPTIONS]"], "END_TIME", simulation_end.strftime("%H:%M:%S"))
    step = f"00:{scenario['output_interval_minutes']:02d}:00"
    _replace_option(lines, *sections["[OPTIONS]"], "REPORT_STEP", step)
    _replace_option(lines, *sections["[OPTIONS]"], "WET_STEP", "00:05:00")
    _replace_option(lines, *sections["[OPTIONS]"], "ROUTING_STEP", "00:05:00")
    _replace_section(lines, "[RAINGAGES]", ["RG_INTERACTIVE  INTENSITY  00:05  1.0  TIMESERIES  TS_INTERACTIVE"])
    # The registered baseline uses RG_PUBLIC in every subcatchment.  Bind all
    # of those references to the scenario gage while leaving the geometry and
    # runoff parameters untouched.
    subcatchment_begin, subcatchment_end = _section_indexes(lines)["[SUBCATCHMENTS]"]
    for index in range(subcatchment_begin + 1, subcatchment_end):
        if lines[index].lstrip().startswith(";"):
            continue
        parts = lines[index].split()
        if len(parts) >= 2 and parts[1] == "RG_PUBLIC":
            parts[1] = "RG_INTERACTIVE"
            lines[index] = "  ".join(parts)
    timeseries = [f"TS_INTERACTIVE  {stamp.strftime('%m/%d/%Y')}  {stamp.strftime('%H:%M')}  {intensity:.8f}" for stamp, intensity in rainfall]
    _replace_section(lines, "[TIMESERIES]", timeseries)
    if scenario["outfall_mode"] == "fixed_level":
        begin, end = _section_indexes(lines)["[OUTFALLS]"]
        fixed_lines = []
        for line in lines[begin + 1:end]:
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                fixed_lines.append(line)
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                fixed_lines.append(f"{parts[0]}  {parts[1]}  FIXED  {scenario['outfall_level_m']:.3f}  NO")
            else:
                fixed_lines.append(line)
        _replace_section(lines, "[OUTFALLS]", fixed_lines)
    capacity_factor = float(scenario["pipe_capacity_multiplier"]) * (1.0 - float(scenario["blockage_percent"]) / 100.0)
    modified_xsections = 0
    if scenario["pipe_scope"] != "none" and abs(capacity_factor - 1.0) > 1e-12:
        diameter_factor = capacity_factor ** (3.0 / 8.0)
        begin, end = _section_indexes(lines)["[XSECTIONS]"]
        modified = []
        for line in lines[begin + 1:end]:
            stripped = line.strip()
            if not stripped or stripped.startswith(";"):
                modified.append(line)
                continue
            parts = stripped.split()
            if len(parts) >= 3 and parts[1].upper() == "CIRCULAR":
                try:
                    parts[2] = f"{float(parts[2]) * diameter_factor:.6f}"
                    modified_xsections += 1
                    modified.append("  ".join(parts))
                except ValueError:
                    modified.append(line)
            else:
                modified.append(line)
        _replace_section(lines, "[XSECTIONS]", modified)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "rainfall": rainfall_stats,
        "rainfall_step_minutes": _STEP_MINUTES,
        "capacity_factor": capacity_factor,
        "equivalent_diameter_factor": capacity_factor ** (3.0 / 8.0),
        "modified_xsection_count": modified_xsections,
        "outfall_mode_applied": scenario["outfall_mode"],
    }


def _summary(receipt: dict[str, Any]) -> dict[str, Any]:
    report = receipt.get("parsed_report", {})
    routing = report.get("flow_routing_continuity", {})
    runoff = report.get("runoff_quantity_continuity", {})
    def pair_second(value: Any) -> float | None:
        try:
            return float(value["second"])
        except (KeyError, TypeError, ValueError):
            return None
    return {
        "solver": report.get("solver", {}),
        "node_count": report.get("element_counts", {}).get("nodes"),
        "link_count": report.get("element_counts", {}).get("links"),
        "routing_method": report.get("analysis_options", {}).get("flow_routing_method"),
        "external_outflow_million_litres": pair_second(routing.get("external_outflow")),
        "flooding_loss_million_litres": pair_second(routing.get("flooding_loss")),
        "runoff_continuity_error_percent": runoff.get("continuity_error_percent"),
        "routing_continuity_error_percent": routing.get("continuity_error_percent"),
        "node_flooding_detected": report.get("node_flooding", {}).get("detected"),
        "numerical_quality_passed": (
            receipt.get("strict_quality_gates", receipt.get("quality_gates", {})).get("passed")
        ),
    }


_NODE_DEPTH_ROW = re.compile(
    rf"^\s*(?P<node>\S+)\s+(?P<node_type>\S+)\s+"
    rf"(?P<average>{_FLOAT})\s+(?P<depth>{_FLOAT})\s+(?P<hgl>{_FLOAT})\s+"
    rf"(?P<day>\d+)\s+(?P<time>\d{{2}}:\d{{2}})\s+(?P<reported>{_FLOAT})\s*$"
)
_NODE_FLOODING_ROW = re.compile(
    rf"^\s*(?P<node>\S+)\s+(?P<hours>{_FLOAT})\s+(?P<rate>{_FLOAT})\s+"
    rf"(?P<day>\d+)\s+(?P<time>\d{{2}}:\d{{2}})\s+(?P<volume>{_FLOAT})\s+"
    rf"(?P<ponded>{_FLOAT})(?:\s+\S+)?\s*$"
)


def _report_section(report_text: str, title: str, next_title: str) -> list[str]:
    begin = report_text.find(title)
    if begin < 0:
        return []
    end = report_text.find(next_title, begin + len(title))
    if end < 0:
        end = len(report_text)
    return report_text[begin:end].splitlines()


def _parse_node_hydraulic_results(report_path: Path) -> dict[str, dict[str, Any]]:
    """Parse node maxima and flooding rows from a native SWMM RPT.

    SWMM's RPT is the authoritative human-readable result for this diagnostic
    run. The binary OUT remains retained for audit, but is not needed to
    produce the maximum node result layer shown by the prototype.
    """
    text = report_path.read_text(encoding="utf-8", errors="replace")
    results: dict[str, dict[str, Any]] = {}
    for line in _report_section(text, "Node Depth Summary", "Node Inflow Summary"):
        match = _NODE_DEPTH_ROW.match(line)
        if not match:
            continue
        values = match.groupdict()
        results[values["node"]] = {
            "node_id": values["node"],
            "node_type": values["node_type"],
            "max_average_depth_m": float(values["average"]),
            "max_water_depth_m": float(values["depth"]),
            "max_hydraulic_head_m": float(values["hgl"]),
            "max_depth_day": int(values["day"]),
            "max_depth_time": values["time"],
            "reported_max_depth_m": float(values["reported"]),
        }
    for line in _report_section(text, "Node Flooding Summary", "Node Outflow Summary"):
        match = _NODE_FLOODING_ROW.match(line)
        if not match:
            continue
        values = match.groupdict()
        row = results.setdefault(values["node"], {"node_id": values["node"]})
        row.update(
            {
                "flooded_hours": float(values["hours"]),
                "max_overflow_or_flooding_m3s": float(values["rate"]),
                "flooding_day": int(values["day"]),
                "flooding_time": values["time"],
                "total_flood_volume_million_litres": float(values["volume"]),
                "maximum_ponded_volume_thousand_m3": float(values["ponded"]),
            }
        )
    return results


def _native_node_hydraulic_results(out_path: Path) -> dict[str, dict[str, Any]]:
    """Aggregate node maxima directly from native SWMM OUT periods.

    Full-city reports intentionally suppress per-object RPT tables to keep
    the text report bounded.  The OUT binary still contains every reporting
    period, so this path is the authoritative source for the map result.
    """
    header = _swmm_out_header(out_path)
    names = [str(value) for value in header.get("node_names", [])]
    aggregate: dict[str, dict[str, Any]] = {
        name: {
            "node_id": name,
            "max_water_depth_m": 0.0,
            "max_hydraulic_head_m": 0.0,
            "max_stored_volume_m3": 0.0,
            "max_total_inflow_m3s": 0.0,
            "max_overflow_or_flooding_m3s": 0.0,
            "flooded_hours": 0.0,
            "total_flood_volume_million_litres": 0.0,
        }
        for name in names
    }
    for time_index in range(int(header["period_count"])):
        period = read_node_period(out_path, header, time_index)
        for position, values in enumerate(period["nodes"]):
            if position >= len(names) or len(values) < 6:
                continue
            row = aggregate[names[position]]
            depth, head, stored, _lateral, inflow, overflow = (
                float(values[index]) for index in range(6)
            )
            row["max_water_depth_m"] = max(row["max_water_depth_m"], max(0.0, depth))
            row["max_hydraulic_head_m"] = max(row["max_hydraulic_head_m"], head)
            row["max_stored_volume_m3"] = max(row["max_stored_volume_m3"], max(0.0, stored))
            row["max_total_inflow_m3s"] = max(row["max_total_inflow_m3s"], max(0.0, inflow))
            row["max_overflow_or_flooding_m3s"] = max(row["max_overflow_or_flooding_m3s"], max(0.0, overflow))
            if overflow > 0.0:
                row["flooded_hours"] += float(header["report_step_seconds"]) / 3600.0
                row["total_flood_volume_million_litres"] += overflow * float(header["report_step_seconds"]) / 1000.0
    return aggregate


@lru_cache(maxsize=4)
def _cached_node_geometry_index(path_text: str, modified_ns: int, size: int) -> dict[str, dict[str, Any]]:
    """Load the private, customer-node geometry index used for map joins."""
    path = Path(path_text)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(feature.get("properties", {}).get("node_id")): feature.get("geometry")
        for feature in payload.get("features", [])
        if feature.get("properties", {}).get("node_id") and feature.get("geometry")
    }


@lru_cache(maxsize=4)
def _cached_private_node_geometry_index(path_text: str, modified_ns: int, size: int) -> dict[str, dict[str, Any]]:
    """Project the complete customer node snapshot to WGS84 for full-city joins."""
    try:
        import pandas as pd
        from pyproj import Transformer

        frame = pd.read_parquet(path_text, columns=["node_id", "snap_x_m", "snap_y_m"])
        transformer = Transformer.from_crs(32640, 4326, always_xy=True)
        x_values = frame["snap_x_m"].astype(float).to_numpy()
        y_values = frame["snap_y_m"].astype(float).to_numpy()
        longitudes, latitudes = transformer.transform(x_values, y_values)
        return {
            str(node_id): {"type": "Point", "coordinates": [float(lon), float(lat)]}
            for node_id, lon, lat in zip(frame["node_id"], longitudes, latitudes, strict=True)
        }
    except (OSError, ValueError, ImportError, KeyError):
        return {}


def _node_geometry_index() -> dict[str, dict[str, Any]]:
    path = _configured_path("ABU_DHABI_SWMM_NODE_GEOMETRY", DEFAULT_NODE_GEOMETRY).expanduser().resolve()
    try:
        stat = path.stat()
        result = _cached_node_geometry_index(str(path), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        result = {}
    # The old prototype GeoJSON contains only the independent-chunk subset.
    # Merge the private customer snapshot so full-city OUT node IDs resolve to
    # their real locations without publishing customer geometry.
    private_path = _configured_path(
        "ABU_DHABI_SWMM_NODE_SNAPSHOT",
        DEFAULT_PRIVATE_ROOT / "customer_stormwater_nodes.private.parquet",
    ).expanduser().resolve()
    try:
        private_stat = private_path.stat()
        result.update(_cached_private_node_geometry_index(str(private_path), int(private_stat.st_mtime_ns), int(private_stat.st_size)))
    except OSError:
        pass
    return result


@lru_cache(maxsize=256)
def _cached_swmm_out_header(path_text: str, modified_ns: int, size: int) -> dict[str, Any]:
    return read_swmm_out_header(Path(path_text))


def _swmm_out_header(path: Path) -> dict[str, Any]:
    source = path.expanduser().resolve()
    try:
        stat = source.stat()
    except OSError as error:
        raise ValueError("swmm_out_missing") from error
    return _cached_swmm_out_header(str(source), int(stat.st_mtime_ns), int(stat.st_size))


def _completed_partition_rows(run: dict[str, Any]) -> tuple[dict[Any, dict[str, Any]], set[Any]]:
    rows = {
        row.get("partition_id"): row
        for row in run.get("partitions", [])
        if row.get("partition_id") is not None
    }
    selected = set(run.get("scenario", {}).get("partitions", []))
    return rows, selected


def _partition_label(partition_id: Any) -> str:
    return "full_city" if partition_id == "full_city" else f"partition_{int(partition_id):02d}"


def _partition_out_path(run_id: str, partition_id: Any) -> Path | None:
    directory = _private_run_root().expanduser().resolve() / run_id / _partition_label(partition_id) / "native_swmm_results"
    paths = sorted(directory.glob("*.out"))
    return paths[0] if paths else None


def _scenario_timeline(run_id: str, run: dict[str, Any]) -> dict[str, Any]:
    rows, selected = _completed_partition_rows(run)
    headers = []
    for partition_id in sorted(selected or rows, key=str):
        row = rows.get(partition_id)
        if not row or row.get("status") not in {"completed", "completed_quality_warning"}:
            continue
        path = _partition_out_path(run_id, partition_id)
        if path:
            try:
                headers.append(_swmm_out_header(path))
            except ValueError:
                continue
    if not headers:
        return {
            "available": False,
            "source": "native SWMM OUT binary reporting periods",
            "reason": "no_completed_native_out_files",
        }
    # All partitions are rendered from one scenario input, so their report
    # clocks should agree.  Use the shortest valid axis if a failed/partial
    # native output has a different period count.
    first = headers[0]
    period_count = min(int(header["period_count"]) for header in headers)
    timeline = timeline_from_header({**first, "period_count": period_count})
    timeline["partition_count"] = len(headers)
    timeline["total_node_count"] = sum(int(header.get("n_nodes", 0)) for header in headers)
    timeline["solver_version"] = "5.2.4"
    return timeline


def _fallback_node_geometry(input_path: Path, node_id: str) -> dict[str, Any] | None:
    """Transform a partition INP coordinate when the canonical index is absent."""
    try:
        text = input_path.read_text(encoding="utf-8", errors="replace")
        section = _section_indexes(text.splitlines()).get("[COORDINATES]")
        if not section:
            return None
        lines = text.splitlines()
        for line in lines[section[0] + 1:section[1]]:
            parts = line.split()
            if len(parts) < 3 or parts[0] != node_id:
                continue
            from pyproj import Transformer

            lon, lat = Transformer.from_crs(32640, 4326, always_xy=True).transform(float(parts[1]), float(parts[2]))
            return {"type": "Point", "coordinates": [lon, lat]}
    except (OSError, ValueError, ImportError):
        return None
    return None


def _run_worker(run_id: str, scenario: dict[str, Any]) -> None:
    run_root = _private_run_root().expanduser().resolve() / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    _json_write(run_root / "scenario_request.json", scenario)
    manifest: dict[str, Any] = {
        "schema": SWMM_SCENARIO_SCHEMA,
        "run_id": run_id,
        "status": "running",
        "started_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "scenario": scenario,
        "traditional_solver_invoked": True,
        "pump_action_applied": False,
        "warnings": ["current_baseline_input_contains_no_pump_links"],
        "partitions": [],
        "claim_boundary": [
            "diagnostic_only",
            "not_calibrated_against_observations",
            "not_engineering_admitted",
            "not_a_city_scale_prediction_claim",
        ],
    }
    if scenario["spatial_pattern"] == "zonal":
        manifest["warnings"].append("zonal_spatial_pattern_not_applied_without_authoritative_zone_coefficients")
    if scenario["pipe_scope"] in {"priority_corridor", "selected_zone"}:
        manifest["warnings"].append("pipe_scope_geometry_not_available_action_applied_to_all_links_in_selected_partitions")
    _update_run(run_id, status="running", manifest=manifest)
    input_root = _private_input_root().expanduser().resolve()
    executable = _executable().expanduser().resolve()
    try:
        rainfall_series, rainfall_stats = _rainfall_series(scenario)
        scenario["rainfall_stats"] = rainfall_stats
        manifest["scenario"] = scenario
        # Persist the resolved source descriptor, not only the original form
        # values.  This makes every private run auditable after the worker has
        # fetched the public source and expanded it to the SWMM step.
        _json_write(run_root / "scenario_request.json", scenario)
        if scenario["rainfall_mode"] == "design_storm":
            manifest["warnings"].append("rainfall_is_parameterized_design_storm_not_customer_authoritative_event")
        elif scenario["rainfall_mode"] == "online_public":
            manifest["warnings"].append("rainfall_is_online_open_meteo_public_proxy_not_customer_authoritative_event")
        _update_run(run_id, scenario=scenario, manifest=manifest)
    except ValueError as error:
        manifest.update(
            {
                "status": "failed",
                "finished_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "failure_reason": str(error),
                "summary": {"partition_count": 0, "completed_count": 0, "failed_count": len(scenario["partitions"]), "node_flooding_partition_count": 0},
            }
        )
        _json_write(run_root / "scenario_manifest.json", manifest)
        _update_run(run_id, status="failed", manifest=manifest, completed_partitions=0, current_partition=None)
        return
    for position, partition_id in enumerate(scenario["partitions"], start=1):
        partition_label = _partition_label(partition_id)
        state = {"partition_id": partition_id, "partition_label": partition_label, "status": "running", "position": position, "total": len(scenario["partitions"])}
        with _RUN_LOCK:
            manifest["partitions"].append(state)
        _update_run(run_id, current_partition=partition_id, completed_partitions=position - 1, manifest=manifest)
        source = (
            DEFAULT_FULL_CITY_INPUT
            if partition_id == "full_city"
            else input_root / partition_label / f"abu_dhabi_city_{partition_label}.inp"
        )
        if not source.is_file():
            state.update({"status": "failed", "failure_reason": "partition_input_missing"})
            continue
        partition_dir = run_root / partition_label
        input_path = partition_dir / "scenario.inp"
        try:
            rewrite = render_scenario_input(source, input_path, scenario, rainfall_series=rainfall_series)
            request = TraditionalSolverRunRequest(
                run_id=f"{run_id}-{'city' if partition_id == 'full_city' else f'p{int(partition_id):02d}'}",
                solver_id="epa_swmm",
                executable_path=executable,
                model_input_path=input_path,
                expected_solver_version="5.2.4",
                evidence_class="customer_unverified",
                calibration_status="not_calibrated",
                intended_use="interactive_scenario_diagnostic",
            )
            receipt = execute_swmm(
                request,
                # Interactive prototype runs retain native output even when
                # the assumed parameters fail strict numerical gates. The
                # strict result is calculated below and shown as a warning;
                # it never becomes an engineering admission.
                quality_policy=TraditionalSolverQualityPolicy(
                    maximum_absolute_runoff_continuity_error_percent=10000.0,
                    maximum_absolute_routing_continuity_error_percent=10000.0,
                    maximum_nonconverging_steps_percent=100.0,
                    require_stable_links=False,
                ),
                timeout_seconds=float(os.environ.get("ABU_DHABI_SWMM_TIMEOUT_SECONDS", "2700")),
                retain_output_directory=partition_dir / "native_swmm_results",
            )
            _json_write(partition_dir / "swmm_execution_receipt.json", receipt)
            result_summary = _summary(receipt)
            strict_quality = evaluate_swmm_quality(
                receipt["parsed_report"],
                TraditionalSolverQualityPolicy(require_stable_links=False),
            )
            receipt["strict_quality_gates"] = strict_quality
            _json_write(partition_dir / "swmm_execution_receipt.json", receipt)
            quality_warning = not bool(strict_quality.get("passed"))
            result_summary["strict_numerical_quality_passed"] = bool(strict_quality.get("passed"))
            state.update({"status": "completed_quality_warning" if quality_warning else "completed", "input_rewrite": rewrite, "result_summary": result_summary, "quality_warning": quality_warning, "receipt_path": str(partition_dir / "swmm_execution_receipt.json")})
            if quality_warning:
                manifest["warnings"].append(f"{partition_label}:swmm_report_links_not_all_stable")
        except TraditionalSolverExecutionError as error:
            state.update({"status": "failed", "failure_reason": error.code, "failure_details": error.details})
        except Exception as error:  # keep one bad partition from hiding other results
            state.update({"status": "failed", "failure_reason": type(error).__name__, "failure_details": {"message": str(error)[:500]}})
        _update_run(run_id, current_partition=partition_id, completed_partitions=position, manifest=manifest)
    failures = [item for item in manifest["partitions"] if item.get("status") not in {"completed", "completed_quality_warning"}]
    has_quality_warning = any(item.get("status") == "completed_quality_warning" for item in manifest["partitions"])
    manifest["status"] = "completed_with_warnings" if failures or has_quality_warning else "completed"
    manifest["finished_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    manifest["summary"] = {
        "partition_count": len(manifest["partitions"]),
        "completed_count": len(manifest["partitions"]) - len(failures),
        "failed_count": len(failures),
        "node_flooding_partition_count": sum(bool(item.get("result_summary", {}).get("node_flooding_detected")) for item in manifest["partitions"]),
    }
    _json_write(run_root / "scenario_manifest.json", manifest)
    _update_run(run_id, status=manifest["status"], completed_partitions=len(manifest["partitions"]), current_partition=None, manifest=manifest)


def _update_run(run_id: str, **changes: Any) -> None:
    with _RUN_LOCK:
        current = _RUNS.setdefault(run_id, {"run_id": run_id})
        current.update(changes)


def start_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    scenario = validate_scenario(payload)
    run_id = f"abu-swmm-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    initial = {
        "run_id": run_id,
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "scenario": scenario,
        "total_partitions": len(scenario["partitions"]),
        "completed_partitions": 0,
        "current_partition": None,
    }
    with _RUN_LOCK:
        _RUNS[run_id] = initial
    future: Future[None] = _EXECUTOR.submit(_run_worker, run_id, scenario)
    with _RUN_LOCK:
        _RUNS[run_id]["future"] = future
    return public_run(run_id)


def public_run(run_id: str) -> dict[str, Any]:
    if not isinstance(run_id, str) or not _IDENTIFIER.fullmatch(run_id):
        raise ValueError("run_id_invalid")
    with _RUN_LOCK:
        item = dict(_RUNS.get(run_id, {}))
    if not item:
        candidate = _private_run_root().expanduser().resolve() / run_id / "scenario_manifest.json"
        if candidate.is_file():
            item = json.loads(candidate.read_text(encoding="utf-8"))
        else:
            raise KeyError("run_not_found")
    item.pop("future", None)
    manifest = item.get("manifest")
    if isinstance(manifest, dict):
        item["summary"] = manifest.get("summary")
        item["partitions"] = manifest.get("partitions", [])
        item["warnings"] = manifest.get("warnings", [])
        item["claim_boundary"] = manifest.get("claim_boundary", [])
        if manifest.get("failure_reason"):
            item["failure_reason"] = manifest["failure_reason"]
    return item


def latest_completed_run() -> dict[str, Any]:
    """Return the newest completed private interactive run for page restore."""

    root = _private_run_root().expanduser().resolve()
    candidates: list[tuple[str, Path]] = []
    if root.is_dir():
        for manifest_path in root.glob("*/scenario_manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if manifest.get("status") not in {"completed", "completed_with_warnings"}:
                continue
            candidates.append((str(manifest.get("finished_at") or ""), manifest_path))
    if not candidates:
        raise KeyError("run_not_found")
    _, manifest_path = max(candidates, key=lambda item: item[0])
    return public_run(manifest_path.parent.name)


def latest_zone_b_design_storm_batch() -> dict[str, Any]:
    """Return the latest completed six-return-period batch without private paths."""

    batch_root = _private_run_root().expanduser().resolve() / "batches"
    candidates: list[tuple[str, Path]] = []
    if batch_root.is_dir():
        for manifest_path in batch_root.glob("*/batch_manifest.json"):
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("status") not in {"completed", "completed_with_quality_warnings"}:
                continue
            candidates.append((str(payload.get("finished_at") or ""), manifest_path))
    if not candidates:
        raise KeyError("design_storm_batch_not_found")
    _, manifest_path = max(candidates, key=lambda item: item[0])
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    public_runs = []
    for row in payload.get("runs", []):
        public_runs.append(
            {
                "return_period_years": row.get("return_period_years"),
                "published_180_minute_mean_intensity_mm_per_hour": row.get(
                    "published_180_minute_mean_intensity_mm_per_hour"
                ),
                "published_180_minute_depth_mm": row.get("published_180_minute_depth_mm"),
                "status": row.get("status"),
                "run_id": row.get("run_id"),
                "rainfall_stats": row.get("rainfall_stats"),
                "hydraulic_summary": row.get("hydraulic_summary"),
                "node_summary": row.get("node_summary"),
                "strict_quality_passed": bool((row.get("strict_quality_gates") or {}).get("passed")),
            }
        )

    def non_decreasing(values: list[float]) -> bool:
        return all(right >= left for left, right in zip(values, values[1:]))

    depth_thresholds = (
        "nodes_depth_ge_0_05_m",
        "nodes_depth_ge_0_15_m",
        "nodes_depth_ge_0_30_m",
        "nodes_depth_ge_0_50_m",
        "nodes_depth_ge_1_00_m",
    )
    checks = {
        "return_period_order": [row["return_period_years"] for row in public_runs],
        "published_depth_non_decreasing": non_decreasing(
            [float(row["published_180_minute_depth_mm"]) for row in public_runs]
        ),
        "flooding_loss_non_decreasing": non_decreasing(
            [float((row.get("hydraulic_summary") or {}).get("flooding_loss_million_litres") or 0.0) for row in public_runs]
        ),
        "node_depth_extent_non_decreasing": {
            threshold: non_decreasing(
                [float((row.get("node_summary") or {}).get(threshold) or 0.0) for row in public_runs]
            )
            for threshold in depth_thresholds
        },
        "overflow_node_count_non_decreasing": non_decreasing(
            [float((row.get("node_summary") or {}).get("nodes_with_overflow") or 0.0) for row in public_runs]
        ),
        "external_outflow_non_decreasing": non_decreasing(
            [float((row.get("hydraulic_summary") or {}).get("external_outflow_million_litres") or 0.0) for row in public_runs]
        ),
        "all_strict_quality_gates_passed": all(row["strict_quality_passed"] for row in public_runs),
    }
    checks["engineering_comparison_admitted"] = bool(
        checks["published_depth_non_decreasing"]
        and checks["flooding_loss_non_decreasing"]
        and all(checks["node_depth_extent_non_decreasing"].values())
        and checks["overflow_node_count_non_decreasing"]
        and checks["external_outflow_non_decreasing"]
        and checks["all_strict_quality_gates_passed"]
    )
    return {
        "schema": payload.get("schema"),
        "batch_id": payload.get("batch_id"),
        "status": payload.get("status"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "source": payload.get("source"),
        "fixed_scenario": payload.get("fixed_scenario"),
        "runs": public_runs,
        "comparison_checks": checks,
        "claim_boundary": payload.get("claim_boundary"),
    }


def scenario_map_bootstrap_payload(run_id: str) -> dict[str, Any]:
    """Return the complete-run contract without serializing citywide nodes.

    This payload is only a lightweight control-plane handshake.  Every native
    OUT reporting period is subsequently returned by the time-series endpoint
    with all nodes, including nodes whose result values are zero.
    """

    run = public_run(run_id)
    if run.get("status") not in {"completed", "completed_with_warnings"}:
        raise ValueError("scenario_map_requires_completed_run")
    timeline = _scenario_timeline(run_id, run)
    if not timeline.get("available"):
        raise ValueError("scenario_timeline_unavailable")
    rainfall_stats = dict(run.get("scenario", {}).get("rainfall_stats") or {})
    total_node_count = int(timeline.get("total_node_count") or 0)
    return {
        "type": "FeatureCollection",
        "name": f"abu_dhabi_interactive_swmm_{run_id}_timeline_bootstrap",
        "metadata": {
            "schema": "gwm.abu_dhabi_flood.interactive_swmm_map_bootstrap.v1",
            "run_id": run_id,
            "solver": "EPA SWMM 5.2.4",
            "rainfall_mode": run.get("scenario", {}).get("rainfall_mode"),
            "rainfall_source": rainfall_stats.get("source_label"),
            "rainfall_source_url": rainfall_stats.get("source_url"),
            "rainfall_resampling_method": rainfall_stats.get("resampling_method"),
            "result_boundary": "full_native_swmm_out_timeline_joined_to_customer_node_geometry",
            "claim_boundary": "complete native diagnostic timeline; not calibrated or engineering admitted",
            "node_result_source": "native SWMM OUT reporting periods",
            "node_geometry_source": "private customer node geometry index (EPSG:4326)",
            "node_feature_count": 0,
            "total_node_result_count": total_node_count,
            "map_node_completeness": "all_native_out_nodes_in_every_returned_frame_including_zero_values",
            "map_node_filter": "none",
            "bootstrap_only": True,
            "timeline": timeline,
        },
        "features": [],
        "partition_features": [],
    }


def scenario_map_payload(run_id: str) -> dict[str, Any]:
    """Return completed native SWMM results joined to real node geometry."""
    run = public_run(run_id)
    if run.get("status") not in {"completed", "completed_with_warnings"}:
        raise ValueError("scenario_map_requires_completed_run")
    template = Path(__file__).resolve().parent / "uploads/admin/abu_dhabi_city_swmm_partition_runtime_status.geojson"
    if not template.is_file():
        raise ValueError("scenario_partition_map_template_missing")
    partition_payload = json.loads(template.read_text(encoding="utf-8"))
    by_partition = {row.get("partition_id"): row for row in run.get("partitions", [])}
    partition_features = []
    selected = set(run.get("scenario", {}).get("partitions", []))
    for feature in partition_payload.get("features", []):
        props = dict(feature.get("properties") or {})
        partition_id = props.get("partition_id", -1)
        if selected and partition_id not in selected:
            continue
        row = by_partition.get(partition_id)
        if not row:
            continue
        summary = dict(row.get("result_summary") or {})
        rainfall_stats = dict(run.get("scenario", {}).get("rainfall_stats") or {})
        props.update(
            {
                "runtime_status": row.get("status"),
                "hydraulic_result_status": "本次情景已运行（质量告警）" if row.get("status") == "completed_quality_warning" else "本次情景已运行",
                "scenario_run_id": run_id,
                "scenario_total_depth_mm": run.get("scenario", {}).get("total_depth_mm"),
                "scenario_duration_minutes": run.get("scenario", {}).get("duration_minutes"),
                "scenario_rainfall_pattern": run.get("scenario", {}).get("rainfall_pattern"),
                "scenario_rainfall_mode": run.get("scenario", {}).get("rainfall_mode"),
                "scenario_rainfall_source": rainfall_stats.get("source_label"),
                "scenario_external_outflow_million_litres": summary.get("external_outflow_million_litres"),
                "scenario_flooding_loss_million_litres": summary.get("flooding_loss_million_litres"),
                "scenario_routing_continuity_error_percent": summary.get("routing_continuity_error_percent"),
                "scenario_node_flooding_detected": summary.get("node_flooding_detected"),
                "scenario_quality_warning": row.get("quality_warning", False),
            }
        )
        partition_features.append({"type": "Feature", "geometry": feature.get("geometry"), "properties": props})

    geometry_index = _node_geometry_index()
    timeline = _scenario_timeline(run_id, run)
    node_features: list[dict[str, Any]] = []
    node_counts: dict[str, int] = {}
    total_node_result_count = 0
    affected_node_count = 0
    for partition_id in sorted(selected or by_partition.keys(), key=str):
        row = by_partition.get(partition_id)
        if not row or row.get("status") not in {"completed", "completed_quality_warning"}:
            continue
        partition_dir = _private_run_root().expanduser().resolve() / run_id / _partition_label(partition_id)
        report_paths = sorted((partition_dir / "native_swmm_results").glob("*.rpt"))
        if not report_paths:
            continue
        input_path = partition_dir / "scenario.inp"
        hydraulic_rows = _parse_node_hydraulic_results(report_paths[0])
        if not hydraulic_rows:
            out_paths = sorted((partition_dir / "native_swmm_results").glob("*.out"))
            if out_paths:
                hydraulic_rows = _native_node_hydraulic_results(out_paths[0])
        node_counts[str(partition_id)] = len(hydraulic_rows)
        for node_id, hydraulic in hydraulic_rows.items():
            total_node_result_count += 1
            max_depth = float(hydraulic.get("max_water_depth_m", 0.0) or 0.0)
            max_overflow = float(hydraulic.get("max_overflow_or_flooding_m3s", 0.0) or 0.0)
            if max_depth >= 0.5 or max_overflow > 0.0:
                affected_node_count += 1
            geometry = geometry_index.get(node_id) or _fallback_node_geometry(input_path, node_id)
            if not geometry:
                continue
            properties = {
                "node_id": node_id,
                "partition_id": partition_id,
                "partition_label": "全市连续网络" if partition_id == "full_city" else f"partition_{int(partition_id):02d}",
                "scenario_run_id": run_id,
                "scenario_status": row.get("status"),
                "scenario_max_water_depth_m": max_depth,
                "scenario_max_hydraulic_head_m": hydraulic.get("max_hydraulic_head_m"),
                "scenario_max_overflow_or_flooding_m3s": max_overflow,
                "scenario_flooded_hours": hydraulic.get("flooded_hours", 0.0),
                "scenario_total_flood_volume_million_litres": hydraulic.get("total_flood_volume_million_litres", 0.0),
                "scenario_maximum_ponded_volume_thousand_m3": hydraulic.get("maximum_ponded_volume_thousand_m3", 0.0),
                "scenario_max_depth_time": f"第 {hydraulic.get('max_depth_day', 0)} 天 {hydraulic.get('max_depth_time', '—')}",
                "scenario_node_flooding_detected": bool(
                    float(hydraulic.get("max_overflow_or_flooding_m3s", 0.0) or 0.0) > 0
                    or float(hydraulic.get("flooded_hours", 0.0) or 0.0) > 0
                ),
                "scenario_quality_warning": bool(row.get("quality_warning", False)),
            }
            node_features.append({"type": "Feature", "geometry": geometry, "properties": properties})
    return {
        "type": "FeatureCollection",
        "name": f"abu_dhabi_interactive_swmm_{run_id}_partition_results",
        "metadata": {
            "schema": "gwm.abu_dhabi_flood.interactive_swmm_node_map.v1",
            "run_id": run_id,
            "solver": "EPA SWMM 5.2.4",
            "rainfall_mode": run.get("scenario", {}).get("rainfall_mode"),
            "rainfall_source": (run.get("scenario", {}).get("rainfall_stats") or {}).get("source_label"),
            "rainfall_source_url": (run.get("scenario", {}).get("rainfall_stats") or {}).get("source_url"),
            "rainfall_resampling_method": (run.get("scenario", {}).get("rainfall_stats") or {}).get("resampling_method"),
            "result_boundary": "node_level_maxima_joined_to_customer_node_geometry",
            "claim_boundary": "node maxima are diagnostic only; not calibrated or engineering admitted",
            "node_result_source": "native SWMM RPT summaries or OUT period aggregation",
            "node_geometry_source": "private customer node geometry index (EPSG:4326), with scenario INP coordinate fallback",
            "node_feature_count": len(node_features),
            "total_node_result_count": total_node_result_count,
            "affected_node_count": affected_node_count,
            "map_node_completeness": "all_native_result_nodes_including_zero_values",
            "node_map_filter": "none",
            "affected_node_definition": "max_water_depth_m >= 0.5 OR max_overflow_or_flooding_m3s > 0",
            "node_counts_by_partition": node_counts,
            "partition_result_feature_count": len(partition_features),
            "timeline": timeline,
        },
        "features": node_features,
        "partition_features": partition_features,
    }


def scenario_map_timeseries_payload(run_id: str, time_index: int) -> dict[str, Any]:
    """Return one real native SWMM node-result time slice for the map.

    The service reads only the selected reporting period from each partition's
    retained ``.out`` file.  It does not interpolate between maxima or create
    synthetic spatial positions.
    """

    run = public_run(run_id)
    if run.get("status") not in {"completed", "completed_with_warnings"}:
        raise ValueError("scenario_map_requires_completed_run")
    if isinstance(time_index, bool) or not isinstance(time_index, int):
        raise ValueError("time_index_invalid")
    timeline = _scenario_timeline(run_id, run)
    if not timeline.get("available"):
        raise ValueError("scenario_timeline_unavailable")
    period_count = int(timeline.get("period_count", 0))
    if time_index < 0 or time_index >= period_count:
        raise ValueError("time_index_out_of_range")

    rows, selected = _completed_partition_rows(run)
    geometry_index = _node_geometry_index()
    features: list[dict[str, Any]] = []
    total_node_result_count = 0
    affected_node_count = 0
    missing_geometry_count = 0
    for partition_id in sorted(selected or rows, key=str):
        row = rows.get(partition_id)
        if not row or row.get("status") not in {"completed", "completed_quality_warning"}:
            continue
        out_path = _partition_out_path(run_id, partition_id)
        if not out_path:
            continue
        header = _swmm_out_header(out_path)
        if time_index >= int(header["period_count"]):
            continue
        period = read_node_period(out_path, header, time_index)
        node_names = header["node_names"]
        for node_position, values in enumerate(period["nodes"]):
            if len(values) < 6:
                continue
            total_node_result_count += 1
            depth = max(0.0, float(values[0]))
            overflow = max(0.0, float(values[5]))
            if depth >= 0.05 or overflow > 0.0:
                affected_node_count += 1
            node_id = str(node_names[node_position])
            geometry = geometry_index.get(node_id)
            if not geometry:
                missing_geometry_count += 1
                continue
            properties = {
                "node_id": node_id,
                "partition_id": partition_id,
                "partition_label": "全市连续网络" if partition_id == "full_city" else f"partition_{int(partition_id):02d}",
                "scenario_run_id": run_id,
                "scenario_status": row.get("status"),
                "scenario_rainfall_mode": run.get("scenario", {}).get("rainfall_mode"),
                "scenario_rainfall_source": (run.get("scenario", {}).get("rainfall_stats") or {}).get("source_label"),
                "time_index": time_index,
                "scenario_timestamp": period["timestamp"],
                "scenario_elapsed_minutes": period["elapsed_minutes"],
                "scenario_water_depth_m": depth,
                "scenario_hydraulic_head_m": float(values[1]),
                "scenario_stored_volume_m3": float(values[2]),
                "scenario_lateral_inflow_m3s": float(values[3]),
                "scenario_total_inflow_m3s": float(values[4]),
                "scenario_overflow_or_flooding_m3s": overflow,
                "scenario_node_flooding_detected": bool(overflow > 0.0),
                "scenario_quality_warning": bool(row.get("quality_warning", False)),
            }
            features.append({"type": "Feature", "geometry": geometry, "properties": properties})
    return {
        "type": "FeatureCollection",
        "name": f"abu_dhabi_interactive_swmm_{run_id}_time_{time_index:04d}",
        "metadata": {
            "schema": "gwm.abu_dhabi_flood.interactive_swmm_node_timeseries.v1",
            "run_id": run_id,
            "solver": "EPA SWMM 5.2.4",
            "rainfall_mode": run.get("scenario", {}).get("rainfall_mode"),
            "rainfall_source": (run.get("scenario", {}).get("rainfall_stats") or {}).get("source_label"),
            "rainfall_source_url": (run.get("scenario", {}).get("rainfall_stats") or {}).get("source_url"),
            "rainfall_resampling_method": (run.get("scenario", {}).get("rainfall_stats") or {}).get("resampling_method"),
            "time_index": time_index,
            "timestamp": timeline["time_values"][time_index],
            "elapsed_minutes": timeline["elapsed_minutes"][time_index],
            "timeline": timeline,
            "result_boundary": "node_level_native_swmm_out_period_joined_to_customer_node_geometry",
            "node_result_source": "native SWMM OUT node result period",
            "node_geometry_source": "private customer node geometry index (EPSG:4326)",
            "node_feature_count": len(features),
            "total_node_result_count": total_node_result_count,
            "affected_node_count": affected_node_count,
            "missing_geometry_count": missing_geometry_count,
            "map_node_completeness": "all_native_out_nodes_including_zero_values",
            "node_map_filter": "none",
            "affected_node_definition": "water_depth_m >= 0.05 OR overflow_or_flooding_m3s > 0",
            "claim_boundary": "native diagnostic time slice; not calibrated or engineering admitted",
        },
        "features": features,
    }
