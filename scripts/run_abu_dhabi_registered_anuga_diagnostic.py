#!/usr/bin/env python3
"""Run the local ANUGA surface diagnostic linked to the registered SWMM subnet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import (
    AnugaQualityPolicy,
    RegisteredAnugaDiagnosticPolicy,
    TraditionalSolverRunRequest,
    build_anuga_maximum_depth_layer,
    compile_registered_anuga_diagnostic,
    execute_anuga,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = REPOSITORY_ROOT / "benchmarks/abu_dhabi_stormwater_data_v1"
DERIVED_ROOT = DATASET_ROOT / "derived/makani_registered"
SWMM_ROOT = DERIVED_ROOT / "swmm_diagnostic"
ANUGA_ROOT = DERIVED_ROOT / "anuga_diagnostic"
TECHNICAL_VALIDATION_ROOT = (
    REPOSITORY_ROOT
    / "docs/customer/abu_dhabi_liveability_site_validation/technical_validation"
)

DEFAULT_SWMM_INPUT = SWMM_ROOT / "registered_subnetwork_openmeteo.inp"
DEFAULT_SWMM_COMPILE_RECEIPT = (
    SWMM_ROOT / "registered_subnetwork_openmeteo_compile_receipt.json"
)
DEFAULT_SWMM_EXECUTION_RECEIPT = (
    TECHNICAL_VALIDATION_ROOT / "swmm_registered_subnetwork_execution_receipt.json"
)
DEFAULT_FORCING = (
    DATASET_ROOT / "online/weather/openmeteo_archive_abu_dhabi_20240415_20240417.json"
)
DEFAULT_PRIMARY_DEM = DATASET_ROOT / "online/terrain/abu_dhabi_copernicus_30m_epsg32640.tif"
DEFAULT_COMPARISON_DEM = DATASET_ROOT / "online/terrain/abu_dhabi_srtm_30m_epsg32640.tif"
DEFAULT_CONTOUR_ROOT = (
    DATASET_ROOT
    / "derived/smartmakani/surface_clip_candidate/contour_2017_zone40/pages"
)
DEFAULT_CONTOUR_MANIFEST = DEFAULT_CONTOUR_ROOT.parent / "manifest.json"
DEFAULT_MODEL_INPUT = ANUGA_ROOT / "registered_surface_openmeteo.py"
DEFAULT_COMPILE_RECEIPT = ANUGA_ROOT / "registered_surface_openmeteo_compile_receipt.json"
DEFAULT_RETAINED_SWW = ANUGA_ROOT / "registered_surface_openmeteo.sww"
DEFAULT_MAXIMUM_DEPTH_LAYER = ANUGA_ROOT / "registered_surface_openmeteo_maximum_depth.parquet"
DEFAULT_OUTPUT = (
    TECHNICAL_VALIDATION_ROOT / "anuga_registered_surface_execution_receipt.json"
)
DEFAULT_PYTHON = REPOSITORY_ROOT / "external_models/anuga-venv/bin/python"
DEFAULT_SOURCE = REPOSITORY_ROOT / "external_models/anuga-core"

ANUGA_COMMIT = "9a7ef669872540a215bbb58972d12262a0209668"
ANUGA_DIFF_SHA256 = "7a8572541f42082f2261017d2b42ed60ea02d90ddcbd162df87c700a8f153aed"
ANUGA_STATUS_SHA256 = "7e63b3d53a4f17d0dc49ea99fea2ef1e2b422a2e595d3b46fab13812294fa614"
ANUGA_VERSION = "0.0.0+g9a7ef66.dirty"
EXECUTION_SCHEMA = "gwm.abu_dhabi_flood.registered_anuga_surface_execution.v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _atomic_write_geoparquet(path: Path, frame: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("registered_anuga_json_object_required")
    return payload


def _repository_path_label(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    try:
        return absolute.relative_to(REPOSITORY_ROOT)
    except ValueError:
        return path


def run(
    *,
    swmm_input_path: Path = DEFAULT_SWMM_INPUT,
    swmm_compile_receipt_path: Path = DEFAULT_SWMM_COMPILE_RECEIPT,
    swmm_execution_receipt_path: Path = DEFAULT_SWMM_EXECUTION_RECEIPT,
    forcing_path: Path = DEFAULT_FORCING,
    primary_dem_path: Path = DEFAULT_PRIMARY_DEM,
    comparison_dem_path: Path = DEFAULT_COMPARISON_DEM,
    contour_pages_root: Path = DEFAULT_CONTOUR_ROOT,
    contour_manifest_path: Path = DEFAULT_CONTOUR_MANIFEST,
    model_input_path: Path = DEFAULT_MODEL_INPUT,
    compile_receipt_path: Path = DEFAULT_COMPILE_RECEIPT,
    retained_sww_path: Path = DEFAULT_RETAINED_SWW,
    maximum_depth_layer_path: Path = DEFAULT_MAXIMUM_DEPTH_LAYER,
    python_path: Path = DEFAULT_PYTHON,
    source_root: Path = DEFAULT_SOURCE,
) -> dict[str, object]:
    policy = RegisteredAnugaDiagnosticPolicy()
    model_label = str(model_input_path.relative_to(REPOSITORY_ROOT))
    model_script, compile_receipt = compile_registered_anuga_diagnostic(
        swmm_input_path=swmm_input_path,
        swmm_compile_receipt_path=swmm_compile_receipt_path,
        forcing_path=forcing_path,
        primary_dem_path=primary_dem_path,
        comparison_dem_path=comparison_dem_path,
        contour_pages_root=contour_pages_root,
        contour_manifest_path=contour_manifest_path,
        model_input_path_label=model_label,
        policy=policy,
    )
    _atomic_write(model_input_path, model_script.encode("ascii"))
    _atomic_write(compile_receipt_path, _json_bytes(compile_receipt))

    surface = compile_receipt["surface_domain"]
    request = TraditionalSolverRunRequest(
        run_id="abu-dhabi-registered-subnetwork-local-surface-openmeteo",
        solver_id="anuga_2d",
        executable_path=_repository_path_label(python_path),
        model_input_path=_repository_path_label(model_input_path),
        expected_solver_version=ANUGA_VERSION,
        evidence_class="public_proxy",
        calibration_status="not_calibrated",
    )
    solver_receipt = execute_anuga(
        request,
        source_root=_repository_path_label(source_root),
        expected_source_commit=ANUGA_COMMIT,
        expected_source_diff_sha256=ANUGA_DIFF_SHA256,
        expected_source_status_sha256=ANUGA_STATUS_SHA256,
        output_filename="registered_surface_openmeteo.sww",
        quality_policy=AnugaQualityPolicy(
            expected_cell_count=int(surface["expected_triangle_count"]),
            expected_step_count=int(surface["expected_output_step_count"]),
            expected_start_seconds=0.0,
            expected_end_seconds=float(surface["duration_seconds"]),
            maximum_absolute_mass_balance_residual_m3=1.0e-3,
            maximum_absolute_relative_mass_balance_error_percent=1.0e-5,
            maximum_output_domain_volume_difference_m3=1.0e-3,
        ),
        timeout_seconds=300.0,
        retained_sww_path=_repository_path_label(retained_sww_path),
    )
    maximum_depth_layer, maximum_depth_layer_summary = build_anuga_maximum_depth_layer(
        retained_sww_path
    )
    _atomic_write_geoparquet(maximum_depth_layer_path, maximum_depth_layer)

    swmm_execution = _load_json(swmm_execution_receipt_path)
    swmm_result = swmm_execution["result_summary"]
    flooding_volume_m3 = float(swmm_result["flooding_loss_million_litres"]) * 1000.0
    if flooding_volume_m3 != 0.0 or swmm_result["node_flooding_detected"] is not False:
        raise RuntimeError("registered_anuga_nonzero_swmm_overflow_requires_explicit_operator")
    inspection = solver_receipt["inspection"]
    state = inspection["state"]
    mass = inspection["mass_balance"]
    payload: dict[str, object] = {
        "schema": EXECUTION_SCHEMA,
        "status": "completed_registered_local_surface_with_zero_swmm_overflow_exchange",
        "event_id": "uae-april-2024-extreme-rainfall",
        "compile_receipt": compile_receipt,
        "solver_receipt": solver_receipt,
        "spatial_output": {
            "retained_sww": solver_receipt["execution"]["retained_sww_artifact"],
            "maximum_depth_layer": {
                "path": str(_repository_path_label(maximum_depth_layer_path)),
                "sha256": _sha256_file(maximum_depth_layer_path),
                "size_bytes": maximum_depth_layer_path.stat().st_size,
                "format": "GeoParquet",
                "crs": "EPSG:32640",
                **maximum_depth_layer_summary,
            },
        },
        "result_summary": {
            "solver": "ANUGA 2D",
            "solver_version": solver_receipt["run_contract"]["expected_solver_version"],
            "domain_area_m2": surface["area_m2"],
            "triangle_count": inspection["mesh"]["cell_count"],
            "simulation_duration_hours": float(surface["duration_seconds"]) / 3600.0,
            "input_rainfall_depth_mm": compile_receipt["forcing"]["total_depth_mm"],
            "maximum_depth_m": state["maximum_depth_m"],
            "maximum_depth_time_hours": state["maximum_depth_time_seconds"] / 3600.0,
            "maximum_depth_cell_centroid_epsg32640": state[
                "maximum_depth_cell_centroid"
            ],
            "inundation_area_by_depth_threshold": state[
                "inundation_area_by_depth_threshold"
            ],
            "maximum_surface_water_volume_m3": mass["maximum_output_volume_m3"],
            "maximum_surface_water_volume_time_hours": (
                mass["maximum_output_volume_time_seconds"] / 3600.0
            ),
            "final_surface_water_volume_m3": mass["final_output_volume_m3"],
            "boundary_flux_integral_m3": mass["boundary_flux_integral_m3"],
            "rainfall_operator_volume_integral_m3": mass[
                "fractional_step_volume_integral_m3"
            ],
            "mass_balance_residual_m3": mass["absolute_residual_m3"],
            "numerical_quality_passed": solver_receipt["quality_gates"]["passed"],
        },
        "one_way_swmm_to_anuga_exchange": {
            "mode": "swmm_node_overflow_volume_applied_to_surface_domain",
            "source_swmm_execution_receipt_path": str(
                _repository_path_label(swmm_execution_receipt_path)
            ),
            "source_swmm_execution_receipt_sha256": _sha256_file(
                swmm_execution_receipt_path
            ),
            "source_swmm_event_window_hours": 72,
            "anuga_peak_subwindow_is_contained_in_source_window": True,
            "swmm_node_flooding_detected": False,
            "swmm_reported_flooding_volume_m3": flooding_volume_m3,
            "applied_swmm_to_anuga_volume_m3": 0.0,
            "nonzero_exchange_operator_created": False,
            "zero_transfer_reason": "source_swmm_run_reported_no_node_flooding",
            "dynamic_anuga_to_swmm_return_flow_simulated": False,
        },
        "architecture_progress": {
            "registered_candidate_1d_network_executed": True,
            "registered_candidate_location_2d_surface_executed": True,
            "shared_public_event_forcing_used": True,
            "one_way_1d_overflow_exchange_evaluated": True,
            "nonzero_1d_overflow_exchange_observed": False,
            "dynamic_two_way_coupling_executed": False,
            "gwm_training_invoked": False,
        },
        "admission": {
            "traditional_model_admitted": False,
            "calibration_admitted": False,
            "gwm_training_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
        "claim_boundary": [
            "this_is_a_real_anuga_execution_at_the_registered_candidate_subnetwork_location",
            "zero_swmm_overflow_means_the_one_way_exchange_term_is_zero_in_this_run",
            "surface_rainfall_is_not_reduced_by_infiltration_or_drain_inlet_abstraction",
            "depth_and_area_results_are_diagnostic_sensitivity_outputs_not_observed_flood_reconstruction",
            "retained_sww_and_maximum_depth_geoparquet_are_diagnostic_spatial_outputs",
            "customer_engineering_dem_rainfall_drainage_and_inundation_observations_remain_required",
        ],
    }
    payload["receipt_sha256"] = _sha256_json(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    os.chdir(REPOSITORY_ROOT)
    payload = run()
    _atomic_write(args.output, _json_bytes(payload))
    print(
        json.dumps(
            {
                "output": str(args.output),
                "receipt_sha256": payload["receipt_sha256"],
                "result_summary": payload["result_summary"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
