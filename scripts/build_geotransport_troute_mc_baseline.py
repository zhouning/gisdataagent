#!/usr/bin/env python3
"""Compare official t-route MC with Kernel v2 on an outcome-free RouteLink path."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import h5py
import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    CtypesTrouteMuskingumCungeKernel,
    LinearReferencedPath,
    NonlinearManningReachTransportOperator,
    NonlinearReachTransportConfig,
    ReachHydraulicGeometry,
    TrouteMuskingumCungeAdapter,
    TrouteMuskingumCungeParameters,
    analyze_dynamic_transfer_response,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTE_LINK_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/route_link_public_audit/acquisition_manifest.json"
)
DEFAULT_SOURCE_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/t_route_mc_source_audit/acquisition_manifest.json"
)
DEFAULT_BUILD_MANIFEST = (
    REPO_ROOT / "data/geotransport_v0_1/t_route_mc_runtime/build_manifest.json"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/t_route_mc_professional_baseline_v2_report.json"
)
SCHEMA = "gwm.geotransport.t_route_mc_professional_baseline.v2"
ROUTE_LINK_SCHEMA = "gwm.geotransport.public_route_link_audit.v1"
SOURCE_SCHEMA = "gwm.geotransport.t_route_mc_source_audit.v1"
BUILD_SCHEMA = "gwm.geotransport.t_route_mc_runtime_build.v1"
T_ROUTE_COMMIT = "12a8eae0cdfed437143c590659fa7077605a5e70"
SOURCE_ID = "t_route_hurricane_laura_nwm_v2_1"
FEATURE_PATH = (
    1622797,
    1622687,
    1623573,
    1621137,
    1621139,
    1623575,
    1622701,
    1622703,
    1622721,
)
TIMESTEP_SECONDS = 300.0
ROLLOUT_HOURS = 120
PULSE_HOURS = 6
DIRECTION_RELATIVE_L1_NUMERIC_MINIMUM = 1e-5
CONFORMANCE_ABSOLUTE_TOLERANCE = 2e-7


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route-link-manifest", type=Path, default=DEFAULT_ROUTE_LINK_MANIFEST
    )
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--build-manifest", type=Path, default=DEFAULT_BUILD_MANIFEST)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_baseline(
    *,
    route_link_manifest_path: Path = DEFAULT_ROUTE_LINK_MANIFEST,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    build_manifest_path: Path = DEFAULT_BUILD_MANIFEST,
) -> dict[str, Any]:
    route_body = route_link_manifest_path.read_bytes()
    source_body = source_manifest_path.read_bytes()
    build_body = build_manifest_path.read_bytes()
    route_manifest = json.loads(route_body)
    source_manifest = json.loads(source_body)
    build_manifest = json.loads(build_body)
    route_descriptor = _validate_manifests(
        route_manifest, source_manifest, build_manifest
    )
    route_path, route_bytes = _read_verified(route_descriptor)
    rows = _route_link_rows(route_path)
    selected = [rows[feature_id] for feature_id in FEATURE_PATH]
    for upstream, downstream in zip(selected[:-1], selected[1:], strict=True):
        if int(upstream["to"]) != int(downstream["link"]):
            raise ValueError("t_route_mc_baseline_fixture_path_topology_mismatch")

    kernel = CtypesTrouteMuskingumCungeKernel(build_manifest_path)
    conformance = _official_conformance(kernel)
    zero_state = _official_zero_state_invariant(selected, kernel)
    forward = _run_pair(selected, kernel, reverse=False)
    reverse = _run_pair(selected, kernel, reverse=True)
    mc_direction = _series_difference(
        forward["t_route_mc"]["outlet_discharge_m3s_5min"],
        reverse["t_route_mc"]["outlet_discharge_m3s_5min"],
    )
    nonlinear_direction = _series_difference(
        forward["nonlinear_storage"]["outlet_discharge_m3s_5min"],
        reverse["nonlinear_storage"]["outlet_discharge_m3s_5min"],
    )
    for rollout in (forward, reverse):
        rollout["t_route_mc"].pop("outlet_discharge_m3s_5min")
        rollout["nonlinear_storage"].pop("outlet_discharge_m3s_5min")
    gates = {
        "official_reference_conformance": conformance["passed"],
        "official_zero_state_invariant": zero_state["passed"],
        "official_qvd_nonnegative_finite": (
            forward["t_route_mc"]["qvd_nonnegative_finite"]
            and reverse["t_route_mc"]["qvd_nonnegative_finite"]
        ),
        "official_mc_conservation_diagnostic_completed": (
            forward["t_route_mc"]["physical_volume_audit_completed"]
            and reverse["t_route_mc"]["physical_volume_audit_completed"]
        ),
        "nonlinear_physical_volume_conservative": (
            forward["nonlinear_storage"]["physical_volume_conservation_passed"]
            and reverse["nonlinear_storage"]["physical_volume_conservation_passed"]
        ),
        "official_direction_response_above_numeric_noise": (
            mc_direction["relative_l1_difference"]
            >= DIRECTION_RELATIVE_L1_NUMERIC_MINIMUM
        ),
        "nonlinear_direction_response_above_numeric_noise": (
            nonlinear_direction["relative_l1_difference"]
            >= DIRECTION_RELATIVE_L1_NUMERIC_MINIMUM
        ),
        "outcome_isolation": True,
        "dynamic_transfer_response_metrics_completed": (
            forward["t_route_mc"]["dynamic_transfer_response"]["sample_count"]
            == forward["t_route_mc"]["completed_step_count"]
            and forward["nonlinear_storage"]["dynamic_transfer_response"][
                "sample_count"
            ]
            == forward["nonlinear_storage"]["completed_step_count"]
        ),
    }
    gates["all_professional_baseline_invariants_passed"] = all(gates.values())
    if not gates["all_professional_baseline_invariants_passed"]:
        failed = sorted(name for name, value in gates.items() if not value)
        raise RuntimeError("t_route_mc_professional_baseline_failed:" + ",".join(failed))

    return {
        "schema": SCHEMA,
        "status": "pass_with_conservation_limitation",
        "source_artifacts": {
            "route_link_manifest": _artifact(route_link_manifest_path, route_body),
            "route_link_fixture": _artifact(route_path, route_bytes),
            "t_route_source_manifest": _artifact(
                source_manifest_path, source_body
            ),
            "t_route_build_manifest": _artifact(build_manifest_path, build_body),
            "t_route_shared_library": build_manifest["library_artifact"],
        },
        "runtime_identity": {
            "repository": "NOAA-OWP/t-route",
            "commit": T_ROUTE_COMMIT,
            "entrypoint": "c_muskingcungenwm",
            "official_source_unmodified": True,
            "compiler": build_manifest["compiler"],
            "platform": build_manifest["platform"],
        },
        "official_reference_conformance": conformance,
        "official_zero_state_invariant": zero_state,
        "data_isolation": {
            "outcome_values_loaded": False,
            "observed_action_loaded": False,
            "observed_forcing_loaded": False,
            "inputs": ["official_route_link_parameters", "synthetic_boundary_pulse"],
        },
        "fixture": {
            "source_id": SOURCE_ID,
            "feature_ids": list(FEATURE_PATH),
            "feature_count": len(FEATURE_PATH),
            "topology_consecutive": True,
            "full_reaches_only": True,
            "center_hill_parameter_fixture": False,
        },
        "registered_protocol": {
            "timestep_seconds": TIMESTEP_SECONDS,
            "rollout_hours": ROLLOUT_HOURS,
            "boundary_pulse_hours": PULSE_HOURS,
            "boundary_pulse_rate_m3s": 20.0,
            "direction_relative_l1_numeric_minimum": (
                DIRECTION_RELATIVE_L1_NUMERIC_MINIMUM
            ),
            "conformance_absolute_tolerance": CONFORMANCE_ABSOLUTE_TOLERANCE,
            "response_quantiles": ["t01", "t05", "t50", "t95"],
            "response_quantile_interpolation": (
                "constant interval-mean flow with within-interval linear volume"
            ),
            "channel_side_slope_compilation": (
                "RouteLink ChSlp is passed unchanged to t-route; nonlinear "
                "horizontal_per_vertical side slope is 1/ChSlp"
            ),
        },
        "forward_authoritative_order": forward,
        "reversed_order_diagnostic": reverse,
        "direction_diagnostics": {
            "t_route_mc": mc_direction,
            "nonlinear_storage": nonlinear_direction,
        },
        "transfer_response_adjudication": {
            "official_mc_response_metrics_completed": True,
            "official_mc_physical_mass_identity_admitted": False,
            "nonlinear_storage_mass_identity_passed": forward[
                "nonlinear_storage"
            ]["dynamic_transfer_response"]["mass_balance_passed"],
            "official_mc_input_t95_recovered_inside_window": forward[
                "t_route_mc"
            ]["dynamic_transfer_response"]["input_recovery_quantile_seconds"][
                "t95"
            ]
            is not None,
            "nonlinear_input_t95_recovered_inside_window": forward[
                "nonlinear_storage"
            ]["dynamic_transfer_response"]["input_recovery_quantile_seconds"][
                "t95"
            ]
            is not None,
            "professional_transfer_operator_certified": False,
        },
        "metric_semantics": {
            "t_route_mc_returned_ck_x_reconstruction": (
                "diagnostic only: the fixed source does not establish returned ck/X "
                "as the exact coefficients used for final Q, and the observed rollout "
                "does not reconstruct the MC equation"
            ),
            "t_route_mc_physical_volume_audit": (
                "independent area(depth)*length stock audit using the official "
                "compound-channel geometry; this is not the internal MC storage state"
            ),
            "nonlinear_storage_conservation": (
                "telescoping physical reach volume plus outlet volume"
            ),
            "qvd_discrepancy": (
                "model-family discrepancy on a synthetic probe, not prediction error"
            ),
        },
        "gates": gates,
        "scientific_limitations": {
            "returned_ck_x_authoritative_for_equation_reconstruction": False,
            "official_mc_forward_physical_volume_conservative": forward[
                "t_route_mc"
            ]["derived_physical_volume_conservation_passed"],
            "official_mc_reverse_physical_volume_conservative": reverse[
                "t_route_mc"
            ]["derived_physical_volume_conservation_passed"],
            "official_mc_conservation_verified": False,
        },
        "claim_boundary": {
            "official_t_route_runtime_built": True,
            "official_t_route_kernel_executed": True,
            "professional_baseline_available_on_official_fixture": True,
            "volume_response_metrics_available": True,
            "professional_transfer_operator_certified": False,
            "official_mc_conservation_verified": False,
            "compound_channel_enabled_in_t_route": True,
            "compound_channel_enabled_in_nonlinear_storage": False,
            "models_numerically_equivalent": False,
            "authoritative_real_world_direction_validated": False,
            "hydrodynamically_validated": False,
            "center_hill_parameters_available": False,
            "center_hill_execution_admitted": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _run_pair(
    selected: list[dict[str, float | int]],
    kernel: CtypesTrouteMuskingumCungeKernel,
    *,
    reverse: bool,
) -> dict[str, Any]:
    rows = list(reversed(selected)) if reverse else selected
    parameters = _mc_parameters(rows, reverse=reverse)
    path, geometry = _nonlinear_contracts(rows, reverse=reverse)
    mc = TrouteMuskingumCungeAdapter(
        parameters, kernel, timestep_seconds=TIMESTEP_SECONDS
    )
    nonlinear = NonlinearManningReachTransportOperator(
        path,
        NonlinearReachTransportConfig(
            timestep_seconds=TIMESTEP_SECONDS,
            path_admitted=True,
            operator_form_admitted=False,
            allow_unadmitted_components_for_diagnostics=True,
            integration_substep_seconds=TIMESTEP_SECONDS,
        ),
    )
    mc_state = mc.zero_state(provenance_id="t-route:zero")
    nonlinear_state = nonlinear.zero_state(provenance_id="nonlinear:zero")
    steps = int(ROLLOUT_HOURS * 3600 / TIMESTEP_SECONDS)
    mc_outlet_q: list[float] = []
    nonlinear_outlet_q: list[float] = []
    mc_outlet_interval_mean_q: list[float] = []
    nonlinear_outlet_interval_mean_q: list[float] = []
    mc_hourly_qvd: list[dict[str, float | int]] = []
    nonlinear_hourly_qvd: list[dict[str, float | int]] = []
    mc_residuals: list[float] = []
    mc_physical_residuals: list[float] = []
    mc_physical_tolerances: list[float] = []
    nonlinear_residuals: list[float] = []
    nonlinear_tolerances: list[float] = []
    nonlinear_cumulative_input = 0.0
    nonlinear_cumulative_outlet = 0.0
    mc_cumulative_input = 0.0
    mc_cumulative_outlet = 0.0
    mc_initial_physical_storage = _official_physical_storage(mc_state.depth_m, rows)
    mc_previous_physical_storage = mc_initial_physical_storage
    bankfull_depths = _bankfull_depths(rows)
    previous_boundary = _boundary_rate(0.0)
    maximum_mc_depth = 0.0
    maximum_nonlinear_depth = 0.0
    mc_all_qvd_valid = True
    nonlinear_all_qvd_valid = True
    compound_channel_activated = False
    for step in range(steps):
        current_boundary = _boundary_rate((step + 1) * TIMESTEP_SECONDS)
        mc_result = mc.step(
            mc_state,
            boundary_previous_m3s=previous_boundary,
            boundary_current_m3s=current_boundary,
            provenance_id=f"t-route:step:{step + 1}",
        )
        mean_boundary = 0.5 * (previous_boundary + current_boundary)
        nonlinear_result = nonlinear.step(
            nonlinear_state,
            geometry,
            action=(
                ActionBoundaryFlux(
                    (mean_boundary,) + (0.0,) * (len(rows) - 1),
                    "m3 s-1",
                    f"synthetic:boundary:{step + 1}",
                )
                if mean_boundary > 0.0
                else None
            ),
        )
        nonlinear_q, nonlinear_v, nonlinear_d = _nonlinear_endpoint_qvd(
            nonlinear_result.next_stock.values, rows
        )
        mc_residuals.append(
            mc_result.network_reconstructed_equation_residual_m3
        )
        mc_new_physical_storage = _official_physical_storage(
            mc_result.next_state.depth_m, rows
        )
        mc_input_volume = TIMESTEP_SECONDS * (
            0.5 * (previous_boundary + current_boundary)
        )
        mc_outlet_volume = TIMESTEP_SECONDS * 0.5 * (
            mc_state.discharge_m3s[-1]
            + mc_result.next_state.discharge_m3s[-1]
        )
        mc_physical_residual = (
            mc_new_physical_storage
            + mc_outlet_volume
            - mc_previous_physical_storage
            - mc_input_volume
        )
        mc_physical_scale = max(
            abs(mc_new_physical_storage),
            abs(mc_previous_physical_storage),
            abs(mc_input_volume),
            abs(mc_outlet_volume),
            1.0,
        )
        mc_physical_tolerance = (
            1e-3 + 128.0 * np.finfo(np.float32).eps * mc_physical_scale
        )
        mc_physical_residuals.append(mc_physical_residual)
        mc_physical_tolerances.append(float(mc_physical_tolerance))
        mc_cumulative_input += mc_input_volume
        mc_cumulative_outlet += mc_outlet_volume
        mc_previous_physical_storage = mc_new_physical_storage
        nonlinear_residuals.append(
            nonlinear_result.global_mass_balance_residual_m3
        )
        nonlinear_tolerances.append(nonlinear_result.numeric_mass_tolerance_m3)
        nonlinear_cumulative_input += nonlinear_result.input_volume_m3
        nonlinear_cumulative_outlet += nonlinear_result.outlet_volume_m3
        mc_outlet_interval_mean_q.append(
            0.5
            * (
                mc_state.discharge_m3s[-1]
                + mc_result.next_state.discharge_m3s[-1]
            )
        )
        nonlinear_outlet_interval_mean_q.append(
            nonlinear_result.outlet_mean_flow_m3s
        )
        mc_outlet_q.append(mc_result.next_state.discharge_m3s[-1])
        nonlinear_outlet_q.append(nonlinear_q[-1])
        maximum_mc_depth = max(maximum_mc_depth, max(mc_result.next_state.depth_m))
        maximum_nonlinear_depth = max(maximum_nonlinear_depth, max(nonlinear_d))
        compound_channel_activated = compound_channel_activated or any(
            depth > bankfull
            for depth, bankfull in zip(
                mc_result.next_state.depth_m, bankfull_depths, strict=True
            )
        )
        mc_all_qvd_valid = mc_all_qvd_valid and _state_is_valid(
            mc_result.next_state
        )
        nonlinear_all_qvd_valid = (
            nonlinear_all_qvd_valid
            and bool(
                np.isfinite([nonlinear_q, nonlinear_v, nonlinear_d]).all()
                and (np.asarray([nonlinear_q, nonlinear_v, nonlinear_d]) >= 0.0).all()
            )
        )
        if (step + 1) % int(3600 / TIMESTEP_SECONDS) == 0:
            hour = int((step + 1) * TIMESTEP_SECONDS / 3600)
            mc_hourly_qvd.append(
                {
                    "hour": hour,
                    "outlet_discharge_m3s": mc_result.next_state.discharge_m3s[-1],
                    "outlet_velocity_mps": mc_result.next_state.velocity_mps[-1],
                    "outlet_depth_m": mc_result.next_state.depth_m[-1],
                }
            )
            nonlinear_hourly_qvd.append(
                {
                    "hour": hour,
                    "outlet_discharge_m3s": nonlinear_q[-1],
                    "outlet_velocity_mps": nonlinear_v[-1],
                    "outlet_depth_m": nonlinear_d[-1],
                }
            )
        mc_state = mc_result.next_state
        nonlinear_state = nonlinear_result.next_stock
        previous_boundary = current_boundary

    nonlinear_horizon_residual = (
        sum(nonlinear_state.values)
        + nonlinear_cumulative_outlet
        - nonlinear_cumulative_input
    )
    mc_horizon_physical_residual = (
        mc_previous_physical_storage
        + mc_cumulative_outlet
        - mc_initial_physical_storage
        - mc_cumulative_input
    )
    mc_transfer_response = analyze_dynamic_transfer_response(
        mc_outlet_interval_mean_q,
        timestep_seconds=TIMESTEP_SECONDS,
        input_volume_m3=mc_cumulative_input,
        final_incremental_storage_m3=(
            mc_previous_physical_storage - mc_initial_physical_storage
        ),
    )
    nonlinear_transfer_response = analyze_dynamic_transfer_response(
        nonlinear_outlet_interval_mean_q,
        timestep_seconds=TIMESTEP_SECONDS,
        input_volume_m3=nonlinear_cumulative_input,
        final_incremental_storage_m3=sum(nonlinear_state.values),
    )
    mc_summary = {
        "completed_step_count": steps,
        "qvd_nonnegative_finite": mc_all_qvd_valid,
        "maximum_depth_m": maximum_mc_depth,
        "minimum_bankfull_depth_m": min(bankfull_depths),
        "compound_channel_activated": compound_channel_activated,
        "returned_ck_x_authoritative_for_equation_reconstruction": False,
        "maximum_absolute_reconstructed_equation_residual_m3": max(
            abs(value) for value in mc_residuals
        ),
        "reconstructed_equation_closes_at_float32_tolerance": False,
        "physical_volume_audit_completed": True,
        "maximum_absolute_step_derived_physical_mass_residual_m3": max(
            abs(value) for value in mc_physical_residuals
        ),
        "horizon_derived_physical_mass_residual_m3": (
            mc_horizon_physical_residual
        ),
        "horizon_derived_physical_mass_tolerance_m3": sum(
            mc_physical_tolerances
        ),
        "derived_physical_volume_conservation_passed": (
            all(
                abs(value) <= tolerance
                for value, tolerance in zip(
                    mc_physical_residuals, mc_physical_tolerances, strict=True
                )
            )
            and abs(mc_horizon_physical_residual)
            <= sum(mc_physical_tolerances)
        ),
        "derived_physical_volume_residual_to_input_ratio": (
            abs(mc_horizon_physical_residual)
            / max(mc_cumulative_input, np.finfo(float).tiny)
        ),
        "dynamic_transfer_response": mc_transfer_response.as_dict(),
        "outlet_discharge_m3s_5min": mc_outlet_q,
        "outlet_qvd_hourly": mc_hourly_qvd,
    }
    nonlinear_summary = {
        "completed_step_count": steps,
        "qvd_nonnegative_finite": nonlinear_all_qvd_valid,
        "maximum_depth_m": maximum_nonlinear_depth,
        "compound_channel_implemented": False,
        "maximum_absolute_step_physical_mass_residual_m3": max(
            abs(value) for value in nonlinear_residuals
        ),
        "horizon_physical_mass_residual_m3": nonlinear_horizon_residual,
        "horizon_physical_mass_tolerance_m3": sum(nonlinear_tolerances),
        "physical_volume_conservation_passed": (
            all(
                abs(value) <= tolerance
                for value, tolerance in zip(
                    nonlinear_residuals, nonlinear_tolerances, strict=True
                )
            )
            and abs(nonlinear_horizon_residual) <= sum(nonlinear_tolerances)
        ),
        "dynamic_transfer_response": nonlinear_transfer_response.as_dict(),
        "outlet_discharge_m3s_5min": nonlinear_outlet_q,
        "outlet_qvd_hourly": nonlinear_hourly_qvd,
    }
    return {
        "feature_ids": [int(row["link"]) for row in rows],
        "t_route_mc": mc_summary,
        "nonlinear_storage": nonlinear_summary,
        "qvd_model_family_discrepancy_hourly": _qvd_discrepancy(
            mc_hourly_qvd, nonlinear_hourly_qvd
        ),
    }


def _official_conformance(
    kernel: CtypesTrouteMuskingumCungeKernel,
) -> dict[str, Any]:
    actual = kernel.step_segment(
        dt=60.0,
        qup=0.04598825,
        quc=0.04598825,
        qdp=0.21487340,
        ql=40.0,
        dx=1800.0,
        bw=112.0,
        tw=448.0,
        twcc=623.5999755859375,
        n=0.02800000086426735,
        ncc=0.03136000037193298,
        cs=1.399999976158142,
        s0=0.0017999999690800905,
        velp=0.0704801953,
        depthp=0.0100334705,
    )
    expected = (
        0.7570106983184814,
        0.12373604625463486,
        0.02334451675415039,
    )
    errors = tuple(abs(actual[index] - expected[index]) for index in range(3))
    return {
        "source": "official mc_sseg_stime_NOLOOP_demo.py single-precision case",
        "expected_qvd": list(expected),
        "actual_qvd": list(actual[:3]),
        "absolute_errors": list(errors),
        "absolute_tolerance": CONFORMANCE_ABSOLUTE_TOLERANCE,
        "passed": all(value <= CONFORMANCE_ABSOLUTE_TOLERANCE for value in errors),
    }


def _official_zero_state_invariant(
    selected: list[dict[str, float | int]],
    kernel: CtypesTrouteMuskingumCungeKernel,
) -> dict[str, Any]:
    adapter = TrouteMuskingumCungeAdapter(
        _mc_parameters(selected, reverse=False),
        kernel,
        timestep_seconds=TIMESTEP_SECONDS,
    )
    state = adapter.zero_state(provenance_id="t-route:zero-invariant")
    completed = 0
    for step in range(288):
        result = adapter.step(
            state,
            boundary_previous_m3s=0.0,
            boundary_current_m3s=0.0,
            provenance_id=f"t-route:zero-invariant:{step + 1}",
        )
        state = result.next_state
        completed += 1
    values = np.asarray(
        [state.discharge_m3s, state.velocity_mps, state.depth_m], dtype=float
    )
    return {
        "registered_hours": 24,
        "completed_step_count": completed,
        "maximum_absolute_qvd": float(np.abs(values).max()),
        "passed": completed == 288 and bool((values == 0.0).all()),
    }


def _mc_parameters(
    rows: list[dict[str, float | int]], *, reverse: bool
) -> TrouteMuskingumCungeParameters:
    suffix = "reverse" if reverse else "forward"
    return TrouteMuskingumCungeParameters(
        feature_ids=tuple(int(row["link"]) for row in rows),
        length_m=tuple(float(row["Length"]) for row in rows),
        bottom_width_m=tuple(float(row["BtmWdth"]) for row in rows),
        top_width_m=tuple(float(row["TopWdth"]) for row in rows),
        compound_top_width_m=tuple(float(row["TopWdthCC"]) for row in rows),
        manning_n=tuple(float(row["n"]) for row in rows),
        compound_manning_n=tuple(float(row["nCC"]) for row in rows),
        channel_side_slope_chslp=tuple(float(row["ChSlp"]) for row in rows),
        bed_slope=tuple(float(row["So"]) for row in rows),
        provenance_id=f"t-route:{SOURCE_ID}:{suffix}",
    )


def _nonlinear_contracts(
    rows: list[dict[str, float | int]], *, reverse: bool
) -> tuple[LinearReferencedPath, ReachHydraulicGeometry]:
    suffix = "reverse" if reverse else "forward"
    ids = tuple(int(row["link"]) for row in rows)
    lengths = tuple(float(row["Length"]) for row in rows)
    path = LinearReferencedPath(
        f"hurricane-laura-mc-comparison:{suffix}",
        ids,
        lengths,
        (0.0,) * len(rows),
        lengths,
        f"t-route:{SOURCE_ID}:{suffix}",
        "derived",
    )
    geometry = ReachHydraulicGeometry(
        ids,
        tuple(float(row["BtmWdth"]) for row in rows),
        tuple(1.0 / float(row["ChSlp"]) for row in rows),
        tuple(float(row["So"]) for row in rows),
        tuple(float(row["n"]) for row in rows),
        f"t-route:{SOURCE_ID}:ChSlp_inverse:{suffix}",
        "derived",
        True,
    )
    return path, geometry


def _nonlinear_endpoint_qvd(
    storage_values: tuple[float, ...], rows: list[dict[str, float | int]]
) -> tuple[list[float], list[float], list[float]]:
    storage = np.asarray(storage_values, dtype=float)
    length = np.asarray([row["Length"] for row in rows], dtype=float)
    bottom = np.asarray([row["BtmWdth"] for row in rows], dtype=float)
    side = 1.0 / np.asarray([row["ChSlp"] for row in rows], dtype=float)
    slope = np.asarray([row["So"] for row in rows], dtype=float)
    manning = np.asarray([row["n"] for row in rows], dtype=float)
    area = storage / length
    depth = (-bottom + np.sqrt(bottom**2 + 4.0 * side * area)) / (2.0 * side)
    perimeter = bottom + 2.0 * depth * np.sqrt(1.0 + side**2)
    radius = np.divide(area, perimeter, out=np.zeros_like(area), where=perimeter > 0)
    discharge = area * radius ** (2.0 / 3.0) * np.sqrt(slope) / manning
    velocity = np.divide(
        discharge, area, out=np.zeros_like(discharge), where=area > 0
    )
    return discharge.tolist(), velocity.tolist(), depth.tolist()


def _bankfull_depths(rows: list[dict[str, float | int]]) -> list[float]:
    result = []
    for row in rows:
        bottom = float(row["BtmWdth"])
        top = float(row["TopWdth"])
        z = 1.0 / float(row["ChSlp"])
        result.append(bottom / 0.00001 if bottom > top else (top - bottom) / (2 * z))
    return result


def _official_physical_storage(
    depths_m: tuple[float, ...], rows: list[dict[str, float | int]]
) -> float:
    volume = 0.0
    for depth, row in zip(depths_m, rows, strict=True):
        bottom = float(row["BtmWdth"])
        top = float(row["TopWdth"])
        compound_top = float(row["TopWdthCC"])
        z = 1.0 / float(row["ChSlp"])
        if bottom > top:
            bankfull = bottom / 0.00001
        elif bottom == top:
            bankfull = bottom / (2.0 * z)
        else:
            bankfull = (top - bottom) / (2.0 * z)
        below = min(float(depth), bankfull)
        above = max(float(depth) - bankfull, 0.0)
        channel_area = (bottom + below * z) * below
        compound_area = compound_top * above
        volume += (channel_area + compound_area) * float(row["Length"])
    return float(volume)


def _boundary_rate(seconds: float) -> float:
    return 20.0 if 0.0 < seconds <= PULSE_HOURS * 3600.0 else 0.0


def _series_difference(left: list[float], right: list[float]) -> dict[str, Any]:
    lhs = np.asarray(left, dtype=float)
    rhs = np.asarray(right, dtype=float)
    absolute = np.abs(lhs - rhs)
    denominator = max(float(np.abs(lhs).sum()), np.finfo(float).tiny)
    return {
        "sample_count": int(lhs.size),
        "absolute_l1_difference_m3s": float(absolute.sum()),
        "relative_l1_difference": float(absolute.sum() / denominator),
        "maximum_absolute_difference_m3s": float(absolute.max()),
        "forward_peak_step_zero_based": int(np.argmax(lhs)),
        "reverse_peak_step_zero_based": int(np.argmax(rhs)),
        "forward_peak_m3s": float(lhs.max()),
        "reverse_peak_m3s": float(rhs.max()),
    }


def _qvd_discrepancy(
    official: list[dict[str, float | int]],
    nonlinear: list[dict[str, float | int]],
) -> dict[str, Any]:
    result: dict[str, Any] = {"sample_count": len(official)}
    for name, unit in (
        ("outlet_discharge_m3s", "m3 s-1"),
        ("outlet_velocity_mps", "m s-1"),
        ("outlet_depth_m", "m"),
    ):
        reference = np.asarray([row[name] for row in official], dtype=float)
        candidate = np.asarray([row[name] for row in nonlinear], dtype=float)
        difference = candidate - reference
        denominator = max(float(np.abs(reference).sum()), np.finfo(float).tiny)
        result[name] = {
            "unit": unit,
            "mean_absolute_difference": float(np.abs(difference).mean()),
            "root_mean_square_difference": float(np.sqrt(np.mean(difference**2))),
            "relative_l1_difference": float(np.abs(difference).sum() / denominator),
        }
    return result


def _state_is_valid(state: Any) -> bool:
    values = np.asarray(
        [state.discharge_m3s, state.velocity_mps, state.depth_m], dtype=float
    )
    return bool(np.isfinite(values).all() and (values >= 0.0).all())


def _route_link_rows(path: Path) -> dict[int, dict[str, float | int]]:
    names = (
        "link",
        "to",
        "Length",
        "BtmWdth",
        "TopWdth",
        "TopWdthCC",
        "ChSlp",
        "So",
        "n",
        "nCC",
    )
    with h5py.File(path, "r") as dataset:
        arrays = {name: np.asarray(dataset[name][...]) for name in names}
    return {
        int(arrays["link"][index]): {
            name: (
                int(values[index])
                if name in {"link", "to"}
                else float(values[index])
            )
            for name, values in arrays.items()
        }
        for index in range(len(arrays["link"]))
    }


def _validate_manifests(
    route: Mapping[str, Any],
    source: Mapping[str, Any],
    build: Mapping[str, Any],
) -> Mapping[str, Any]:
    if route.get("schema") != ROUTE_LINK_SCHEMA or route.get("mode") != "values":
        raise ValueError("t_route_mc_baseline_route_manifest_invalid")
    if (
        source.get("schema") != SOURCE_SCHEMA
        or source.get("mode") != "values"
        or source.get("commit") != T_ROUTE_COMMIT
    ):
        raise ValueError("t_route_mc_baseline_source_manifest_invalid")
    if (
        build.get("schema") != BUILD_SCHEMA
        or build.get("source_commit") != T_ROUTE_COMMIT
        or build.get("official_source_unmodified") is not True
    ):
        raise ValueError("t_route_mc_baseline_build_manifest_invalid")
    for audit in route.get("netcdf_audits") or []:
        if audit.get("source_id") == SOURCE_ID:
            if audit.get("admitted_as_public_invariant_fixture") is not True:
                raise ValueError("t_route_mc_baseline_fixture_not_admitted")
            return audit["artifact"]
    raise ValueError("t_route_mc_baseline_fixture_missing")


def _read_verified(descriptor: Mapping[str, Any]) -> tuple[Path, bytes]:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("t_route_mc_baseline_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("t_route_mc_baseline_artifact_identity_mismatch")
    return path, body


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


def main() -> int:
    args = parse_args()
    report = compile_baseline(
        route_link_manifest_path=args.route_link_manifest,
        source_manifest_path=args.source_manifest,
        build_manifest_path=args.build_manifest,
    )
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
