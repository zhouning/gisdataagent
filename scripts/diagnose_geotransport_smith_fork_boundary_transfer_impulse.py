#!/usr/bin/env python3
"""Compile an outcome-free Smith Fork-to-outlet impulse response diagnostic."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    ObservedInternalBoundaryReplacement,
    StockState,
    analyze_dynamic_transfer_response,
)

if __package__:
    from scripts import run_geotransport_center_hill_dynamic_internal_boundary as dynamic
else:
    import run_geotransport_center_hill_dynamic_internal_boundary as dynamic


REPO_ROOT = dynamic.REPO_ROOT
DEFAULT_DYNAMIC_REPORT = dynamic.DEFAULT_REPORT
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "smith_fork_boundary_transfer_impulse_v2_report.json"
)
SCHEMA = "gwm.geotransport.smith_fork_boundary_transfer_impulse.v2"
HOUR_COUNT = 240
PULSE_RATE_M3S = 1.0
RESPONSE_THRESHOLD_M3S = 1e-6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dynamic-report", type=Path, default=DEFAULT_DYNAMIC_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_diagnostic(*, dynamic_report_path: Path) -> dict[str, Any]:
    downstream_body, downstream = dynamic._load(dynamic_report_path)
    if (
        downstream.get("schema") != dynamic.SCHEMA
        or downstream.get("status")
        != "dynamic_internal_boundary_development_diagnostic_complete"
    ):
        raise ValueError("boundary_impulse_dynamic_report_invalid")
    topology = dynamic._load_descriptor_json(
        downstream["source_artifacts"]["topology_report"]
    )
    development = dynamic._load_descriptor_json(
        downstream["source_artifacts"]["development_input_report"]
    )
    network_body = dynamic._read_verified(topology["artifacts"]["full_subnetwork"])
    original_network = dynamic.parent._network(json.loads(network_body)["network"])
    route_link_body = dynamic._read_verified(topology["artifacts"]["route_link_subset"])
    route_link_path = REPO_ROOT / topology["artifacts"]["route_link_subset"]["path"]
    geometry = dynamic.parent._geometry(
        route_link_path, original_network, route_link_body
    )
    fraction = float(downstream["domain_compilation"]["downstream_fraction"])
    cut_length = float(downstream["domain_compilation"]["cut_effective_length_m"])
    gauge_index = original_network.feature_ids.index(dynamic.parent.INTERIOR_FEATURE_ID)
    lengths = list(original_network.effective_lengths_m)
    lengths[gauge_index] = cut_length
    cut_network = replace(
        original_network,
        network_id=f"{original_network.network_id}:smith-fork-unit-impulse",
        effective_lengths_m=tuple(lengths),
        provenance_id=(
            f"{original_network.provenance_id}|outcome-free-unit-impulse"
        ),
        evidence_level="candidate",
        admitted=False,
    )
    arrays = {
        name: dynamic.parent._read_npy(descriptor)
        for name, descriptor in development["decoded_arrays"].items()
    }
    feature_ids = tuple(int(value) for value in arrays["feature_ids"])
    initial_storage = np.asarray(arrays["initial_storage_m3"], dtype=float).copy()
    initial_velocity = np.asarray(
        arrays["initial_velocity_ms"], dtype=float
    )
    if feature_ids != cut_network.feature_ids:
        raise ValueError("boundary_impulse_feature_axis_invalid")
    initial_storage[gauge_index] *= fraction
    base_state = StockState(
        values=tuple(float(value) for value in initial_storage),
        unit="m3",
        provenance_id="smith-fork-impulse-common-initial-state",
    )
    pulse_state = base_state
    transport = BranchingManningNetworkTransportOperator(
        cut_network,
        BranchingNetworkTransportConfig(
            timestep_seconds=3600.0,
            integration_substep_seconds=300.0,
            operator_form_admitted=True,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    )
    base_outlet = []
    pulse_outlet = []
    base_mass_ratios = []
    pulse_mass_ratios = []
    for hour in range(HOUR_COUNT):
        zero = _boundary(0.0, hour)
        pulse = _boundary(PULSE_RATE_M3S if hour == 0 else 0.0, hour)
        base_result = transport.step(
            base_state, geometry, internal_boundary=zero
        )
        pulse_result = transport.step(
            pulse_state, geometry, internal_boundary=pulse
        )
        base_state = base_result.next_stock
        pulse_state = pulse_result.next_stock
        base_outlet.append(base_result.outlet_mean_flow_m3s)
        pulse_outlet.append(pulse_result.outlet_mean_flow_m3s)
        base_mass_ratios.append(
            abs(base_result.global_mass_balance_residual_m3)
            / base_result.numeric_mass_tolerance_m3
        )
        pulse_mass_ratios.append(
            abs(pulse_result.global_mass_balance_residual_m3)
            / pulse_result.numeric_mass_tolerance_m3
        )

    response = np.asarray(pulse_outlet) - np.asarray(base_outlet)
    input_volume = PULSE_RATE_M3S * 3600.0
    final_storage_difference = float(
        np.asarray(pulse_state.values).sum() - np.asarray(base_state.values).sum()
    )
    response_metrics = analyze_dynamic_transfer_response(
        response,
        timestep_seconds=3600.0,
        input_volume_m3=input_volume,
        final_incremental_storage_m3=final_storage_difference,
        response_threshold_m3s=RESPONSE_THRESHOLD_M3S,
    )
    response_record = response_metrics.as_dict()
    peak_index = int(np.argmax(response))
    first_arrival_seconds = response_metrics.first_arrival_above_threshold_seconds
    first_arrival = (
        None
        if first_arrival_seconds is None
        else int(round(first_arrival_seconds / 3600.0))
    )
    recovered = response_metrics.net_outlet_volume_m3
    impulse_residual = response_metrics.mass_balance_residual_m3

    path_ids = _downstream_path(cut_network)
    index = {feature_id: value for value, feature_id in enumerate(feature_ids)}
    path_lengths = np.asarray(
        [cut_network.effective_lengths_m[index[value]] for value in path_ids],
        dtype=float,
    )
    path_velocity = np.asarray(
        [initial_velocity[index[value]] for value in path_ids], dtype=float
    )
    if bool((path_velocity <= 0.0).any()):
        raise ValueError("boundary_impulse_path_velocity_must_be_positive")
    velocity_prior_hours = float(np.sum(path_lengths / path_velocity) / 3600.0)
    center_seconds = response_metrics.center_of_positive_response_seconds
    center_hours = (
        None if center_seconds is None else center_seconds / 3600.0
    )
    input_quantiles = dict(response_metrics.input_recovery_quantile_seconds)
    certification_gates = {
        "base_solver_conservation": max(base_mass_ratios) <= 1.0,
        "pulse_solver_conservation": max(pulse_mass_ratios) <= 1.0,
        "differenced_mass_identity": response_metrics.mass_balance_passed,
        "negative_response_lobe_within_tolerance": (
            response_metrics.negative_lobe_within_tolerance
        ),
        "input_t95_recovered_inside_window": input_quantiles["t95"] is not None,
        "outcome_isolation": True,
    }
    certification_gates["all_outcome_free_response_gates_passed"] = all(
        certification_gates.values()
    )
    return {
        "schema": SCHEMA,
        "status": "outcome_free_boundary_transfer_impulse_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_artifacts": {
            "dynamic_internal_boundary_report": _artifact(
                dynamic_report_path, downstream_body
            ),
            "topology_report": downstream["source_artifacts"]["topology_report"],
            "development_input_report": downstream["source_artifacts"][
                "development_input_report"
            ],
            "route_link_subset": topology["artifacts"]["route_link_subset"],
        },
        "path": {
            "boundary_feature_id": dynamic.parent.INTERIOR_FEATURE_ID,
            "outlet_feature_id": cut_network.outlet_feature_id,
            "feature_count": len(path_ids),
            "feature_ids": list(path_ids),
            "effective_length_m": float(path_lengths.sum()),
            "nwm_initial_velocity_travel_time_prior_hours": velocity_prior_hours,
        },
        "impulse": {
            "rate_m3s": PULSE_RATE_M3S,
            "duration_seconds": 3600,
            "input_volume_m3": input_volume,
            "simulation_hours": HOUR_COUNT,
            "first_arrival_above_threshold_hour": first_arrival,
            "response_threshold_m3s": RESPONSE_THRESHOLD_M3S,
            "peak_response_hour": peak_index + 1,
            "peak_outlet_increment_m3s": float(response[peak_index]),
            "response_center_of_mass_hour_within_window": center_hours,
            "outlet_recovered_volume_m3": recovered,
            "final_incremental_storage_m3": final_storage_difference,
            "recovered_fraction": response_metrics.net_recovered_fraction,
            "differenced_mass_residual_m3": impulse_residual,
        },
        "dynamic_transfer_response": response_record,
        "certification_gates": certification_gates,
        "conservation": {
            "base_maximum_residual_to_tolerance_ratio": max(base_mass_ratios),
            "pulse_maximum_residual_to_tolerance_ratio": max(pulse_mass_ratios),
            "differenced_mass_residual_absolute_m3": abs(impulse_residual),
            "passed": (
                max(base_mass_ratios) <= 1.0
                and max(pulse_mass_ratios) <= 1.0
                and response_metrics.mass_balance_passed
            ),
        },
        "data_isolation": {
            "observed_outlet_discharge_used": False,
            "observed_smith_fork_discharge_used": False,
            "target_fitted_parameters": 0,
            "synthetic_unit_boundary_only": True,
        },
        "claim_boundary": {
            "outcome_free_transfer_diagnostic_executed": True,
            "volume_response_metrics_certified": certification_gates[
                "all_outcome_free_response_gates_passed"
            ],
            "linear_reference_admitted": False,
            "transfer_dynamics_validated": False,
            "forecast_closure_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _boundary(value: float, hour: int) -> ObservedInternalBoundaryReplacement:
    return ObservedInternalBoundaryReplacement(
        feature_ids=(dynamic.parent.INTERIOR_FEATURE_ID,),
        values=(value,),
        unit="m3 s-1",
        provenance_id=f"synthetic-unit-impulse:hour={hour}:value={value}",
        evidence_level="candidate",
        admitted=False,
        archive_revised=False,
        operational_vintage_verified=False,
    )


def _downstream_path(network: Any) -> tuple[int, ...]:
    downstream = dict(
        zip(network.feature_ids, network.downstream_feature_ids, strict=True)
    )
    path = [dynamic.parent.INTERIOR_FEATURE_ID]
    while path[-1] != network.outlet_feature_id:
        next_feature = downstream[path[-1]]
        if next_feature is None or next_feature in path:
            raise ValueError("boundary_impulse_downstream_path_invalid")
        path.append(next_feature)
    return tuple(path)


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
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
        raise ValueError("boundary_impulse_report_refuses_overwrite")
    report = compile_diagnostic(dynamic_report_path=args.dynamic_report)
    if not report["certification_gates"][
        "all_outcome_free_response_gates_passed"
    ]:
        raise RuntimeError("boundary_impulse_response_certification_failed")
    body = _json_body(report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(body)
    print(args.report)
    print(hashlib.sha256(body).hexdigest())
    print(
        "velocity_prior_hours="
        f"{report['path']['nwm_initial_velocity_travel_time_prior_hours']:.6f}"
    )
    print(
        "impulse_peak_hour="
        f"{report['impulse']['peak_response_hour']}"
    )
    print(
        "recovered_fraction="
        f"{report['impulse']['recovered_fraction']:.9f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
