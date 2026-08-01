#!/usr/bin/env python3
"""Compile outcome-independent physical uncertainty profiles for two real systems."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import netcdf_file

from data_agent.uwm.geospatial_kernel_v2 import (
    ActionBoundaryFlux,
    BranchingManningNetworkTransportOperator,
    BranchingNetworkTransportConfig,
    ForcingFlux,
    ReachForcingSupport,
    StockState,
)
from data_agent.uwm.geospatial_kernel_v2.physical_uncertainty_profile import (
    FeatureAlignedPhysicalUncertaintyProfile,
    PhysicalUncertaintySource,
)

if __package__:
    from scripts.run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )
else:
    from run_geotransport_center_hill_v2_d5_full_subnetwork_outcome_free import (
        _geometry,
        _network,
        _read_npy,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIOR_INPUT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geotransport_v2_blind_validation_inputs_report.json"
)
DEFAULT_EVALUATION_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_protocol.json"
)
DEFAULT_EVALUATION_STATIC_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_horizon_assimilation_holdout_static_inputs_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_external_physical_uncertainty_profiles.json"
)

SCHEMA = "gwm.geospatial_kernel.external_physical_uncertainty_profiles.v1"
PRIOR_INPUT_SCHEMA = "gwm.geotransport.v2_blind_validation_inputs.v1"
EVALUATION_PROTOCOL_SCHEMA = (
    "gwm.geotransport.horizon_assimilation_holdout_protocol.v1"
)
EVALUATION_STATIC_SCHEMA = (
    "gwm.geotransport.horizon_assimilation_holdout_static_inputs.v1"
)
SYSTEM_IDS = ("center_hill", "j_percy_priest")
TIMESTEP_SECONDS = 3600.0
SUBSTEP_SECONDS = 300.0
STORAGE_NUMERICAL_FLOOR_M3 = 1.0
FORCING_NUMERICAL_FLOOR_M3S = 0.01
FORCING_CHANGE_QUANTILE = 0.90


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prior-input-report", type=Path, default=DEFAULT_PRIOR_INPUT_REPORT
    )
    parser.add_argument(
        "--evaluation-protocol", type=Path, default=DEFAULT_EVALUATION_PROTOCOL
    )
    parser.add_argument(
        "--evaluation-static-report",
        type=Path,
        default=DEFAULT_EVALUATION_STATIC_REPORT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_external_uncertainty_profiles(
    *,
    prior_input_report_path: Path = DEFAULT_PRIOR_INPUT_REPORT,
    evaluation_protocol_path: Path = DEFAULT_EVALUATION_PROTOCOL,
    evaluation_static_report_path: Path = DEFAULT_EVALUATION_STATIC_REPORT,
) -> dict[str, Any]:
    """Compile diagnostic amplitudes without loading evaluation outcomes."""

    prior_body = prior_input_report_path.read_bytes()
    prior = json.loads(prior_body)
    protocol_body = evaluation_protocol_path.read_bytes()
    protocol = json.loads(protocol_body)
    static_body = evaluation_static_report_path.read_bytes()
    static = json.loads(static_body)
    _validate_reports(prior=prior, protocol=protocol, static=static)

    prior_start = _parse_time(prior["window"]["initial_state_valid_at"])
    prior_hour_count = int(prior["window"]["hour_count"])
    evaluation_reference = _parse_time(
        protocol["window"]["initial_state_valid_at_utc"]
    )
    evaluation_start = _parse_time(protocol["window"]["start_inclusive_utc"])
    evidence_end = _parse_time(prior["window"]["end_exclusive"])
    if (
        prior_start + timedelta(hours=prior_hour_count) != evaluation_reference
        or evidence_end != evaluation_start
        or evaluation_start - evaluation_reference != timedelta(hours=1)
    ):
        raise ValueError("external_uncertainty_profile_window_continuity_invalid")

    systems: dict[str, Any] = {}
    for system_id in SYSTEM_IDS:
        systems[system_id] = _compile_system(
            system_id=system_id,
            lock=protocol["systems"][system_id],
            prior_inputs=prior["systems"][system_id],
            evaluation_inputs=static["systems"][system_id],
            prior_start=prior_start,
            evidence_end=evidence_end,
            evaluation_start=evaluation_start,
            hour_count=prior_hour_count,
        )

    all_gates_passed = all(
        system["execution_gates"]["all_passed"] for system in systems.values()
    )
    if not all_gates_passed:
        failed = {
            system_id: [
                name
                for name, passed in system["execution_gates"].items()
                if name != "all_passed" and not passed
            ]
            for system_id, system in systems.items()
            if not system["execution_gates"]["all_passed"]
        }
        raise RuntimeError(
            f"external_uncertainty_profile_execution_gate_failed:{failed}"
        )
    return {
        "schema": SCHEMA,
        "status": "outcome_independent_feature_profiles_compiled",
        "method": {
            "initial_storage": {
                "semantic_role": "model_closure_discrepancy",
                "formula": "abs(propagated-reference)/(abs(propagated)+abs(reference)+2*floor)",
                "numerical_floor_m3": STORAGE_NUMERICAL_FLOOR_M3,
            },
            "manning_n": {
                "semantic_role": "hydraulic_structural_contrast",
                "formula": "abs(nCC-n)/(abs(nCC)+abs(n))",
            },
            "modeled_forcing": {
                "semantic_role": "forcing_change_proxy",
                "formula": "q90_hourly_abs_change/(abs(previous)+abs(current)+2*floor)",
                "quantile": FORCING_CHANGE_QUANTILE,
                "numerical_floor_m3s": FORCING_NUMERICAL_FLOOR_M3S,
            },
            "timestep_seconds": TIMESTEP_SECONDS,
            "integration_substep_seconds": SUBSTEP_SECONDS,
            "evaluation_window_start_utc": _iso(evaluation_start),
            "evidence_window_end_utc": _iso(evidence_end),
        },
        "input_artifacts": {
            "prior_outcome_free_input_report": _artifact(
                prior_input_report_path, prior_body
            ),
            "evaluation_protocol": _artifact(
                evaluation_protocol_path, protocol_body
            ),
            "evaluation_static_input_report": _artifact(
                evaluation_static_report_path, static_body
            ),
        },
        "systems": systems,
        "execution_gates": {
            "system_count": len(systems),
            "all_system_gates_passed": all_gates_passed,
        },
        "data_isolation": {
            "outcome_path_argument_accepted": False,
            "future_target_argument_accepted": False,
            "score_or_loss_argument_accepted": False,
            "evaluation_outcome_loaded": False,
            "evaluation_score_loaded": False,
            "issue_observation_loaded": False,
            "prior_modeled_inputs_loaded": True,
            "evaluation_initial_modeled_state_loaded": True,
        },
        "claim_boundary": {
            "feature_aligned_physical_amplitudes_compiled": True,
            "amplitudes_outcome_independent": True,
            "amplitudes_calibrated_as_forecast_error": False,
            "probabilistic_coverage_validated": False,
            "candidate_admitted": False,
            "runtime_default_enabled": False,
            "forecast_skill_evidence_produced": False,
            "geospatial_kernel_validated": False,
            "superiority_claim_supported": False,
        },
    }


def _compile_system(
    *,
    system_id: str,
    lock: Mapping[str, Any],
    prior_inputs: Mapping[str, Any],
    evaluation_inputs: Mapping[str, Any],
    prior_start: datetime,
    evidence_end: datetime,
    evaluation_start: datetime,
    hour_count: int,
) -> dict[str, Any]:
    if (
        prior_inputs.get("topology_report") != lock.get("topology_report")
        or evaluation_inputs.get("topology_report", lock.get("topology_report"))
        != lock.get("topology_report")
    ):
        raise ValueError(f"external_uncertainty_{system_id}_topology_identity_mismatch")
    topology_body = _read_verified(lock["topology_report"])
    topology = json.loads(topology_body)
    network_payload = json.loads(
        _read_verified(topology["artifacts"]["full_subnetwork"])
    )
    network = _network(network_payload["network"])
    if (
        len(network.feature_ids) != int(lock["feature_count"])
        or network.outlet_feature_id != int(lock["outlet_feature_id"])
        or network.action_entry_feature_ids != (int(lock["action_entry_feature_id"]),)
    ):
        raise ValueError(f"external_uncertainty_{system_id}_network_lock_mismatch")

    prior_arrays = {
        name: _read_npy(descriptor)
        for name, descriptor in prior_inputs["decoded_arrays"].items()
    }
    evaluation_arrays = {
        name: _read_npy(descriptor)
        for name, descriptor in evaluation_inputs["decoded_arrays"].items()
    }
    feature_ids = tuple(int(value) for value in prior_arrays["feature_ids"])
    evaluation_feature_ids = tuple(
        int(value) for value in evaluation_arrays["feature_ids"]
    )
    prior_initial = np.asarray(prior_arrays["initial_storage_m3"], dtype=float)
    evaluation_initial = np.asarray(
        evaluation_arrays["initial_storage_m3"], dtype=float
    )
    q_lateral = np.asarray(prior_arrays["q_lateral_m3s"], dtype=float)
    timestamps = tuple(str(value) for value in prior_arrays["forcing_timestamps_utc"])
    expected_timestamps = tuple(
        _iso(prior_start + timedelta(hours=index + 1))
        for index in range(hour_count)
    )
    if (
        feature_ids != network.feature_ids
        or evaluation_feature_ids != feature_ids
        or prior_initial.shape != (len(feature_ids),)
        or evaluation_initial.shape != (len(feature_ids),)
        or q_lateral.shape != (hour_count, len(feature_ids))
        or timestamps != expected_timestamps
    ):
        raise ValueError(f"external_uncertainty_{system_id}_dynamic_axis_mismatch")

    route_link = topology["artifacts"]["route_link_subset"]
    route_link_body = _read_verified(route_link)
    route_link_path = REPO_ROOT / route_link["path"]
    geometry = _geometry(route_link_path, network, route_link_body)
    channel_n, compound_n = _read_roughness_pair(route_link_path, feature_ids)
    forcing_support = _forcing_support(
        system_id=system_id,
        lock=lock,
        feature_ids=feature_ids,
        outlet_feature_id=network.outlet_feature_id,
    )
    actions = _parse_ordered_actions(
        _read_verified(prior_inputs["action_values"]),
        expected_count=hour_count,
    )
    propagated, mass_ratios = _propagate_prior_state(
        system_id=system_id,
        network=network,
        geometry=geometry,
        forcing_support=forcing_support,
        initial_storage=prior_initial,
        q_lateral=q_lateral,
        actions=actions,
    )

    storage_fraction = np.abs(propagated - evaluation_initial) / (
        np.abs(propagated)
        + np.abs(evaluation_initial)
        + 2.0 * STORAGE_NUMERICAL_FLOOR_M3
    )
    manning_fraction = np.abs(compound_n - channel_n) / (
        np.abs(compound_n) + np.abs(channel_n)
    )
    forcing_change = np.abs(q_lateral[1:] - q_lateral[:-1]) / (
        np.abs(q_lateral[1:])
        + np.abs(q_lateral[:-1])
        + 2.0 * FORCING_NUMERICAL_FLOOR_M3S
    )
    forcing_fraction = np.quantile(
        forcing_change, FORCING_CHANGE_QUANTILE, axis=0
    )
    profile = FeatureAlignedPhysicalUncertaintyProfile(
        profile_id=f"external-physical-diagnostic:{system_id}",
        feature_ids=feature_ids,
        initial_storage_fraction_by_feature=tuple(storage_fraction),
        manning_n_fraction_by_feature=tuple(manning_fraction),
        modeled_forcing_fraction_by_feature=tuple(forcing_fraction),
        initial_storage_source=PhysicalUncertaintySource(
            source_name="initial_storage",
            semantic_role="model_closure_discrepancy",
            provenance_ids=(
                prior_inputs["decoded_arrays"]["initial_storage_m3"]["sha256"],
                prior_inputs["decoded_arrays"]["q_lateral_m3s"]["sha256"],
                prior_inputs["action_values"]["sha256"],
                evaluation_inputs["decoded_arrays"]["initial_storage_m3"]["sha256"],
            ),
            evidence_window_end_utc=evidence_end,
        ),
        manning_n_source=PhysicalUncertaintySource(
            source_name="manning_n",
            semantic_role="hydraulic_structural_contrast",
            provenance_ids=(route_link["sha256"],),
        ),
        modeled_forcing_source=PhysicalUncertaintySource(
            source_name="modeled_forcing",
            semantic_role="forcing_change_proxy",
            provenance_ids=(
                prior_inputs["decoded_arrays"]["q_lateral_m3s"]["sha256"],
            ),
            evidence_window_end_utc=evidence_end,
        ),
        evaluation_window_start_utc=evaluation_start,
    )
    gates = {
        "feature_axis_matches_locked_network": profile.feature_ids
        == network.feature_ids,
        "prior_transition_count_complete": len(actions) == hour_count,
        "prior_transition_mass_balance_passed": max(mass_ratios) <= 1.0,
        "initial_storage_amplitude_nonzero": bool((storage_fraction > 0.0).any()),
        "manning_amplitude_nonzero": bool((manning_fraction > 0.0).any()),
        "forcing_amplitude_nonzero": bool((forcing_fraction > 0.0).any()),
        "all_amplitudes_below_one": all(
            bool((values < 1.0).all())
            for values in (storage_fraction, manning_fraction, forcing_fraction)
        ),
        "evaluation_outcome_not_used": True,
    }
    return {
        "system_id": system_id,
        "feature_count": len(feature_ids),
        "profile": profile.as_dict(),
        "amplitude_summary": {
            "initial_storage": _summary(storage_fraction),
            "manning_n": _summary(manning_fraction),
            "modeled_forcing": _summary(forcing_fraction),
        },
        "state_closure": {
            "prior_initial_total_m3": float(prior_initial.sum()),
            "propagated_total_m3": float(propagated.sum()),
            "evaluation_reference_total_m3": float(evaluation_initial.sum()),
            "transition_count": hour_count,
            "maximum_mass_residual_to_tolerance_ratio": max(mass_ratios),
            "forcing_timestamp_role": "assumed_transition_support_end",
            "forcing_interval_support_verified": False,
            "action_timestamp_shift_matches_existing_kernel_rollout": True,
        },
        "execution_gates": {**gates, "all_passed": all(gates.values())},
    }


def _propagate_prior_state(
    *,
    system_id: str,
    network: Any,
    geometry: Any,
    forcing_support: ReachForcingSupport,
    initial_storage: np.ndarray,
    q_lateral: np.ndarray,
    actions: tuple[float, ...],
) -> tuple[np.ndarray, tuple[float, ...]]:
    operator = BranchingManningNetworkTransportOperator(
        network,
        BranchingNetworkTransportConfig(
            timestep_seconds=TIMESTEP_SECONDS,
            integration_substep_seconds=SUBSTEP_SECONDS,
            operator_form_admitted=True,
        ),
    )
    state = StockState(
        values=tuple(float(value) for value in initial_storage),
        unit="m3",
        provenance_id=f"external-uncertainty:{system_id}:prior-initial",
    )
    action_index = network.feature_ids.index(network.action_entry_feature_ids[0])
    mass_ratios: list[float] = []
    for index, (release, forcing_values) in enumerate(
        zip(actions, q_lateral, strict=True)
    ):
        action_values = np.zeros(len(network.feature_ids), dtype=float)
        action_values[action_index] = release
        result = operator.step(
            state,
            geometry,
            action=ActionBoundaryFlux(
                values=tuple(action_values),
                unit="m3 s-1",
                provenance_id=f"external-uncertainty:{system_id}:action:{index}",
            ),
            forcing=ForcingFlux(
                values=tuple(float(value) for value in forcing_values),
                unit="m3 s-1",
                provenance_id=f"external-uncertainty:{system_id}:forcing:{index}",
                modeled=True,
            ),
            forcing_support=forcing_support,
        )
        state = result.next_stock
        mass_ratios.append(
            abs(result.global_mass_balance_residual_m3)
            / result.numeric_mass_tolerance_m3
        )
    return np.asarray(state.values, dtype=float), tuple(mass_ratios)


def _read_roughness_pair(
    path: Path, feature_ids: tuple[int, ...]
) -> tuple[np.ndarray, np.ndarray]:
    with netcdf_file(path, "r", mmap=False) as dataset:
        links = tuple(int(value) for value in dataset.variables["link"][:])
        channel_n = np.asarray(dataset.variables["n"][:], dtype=float).copy()
        compound_n = np.asarray(dataset.variables["nCC"][:], dtype=float).copy()
    if links != feature_ids:
        raise ValueError("external_uncertainty_routelink_axis_mismatch")
    if (
        channel_n.shape != (len(feature_ids),)
        or compound_n.shape != channel_n.shape
        or not np.isfinite(channel_n).all()
        or not np.isfinite(compound_n).all()
        or bool((channel_n <= 0.0).any())
        or bool((compound_n <= 0.0).any())
    ):
        raise ValueError("external_uncertainty_routelink_roughness_invalid")
    return channel_n, compound_n


def _forcing_support(
    *,
    system_id: str,
    lock: Mapping[str, Any],
    feature_ids: tuple[int, ...],
    outlet_feature_id: int,
) -> ReachForcingSupport:
    terminal_fraction = float(
        lock["forcing_support"]["partial_terminal_reach_fraction"]
    )
    return ReachForcingSupport(
        feature_ids=feature_ids,
        coverage_fractions=tuple(
            terminal_fraction if value == outlet_feature_id else 1.0
            for value in feature_ids
        ),
        support_method=str(lock["forcing_support"]["partial_terminal_reach_method"]),
        provenance_id=f"external-uncertainty:{system_id}:forcing-support",
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )


def _parse_ordered_actions(body: bytes, *, expected_count: int) -> tuple[float, ...]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    expected_columns = (
        "support_start_utc",
        "support_end_utc",
        "action_release_m3s",
        "source_role",
    )
    if tuple(reader.fieldnames or ()) != expected_columns:
        raise ValueError("external_uncertainty_action_columns_invalid")
    actions: list[float] = []
    previous_start: datetime | None = None
    for row in reader:
        start = _parse_time(row["support_start_utc"])
        end = _parse_time(row["support_end_utc"])
        value = float(row["action_release_m3s"])
        if (
            end - start != timedelta(hours=1)
            or (previous_start is not None and start - previous_start != timedelta(hours=1))
            or row["source_role"] != "boundary_action"
            or not np.isfinite(value)
            or value < 0.0
        ):
            raise ValueError("external_uncertainty_action_value_invalid")
        actions.append(value)
        previous_start = start
    if len(actions) != expected_count:
        raise ValueError("external_uncertainty_action_axis_invalid")
    return tuple(actions)


def _summary(values: np.ndarray) -> dict[str, float | int]:
    quantiles = np.quantile(values, (0.0, 0.25, 0.5, 0.75, 0.9, 0.95, 1.0))
    return {
        "minimum": float(quantiles[0]),
        "p25": float(quantiles[1]),
        "median": float(quantiles[2]),
        "p75": float(quantiles[3]),
        "p90": float(quantiles[4]),
        "p95": float(quantiles[5]),
        "maximum": float(quantiles[6]),
        "nonzero_feature_count": int(np.count_nonzero(values > 0.0)),
    }


def _validate_reports(
    *,
    prior: Mapping[str, Any],
    protocol: Mapping[str, Any],
    static: Mapping[str, Any],
) -> None:
    prior_isolation = prior.get("data_isolation") or {}
    protocol_claims = protocol.get("claim_boundary") or {}
    static_isolation = static.get("data_isolation") or {}
    if (
        prior.get("schema") != PRIOR_INPUT_SCHEMA
        or prior.get("status") != "pass_outcome_free_two_system_inputs_acquired"
        or prior_isolation.get("outcome_values_loaded") is not False
        or protocol.get("schema") != EVALUATION_PROTOCOL_SCHEMA
        or protocol.get("status") != "frozen_before_holdout_input_value_access"
        or protocol_claims.get("holdout_outcomes_acquired") is not False
        or static.get("schema") != EVALUATION_STATIC_SCHEMA
        or static.get("status")
        != "static_inputs_acquired_issue_observations_deferred"
        or static_isolation.get("future_target_loaded") is not False
        or static_isolation.get("score_or_loss_loaded") is not False
    ):
        raise ValueError("external_uncertainty_profile_input_reports_invalid")


def _read_verified(descriptor: Mapping[str, Any]) -> bytes:
    path = (REPO_ROOT / str(descriptor.get("path"))).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("external_uncertainty_artifact_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("external_uncertainty_artifact_identity_mismatch")
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


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("external_uncertainty_timezone_required")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    report = compile_external_uncertainty_profiles(
        prior_input_report_path=args.prior_input_report,
        evaluation_protocol_path=args.evaluation_protocol,
        evaluation_static_report_path=args.evaluation_static_report,
    )
    _write_json(args.output, report)
    print(args.output)
    for system_id, system in report["systems"].items():
        summaries = system["amplitude_summary"]
        print(
            f"{system_id}: "
            f"storage_p90={summaries['initial_storage']['p90']:.6f}, "
            f"manning_p90={summaries['manning_n']['p90']:.6f}, "
            f"forcing_p90={summaries['modeled_forcing']['p90']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
