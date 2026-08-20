#!/usr/bin/env python3
"""Compile and run a registered-Makani SWMM diagnostic subnetwork."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import TraditionalSolverRunRequest, execute_swmm
from data_agent.uwm.abu_dhabi_flood.registered_swmm_diagnostic import (
    compile_registered_swmm_diagnostic,
    verify_registered_swmm_compile_receipt,
)

if __package__:
    from scripts.run_abu_dhabi_flood_public_forcing_comparison import (
        DEFAULT_NASA_HOURLY_FORCING,
        load_nasa_power_hourly,
    )
    from scripts.run_abu_dhabi_flood_public_proxy_candidate import (
        DEFAULT_FORCING,
        load_openmeteo_hourly,
    )
else:
    from run_abu_dhabi_flood_public_forcing_comparison import (
        DEFAULT_NASA_HOURLY_FORCING,
        load_nasa_power_hourly,
    )
    from run_abu_dhabi_flood_public_proxy_candidate import (
        DEFAULT_FORCING,
        load_openmeteo_hourly,
    )

RECEIPT_SCHEMA = "gwm.abu_dhabi_flood.registered_swmm_diagnostic_receipt.v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_ROOT = REPOSITORY_ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"
DEFAULT_EXECUTABLE = REPOSITORY_ROOT / "external_models/swmm-5.2.4/build-local/bin/runswmm"
DEFAULT_INPUT = (
    DEFAULT_DATASET_ROOT
    / "derived/makani_registered/swmm_diagnostic/registered_subnetwork_openmeteo.inp"
)
DEFAULT_COMPILE_RECEIPT = (
    DEFAULT_DATASET_ROOT
    / "derived/makani_registered/swmm_diagnostic/registered_subnetwork_compile_receipt.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    / "swmm_registered_subnetwork_execution_receipt.json"
)
FORCING_SOURCES = ("openmeteo", "nasa_power_merra2")


def _sha256_json(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _json_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("ascii")


def _forcing_input(source_id: str, forcing_path: Path) -> tuple[dict[str, object], dict]:
    if source_id == "openmeteo":
        forcing = load_openmeteo_hourly(forcing_path)
        descriptor: dict[str, object] = {
            "source_id": source_id,
            "source": "Open-Meteo Historical API archive point product",
            "model_label": "Open-Meteo",
            "source_file": str(forcing_path.relative_to(REPOSITORY_ROOT)),
            "file_sha256": forcing["file_sha256"],
            "time_standard": forcing["payload"]["timezone"],
            "source_unit": "mm_per_hour_interval_depth",
            "conversion_to_interval_depth": "identity",
            "hourly_interval_count": len(forcing["precipitation_mm"]),
            "total_precipitation_mm": round(forcing["total_precipitation_mm"], 8),
            "maximum_hourly_precipitation_mm": round(
                forcing["maximum_hourly_precipitation_mm"], 8
            ),
            "evidence_class": "public_proxy",
            "calibration_admission": "not_admitted_for_calibration",
        }
        return descriptor, forcing
    if source_id == "nasa_power_merra2":
        forcing = load_nasa_power_hourly(forcing_path)
        descriptor = {
            "source_id": source_id,
            "source": "NASA POWER Hourly API MERRA2 point product",
            "model_label": "NASA POWER/MERRA2",
            "source_file": str(forcing_path.relative_to(REPOSITORY_ROOT)),
            "file_sha256": forcing["file_sha256"],
            "time_standard": forcing["time_standard"],
            "source_unit": "mm/day",
            "source_unit_semantics": "hourly_rate_expressed_as_mm_per_day",
            "conversion_to_interval_depth": "interval_depth_mm=source_rate/24",
            "raw_rate_sum_not_a_depth": forcing["raw_rate_sum_not_a_depth"],
            "direct_raw_sum_forcing_forbidden": True,
            "hourly_interval_count": len(forcing["precipitation_mm"]),
            "total_precipitation_mm": round(forcing["total_precipitation_mm"], 8),
            "maximum_hourly_precipitation_mm": round(
                forcing["maximum_hourly_precipitation_mm"], 8
            ),
            "evidence_class": "public_proxy",
            "calibration_admission": "not_admitted_for_calibration",
        }
        return descriptor, forcing
    raise ValueError(f"registered_swmm_forcing_source_unsupported:{source_id}")


def run(
    *,
    dataset_root: Path = DEFAULT_DATASET_ROOT,
    forcing_path: Path | None = None,
    executable_path: Path = DEFAULT_EXECUTABLE,
    input_path: Path = DEFAULT_INPUT,
    compile_receipt_path: Path = DEFAULT_COMPILE_RECEIPT,
    forcing_source: str = "openmeteo",
) -> dict[str, object]:
    dataset_root = dataset_root.resolve()
    if forcing_path is None:
        forcing_path = (
            DEFAULT_FORCING
            if forcing_source == "openmeteo"
            else DEFAULT_NASA_HOURLY_FORCING
        )
    forcing_path = forcing_path.resolve()
    executable_path = executable_path.resolve()
    input_path = input_path.resolve()
    compile_receipt_path = compile_receipt_path.resolve()
    forcing_descriptor, forcing = _forcing_input(forcing_source, forcing_path)
    try:
        input_label = str(input_path.relative_to(REPOSITORY_ROOT))
    except ValueError:
        input_label = f"diagnostic-output:{input_path.name}"
    input_text, compile_receipt = compile_registered_swmm_diagnostic(
        dataset_root,
        hourly_precipitation_mm=tuple(forcing["precipitation_mm"]),
        forcing_descriptor=forcing_descriptor,
        input_path_label=input_label,
    )
    verify_registered_swmm_compile_receipt(compile_receipt)
    _atomic_write(input_path, input_text.encode("ascii"))
    if (
        hashlib.sha256(input_path.read_bytes()).hexdigest()
        != compile_receipt["model_input"]["sha256"]
    ):
        raise RuntimeError("registered_swmm_written_input_sha256_mismatch")
    _atomic_write(compile_receipt_path, _json_bytes(compile_receipt))

    request = TraditionalSolverRunRequest(
        run_id=f"abu-dhabi-swmm-registered-subnetwork-{forcing_source}-diagnostic",
        solver_id="epa_swmm",
        executable_path=executable_path,
        model_input_path=input_path,
        expected_solver_version="5.2.4",
        evidence_class="customer_unverified",
        calibration_status="not_calibrated",
        intended_use=("registered_asset_subnetwork_runtime_diagnostic_with_public_proxy_rainfall"),
    )
    solver_receipt = execute_swmm(request, timeout_seconds=120.0)
    parsed = solver_receipt["parsed_report"]
    payload: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "status": "completed_registered_asset_subnetwork_swmm_diagnostic_not_calibrated",
        "compile_receipt": compile_receipt,
        "solver_receipt": solver_receipt,
        "result_summary": {
            "solver": parsed["solver"],
            "element_counts": parsed["element_counts"],
            "analysis_options": parsed["analysis_options"],
            "total_precipitation_mm": parsed["runoff_quantity_continuity"]["total_precipitation"][
                "second"
            ],
            "surface_runoff_mm": parsed["runoff_quantity_continuity"]["surface_runoff"]["second"],
            "wet_weather_inflow_million_litres": parsed["flow_routing_continuity"][
                "wet_weather_inflow"
            ]["second"],
            "external_outflow_million_litres": parsed["flow_routing_continuity"][
                "external_outflow"
            ]["second"],
            "flooding_loss_million_litres": parsed["flow_routing_continuity"]["flooding_loss"][
                "second"
            ],
            "runoff_continuity_error_percent": parsed["runoff_quantity_continuity"][
                "continuity_error_percent"
            ],
            "routing_continuity_error_percent": parsed["flow_routing_continuity"][
                "continuity_error_percent"
            ],
            "steps_not_converging_percent": parsed["convergence"]["steps_not_converging_percent"],
            "all_links_stable": parsed["stability"]["all_links_stable"],
            "node_flooding_detected": parsed["node_flooding"]["detected"],
            "numerical_quality_passed": solver_receipt["quality_gates"]["passed"],
        },
        "execution_boundary": {
            "registered_candidate_pipeline_rows_consumed": compile_receipt["selection"][
                "selected_pipeline_count"
            ],
            "registered_candidate_node_rows_consumed": compile_receipt["selection"][
                "selected_node_count"
            ],
            "public_proxy_rainfall_consumed": True,
            "live_database_connection_executed": False,
            "credentials_consumed_or_recorded": False,
            "traditional_solver_invoked": True,
            "gwm_training_invoked": False,
            "synthetic_catchment_parameters_used": True,
            "forcing_source_id": forcing_source,
        },
        "admission": {
            "k0_status": "closed_not_admitted",
            "traditional_model_admitted": False,
            "calibration_admitted": False,
            "gwm_training_admitted": False,
            "hybrid_planner_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "first_swmm_run_using_registered_makani_candidate_asset_geometry_and_attributes",
            "network_selection_and_flow_direction_are_diagnostic_candidates",
            "diameter_unit_vertical_datum_roughness_node_depth_and_catchments_are_unverified",
            f"{forcing_source}_is_public_proxy_rainfall_not_customer_event_observation",
            "al_ain_reported_254_8_mm_station_depth_was_not_used_as_forcing",
            "numerical_quality_pass_does_not_establish_engineering_calibration",
            "not_a_city_scale_prediction_or_operational_action_recommendation",
        ],
    }
    payload["receipt_sha256"] = _sha256_json(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--forcing", type=Path)
    parser.add_argument("--forcing-source", choices=FORCING_SOURCES, default="openmeteo")
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--compile-receipt", type=Path, default=DEFAULT_COMPILE_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    os.chdir(REPOSITORY_ROOT)
    payload = run(
        dataset_root=args.dataset_root,
        forcing_path=args.forcing,
        executable_path=args.executable,
        input_path=args.input,
        compile_receipt_path=args.compile_receipt,
        forcing_source=args.forcing_source,
    )
    output = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output
    _atomic_write(output, _json_bytes(payload))
    print(json.dumps({"output": str(output), "receipt_sha256": payload["receipt_sha256"]}))


if __name__ == "__main__":
    main()
