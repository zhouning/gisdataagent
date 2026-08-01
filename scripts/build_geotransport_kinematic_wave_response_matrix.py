#!/usr/bin/env python3
"""Build an outcome-free response matrix for the finite-volume kinematic wave."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    FiniteVolumeKinematicWaveOperator,
    KinematicWaveConfig,
    analyze_dynamic_transfer_response,
)

if __package__:
    from scripts import build_geotransport_troute_mc_baseline as baseline
else:
    import build_geotransport_troute_mc_baseline as baseline


REPO_ROOT = baseline.REPO_ROOT
DEFAULT_ROUTE_LINK_MANIFEST = baseline.DEFAULT_ROUTE_LINK_MANIFEST
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/"
    "kinematic_wave_response_matrix_report.json"
)
SCHEMA = "gwm.geotransport.kinematic_wave_response_matrix.v1"
BACKGROUND_FLOWS_M3S = (2.0, 20.0, 100.0)
PULSE_RATES_M3S = (0.1, 1.0, 10.0)
TIMESTEPS_SECONDS = (300.0, 900.0, 3600.0)
TARGET_CELL_LENGTHS_M = (2000.0, 1000.0, 500.0)
PRIMARY_TARGET_CELL_LENGTH_M = 1000.0
FINE_TARGET_CELL_LENGTH_M = 500.0
WARMUP_HOURS = 240
ROLLOUT_HOURS = 240
PULSE_DURATION_SECONDS = 3600.0
STABILITY_ABSOLUTE_TOLERANCE_SECONDS = 3600.0
STABILITY_RELATIVE_TOLERANCE = 0.10
QUANTILES = ("t05", "t50", "t95")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route-link-manifest", type=Path, default=DEFAULT_ROUTE_LINK_MANIFEST
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_diagnostic(
    *, route_link_manifest_path: Path = DEFAULT_ROUTE_LINK_MANIFEST
) -> dict[str, Any]:
    route_body = route_link_manifest_path.read_bytes()
    route_manifest = json.loads(route_body)
    route_descriptor = _route_descriptor(route_manifest)
    route_path, route_bytes = baseline._read_verified(route_descriptor)
    by_feature = baseline._route_link_rows(route_path)
    rows = [by_feature[feature_id] for feature_id in baseline.FEATURE_PATH]
    for upstream, downstream in zip(rows[:-1], rows[1:], strict=True):
        if int(upstream["to"]) != int(downstream["link"]):
            raise ValueError("kinematic_wave_response_matrix_topology_mismatch")

    cases_by_key: dict[tuple[float, float, float], dict[str, Any]] = {}
    for timestep in TIMESTEPS_SECONDS:
        for background in BACKGROUND_FLOWS_M3S:
            for pulse in PULSE_RATES_M3S:
                cases_by_key[(background, pulse, timestep)] = {
                    "case_id": (
                        f"q{background:g}_pulse{pulse:g}_dt{timestep:g}"
                    ),
                    "background_flow_m3s": background,
                    "pulse_rate_m3s": pulse,
                    "pulse_input_volume_m3": pulse * PULSE_DURATION_SECONDS,
                    "timestep_seconds": timestep,
                    "rollout_hours": ROLLOUT_HOURS,
                    "resolutions": [],
                }

    warmups: list[dict[str, Any]] = []
    for target_cell_length in TARGET_CELL_LENGTHS_M:
        for timestep in TIMESTEPS_SECONDS:
            for background in BACKGROUND_FLOWS_M3S:
                context, warmup = _warm_operator(
                    rows,
                    target_cell_length_m=target_cell_length,
                    timestep_seconds=timestep,
                    background_flow_m3s=background,
                )
                warmups.append(warmup)
                for pulse in PULSE_RATES_M3S:
                    result = _run_response_case(
                        context,
                        target_cell_length_m=target_cell_length,
                        timestep_seconds=timestep,
                        background_flow_m3s=background,
                        pulse_rate_m3s=pulse,
                    )
                    cases_by_key[(background, pulse, timestep)][
                        "resolutions"
                    ].append(result)

    cases = list(cases_by_key.values())
    temporal_stability = _compile_temporal_stability(cases)
    spatial_stability = _compile_spatial_stability(cases)
    resolution_results = [
        resolution
        for case in cases
        for resolution in case["resolutions"]
    ]
    all_mass_steps = all(
        item["maximum_step_mass_residual_to_tolerance_ratio"] <= 1.0
        for item in [*warmups, *resolution_results]
    )
    all_cfl_steps = all(
        item["maximum_courant_number"]
        <= item["configured_cfl_number"] + 1e-12
        for item in [*warmups, *resolution_results]
    )
    all_states_valid = all(
        item["states_nonnegative_finite"]
        for item in [*warmups, *resolution_results]
    )
    all_response_mass = all(
        item["dynamic_transfer_response"]["mass_balance_passed"]
        for item in resolution_results
    )
    all_negative_lobes = all(
        item["dynamic_transfer_response"][
            "negative_lobe_within_tolerance"
        ]
        for item in resolution_results
    )
    all_diagnostic_only = all(
        item["diagnostic_only"] and not item["operator_form_admitted"]
        for item in [*warmups, *resolution_results]
    )
    gates = {
        "all_step_mass_identities_passed": all_mass_steps,
        "all_response_mass_identities_passed": all_response_mass,
        "all_states_nonnegative_finite": all_states_valid,
        "all_negative_lobes_within_tolerance": all_negative_lobes,
        "all_cfl_limits_respected": all_cfl_steps,
        "primary_resolution_timestep_stability": temporal_stability[
            "all_comparisons_passed"
        ],
        "primary_to_fine_spatial_stability": spatial_stability[
            "primary_to_fine"
        ]["all_comparisons_passed"],
        "spatial_refinement_error_nonincreasing": spatial_stability[
            "refinement_trend"
        ]["all_comparisons_passed"],
        "outcome_isolation": True,
        "operator_remains_diagnostic_only": all_diagnostic_only,
    }
    gates["all_registered_diagnostic_gates_passed"] = all(gates.values())
    return {
        "schema": SCHEMA,
        "status": "outcome_free_finite_volume_diagnostic_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "route_link_manifest": _artifact(route_link_manifest_path, route_body),
            "route_link_fixture": _artifact(route_path, route_bytes),
        },
        "fixture": {
            "source_id": baseline.SOURCE_ID,
            "feature_ids": list(baseline.FEATURE_PATH),
            "feature_count": len(rows),
            "full_reaches_only": True,
            "topology_consecutive": True,
            "geometry_semantics": {
                "bottom_width_m": "RouteLink/BtmWdth",
                "side_slope_horizontal_per_vertical": "1/RouteLink/ChSlp",
                "bed_slope": "RouteLink/So",
                "manning_n": "RouteLink/n",
            },
        },
        "registered_protocol": {
            "background_flows_m3s": list(BACKGROUND_FLOWS_M3S),
            "pulse_rates_m3s": list(PULSE_RATES_M3S),
            "pulse_duration_seconds": PULSE_DURATION_SECONDS,
            "timesteps_seconds": list(TIMESTEPS_SECONDS),
            "target_cell_lengths_m": list(TARGET_CELL_LENGTHS_M),
            "primary_target_cell_length_m": PRIMARY_TARGET_CELL_LENGTH_M,
            "fine_target_cell_length_m": FINE_TARGET_CELL_LENGTH_M,
            "warmup_hours": WARMUP_HOURS,
            "rollout_hours": ROLLOUT_HOURS,
            "case_count": len(cases),
            "resolution_run_count": len(resolution_results),
            "response_quantiles": list(QUANTILES),
            "stability_absolute_tolerance_seconds": (
                STABILITY_ABSOLUTE_TOLERANCE_SECONDS
            ),
            "stability_relative_tolerance": STABILITY_RELATIVE_TOLERANCE,
            "initialization": (
                "zero-volume state followed by 240-hour constant-boundary warmup; "
                "base and pulse branches fork from the identical warmed state"
            ),
            "pulse_discretization": (
                "interval-mean rate from trapezoidal endpoint samples, preserving "
                "the registered pulse volume at every external timestep"
            ),
        },
        "operator_contract": {
            "equation": "dA/dt + dQ(A)/dx = q_lateral",
            "state_quantity": "cell_water_volume_m3",
            "flux": "downstream_upwind_manning_discharge",
            "time_integration": "explicit_euler_with_adaptive_cfl_substeps",
            "configured_cfl_number": 0.8,
            "path_admitted": True,
            "geometry_admitted": True,
            "operator_form_admitted": False,
            "diagnostic_only": True,
        },
        "warmup_states": warmups,
        "cases": cases,
        "temporal_timestep_stability": temporal_stability,
        "spatial_subdivision_stability": spatial_stability,
        "gates": gates,
        "data_isolation": {
            "observed_discharge_loaded": False,
            "observed_action_loaded": False,
            "observed_forcing_loaded": False,
            "target_fitted_parameters": 0,
            "inputs": [
                "public_route_link_parameters",
                "synthetic_constant_background_flow",
                "synthetic_boundary_pulse",
            ],
        },
        "scientific_limitations": {
            "kinematic_assumption_backwater_excluded": True,
            "compound_channel_geometry_excluded": True,
            "lateral_inflow_matrix_exercised": False,
            "real_world_transfer_validated": False,
            "independent_outlet_outcomes_used": False,
            "spatial_convergence_is_reference_refinement_not_exact_solution": True,
        },
        "claim_boundary": {
            "finite_volume_equation_implemented": True,
            "outcome_free_response_matrix_executed": True,
            "physical_volume_conservation_tested": True,
            "operator_form_admitted": False,
            "professional_transfer_operator_certified": False,
            "hydrodynamically_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _warm_operator(
    rows: list[dict[str, float | int]],
    *,
    target_cell_length_m: float,
    timestep_seconds: float,
    background_flow_m3s: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path, geometry = baseline._nonlinear_contracts(rows, reverse=False)
    operator = FiniteVolumeKinematicWaveOperator(
        path,
        geometry,
        KinematicWaveConfig(
            timestep_seconds=timestep_seconds,
            target_cell_length_m=target_cell_length_m,
            cfl_number=0.8,
            path_admitted=True,
            operator_form_admitted=False,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    )
    state = operator.zero_state(
        provenance_id="kinematic-wave-response:warmup:zero"
    )
    maximum_mass_ratio = 0.0
    maximum_courant = 0.0
    total_substeps = 0
    result = None
    steps = int(WARMUP_HOURS * 3600.0 / timestep_seconds)
    for step in range(steps):
        result = operator.step(
            state,
            boundary_inflow_m3s=background_flow_m3s,
            provenance_id=f"kinematic-wave-response:warmup:{step + 1}",
        )
        state = result.next_state
        maximum_mass_ratio = max(
            maximum_mass_ratio,
            abs(result.global_mass_balance_residual_m3)
            / result.numeric_mass_tolerance_m3,
        )
        maximum_courant = max(
            maximum_courant, result.maximum_courant_number
        )
        total_substeps += result.integration_substep_count
    if result is None:
        raise RuntimeError("kinematic_wave_response_matrix_empty_warmup")
    volume = np.asarray(state.cell_volume_m3, dtype=float)
    report = {
        "target_cell_length_m": target_cell_length_m,
        "actual_cell_count": operator.cell_count,
        "reach_cell_counts": list(operator.reach_cell_counts),
        "timestep_seconds": timestep_seconds,
        "background_flow_m3s": background_flow_m3s,
        "warmup_step_count": steps,
        "integration_substep_count": total_substeps,
        "outlet_mean_flow_m3s": result.outlet_mean_flow_m3s,
        "outlet_relative_steady_error": abs(
            result.outlet_mean_flow_m3s - background_flow_m3s
        )
        / background_flow_m3s,
        "maximum_step_mass_residual_to_tolerance_ratio": maximum_mass_ratio,
        "maximum_courant_number": maximum_courant,
        "configured_cfl_number": result.cfl_number,
        "states_nonnegative_finite": bool(
            np.isfinite(volume).all() and (volume >= 0.0).all()
        ),
        "path_admitted": result.path_admitted,
        "geometry_admitted": result.geometry_admitted,
        "operator_form_admitted": result.operator_form_admitted,
        "diagnostic_only": result.diagnostic_only,
    }
    return {"operator": operator, "state": state}, report


def _run_response_case(
    context: Mapping[str, Any],
    *,
    target_cell_length_m: float,
    timestep_seconds: float,
    background_flow_m3s: float,
    pulse_rate_m3s: float,
) -> dict[str, Any]:
    operator = context["operator"]
    base_state = context["state"]
    pulse_state = context["state"]
    response: list[float] = []
    input_volume = 0.0
    maximum_mass_ratio = 0.0
    maximum_courant = 0.0
    maximum_substeps = 0
    total_substeps = 0
    steps = int(ROLLOUT_HOURS * 3600.0 / timestep_seconds)
    last_result = None
    for step in range(steps):
        previous_seconds = step * timestep_seconds
        current_seconds = (step + 1) * timestep_seconds
        mean_pulse = 0.5 * (
            _pulse_component(previous_seconds, pulse_rate_m3s)
            + _pulse_component(current_seconds, pulse_rate_m3s)
        )
        input_volume += mean_pulse * timestep_seconds
        base_result = operator.step(
            base_state,
            boundary_inflow_m3s=background_flow_m3s,
            provenance_id=f"kinematic-wave-response:base:{step + 1}",
        )
        pulse_result = operator.step(
            pulse_state,
            boundary_inflow_m3s=background_flow_m3s + mean_pulse,
            provenance_id=f"kinematic-wave-response:pulse:{step + 1}",
        )
        response.append(
            pulse_result.outlet_mean_flow_m3s
            - base_result.outlet_mean_flow_m3s
        )
        for result in (base_result, pulse_result):
            maximum_mass_ratio = max(
                maximum_mass_ratio,
                abs(result.global_mass_balance_residual_m3)
                / result.numeric_mass_tolerance_m3,
            )
            maximum_courant = max(
                maximum_courant, result.maximum_courant_number
            )
            maximum_substeps = max(
                maximum_substeps, result.integration_substep_count
            )
            total_substeps += result.integration_substep_count
        base_state = base_result.next_state
        pulse_state = pulse_result.next_state
        last_result = pulse_result
    expected_input = pulse_rate_m3s * PULSE_DURATION_SECONDS
    if not np.isclose(input_volume, expected_input, rtol=0.0, atol=1e-9):
        raise RuntimeError("kinematic_wave_response_matrix_pulse_volume_invalid")
    if last_result is None:
        raise RuntimeError("kinematic_wave_response_matrix_empty_rollout")
    base_volume = np.asarray(base_state.cell_volume_m3, dtype=float)
    pulse_volume = np.asarray(pulse_state.cell_volume_m3, dtype=float)
    metrics = analyze_dynamic_transfer_response(
        response,
        timestep_seconds=timestep_seconds,
        input_volume_m3=input_volume,
        final_incremental_storage_m3=float(pulse_volume.sum() - base_volume.sum()),
    )
    return {
        "target_cell_length_m": target_cell_length_m,
        "actual_cell_count": operator.cell_count,
        "reach_cell_counts": list(operator.reach_cell_counts),
        "dynamic_transfer_response": metrics.as_dict(),
        "maximum_step_mass_residual_to_tolerance_ratio": maximum_mass_ratio,
        "maximum_courant_number": maximum_courant,
        "configured_cfl_number": last_result.cfl_number,
        "maximum_integration_substeps_per_external_step": maximum_substeps,
        "integration_substep_count": total_substeps,
        "states_nonnegative_finite": bool(
            np.isfinite(base_volume).all()
            and np.isfinite(pulse_volume).all()
            and (base_volume >= 0.0).all()
            and (pulse_volume >= 0.0).all()
        ),
        "path_admitted": last_result.path_admitted,
        "geometry_admitted": last_result.geometry_admitted,
        "operator_form_admitted": last_result.operator_form_admitted,
        "diagnostic_only": last_result.diagnostic_only,
    }


def _compile_temporal_stability(cases: list[dict[str, Any]]) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    for background in BACKGROUND_FLOWS_M3S:
        for pulse in PULSE_RATES_M3S:
            group = {
                float(case["timestep_seconds"]): _metrics(
                    case, PRIMARY_TARGET_CELL_LENGTH_M
                )
                for case in cases
                if case["background_flow_m3s"] == background
                and case["pulse_rate_m3s"] == pulse
            }
            reference = group[TIMESTEPS_SECONDS[0]][
                "input_recovery_quantile_seconds"
            ]
            for timestep in TIMESTEPS_SECONDS[1:]:
                candidate = group[timestep]["input_recovery_quantile_seconds"]
                for quantile in QUANTILES:
                    comparisons.append(
                        _stability_comparison(
                            reference[quantile],
                            candidate[quantile],
                            {
                                "background_flow_m3s": background,
                                "pulse_rate_m3s": pulse,
                                "target_cell_length_m": (
                                    PRIMARY_TARGET_CELL_LENGTH_M
                                ),
                                "reference_timestep_seconds": (
                                    TIMESTEPS_SECONDS[0]
                                ),
                                "candidate_timestep_seconds": timestep,
                                "quantile": quantile,
                            },
                        )
                    )
    return {
        "comparison_count": len(comparisons),
        "comparisons": comparisons,
        "all_comparisons_passed": all(item["passed"] for item in comparisons),
    }


def _compile_spatial_stability(cases: list[dict[str, Any]]) -> dict[str, Any]:
    primary_comparisons: list[dict[str, Any]] = []
    trend_comparisons: list[dict[str, Any]] = []
    for case in cases:
        values = {
            target: _metrics(case, target)["input_recovery_quantile_seconds"]
            for target in TARGET_CELL_LENGTHS_M
        }
        for quantile in QUANTILES:
            metadata = {
                "case_id": case["case_id"],
                "background_flow_m3s": case["background_flow_m3s"],
                "pulse_rate_m3s": case["pulse_rate_m3s"],
                "timestep_seconds": case["timestep_seconds"],
                "quantile": quantile,
            }
            primary_comparisons.append(
                _stability_comparison(
                    values[FINE_TARGET_CELL_LENGTH_M][quantile],
                    values[PRIMARY_TARGET_CELL_LENGTH_M][quantile],
                    {
                        **metadata,
                        "reference_target_cell_length_m": (
                            FINE_TARGET_CELL_LENGTH_M
                        ),
                        "candidate_target_cell_length_m": (
                            PRIMARY_TARGET_CELL_LENGTH_M
                        ),
                    },
                )
            )
            coarse = values[TARGET_CELL_LENGTHS_M[0]][quantile]
            primary = values[PRIMARY_TARGET_CELL_LENGTH_M][quantile]
            fine = values[FINE_TARGET_CELL_LENGTH_M][quantile]
            coarse_error = (
                None if coarse is None or fine is None else abs(coarse - fine)
            )
            primary_error = (
                None if primary is None or fine is None else abs(primary - fine)
            )
            trend_comparisons.append(
                {
                    **metadata,
                    "coarse_target_cell_length_m": TARGET_CELL_LENGTHS_M[0],
                    "primary_target_cell_length_m": (
                        PRIMARY_TARGET_CELL_LENGTH_M
                    ),
                    "fine_target_cell_length_m": FINE_TARGET_CELL_LENGTH_M,
                    "coarse_to_fine_absolute_error_seconds": coarse_error,
                    "primary_to_fine_absolute_error_seconds": primary_error,
                    "passed": (
                        coarse_error is not None
                        and primary_error is not None
                        and primary_error <= coarse_error + 1e-9
                    ),
                }
            )
    return {
        "primary_to_fine": {
            "comparison_count": len(primary_comparisons),
            "comparisons": primary_comparisons,
            "all_comparisons_passed": all(
                item["passed"] for item in primary_comparisons
            ),
        },
        "refinement_trend": {
            "comparison_count": len(trend_comparisons),
            "comparisons": trend_comparisons,
            "all_comparisons_passed": all(
                item["passed"] for item in trend_comparisons
            ),
        },
    }


def _metrics(case: Mapping[str, Any], target: float) -> Mapping[str, Any]:
    for resolution in case["resolutions"]:
        if float(resolution["target_cell_length_m"]) == target:
            return resolution["dynamic_transfer_response"]
    raise ValueError("kinematic_wave_response_matrix_resolution_missing")


def _stability_comparison(
    reference: float | None,
    candidate: float | None,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    tolerance = (
        None
        if reference is None
        else max(
            STABILITY_ABSOLUTE_TOLERANCE_SECONDS,
            STABILITY_RELATIVE_TOLERANCE * reference,
        )
    )
    difference = (
        None
        if reference is None or candidate is None
        else abs(candidate - reference)
    )
    return {
        **metadata,
        "reference_seconds": reference,
        "candidate_seconds": candidate,
        "absolute_difference_seconds": difference,
        "tolerance_seconds": tolerance,
        "passed": (
            difference is not None
            and tolerance is not None
            and difference <= tolerance
        ),
    }


def _pulse_component(seconds: float, pulse_rate_m3s: float) -> float:
    return (
        pulse_rate_m3s
        if 0.0 < seconds <= PULSE_DURATION_SECONDS
        else 0.0
    )


def _route_descriptor(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    if (
        manifest.get("schema") != baseline.ROUTE_LINK_SCHEMA
        or manifest.get("mode") != "values"
    ):
        raise ValueError("kinematic_wave_response_matrix_route_manifest_invalid")
    for audit in manifest.get("netcdf_audits") or []:
        if audit.get("source_id") == baseline.SOURCE_ID:
            if audit.get("admitted_as_public_invariant_fixture") is not True:
                raise ValueError("kinematic_wave_response_matrix_fixture_not_admitted")
            return audit["artifact"]
    raise ValueError("kinematic_wave_response_matrix_fixture_missing")


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.report.exists():
        raise ValueError("kinematic_wave_response_matrix_refuses_overwrite")
    report = compile_diagnostic(route_link_manifest_path=args.route_link_manifest)
    body = _json_body(report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(body)
    print(args.report)
    print(hashlib.sha256(body).hexdigest())
    print(f"case_count={len(report['cases'])}")
    print(
        "all_registered_diagnostic_gates_passed="
        f"{report['gates']['all_registered_diagnostic_gates_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
