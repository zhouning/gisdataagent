#!/usr/bin/env python3
"""Compile and execute a private customer-GDB SWMM diagnostic subnetwork."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import TraditionalSolverRunRequest, execute_swmm
from data_agent.uwm.abu_dhabi_flood.customer_gdb_network import (
    CustomerGdbSwmmBatchPolicy,
    compile_customer_gdb_swmm_diagnostic,
    compile_customer_gdb_swmm_diagnostic_batch,
)
from data_agent.uwm.abu_dhabi_flood.smartmakani_acquisition import canonical_json_bytes

if __package__:
    from scripts.run_abu_dhabi_flood_public_proxy_candidate import (
        DEFAULT_FORCING,
        load_openmeteo_hourly,
    )
else:
    from run_abu_dhabi_flood_public_proxy_candidate import (
        DEFAULT_FORCING,
        load_openmeteo_hourly,
    )

RECEIPT_SCHEMA = "gwm.abu_dhabi_flood.customer_gdb_swmm_execution.v1"
BATCH_RECEIPT_SCHEMA = "gwm.abu_dhabi_flood.customer_gdb_swmm_batch_execution.v1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXECUTABLE = REPOSITORY_ROOT / "external_models/swmm-5.2.4/build-local/bin/runswmm"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(payload))
    temporary.replace(path)


def _forcing_descriptor(forcing: dict[str, object]) -> dict[str, object]:
    return {
        "source_id": "openmeteo",
        "model_label": "Open-Meteo",
        "time_standard": forcing["payload"]["timezone"],
        "source_unit": "mm_per_hour_interval_depth",
        "hourly_interval_count": len(forcing["precipitation_mm"]),
        "total_precipitation_mm": round(float(forcing["total_precipitation_mm"]), 8),
        "maximum_hourly_precipitation_mm": round(
            float(forcing["maximum_hourly_precipitation_mm"]), 8
        ),
        "file_sha256": forcing["file_sha256"],
        "evidence_class": "public_proxy_not_customer_event_observation",
        "calibration_admission": "not_admitted_for_calibration",
    }


def _solver_result_summary(solver_receipt: dict[str, object]) -> dict[str, object]:
    parsed = solver_receipt["parsed_report"]
    return {
        "solver": parsed["solver"],
        "element_counts": parsed["element_counts"],
        "analysis_options": parsed["analysis_options"],
        "total_precipitation_mm": parsed["runoff_quantity_continuity"][
            "total_precipitation"
        ]["second"],
        "surface_runoff_mm": parsed["runoff_quantity_continuity"]["surface_runoff"][
            "second"
        ],
        "wet_weather_inflow_million_litres": parsed["flow_routing_continuity"][
            "wet_weather_inflow"
        ]["second"],
        "external_outflow_million_litres": parsed["flow_routing_continuity"][
            "external_outflow"
        ]["second"],
        "flooding_loss_million_litres": parsed["flow_routing_continuity"][
            "flooding_loss"
        ]["second"],
        "runoff_continuity_error_percent": parsed["runoff_quantity_continuity"][
            "continuity_error_percent"
        ],
        "routing_continuity_error_percent": parsed["flow_routing_continuity"][
            "continuity_error_percent"
        ],
        "steps_not_converging_percent": parsed["convergence"][
            "steps_not_converging_percent"
        ],
        "all_links_stable": parsed["stability"]["all_links_stable"],
        "node_flooding_detected": parsed["node_flooding"]["detected"],
        "numerical_quality_passed": solver_receipt["quality_gates"]["passed"],
    }


def run(
    *,
    private_root: Path,
    forcing_path: Path = DEFAULT_FORCING,
    executable_path: Path = DEFAULT_EXECUTABLE,
    retain_output_directory: Path | None = None,
) -> dict[str, object]:
    root = private_root.expanduser().resolve()
    forcing = load_openmeteo_hourly(forcing_path.expanduser().resolve())
    forcing_descriptor = _forcing_descriptor(forcing)
    compile_receipt = compile_customer_gdb_swmm_diagnostic(
        root,
        hourly_precipitation_mm=tuple(forcing["precipitation_mm"]),
        forcing_descriptor=forcing_descriptor,
    )
    input_path = root / str(compile_receipt["model_input"]["path"])
    request = TraditionalSolverRunRequest(
        run_id="abu-dhabi-customer-gdb-subnetwork-diagnostic",
        solver_id="epa_swmm",
        executable_path=executable_path.expanduser().resolve(),
        model_input_path=input_path,
        expected_solver_version="5.2.4",
        evidence_class="customer_unverified",
        calibration_status="not_calibrated",
        intended_use="customer_gdb_network_compilation_and_numerical_runtime_diagnostic",
    )
    solver_receipt = execute_swmm(
        request,
        timeout_seconds=120.0,
        retain_output_directory=retain_output_directory,
    )
    run_contract = solver_receipt["run_contract"]
    execution = solver_receipt["execution"]
    payload: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "status": "completed_customer_gdb_subnetwork_diagnostic_not_calibrated",
        "compile_receipt": compile_receipt,
        "solver_execution": {
            "schema": solver_receipt["schema"],
            "status": solver_receipt["status"],
            "solver_id": run_contract["solver_id"],
            "expected_solver_version": run_contract["expected_solver_version"],
            "runtime_sha256": run_contract["runtime_artifact"]["sha256"],
            "model_input_sha256": run_contract["model_input_artifact"]["sha256"],
            "input_governance": run_contract["input_governance"],
            "quality_policy": run_contract["quality_policy"],
            "quality_gates": solver_receipt["quality_gates"],
            "execution": {
                "elapsed_seconds": execution["elapsed_seconds"],
                "returncode": execution["returncode"],
                "isolated_temporary_working_directory": execution[
                    "isolated_temporary_working_directory"
                ],
                "temporary_working_directory_retained": execution[
                    "temporary_working_directory_retained"
                ],
                "input_copy_hash_verified": execution["input_copy_hash_verified"],
                "executable_copied_and_hash_verified": execution[
                    "executable_copied_and_hash_verified"
                ],
                "shell_used": execution["shell_used"],
                "timeout_seconds": execution["timeout_seconds"],
                "output_hashes": {
                    name: artifact["sha256"]
                    for name, artifact in execution["output_artifacts"].items()
                },
                "absolute_paths_persisted": False,
                **(
                    {
                        "retained_output_artifacts": execution[
                            "retained_output_artifacts"
                        ],
                        "retained_output_directory_provided": True,
                    }
                    if execution.get("retained_output_artifacts")
                    else {"retained_output_directory_provided": False}
                ),
            },
        },
        "result_summary": _solver_result_summary(solver_receipt),
        "execution_boundary": {
            "customer_derived_private_artifacts_consumed": True,
            "source_customer_gdb_reopened_during_solver_execution": False,
            "source_customer_asset_identifiers_persisted": False,
            "public_proxy_rainfall_consumed": True,
            "traditional_solver_invoked": True,
            "gwm_training_invoked": False,
            "synthetic_catchment_parameters_used": True,
        },
        "admission": {
            "network_cleanup_and_prototype_allowed": True,
            "traditional_model_admitted": False,
            "calibration_admitted": False,
            "gwm_training_admitted": False,
            "hybrid_planner_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "first_swmm_run_from_customer_provided_gdb_geometry",
            "topology_and_processed_elevations_remain_engineering_unverified",
            "rainfall_is_public_proxy_not_customer_gauge_or_radar_qpe",
            "catchments_roughness_node_depth_and_diameter_unit_are_assumptions",
            "numerical_quality_pass_does_not_establish_calibration",
            "not_a_2024_event_reconstruction_or_city_scale_prediction",
        ],
    }
    output = root / "customer_stormwater_subnetwork_execution_receipt.json"
    _write_json(output, payload)
    return payload


def run_batch(
    *,
    private_root: Path,
    forcing_path: Path = DEFAULT_FORCING,
    executable_path: Path = DEFAULT_EXECUTABLE,
    maximum_pilots: int = 5,
    maximum_edge_overlap_fraction: float = 0.75,
    retain_output_directory: Path | None = None,
) -> dict[str, object]:
    """Compile and execute several diverse private SWMM pilot subnetworks."""

    root = private_root.expanduser().resolve()
    forcing = load_openmeteo_hourly(forcing_path.expanduser().resolve())
    descriptor = _forcing_descriptor(forcing)
    compile_receipt = compile_customer_gdb_swmm_diagnostic_batch(
        root,
        hourly_precipitation_mm=tuple(forcing["precipitation_mm"]),
        forcing_descriptor=descriptor,
        batch_policy=CustomerGdbSwmmBatchPolicy(
            maximum_pilots=maximum_pilots,
            maximum_candidate_attempts=max(maximum_pilots * 8, maximum_pilots),
            maximum_edge_overlap_fraction=maximum_edge_overlap_fraction,
        ),
    )
    pilot_results = []
    for pilot in compile_receipt["pilots"]:
        pilot_id = str(pilot["pilot_id"])
        input_path = root / str(pilot["model_input"]["path"])
        request = TraditionalSolverRunRequest(
            run_id=f"abu-dhabi-customer-gdb-{pilot_id}-diagnostic",
            solver_id="epa_swmm",
            executable_path=executable_path.expanduser().resolve(),
            model_input_path=input_path,
            expected_solver_version="5.2.4",
            evidence_class="customer_unverified",
            calibration_status="not_calibrated",
            intended_use="customer_gdb_multi_outfall_numerical_runtime_diagnostic",
        )
        pilot_retention_directory = (
            retain_output_directory / pilot_id
            if retain_output_directory is not None
            else None
        )
        solver_receipt = execute_swmm(
            request,
            timeout_seconds=120.0,
            retain_output_directory=pilot_retention_directory,
        )
        run_contract = solver_receipt["run_contract"]
        execution = solver_receipt["execution"]
        pilot_results.append(
            {
                "pilot_id": pilot_id,
                "selection": pilot["selection"],
                "model_input_sha256": run_contract["model_input_artifact"]["sha256"],
                "runtime_sha256": run_contract["runtime_artifact"]["sha256"],
                "quality_gates": solver_receipt["quality_gates"],
                "execution": {
                    "elapsed_seconds": execution["elapsed_seconds"],
                    "returncode": execution["returncode"],
                    "isolated_temporary_working_directory": execution[
                        "isolated_temporary_working_directory"
                    ],
                    "temporary_working_directory_retained": execution[
                        "temporary_working_directory_retained"
                    ],
                    "input_copy_hash_verified": execution["input_copy_hash_verified"],
                    "executable_copied_and_hash_verified": execution[
                        "executable_copied_and_hash_verified"
                    ],
                    "shell_used": execution["shell_used"],
                    "absolute_paths_persisted": False,
                    **(
                        {
                            "retained_output_artifacts": execution[
                                "retained_output_artifacts"
                            ],
                            "retained_output_directory_provided": True,
                        }
                        if execution.get("retained_output_artifacts")
                        else {"retained_output_directory_provided": False}
                    ),
                },
                "result_summary": _solver_result_summary(solver_receipt),
            }
        )
    passed_count = sum(
        bool(pilot["result_summary"]["numerical_quality_passed"])
        for pilot in pilot_results
    )
    payload: dict[str, object] = {
        "schema": BATCH_RECEIPT_SCHEMA,
        "status": "completed_customer_gdb_multi_outfall_diagnostics_not_calibrated",
        "compile_receipt": compile_receipt,
        "result_summary": {
            "executed_pilot_count": len(pilot_results),
            "numerical_quality_passed_count": passed_count,
            "all_pilots_numerical_quality_passed": passed_count == len(pilot_results),
            "all_pilots_links_stable": all(
                bool(pilot["result_summary"]["all_links_stable"])
                for pilot in pilot_results
            ),
            "pilot_with_node_flooding_count": sum(
                bool(pilot["result_summary"]["node_flooding_detected"])
                for pilot in pilot_results
            ),
        },
        "pilots": pilot_results,
        "execution_boundary": {
            "customer_derived_private_artifacts_consumed": True,
            "source_customer_gdb_reopened_during_solver_execution": False,
            "source_customer_asset_identifiers_persisted": False,
            "public_proxy_rainfall_consumed": True,
            "traditional_solver_invoked": True,
            "gwm_training_invoked": False,
            "synthetic_catchment_parameters_used": True,
        },
        "admission": {
            "network_cleanup_and_prototype_allowed": True,
            "traditional_model_admitted": False,
            "calibration_admitted": False,
            "gwm_training_admitted": False,
            "hybrid_planner_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "multi_outfall_numerical_diagnostics_from_customer_provided_gdb_geometry",
            "topology_and_processed_elevations_remain_engineering_unverified",
            "rainfall_is_public_proxy_not_customer_gauge_or_radar_qpe",
            "catchments_roughness_node_depth_and_diameter_unit_are_assumptions",
            "numerical_quality_pass_does_not_establish_calibration",
            "not_a_2024_event_reconstruction_or_city_scale_prediction",
        ],
    }
    output = root / "customer_stormwater_subnetwork_batch_execution_receipt.json"
    _write_json(output, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--forcing", type=Path, default=DEFAULT_FORCING)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--pilot-count", type=int, default=1)
    parser.add_argument("--maximum-edge-overlap-fraction", type=float, default=0.75)
    parser.add_argument(
        "--retain-output-dir",
        type=Path,
        default=None,
        help="Opt-in private archive directory for native SWMM .rpt/.out files",
    )
    args = parser.parse_args()
    if args.pilot_count == 1:
        payload = run(
            private_root=args.private_root,
            forcing_path=args.forcing,
            executable_path=args.executable,
            retain_output_directory=args.retain_output_dir,
        )
    else:
        payload = run_batch(
            private_root=args.private_root,
            forcing_path=args.forcing,
            executable_path=args.executable,
            maximum_pilots=args.pilot_count,
            maximum_edge_overlap_fraction=args.maximum_edge_overlap_fraction,
            retain_output_directory=args.retain_output_dir,
        )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "selection": payload["compile_receipt"].get("selection"),
                "result_summary": payload["result_summary"],
                "admission": payload["admission"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
