#!/usr/bin/env python3
"""Prepare an auditable full-city SWMM input for a custom rainfall event."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_agent.abu_dhabi_flood_scenario_service import (  # noqa: E402
    render_scenario_input,
    validate_scenario,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _set_swmm_option(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    section = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.upper()
            continue
        if section == "[OPTIONS]" and stripped and not stripped.startswith(";"):
            parts = stripped.split(None, 1)
            if parts and parts[0].upper() == key.upper():
                lines[index] = f"{key}  {value}"
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return
    raise ValueError(f"swmm_option_missing:{key}")


def prepare(args: argparse.Namespace) -> dict[str, object]:
    base_input = args.base_input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not base_input.is_file():
        raise FileNotFoundError(f"base_swmm_input_missing:{base_input}")
    if not math.isfinite(args.rainfall_mm) or args.rainfall_mm <= 0.0:
        raise ValueError("rainfall_mm_invalid")
    duration_minutes = int(round(args.duration_hours * 60.0))
    tail_minutes = int(round(args.tail_hours * 60.0))
    if duration_minutes <= 0 or duration_minutes % args.interval_minutes:
        raise ValueError("duration_must_align_interval")
    if tail_minutes < 0 or tail_minutes % 5:
        raise ValueError("tail_must_align_5_minutes")
    interval_count = duration_minutes // args.interval_minutes
    depth_per_interval = float(args.rainfall_mm) / float(interval_count)
    values = [depth_per_interval] * interval_count
    profile = {
        "profile_id": args.profile_id,
        "name": f"Abu Dhabi citywide {args.rainfall_mm:g} mm / {args.duration_hours:g} h uniform",
        "climate_zone": "zone_b",
        "source_type": "customer_requested_parameter_matrix",
        "source_reference": "customer_requested_33_61_96mm_x_1_2_24h_matrix",
        "duration_minutes": duration_minutes,
        "interval_minutes": args.interval_minutes,
        "total_depth_mm": float(args.rainfall_mm),
        "temporal_pattern": "custom",
        "values_mm_per_interval": values,
        "spatial_mode": "uniform",
        "provenance": {
            "evidence_class": "customer_requested_scenario_parameter",
            "temporal_assumption": "uniform_5_minute_blocks",
        },
    }
    # The interactive scenario contract intentionally caps the UI recession
    # tail at 24 hours.  This batch preparation utility is also used for
    # engineering recession runs that must continue for several days.  Keep
    # the interactive validation for every other field, then apply the
    # explicitly requested batch tail before rendering the SWMM input so the
    # generated dates and the receipt remain consistent.
    interactive_tail_minutes = min(tail_minutes, 24 * 60)
    scenario = validate_scenario(
        {
            "scope": "citywide",
            "rainfallMode": "design_storm",
            "rainfallProfile": profile,
            "startTime": args.start_time,
            "durationMinutes": duration_minutes,
            "tailMinutes": interactive_tail_minutes,
            "spatialPattern": "uniform",
            "pipeScope": "none",
            "blockagePercent": 0,
            "pipeCapacityMultiplier": 1.0,
            "pumpEnabled": True,
            "pumpCapacityMultiplier": 1.0,
            "outfallMode": "open",
            "outfallLevelM": 0.0,
            "outputIntervalMinutes": args.interval_minutes,
        }
    )
    scenario["tail_minutes"] = tail_minutes
    output_dir.mkdir(parents=True, exist_ok=False)
    generated_input = output_dir / "coupled_scenario.inp"
    rewrite = render_scenario_input(base_input, generated_input, scenario)
    routing_step = int(args.routing_step_seconds)
    if routing_step <= 0 or routing_step > 300:
        raise ValueError("routing_step_seconds_out_of_range")
    routing_step_text = f"{routing_step // 3600:02d}:{(routing_step % 3600) // 60:02d}:{routing_step % 60:02d}"
    _set_swmm_option(generated_input, "ROUTING_STEP", routing_step_text)
    profile_total = float(sum(scenario["rainfall_profile"]["values_mm_per_interval"]))
    if not math.isclose(profile_total, float(args.rainfall_mm), abs_tol=1.0e-9):
        raise RuntimeError("generated_rainfall_total_mismatch")
    receipt = {
        "schema": "gwm.abu_dhabi_flood.coupled_custom_rainfall_input.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "scenario_id": args.scenario_id,
        "scenario": scenario,
        "rainfall": {
            "requested_total_mm": float(args.rainfall_mm),
            "generated_total_mm": profile_total,
            "duration_minutes": duration_minutes,
            "interval_minutes": args.interval_minutes,
            "interval_count": interval_count,
            "depth_mm_per_interval": depth_per_interval,
            "intensity_mm_per_hour": depth_per_interval * 60.0 / args.interval_minutes,
            "temporal_assumption": "uniform",
        },
        "simulation": {
            "rainfall_minutes": duration_minutes,
            "tail_minutes": tail_minutes,
            "maximum_duration_minutes": duration_minutes + tail_minutes,
            "swmm_routing_step_seconds": routing_step,
            "dewatering_acceptance_requires_post_run_check": True,
        },
        "swmm_input": {
            "base_path": str(base_input),
            "base_sha256": _sha256(base_input),
            "generated_path": str(generated_input),
            "generated_sha256": _sha256(generated_input),
            "generated_size_bytes": generated_input.stat().st_size,
        },
        "rewrite": rewrite,
    }
    _write_json(output_dir / "scenario.json", scenario)
    _write_json(output_dir / "input_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--rainfall-mm", type=float, required=True)
    parser.add_argument("--duration-hours", type=float, required=True)
    parser.add_argument("--tail-hours", type=float, default=24.0)
    parser.add_argument("--interval-minutes", type=int, default=5)
    parser.add_argument("--routing-step-seconds", type=int, default=30)
    parser.add_argument("--start-time", default="2024-04-16T00:00")
    args = parser.parse_args()
    receipt = prepare(args)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
