#!/usr/bin/env python3
"""Run two public rainfall products through one registered Makani SWMM subnet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

if __package__:
    from scripts.run_abu_dhabi_flood_public_forcing_comparison import (
        DEFAULT_NASA_HOURLY_FORCING,
        DEFAULT_OPENMETEO_FORCING,
    )
    from scripts.run_abu_dhabi_registered_swmm_diagnostic import (
        DEFAULT_DATASET_ROOT,
        DEFAULT_EXECUTABLE,
        REPOSITORY_ROOT,
    )
    from scripts.run_abu_dhabi_registered_swmm_diagnostic import (
        run as run_registered_swmm,
    )
else:
    from run_abu_dhabi_flood_public_forcing_comparison import (
        DEFAULT_NASA_HOURLY_FORCING,
        DEFAULT_OPENMETEO_FORCING,
    )
    from run_abu_dhabi_registered_swmm_diagnostic import (
        DEFAULT_DATASET_ROOT,
        DEFAULT_EXECUTABLE,
        REPOSITORY_ROOT,
    )
    from run_abu_dhabi_registered_swmm_diagnostic import (
        run as run_registered_swmm,
    )


COMPARISON_SCHEMA = "gwm.abu_dhabi_flood.registered_swmm_forcing_comparison.v1"
DEFAULT_DERIVED_ROOT = (
    DEFAULT_DATASET_ROOT / "derived/makani_registered/swmm_diagnostic"
)
DEFAULT_OPENMETEO_INPUT = DEFAULT_DERIVED_ROOT / "registered_subnetwork_openmeteo.inp"
DEFAULT_NASA_INPUT = DEFAULT_DERIVED_ROOT / "registered_subnetwork_nasa_power.inp"
DEFAULT_OPENMETEO_COMPILE_RECEIPT = (
    DEFAULT_DERIVED_ROOT / "registered_subnetwork_openmeteo_compile_receipt.json"
)
DEFAULT_NASA_COMPILE_RECEIPT = (
    DEFAULT_DERIVED_ROOT / "registered_subnetwork_nasa_power_compile_receipt.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    / "swmm_registered_subnetwork_forcing_comparison_receipt.json"
)


def _sha256_json(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _json_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    ).encode("ascii")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _percent_difference(new: float, reference: float) -> float | None:
    if reference == 0.0:
        return None
    return 100.0 * (new - reference) / reference


def run(
    *,
    dataset_root: Path = DEFAULT_DATASET_ROOT,
    executable_path: Path = DEFAULT_EXECUTABLE,
    openmeteo_forcing_path: Path = DEFAULT_OPENMETEO_FORCING,
    nasa_forcing_path: Path = DEFAULT_NASA_HOURLY_FORCING,
    openmeteo_input_path: Path = DEFAULT_OPENMETEO_INPUT,
    nasa_input_path: Path = DEFAULT_NASA_INPUT,
    openmeteo_compile_receipt_path: Path = DEFAULT_OPENMETEO_COMPILE_RECEIPT,
    nasa_compile_receipt_path: Path = DEFAULT_NASA_COMPILE_RECEIPT,
) -> dict[str, object]:
    open_run = run_registered_swmm(
        dataset_root=dataset_root,
        executable_path=executable_path,
        forcing_path=openmeteo_forcing_path,
        forcing_source="openmeteo",
        input_path=openmeteo_input_path,
        compile_receipt_path=openmeteo_compile_receipt_path,
    )
    nasa_run = run_registered_swmm(
        dataset_root=dataset_root,
        executable_path=executable_path,
        forcing_path=nasa_forcing_path,
        forcing_source="nasa_power_merra2",
        input_path=nasa_input_path,
        compile_receipt_path=nasa_compile_receipt_path,
    )
    open_selection = open_run["compile_receipt"]["selection"]
    nasa_selection = nasa_run["compile_receipt"]["selection"]
    open_result = open_run["result_summary"]
    nasa_result = nasa_run["result_summary"]
    invariant_fields = (
        "root_outfall_node_id",
        "selected_component_id",
        "selected_pipeline_count",
        "selected_node_count",
        "selected_surface_intake_node_count",
        "selected_registered_pipeline_fids",
    )
    invariant_comparison = {
        field: open_selection[field] == nasa_selection[field]
        for field in invariant_fields
    }
    same_network = all(invariant_comparison.values())
    if not same_network:
        raise RuntimeError("registered_swmm_forcing_comparison_network_changed")
    result_fields = (
        "total_precipitation_mm",
        "surface_runoff_mm",
        "wet_weather_inflow_million_litres",
        "external_outflow_million_litres",
        "flooding_loss_million_litres",
        "runoff_continuity_error_percent",
        "routing_continuity_error_percent",
        "steps_not_converging_percent",
        "all_links_stable",
        "node_flooding_detected",
        "numerical_quality_passed",
    )
    metrics = {
        field: {
            "openmeteo": open_result[field],
            "nasa_power_merra2": nasa_result[field],
        }
        for field in result_fields
    }
    metrics["input_forcing_total_precipitation_mm"] = {
        "openmeteo": open_run["compile_receipt"]["forcing"]["total_precipitation_mm"],
        "nasa_power_merra2": nasa_run["compile_receipt"]["forcing"][
            "total_precipitation_mm"
        ],
    }
    metrics["swmm_report_total_precipitation_precision_decimals"] = 3
    metrics["nasa_total_precipitation_difference_from_openmeteo_percent"] = (
        _percent_difference(
            float(nasa_result["total_precipitation_mm"]),
            float(open_result["total_precipitation_mm"]),
        )
    )
    metrics["nasa_surface_runoff_difference_from_openmeteo_percent"] = (
        _percent_difference(
            float(nasa_result["surface_runoff_mm"]),
            float(open_result["surface_runoff_mm"]),
        )
    )
    payload: dict[str, object] = {
        "schema": COMPARISON_SCHEMA,
        "status": "completed_same_registered_subnetwork_public_forcing_sensitivity",
        "event_id": "uae-april-2024-extreme-rainfall",
        "comparison_mode": (
            "same_network_same_parameters_source_native_72_hour_sequence_"
            "not_event_time_aligned"
        ),
        "event_record_boundary": {
            "reported_national_record_period_years": 75,
            "reported_peak_station": "Khatm Al Shakla, Al Ain",
            "reported_peak_station_depth_mm": 254.8,
            "reported_peak_station_depth_used_as_model_forcing": False,
        },
        "network_invariants": {
            "same_registered_subnetwork": same_network,
            "field_checks": invariant_comparison,
            "selected_component_id": open_selection["selected_component_id"],
            "root_outfall_node_id": open_selection["root_outfall_node_id"],
            "selected_pipeline_count": open_selection["selected_pipeline_count"],
            "selected_node_count": open_selection["selected_node_count"],
            "selected_registered_pipeline_fids": open_selection[
                "selected_registered_pipeline_fids"
            ],
            "same_synthetic_catchment_and_hydraulic_assumptions": True,
        },
        "source_runs": {
            "openmeteo": open_run,
            "nasa_power_merra2": nasa_run,
        },
        "comparison_metrics": metrics,
        "source_clock_boundary": {
            "openmeteo_time_standard": open_run["compile_receipt"]["forcing"][
                "time_standard"
            ],
            "nasa_power_merra2_time_standard": nasa_run["compile_receipt"]["forcing"][
                "time_standard"
            ],
            "time_standards_differ": True,
            "hourly_pointwise_difference_admitted": False,
            "direct_source_averaging_admitted": False,
        },
        "execution": {
            "traditional_solver": "EPA SWMM 5.2.4",
            "traditional_solver_runs": 2,
            "registered_candidate_network_consumed": True,
            "public_proxy_forcings_consumed": 2,
            "customer_event_observation_consumed": False,
            "gwm_training_invoked": False,
        },
        "admission": {
            "calibration_admitted": False,
            "gwm_training_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "comparison_quantifies_public_forcing_sensitivity_on_one_real_asset_candidate_subnet",
            "registered_topology_and_hydraulic_units_remain_customer_unverified",
            "catchments_roughness_node_depth_and_free_outfall_are_diagnostic_assumptions",
            "zero_node_flooding_does_not_establish_real_drainage_capacity",
            "not_a_calibrated_event_reconstruction_or_city_scale_prediction",
        ],
    }
    payload["receipt_sha256"] = _sha256_json(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_DATASET_ROOT)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--openmeteo-forcing", type=Path, default=DEFAULT_OPENMETEO_FORCING)
    parser.add_argument("--nasa-forcing", type=Path, default=DEFAULT_NASA_HOURLY_FORCING)
    parser.add_argument("--openmeteo-input", type=Path, default=DEFAULT_OPENMETEO_INPUT)
    parser.add_argument("--nasa-input", type=Path, default=DEFAULT_NASA_INPUT)
    parser.add_argument(
        "--openmeteo-compile-receipt",
        type=Path,
        default=DEFAULT_OPENMETEO_COMPILE_RECEIPT,
    )
    parser.add_argument(
        "--nasa-compile-receipt",
        type=Path,
        default=DEFAULT_NASA_COMPILE_RECEIPT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    os.chdir(REPOSITORY_ROOT)
    payload = run(
        dataset_root=args.dataset_root,
        executable_path=args.executable,
        openmeteo_forcing_path=args.openmeteo_forcing,
        nasa_forcing_path=args.nasa_forcing,
        openmeteo_input_path=args.openmeteo_input,
        nasa_input_path=args.nasa_input,
        openmeteo_compile_receipt_path=args.openmeteo_compile_receipt,
        nasa_compile_receipt_path=args.nasa_compile_receipt,
    )
    output = args.output if args.output.is_absolute() else REPOSITORY_ROOT / args.output
    _atomic_write(output, _json_bytes(payload))
    print(json.dumps({"output": str(output), "receipt_sha256": payload["receipt_sha256"]}))


if __name__ == "__main__":
    main()
