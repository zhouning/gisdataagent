#!/usr/bin/env python3
"""Run outcome-free Kernel v2 invariants on an official RouteLink fixture."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import h5py
import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    ForcingFlux,
    LinearReferencedPath,
    NONLINEAR_REACH_TRANSPORT_OPERATOR_SCHEMA,
    NonlinearManningReachTransportOperator,
    NonlinearReachTransportConfig,
    ReachHydraulicGeometry,
    StockState,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTE_LINK_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/route_link_public_audit/acquisition_manifest.json"
)
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/kernel_v2_nonlinear_manning_invariant_report.json"
)
SCHEMA = "gwm.geotransport.kernel_v2_nonlinear_manning_invariants.v1"
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
TIMESTEP_SECONDS = 3600.0
ACTION_ROLLOUT_HOURS = 120
ACTION_PULSE_HOURS = 6
FORCING_ROLLOUT_HOURS = 48
FORCING_PULSE_HOURS = 12
LOW_FLOW_ROLLOUT_HOURS = 48
DIRECTION_RELATIVE_L1_MINIMUM = 0.005
HOMOGENEOUS_RELATIVE_L1_MAXIMUM = 1e-8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--route-link-manifest", type=Path, default=DEFAULT_ROUTE_LINK_MANIFEST
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_invariants(
    *, route_link_manifest_path: Path = DEFAULT_ROUTE_LINK_MANIFEST
) -> dict[str, Any]:
    manifest_body = route_link_manifest_path.read_bytes()
    manifest = json.loads(manifest_body)
    route_link_descriptor = _validate_manifest_and_select_fixture(manifest)
    route_link_path = REPO_ROOT / str(route_link_descriptor["path"])
    route_link_body = _read_verified(route_link_descriptor)
    rows = _route_link_rows(route_link_path)
    selected = [rows[feature_id] for feature_id in FEATURE_PATH]
    for upstream, downstream in zip(selected[:-1], selected[1:], strict=True):
        if int(upstream["to"]) != int(downstream["link"]):
            raise ValueError("kernel_v2_fixture_path_topology_mismatch")

    path, geometry = _path_and_geometry(selected, reverse=False)
    reverse_path, reverse_geometry = _path_and_geometry(selected, reverse=True)
    config = NonlinearReachTransportConfig(
        timestep_seconds=TIMESTEP_SECONDS,
        path_admitted=True,
        operator_form_admitted=False,
        allow_unadmitted_components_for_diagnostics=True,
        integration_substep_seconds=300.0,
    )
    forward = NonlinearManningReachTransportOperator(path, config)
    reverse = NonlinearManningReachTransportOperator(reverse_path, config)

    zero = _rollout(
        forward,
        geometry,
        hours=ACTION_ROLLOUT_HOURS,
        action_rate=lambda _hour: 0.0,
        forcing_rate=lambda _hour, _count: np.zeros(_count, dtype=float),
        provenance="official_fixture:zero_action_zero_forcing",
    )
    action = _rollout(
        forward,
        geometry,
        hours=ACTION_ROLLOUT_HOURS,
        action_rate=lambda hour: 20.0 if hour < ACTION_PULSE_HOURS else 0.0,
        forcing_rate=lambda _hour, count: np.zeros(count, dtype=float),
        provenance="official_fixture:action_pulse_recession",
    )
    reversed_action = _rollout(
        reverse,
        reverse_geometry,
        hours=ACTION_ROLLOUT_HOURS,
        action_rate=lambda hour: 20.0 if hour < ACTION_PULSE_HOURS else 0.0,
        forcing_rate=lambda _hour, count: np.zeros(count, dtype=float),
        provenance="official_fixture:reversed_action_pulse_recession",
    )
    forcing = _rollout(
        forward,
        geometry,
        hours=FORCING_ROLLOUT_HOURS,
        action_rate=lambda _hour: 0.0,
        forcing_rate=lambda hour, count: (
            np.linspace(0.01, 0.09, count)
            if hour < FORCING_PULSE_HOURS
            else np.zeros(count, dtype=float)
        ),
        provenance="official_fixture:lateral_forcing_recession",
    )
    low_flow = _rollout(
        forward,
        geometry,
        hours=LOW_FLOW_ROLLOUT_HOURS,
        action_rate=lambda hour: 1e-6 if hour == 0 else 0.0,
        forcing_rate=lambda _hour, count: np.zeros(count, dtype=float),
        provenance="official_fixture:low_flow_recession",
    )

    direction = _series_difference(
        action["outlet_mean_flow_m3s"],
        reversed_action["outlet_mean_flow_m3s"],
    )
    homogeneous = _homogeneous_direction_control(config)
    gates = {
        "zero_state_invariant": (
            zero["final_storage_m3"] == 0.0
            and zero["cumulative_outlet_volume_m3"] == 0.0
            and zero["horizon_mass_balance_residual_m3"] == 0.0
        ),
        "action_rollout_conservative": action["conservation_passed"],
        "reversed_rollout_conservative": reversed_action["conservation_passed"],
        "forcing_rollout_conservative": forcing["conservation_passed"],
        "low_flow_rollout_conservative": low_flow["conservation_passed"],
        "long_recession_completed_without_cleanup": (
            action["completed_hour_count"] == ACTION_ROLLOUT_HOURS
            and action["componentwise_cleanup_applied"] is False
        ),
        "heterogeneous_direction_noncommutative": (
            direction["relative_l1_difference"]
            >= DIRECTION_RELATIVE_L1_MINIMUM
        ),
        "homogeneous_control_does_not_invent_direction": (
            homogeneous["relative_l1_difference"]
            <= HOMOGENEOUS_RELATIVE_L1_MAXIMUM
        ),
        "outcome_isolation": True,
    }
    gates["all_invariants_passed"] = all(gates.values())
    if not gates["all_invariants_passed"]:
        failed = sorted(name for name, passed in gates.items() if not passed)
        raise RuntimeError(
            "kernel_v2_nonlinear_manning_invariant_gate_failed:"
            + ",".join(failed)
            + f":direction_relative_l1={direction['relative_l1_difference']:.12g}"
        )

    return {
        "schema": SCHEMA,
        "status": "pass",
        "operator_schema": NONLINEAR_REACH_TRANSPORT_OPERATOR_SCHEMA,
        "operator_identity": (
            "nonlinear Manning reach-storage research operator; not "
            "Muskingum-Cunge or a hydrodynamic solver"
        ),
        "source_artifacts": {
            "route_link_manifest": _artifact(
                route_link_manifest_path, manifest_body
            ),
            "route_link_fixture": _artifact(route_link_path, route_link_body),
        },
        "data_isolation": {
            "outcome_values_loaded": False,
            "action_observations_loaded": False,
            "forcing_observations_loaded": False,
            "inputs": ["official_route_link_parameters", "synthetic_flux_probes"],
        },
        "fixture": {
            "source_id": SOURCE_ID,
            "feature_ids": list(FEATURE_PATH),
            "feature_count": len(FEATURE_PATH),
            "topology_consecutive": True,
            "full_reaches_only": True,
            "geometry_evidence_level": geometry.evidence_level,
            "channel_side_slope_compilation": (
                "horizontal_per_vertical=1/RouteLink_ChSlp, matching the "
                "fixed t-route kernel's z=1/cs geometry"
            ),
            "geometry_admitted_for_exact_fixture_features": (
                geometry.admitted_as_hydraulic_geometry
            ),
            "center_hill_parameter_fixture": False,
        },
        "registered_thresholds": {
            "heterogeneous_direction_relative_l1_minimum": (
                DIRECTION_RELATIVE_L1_MINIMUM
            ),
            "homogeneous_control_relative_l1_maximum": (
                HOMOGENEOUS_RELATIVE_L1_MAXIMUM
            ),
        },
        "rollouts": {
            "zero_action_zero_forcing": zero,
            "action_pulse_recession": action,
            "reversed_action_pulse_recession": reversed_action,
            "lateral_forcing_recession": forcing,
            "low_flow_recession": low_flow,
        },
        "direction_diagnostics": {
            "heterogeneous_official_fixture": direction,
            "homogeneous_synthetic_control": homogeneous,
        },
        "gates": gates,
        "claim_boundary": {
            "operator_invariants_passed": True,
            "operator_can_express_noncommutative_direction": True,
            "authoritative_real_world_direction_validated": False,
            "center_hill_parameters_available": False,
            "center_hill_execution_admitted": False,
            "muskingum_cunge_implemented": False,
            "hydrodynamically_validated": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _rollout(
    operator: NonlinearManningReachTransportOperator,
    geometry: ReachHydraulicGeometry,
    *,
    hours: int,
    action_rate: Callable[[int], float],
    forcing_rate: Callable[[int, int], np.ndarray],
    provenance: str,
) -> dict[str, Any]:
    count = len(operator.active_feature_ids)
    state = operator.zero_state(provenance_id=f"{provenance}:zero_state")
    initial_storage = float(sum(state.values))
    cumulative_input = 0.0
    cumulative_outlet = 0.0
    outlet_flows: list[float] = []
    step_residuals: list[float] = []
    step_tolerances: list[float] = []
    maximum_storage = 0.0
    maximum_depth = 0.0
    for hour in range(hours):
        action_value = float(action_rate(hour))
        forcing_values = np.asarray(forcing_rate(hour, count), dtype=float)
        if forcing_values.shape != (count,):
            raise ValueError("kernel_v2_invariant_forcing_shape_mismatch")
        action = (
            ActionBoundaryFlux(
                (action_value,) + (0.0,) * (count - 1),
                "m3 s-1",
                f"{provenance}:action:{hour}",
            )
            if action_value != 0.0
            else None
        )
        forcing = (
            ForcingFlux(
                tuple(float(value) for value in forcing_values),
                "m3 s-1",
                f"{provenance}:forcing:{hour}",
                modeled=True,
            )
            if bool((forcing_values != 0.0).any())
            else None
        )
        result = operator.step(
            state,
            geometry,
            action=action,
            forcing=forcing,
        )
        cumulative_input += result.input_volume_m3
        cumulative_outlet += result.outlet_volume_m3
        outlet_flows.append(result.outlet_mean_flow_m3s)
        step_residuals.append(result.global_mass_balance_residual_m3)
        step_tolerances.append(result.numeric_mass_tolerance_m3)
        maximum_storage = max(maximum_storage, float(sum(result.next_stock.values)))
        maximum_depth = max(maximum_depth, max(result.reach_end_depth_m))
        state = result.next_stock
    final_storage = float(sum(state.values))
    horizon_residual = (
        final_storage + cumulative_outlet - initial_storage - cumulative_input
    )
    horizon_tolerance = float(sum(step_tolerances))
    return {
        "registered_hour_count": hours,
        "completed_hour_count": len(outlet_flows),
        "initial_storage_m3": initial_storage,
        "cumulative_input_volume_m3": cumulative_input,
        "cumulative_outlet_volume_m3": cumulative_outlet,
        "final_storage_m3": final_storage,
        "maximum_storage_m3": maximum_storage,
        "maximum_depth_m": maximum_depth,
        "maximum_absolute_step_mass_balance_residual_m3": max(
            abs(value) for value in step_residuals
        ),
        "horizon_mass_balance_residual_m3": horizon_residual,
        "horizon_numeric_tolerance_m3": horizon_tolerance,
        "conservation_passed": (
            all(
                abs(residual) <= tolerance
                for residual, tolerance in zip(
                    step_residuals, step_tolerances, strict=True
                )
            )
            and abs(horizon_residual) <= horizon_tolerance
        ),
        "minimum_outlet_mean_flow_m3s": min(outlet_flows),
        "maximum_outlet_mean_flow_m3s": max(outlet_flows),
        "outlet_mean_flow_m3s": outlet_flows,
        "componentwise_cleanup_applied": False,
    }


def _series_difference(
    forward: list[float], reverse: list[float]
) -> dict[str, float | int]:
    forward_array = np.asarray(forward, dtype=float)
    reverse_array = np.asarray(reverse, dtype=float)
    absolute = np.abs(forward_array - reverse_array)
    denominator = max(float(np.abs(forward_array).sum()), np.finfo(float).tiny)
    return {
        "sample_count": int(forward_array.size),
        "absolute_l1_difference_m3s": float(absolute.sum()),
        "relative_l1_difference": float(absolute.sum() / denominator),
        "maximum_absolute_difference_m3s": float(absolute.max()),
        "forward_peak_hour_zero_based": int(np.argmax(forward_array)),
        "reverse_peak_hour_zero_based": int(np.argmax(reverse_array)),
        "forward_peak_m3s": float(forward_array.max()),
        "reverse_peak_m3s": float(reverse_array.max()),
    }


def _homogeneous_direction_control(
    config: NonlinearReachTransportConfig,
) -> dict[str, float | int]:
    ids = (9001, 9002, 9003)
    reverse_ids = tuple(reversed(ids))
    path = LinearReferencedPath(
        "homogeneous:forward",
        ids,
        (1000.0,) * 3,
        (0.0,) * 3,
        (1000.0,) * 3,
        "synthetic:homogeneous:forward",
        "derived",
    )
    reverse_path = LinearReferencedPath(
        "homogeneous:reverse",
        reverse_ids,
        (1000.0,) * 3,
        (0.0,) * 3,
        (1000.0,) * 3,
        "synthetic:homogeneous:reverse",
        "derived",
    )
    geometry = ReachHydraulicGeometry(
        ids,
        (10.0,) * 3,
        (1.0,) * 3,
        (0.001,) * 3,
        (0.05,) * 3,
        "synthetic:homogeneous",
        "derived",
        True,
    )
    reverse_geometry = ReachHydraulicGeometry(
        reverse_ids,
        (10.0,) * 3,
        (1.0,) * 3,
        (0.001,) * 3,
        (0.05,) * 3,
        "synthetic:homogeneous:reverse",
        "derived",
        True,
    )
    forward = _rollout(
        NonlinearManningReachTransportOperator(path, config),
        geometry,
        hours=48,
        action_rate=lambda hour: 5.0 if hour < 3 else 0.0,
        forcing_rate=lambda _hour, count: np.zeros(count, dtype=float),
        provenance="homogeneous:forward",
    )
    reverse = _rollout(
        NonlinearManningReachTransportOperator(reverse_path, config),
        reverse_geometry,
        hours=48,
        action_rate=lambda hour: 5.0 if hour < 3 else 0.0,
        forcing_rate=lambda _hour, count: np.zeros(count, dtype=float),
        provenance="homogeneous:reverse",
    )
    return _series_difference(
        forward["outlet_mean_flow_m3s"], reverse["outlet_mean_flow_m3s"]
    )


def _path_and_geometry(
    selected: list[dict[str, float | int]], *, reverse: bool
) -> tuple[LinearReferencedPath, ReachHydraulicGeometry]:
    rows = list(reversed(selected)) if reverse else selected
    ids = tuple(int(row["link"]) for row in rows)
    lengths = tuple(float(row["Length"]) for row in rows)
    suffix = "reverse" if reverse else "forward"
    path = LinearReferencedPath(
        f"hurricane-laura-fixture:{suffix}",
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


def _route_link_rows(path: Path) -> dict[int, dict[str, float | int]]:
    names = ("link", "to", "Length", "BtmWdth", "ChSlp", "So", "n")
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


def _validate_manifest_and_select_fixture(
    manifest: Mapping[str, Any],
) -> Mapping[str, Any]:
    if (
        manifest.get("schema") != "gwm.geotransport.public_route_link_audit.v1"
        or manifest.get("mode") != "values"
        or (manifest.get("adjudication") or {}).get(
            "regional_real_parameter_fixtures_acquired"
        )
        is not True
        or (manifest.get("adjudication") or {}).get(
            "center_hill_route_link_parameters_available"
        )
        is not False
    ):
        raise ValueError("kernel_v2_route_link_manifest_invalid")
    for audit in manifest.get("netcdf_audits") or []:
        if audit.get("source_id") == SOURCE_ID:
            if (
                audit.get("all_required_muskingum_cunge_fields_present") is not True
                or audit.get("admitted_as_public_invariant_fixture") is not True
                or audit.get("admitted_as_center_hill_parameters") is not False
            ):
                raise ValueError("kernel_v2_route_link_fixture_not_admitted")
            return audit["artifact"]
    raise ValueError("kernel_v2_route_link_fixture_missing")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("kernel_v2_invariant_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("kernel_v2_invariant_artifact_identity_mismatch")
    return body


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": _display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def main() -> int:
    args = parse_args()
    report = compile_invariants(route_link_manifest_path=args.route_link_manifest)
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
