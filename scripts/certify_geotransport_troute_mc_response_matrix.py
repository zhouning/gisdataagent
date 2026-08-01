#!/usr/bin/env python3
"""Certify t-route MC transfer responses across state, pulse, and timestep."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    CtypesTrouteMuskingumCungeKernel,
    NonlinearManningReachTransportOperator,
    NonlinearReachTransportConfig,
    TrouteMuskingumCungeAdapter,
    analyze_dynamic_transfer_response,
)

if __package__:
    from scripts import build_geotransport_troute_mc_baseline as baseline
else:
    import build_geotransport_troute_mc_baseline as baseline


REPO_ROOT = baseline.REPO_ROOT
DEFAULT_ROUTE_LINK_MANIFEST = baseline.DEFAULT_ROUTE_LINK_MANIFEST
DEFAULT_SOURCE_MANIFEST = baseline.DEFAULT_SOURCE_MANIFEST
DEFAULT_BUILD_MANIFEST = baseline.DEFAULT_BUILD_MANIFEST
DEFAULT_BASELINE_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/t_route_mc_professional_baseline_v2_report.json"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/t_route_mc_response_matrix_report.json"
)
SCHEMA = "gwm.geotransport.t_route_mc_response_matrix.v1"
BASELINE_SCHEMA = "gwm.geotransport.t_route_mc_professional_baseline.v2"
BACKGROUND_FLOWS_M3S = (2.0, 20.0, 100.0)
PULSE_RATES_M3S = (0.1, 1.0, 10.0)
TIMESTEPS_SECONDS = (300.0, 900.0, 3600.0)
WARMUP_HOURS = 240
ROLLOUT_HOURS = 240
PULSE_DURATION_SECONDS = 3600.0
STABILITY_ABSOLUTE_TOLERANCE_SECONDS = 3600.0
STABILITY_RELATIVE_TOLERANCE = 0.10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route-link-manifest", type=Path, default=DEFAULT_ROUTE_LINK_MANIFEST
    )
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--build-manifest", type=Path, default=DEFAULT_BUILD_MANIFEST)
    parser.add_argument("--baseline-report", type=Path, default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_certification(
    *,
    route_link_manifest_path: Path = DEFAULT_ROUTE_LINK_MANIFEST,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    build_manifest_path: Path = DEFAULT_BUILD_MANIFEST,
    baseline_report_path: Path = DEFAULT_BASELINE_REPORT,
) -> dict[str, Any]:
    route_body = route_link_manifest_path.read_bytes()
    source_body = source_manifest_path.read_bytes()
    build_body = build_manifest_path.read_bytes()
    prior_body = baseline_report_path.read_bytes()
    route_manifest = json.loads(route_body)
    source_manifest = json.loads(source_body)
    build_manifest = json.loads(build_body)
    prior = json.loads(prior_body)
    if prior.get("schema") != BASELINE_SCHEMA:
        raise ValueError("t_route_mc_response_matrix_baseline_invalid")
    route_descriptor = baseline._validate_manifests(
        route_manifest, source_manifest, build_manifest
    )
    route_path, route_bytes = baseline._read_verified(route_descriptor)
    by_feature = baseline._route_link_rows(route_path)
    rows = [by_feature[feature_id] for feature_id in baseline.FEATURE_PATH]
    for upstream, downstream in zip(rows[:-1], rows[1:], strict=True):
        if int(upstream["to"]) != int(downstream["link"]):
            raise ValueError("t_route_mc_response_matrix_topology_mismatch")

    kernel = CtypesTrouteMuskingumCungeKernel(build_manifest_path)
    cases: list[dict[str, Any]] = []
    warmups: list[dict[str, Any]] = []
    for timestep in TIMESTEPS_SECONDS:
        for background in BACKGROUND_FLOWS_M3S:
            context, warmup = _warm_operators(
                rows,
                kernel,
                timestep_seconds=timestep,
                background_flow_m3s=background,
            )
            warmups.append(warmup)
            for pulse in PULSE_RATES_M3S:
                cases.append(
                    _run_response_case(
                        rows,
                        context,
                        timestep_seconds=timestep,
                        background_flow_m3s=background,
                        pulse_rate_m3s=pulse,
                    )
                )

    stability = _compile_timestep_stability(cases)
    sensitivity = _compile_state_amplitude_sensitivity(cases)
    gates = {
        "official_runtime_reference_conformance": prior[
            "gates"
        ]["official_reference_conformance"],
        "all_warmup_states_nonnegative_finite": all(
            item["states_nonnegative_finite"] for item in warmups
        ),
        "all_nonlinear_case_mass_identities_passed": all(
            item["nonlinear_storage"]["mass_balance_passed"] for item in cases
        ),
        "all_nonlinear_solver_step_mass_gates_passed": all(
            item["nonlinear_solver_mass_gate_passed"] for item in cases
        ),
        "all_official_mc_negative_lobes_within_tolerance": all(
            item["t_route_mc"]["negative_lobe_within_tolerance"]
            for item in cases
        ),
        "all_nonlinear_negative_lobes_within_tolerance": all(
            item["nonlinear_storage"]["negative_lobe_within_tolerance"]
            for item in cases
        ),
        "official_mc_timestep_stability": stability["t_route_mc"][
            "all_comparisons_passed"
        ],
        "nonlinear_timestep_stability": stability["nonlinear_storage"][
            "all_comparisons_passed"
        ],
        "outcome_isolation": True,
    }
    gates["all_registered_matrix_gates_passed"] = all(gates.values())
    return {
        "schema": SCHEMA,
        "status": "outcome_free_transfer_response_matrix_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "route_link_manifest": _artifact(route_link_manifest_path, route_body),
            "route_link_fixture": _artifact(route_path, route_bytes),
            "t_route_source_manifest": _artifact(source_manifest_path, source_body),
            "t_route_build_manifest": _artifact(build_manifest_path, build_body),
            "professional_baseline_v2": _artifact(
                baseline_report_path, prior_body
            ),
            "t_route_shared_library": build_manifest["library_artifact"],
        },
        "runtime_identity": prior["runtime_identity"],
        "fixture": {
            "source_id": baseline.SOURCE_ID,
            "feature_ids": list(baseline.FEATURE_PATH),
            "feature_count": len(baseline.FEATURE_PATH),
            "full_reaches_only": True,
            "observed_outcomes_used": False,
        },
        "registered_protocol": {
            "background_flows_m3s": list(BACKGROUND_FLOWS_M3S),
            "pulse_rates_m3s": list(PULSE_RATES_M3S),
            "pulse_duration_seconds": PULSE_DURATION_SECONDS,
            "timesteps_seconds": list(TIMESTEPS_SECONDS),
            "warmup_hours": WARMUP_HOURS,
            "rollout_hours": ROLLOUT_HOURS,
            "case_count": len(cases),
            "response_quantiles": ["t01", "t05", "t50", "t95"],
            "timestep_stability_absolute_tolerance_seconds": (
                STABILITY_ABSOLUTE_TOLERANCE_SECONDS
            ),
            "timestep_stability_relative_tolerance": (
                STABILITY_RELATIVE_TOLERANCE
            ),
            "initialization": (
                "operator-specific 240-hour constant-boundary warmup; base and "
                "pulse branches fork from the identical warmed state"
            ),
        },
        "warmup_states": warmups,
        "cases": cases,
        "timestep_stability": stability,
        "state_amplitude_sensitivity": sensitivity,
        "gates": gates,
        "data_isolation": {
            "observed_discharge_loaded": False,
            "observed_action_loaded": False,
            "observed_forcing_loaded": False,
            "target_fitted_parameters": 0,
            "inputs": [
                "official_route_link_parameters",
                "synthetic_constant_background_flow",
                "synthetic_boundary_pulse",
            ],
        },
        "scientific_limitations": {
            "official_mc_internal_storage_exposed": False,
            "official_mc_mass_identity_admitted": False,
            "synthetic_background_flow_is_historical_regime": False,
            "real_world_transfer_validated": False,
            "reach_subdivision_tested": False,
            "kinematic_wave_comparator_available": False,
        },
        "claim_boundary": {
            "outcome_free_state_amplitude_timestep_matrix_executed": True,
            "official_mc_response_metrics_available": True,
            "official_mc_conservation_verified": False,
            "professional_transfer_operator_certified": False,
            "hydrodynamically_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _warm_operators(
    rows: list[dict[str, float | int]],
    kernel: CtypesTrouteMuskingumCungeKernel,
    *,
    timestep_seconds: float,
    background_flow_m3s: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    parameters = baseline._mc_parameters(rows, reverse=False)
    path, geometry = baseline._nonlinear_contracts(rows, reverse=False)
    mc = TrouteMuskingumCungeAdapter(
        parameters, kernel, timestep_seconds=timestep_seconds
    )
    nonlinear = NonlinearManningReachTransportOperator(
        path,
        NonlinearReachTransportConfig(
            timestep_seconds=timestep_seconds,
            path_admitted=True,
            operator_form_admitted=False,
            allow_unadmitted_components_for_diagnostics=True,
            integration_substep_seconds=min(300.0, timestep_seconds),
        ),
    )
    mc_state = mc.zero_state(provenance_id="response-matrix:mc:warmup-zero")
    nonlinear_state = nonlinear.zero_state(
        provenance_id="response-matrix:nonlinear:warmup-zero"
    )
    maximum_nonlinear_mass_ratio = 0.0
    steps = int(WARMUP_HOURS * 3600.0 / timestep_seconds)
    for step in range(steps):
        mc_state = mc.step(
            mc_state,
            boundary_previous_m3s=background_flow_m3s,
            boundary_current_m3s=background_flow_m3s,
            provenance_id=f"response-matrix:mc:warmup:{step + 1}",
        ).next_state
        nonlinear_result = nonlinear.step(
            nonlinear_state,
            geometry,
            action=_action(
                len(rows),
                background_flow_m3s,
                f"response-matrix:nonlinear:warmup:{step + 1}",
            ),
        )
        nonlinear_state = nonlinear_result.next_stock
        maximum_nonlinear_mass_ratio = max(
            maximum_nonlinear_mass_ratio,
            abs(nonlinear_result.global_mass_balance_residual_m3)
            / nonlinear_result.numeric_mass_tolerance_m3,
        )
    nonlinear_q, _, _ = baseline._nonlinear_endpoint_qvd(
        nonlinear_state.values, rows
    )
    state_values = np.asarray(
        [mc_state.discharge_m3s, mc_state.velocity_mps, mc_state.depth_m],
        dtype=float,
    )
    warmup = {
        "timestep_seconds": timestep_seconds,
        "background_flow_m3s": background_flow_m3s,
        "warmup_step_count": steps,
        "t_route_mc_outlet_flow_m3s": mc_state.discharge_m3s[-1],
        "nonlinear_storage_outlet_endpoint_flow_m3s": nonlinear_q[-1],
        "t_route_mc_outlet_relative_steady_error": abs(
            mc_state.discharge_m3s[-1] - background_flow_m3s
        )
        / background_flow_m3s,
        "nonlinear_outlet_relative_steady_error": abs(
            nonlinear_q[-1] - background_flow_m3s
        )
        / background_flow_m3s,
        "nonlinear_maximum_step_mass_residual_to_tolerance_ratio": (
            maximum_nonlinear_mass_ratio
        ),
        "states_nonnegative_finite": bool(
            np.isfinite(state_values).all()
            and (state_values >= 0.0).all()
            and np.isfinite(nonlinear_state.values).all()
            and (np.asarray(nonlinear_state.values) >= 0.0).all()
        ),
    }
    return (
        {
            "mc": mc,
            "nonlinear": nonlinear,
            "geometry": geometry,
            "mc_state": mc_state,
            "nonlinear_state": nonlinear_state,
        },
        warmup,
    )


def _run_response_case(
    rows: list[dict[str, float | int]],
    context: Mapping[str, Any],
    *,
    timestep_seconds: float,
    background_flow_m3s: float,
    pulse_rate_m3s: float,
) -> dict[str, Any]:
    mc = context["mc"]
    nonlinear = context["nonlinear"]
    geometry = context["geometry"]
    base_mc_state = context["mc_state"]
    pulse_mc_state = context["mc_state"]
    base_nonlinear_state = context["nonlinear_state"]
    pulse_nonlinear_state = context["nonlinear_state"]
    mc_response: list[float] = []
    nonlinear_response: list[float] = []
    input_volume = 0.0
    maximum_nonlinear_mass_ratio = 0.0
    steps = int(ROLLOUT_HOURS * 3600.0 / timestep_seconds)
    for step in range(steps):
        previous_seconds = step * timestep_seconds
        current_seconds = (step + 1) * timestep_seconds
        previous_pulse = _pulse_component(previous_seconds, pulse_rate_m3s)
        current_pulse = _pulse_component(current_seconds, pulse_rate_m3s)
        mean_pulse = 0.5 * (previous_pulse + current_pulse)
        input_volume += mean_pulse * timestep_seconds

        base_mc_result = mc.step(
            base_mc_state,
            boundary_previous_m3s=background_flow_m3s,
            boundary_current_m3s=background_flow_m3s,
            provenance_id=f"response-matrix:mc:base:{step + 1}",
        )
        pulse_mc_result = mc.step(
            pulse_mc_state,
            boundary_previous_m3s=background_flow_m3s + previous_pulse,
            boundary_current_m3s=background_flow_m3s + current_pulse,
            provenance_id=f"response-matrix:mc:pulse:{step + 1}",
        )
        base_mc_mean = 0.5 * (
            base_mc_state.discharge_m3s[-1]
            + base_mc_result.next_state.discharge_m3s[-1]
        )
        pulse_mc_mean = 0.5 * (
            pulse_mc_state.discharge_m3s[-1]
            + pulse_mc_result.next_state.discharge_m3s[-1]
        )
        mc_response.append(pulse_mc_mean - base_mc_mean)
        base_mc_state = base_mc_result.next_state
        pulse_mc_state = pulse_mc_result.next_state

        base_nonlinear_result = nonlinear.step(
            base_nonlinear_state,
            geometry,
            action=_action(
                len(rows),
                background_flow_m3s,
                f"response-matrix:nonlinear:base:{step + 1}",
            ),
        )
        pulse_nonlinear_result = nonlinear.step(
            pulse_nonlinear_state,
            geometry,
            action=_action(
                len(rows),
                background_flow_m3s + mean_pulse,
                f"response-matrix:nonlinear:pulse:{step + 1}",
            ),
        )
        nonlinear_response.append(
            pulse_nonlinear_result.outlet_mean_flow_m3s
            - base_nonlinear_result.outlet_mean_flow_m3s
        )
        for result in (base_nonlinear_result, pulse_nonlinear_result):
            maximum_nonlinear_mass_ratio = max(
                maximum_nonlinear_mass_ratio,
                abs(result.global_mass_balance_residual_m3)
                / result.numeric_mass_tolerance_m3,
            )
        base_nonlinear_state = base_nonlinear_result.next_stock
        pulse_nonlinear_state = pulse_nonlinear_result.next_stock

    if not np.isclose(
        input_volume, pulse_rate_m3s * PULSE_DURATION_SECONDS, rtol=0.0, atol=1e-9
    ):
        raise RuntimeError("t_route_mc_response_matrix_pulse_volume_invalid")
    mc_storage_difference = baseline._official_physical_storage(
        pulse_mc_state.depth_m, rows
    ) - baseline._official_physical_storage(base_mc_state.depth_m, rows)
    nonlinear_storage_difference = float(
        np.asarray(pulse_nonlinear_state.values).sum()
        - np.asarray(base_nonlinear_state.values).sum()
    )
    mc_metrics = analyze_dynamic_transfer_response(
        mc_response,
        timestep_seconds=timestep_seconds,
        input_volume_m3=input_volume,
        final_incremental_storage_m3=mc_storage_difference,
    )
    nonlinear_metrics = analyze_dynamic_transfer_response(
        nonlinear_response,
        timestep_seconds=timestep_seconds,
        input_volume_m3=input_volume,
        final_incremental_storage_m3=nonlinear_storage_difference,
    )
    return {
        "case_id": (
            f"q{background_flow_m3s:g}_pulse{pulse_rate_m3s:g}_dt{timestep_seconds:g}"
        ),
        "background_flow_m3s": background_flow_m3s,
        "pulse_rate_m3s": pulse_rate_m3s,
        "pulse_input_volume_m3": input_volume,
        "timestep_seconds": timestep_seconds,
        "rollout_hours": ROLLOUT_HOURS,
        "t_route_mc": mc_metrics.as_dict(),
        "nonlinear_storage": nonlinear_metrics.as_dict(),
        "nonlinear_maximum_step_mass_residual_to_tolerance_ratio": (
            maximum_nonlinear_mass_ratio
        ),
        "nonlinear_solver_mass_gate_passed": maximum_nonlinear_mass_ratio <= 1.0,
    }


def _compile_timestep_stability(cases: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for operator in ("t_route_mc", "nonlinear_storage"):
        comparisons = []
        for background in BACKGROUND_FLOWS_M3S:
            for pulse in PULSE_RATES_M3S:
                group = {
                    float(item["timestep_seconds"]): item[operator]
                    for item in cases
                    if item["background_flow_m3s"] == background
                    and item["pulse_rate_m3s"] == pulse
                }
                reference = group[TIMESTEPS_SECONDS[0]][
                    "input_recovery_quantile_seconds"
                ]
                for timestep in TIMESTEPS_SECONDS[1:]:
                    candidate = group[timestep]["input_recovery_quantile_seconds"]
                    for quantile in ("t05", "t50", "t95"):
                        reference_time = reference[quantile]
                        candidate_time = candidate[quantile]
                        tolerance = (
                            None
                            if reference_time is None
                            else max(
                                STABILITY_ABSOLUTE_TOLERANCE_SECONDS,
                                STABILITY_RELATIVE_TOLERANCE * reference_time,
                            )
                        )
                        difference = (
                            None
                            if reference_time is None or candidate_time is None
                            else abs(candidate_time - reference_time)
                        )
                        comparisons.append(
                            {
                                "background_flow_m3s": background,
                                "pulse_rate_m3s": pulse,
                                "reference_timestep_seconds": TIMESTEPS_SECONDS[0],
                                "candidate_timestep_seconds": timestep,
                                "quantile": quantile,
                                "absolute_difference_seconds": difference,
                                "tolerance_seconds": tolerance,
                                "passed": (
                                    difference is not None
                                    and tolerance is not None
                                    and difference <= tolerance
                                ),
                            }
                        )
        result[operator] = {
            "comparison_count": len(comparisons),
            "comparisons": comparisons,
            "all_comparisons_passed": all(
                item["passed"] for item in comparisons
            ),
        }
    return result


def _compile_state_amplitude_sensitivity(
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for operator in ("t_route_mc", "nonlinear_storage"):
        amplitude = []
        for timestep in TIMESTEPS_SECONDS:
            for background in BACKGROUND_FLOWS_M3S:
                selected = [
                    item
                    for item in cases
                    if item["timestep_seconds"] == timestep
                    and item["background_flow_m3s"] == background
                ]
                values = {
                    str(item["pulse_rate_m3s"]): item[operator][
                        "input_recovery_quantile_seconds"
                    ]["t50"]
                    for item in selected
                }
                finite = [value for value in values.values() if value is not None]
                amplitude.append(
                    {
                        "timestep_seconds": timestep,
                        "background_flow_m3s": background,
                        "t50_seconds_by_pulse_rate_m3s": values,
                        "t50_range_seconds": (
                            None if not finite else max(finite) - min(finite)
                        ),
                    }
                )
        state_order = []
        for pulse in PULSE_RATES_M3S:
            values = {
                str(item["background_flow_m3s"]): item[operator][
                    "input_recovery_quantile_seconds"
                ]["t50"]
                for item in cases
                if item["timestep_seconds"] == TIMESTEPS_SECONDS[0]
                and item["pulse_rate_m3s"] == pulse
            }
            finite = all(value is not None for value in values.values())
            ordered = (
                finite
                and values[str(BACKGROUND_FLOWS_M3S[2])]
                <= values[str(BACKGROUND_FLOWS_M3S[1])]
                <= values[str(BACKGROUND_FLOWS_M3S[0])]
            )
            state_order.append(
                {
                    "pulse_rate_m3s": pulse,
                    "t50_seconds_by_background_flow_m3s": values,
                    "higher_background_not_slower": ordered,
                }
            )
        result[operator] = {
            "amplitude_sensitivity": amplitude,
            "state_order_diagnostic_at_300s": state_order,
            "all_state_order_diagnostics_passed": all(
                item["higher_background_not_slower"] for item in state_order
            ),
        }
    return result


def _pulse_component(seconds: float, pulse_rate_m3s: float) -> float:
    return (
        pulse_rate_m3s
        if 0.0 < seconds <= PULSE_DURATION_SECONDS
        else 0.0
    )


def _action(count: int, rate_m3s: float, provenance_id: str) -> ActionBoundaryFlux:
    return ActionBoundaryFlux(
        (rate_m3s,) + (0.0,) * (count - 1),
        "m3 s-1",
        provenance_id,
    )


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
        raise ValueError("t_route_mc_response_matrix_refuses_overwrite")
    report = compile_certification(
        route_link_manifest_path=args.route_link_manifest,
        source_manifest_path=args.source_manifest,
        build_manifest_path=args.build_manifest,
        baseline_report_path=args.baseline_report,
    )
    body = _json_body(report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(body)
    print(args.report)
    print(hashlib.sha256(body).hexdigest())
    print(f"case_count={len(report['cases'])}")
    print(
        "all_registered_matrix_gates_passed="
        f"{report['gates']['all_registered_matrix_gates_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
