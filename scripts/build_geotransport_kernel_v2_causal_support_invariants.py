#!/usr/bin/env python3
"""Run outcome-free causal-update and partial-forcing Kernel v2 invariants."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import h5py
import numpy as np

from data_agent.uwm.geospatial_kernel_v2 import (
    CAUSAL_MANNING_STATE_UPDATE_SCHEMA,
    NONLINEAR_REACH_TRANSPORT_OPERATOR_SCHEMA,
    REACH_FORCING_SUPPORT_SCHEMA,
    CausalDischargeObservation,
    CausalManningDischargeStateUpdater,
    CausalObservationUpdateConfig,
    ForcingFlux,
    LinearReferencedPath,
    NonlinearManningReachTransportOperator,
    NonlinearReachTransportConfig,
    ReachForcingSupport,
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
    / "benchmarks/geotransport_v0_1/"
    "kernel_v2_causal_support_invariant_report.json"
)
SCHEMA = "gwm.geotransport.kernel_v2_causal_support_invariants.v1"
SOURCE_ID = "t_route_hurricane_laura_nwm_v2_1"
FEATURE_IDS = (1622797, 1622687)
ANALYSIS_TIME = datetime(2022, 1, 1, 13, tzinfo=timezone.utc)
TIMESTEP_SECONDS = 3600.0
PARTIAL_COVERAGE_FRACTION = 0.4


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
    descriptor = _fixture_descriptor(manifest)
    route_link_path = REPO_ROOT / str(descriptor["path"])
    route_link_body = _read_verified(route_link_path, descriptor)
    rows = _route_link_rows(route_link_path)
    selected = [rows[feature_id] for feature_id in FEATURE_IDS]
    if int(selected[0]["to"]) != int(selected[1]["link"]):
        raise ValueError("causal_support_fixture_path_topology_mismatch")

    full_lengths = tuple(float(row["Length"]) for row in selected)
    effective_lengths = (
        full_lengths[0],
        full_lengths[1] * PARTIAL_COVERAGE_FRACTION,
    )
    path = LinearReferencedPath(
        path_id="hurricane-laura-causal-support-probe",
        feature_ids=FEATURE_IDS,
        full_lengths_m=full_lengths,
        entry_offsets_m=(0.0, 0.0),
        exit_offsets_m=effective_lengths,
        provenance_id=f"t-route:{SOURCE_ID}:partial-probe",
        evidence_level="derived",
    )
    geometry = ReachHydraulicGeometry(
        feature_ids=FEATURE_IDS,
        bottom_width_m=tuple(float(row["BtmWdth"]) for row in selected),
        side_slope_horizontal_per_vertical=tuple(
            1.0 / float(row["ChSlp"]) for row in selected
        ),
        bed_slope=tuple(float(row["So"]) for row in selected),
        manning_n=tuple(float(row["n"]) for row in selected),
        provenance_id=f"t-route:{SOURCE_ID}:ChSlp_inverse",
        evidence_level="derived",
        admitted_as_hydraulic_geometry=True,
    )

    observation_probe = _observation_invariants(path, geometry)
    forcing_probe = _forcing_invariants(path, geometry)
    rejection_reasons = observation_probe["rejection_reasons"]
    forcing_rejections = forcing_probe["rejection_reasons"]
    gates = {
        "future_observation_fail_closed": rejection_reasons["future_valid_time"]
        == "future_observation_valid_time_forbidden",
        "unavailable_observation_fail_closed": rejection_reasons[
            "not_yet_available"
        ]
        == "observation_not_yet_available_at_analysis_time",
        "stale_observation_fail_closed": rejection_reasons["stale"]
        == "causal_observation_exceeds_maximum_age",
        "unadmitted_quality_fail_closed": rejection_reasons[
            "provisional_quality"
        ]
        == (
            "unadmitted_causal_observation_components_require_explicit_"
            "diagnostic_mode"
        ),
        "manning_discharge_to_storage_inversion": observation_probe[
            "storage_inversion_passed"
        ],
        "analysis_increment_separate_from_transition_flux": observation_probe[
            "analysis_increment_accounting_passed"
        ],
        "partial_forcing_without_support_fail_closed": forcing_rejections[
            "missing_support"
        ]
        == "partial_reach_forcing_requires_admitted_spatial_support",
        "unadmitted_partial_forcing_support_fail_closed": forcing_rejections[
            "candidate_support"
        ]
        == (
            "unadmitted_partial_reach_forcing_support_requires_explicit_"
            "diagnostic_mode"
        ),
        "partial_forcing_ledger_closes": forcing_probe["forcing_ledger_passed"],
        "projected_forcing_transition_conservative": forcing_probe[
            "projected_conservation_passed"
        ],
        "outcome_and_action_observation_isolation": True,
        "center_hill_chunk_561_isolation": True,
    }
    gates["all_invariants_passed"] = all(gates.values())
    if not gates["all_invariants_passed"]:
        failed = sorted(name for name, passed in gates.items() if not passed)
        raise RuntimeError(
            "kernel_v2_causal_support_invariant_gate_failed:" + ",".join(failed)
        )

    return {
        "schema": SCHEMA,
        "status": "pass",
        "operator_schemas": {
            "transition": NONLINEAR_REACH_TRANSPORT_OPERATOR_SCHEMA,
            "observation_update": CAUSAL_MANNING_STATE_UPDATE_SCHEMA,
            "forcing_support": REACH_FORCING_SUPPORT_SCHEMA,
        },
        "source_artifacts": {
            "route_link_manifest": _artifact(route_link_manifest_path, manifest_body),
            "route_link_fixture": _artifact(route_link_path, route_link_body),
        },
        "data_isolation": {
            "outcome_values_loaded": False,
            "observed_action_values_loaded": False,
            "observed_forcing_values_loaded": False,
            "center_hill_chunk_560_loaded": False,
            "center_hill_chunk_561_loaded": False,
            "inputs": [
                "official_route_link_geometry",
                "synthetic_historical_discharge_probe",
                "synthetic_full_reach_forcing_probe",
            ],
        },
        "fixture": {
            "source_id": SOURCE_ID,
            "feature_ids": list(FEATURE_IDS),
            "topology_consecutive": True,
            "full_lengths_m": list(full_lengths),
            "effective_lengths_m": list(effective_lengths),
            "partial_reach_feature_ids": [FEATURE_IDS[1]],
            "partial_coverage_fraction": PARTIAL_COVERAGE_FRACTION,
            "center_hill_parameter_fixture": False,
        },
        "observation_update_probe": observation_probe,
        "partial_forcing_probe": forcing_probe,
        "gates": gates,
        "claim_boundary": {
            "causal_observation_contract_invariants_passed": True,
            "partial_forcing_support_invariants_passed": True,
            "real_observation_update_validated": False,
            "real_forcing_support_validated": False,
            "center_hill_initial_state_available": False,
            "center_hill_execution_admitted": False,
            "benchmark_validated": False,
            "geospatial_kernel_validated": False,
        },
    }


def _observation_invariants(
    path: LinearReferencedPath,
    geometry: ReachHydraulicGeometry,
) -> dict[str, Any]:
    config = CausalObservationUpdateConfig(
        analysis_gain=1.0,
        maximum_observation_age_seconds=3600.0,
    )
    updater = CausalManningDischargeStateUpdater(path, config)
    target_storage = _storage_at_depth(
        depth_m=1.0,
        length_m=path.effective_lengths_m[1],
        bottom_width_m=geometry.bottom_width_m[1],
        side_slope=geometry.side_slope_horizontal_per_vertical[1],
    )
    forecast_storage = target_storage * 0.25
    observed_discharge = _manning_discharge(
        target_storage,
        length_m=path.effective_lengths_m[1],
        bottom_width_m=geometry.bottom_width_m[1],
        side_slope=geometry.side_slope_horizontal_per_vertical[1],
        bed_slope=geometry.bed_slope[1],
        manning_n=geometry.manning_n[1],
    )
    observation = _observation(
        discharge_m3s=observed_discharge,
        valid_at=ANALYSIS_TIME - timedelta(hours=1),
        available_at=ANALYSIS_TIME - timedelta(minutes=55),
    )
    forecast = StockState(
        (target_storage * 0.1, forecast_storage),
        "m3",
        "synthetic:forecast-state",
    )
    result = updater.update(
        forecast, geometry, observation, analysis_time=ANALYSIS_TIME
    )
    result_dict = result.as_dict()
    tolerance = max(1e-7, target_storage * 1e-10)

    future = _observation(
        discharge_m3s=observed_discharge,
        valid_at=ANALYSIS_TIME + timedelta(minutes=1),
        available_at=ANALYSIS_TIME + timedelta(minutes=1),
    )
    unavailable = _observation(
        discharge_m3s=observed_discharge,
        valid_at=ANALYSIS_TIME - timedelta(minutes=30),
        available_at=ANALYSIS_TIME + timedelta(minutes=5),
    )
    stale = _observation(
        discharge_m3s=observed_discharge,
        valid_at=ANALYSIS_TIME - timedelta(hours=1, seconds=1),
        available_at=ANALYSIS_TIME - timedelta(hours=1),
    )
    provisional = _observation(
        discharge_m3s=observed_discharge,
        valid_at=ANALYSIS_TIME - timedelta(minutes=30),
        available_at=ANALYSIS_TIME - timedelta(minutes=25),
        quality_status="provisional",
    )
    return {
        "analysis_time": ANALYSIS_TIME.isoformat(),
        "synthetic_observation": observation.as_dict(),
        "target_storage_m3": target_storage,
        "forecast_storage_m3": forecast_storage,
        "update_result": result_dict,
        "storage_inversion_absolute_error_m3": abs(
            result.observation_equivalent_storage_m3 - target_storage
        ),
        "storage_inversion_passed": abs(
            result.observation_equivalent_storage_m3 - target_storage
        )
        <= tolerance,
        "analysis_increment_accounting_passed": (
            abs(
                result.analysis_increment_m3
                - (result.analysis_storage_m3 - result.forecast_storage_m3)
            )
            <= tolerance
            and result_dict["mass_accounting_role"]
            == "external_analysis_increment_not_transition_flux"
            and result.updated_stock.values[0] == forecast.values[0]
        ),
        "rejection_reasons": {
            "future_valid_time": _expect_value_error(
                lambda: updater.update(
                    forecast, geometry, future, analysis_time=ANALYSIS_TIME
                )
            ),
            "not_yet_available": _expect_value_error(
                lambda: updater.update(
                    forecast, geometry, unavailable, analysis_time=ANALYSIS_TIME
                )
            ),
            "stale": _expect_value_error(
                lambda: updater.update(
                    forecast, geometry, stale, analysis_time=ANALYSIS_TIME
                )
            ),
            "provisional_quality": _expect_value_error(
                lambda: updater.update(
                    forecast, geometry, provisional, analysis_time=ANALYSIS_TIME
                )
            ),
        },
    }


def _forcing_invariants(
    path: LinearReferencedPath,
    geometry: ReachHydraulicGeometry,
) -> dict[str, Any]:
    operator = NonlinearManningReachTransportOperator(
        path,
        NonlinearReachTransportConfig(
            timestep_seconds=TIMESTEP_SECONDS,
            path_admitted=True,
            operator_form_admitted=True,
            integration_substep_seconds=300.0,
        ),
    )
    stock = operator.zero_state(provenance_id="synthetic:partial-forcing:cold")
    forcing = ForcingFlux(
        (0.25, 1.0),
        "m3 s-1",
        "synthetic:full-reach-forcing",
        modeled=True,
    )
    support = ReachForcingSupport(
        feature_ids=FEATURE_IDS,
        coverage_fractions=(1.0, PARTIAL_COVERAGE_FRACTION),
        support_method="fixed_fixture_intersection_probe",
        provenance_id="synthetic:partial-forcing-support",
        evidence_level="derived",
        admitted_as_spatial_support=True,
    )
    result = operator.step(
        stock,
        geometry,
        forcing=forcing,
        forcing_support=support,
    )
    raw_expected = sum(forcing.values) * TIMESTEP_SECONDS
    applied_expected = (
        forcing.values[0]
        + forcing.values[1] * PARTIAL_COVERAGE_FRACTION
    ) * TIMESTEP_SECONDS
    excluded_expected = raw_expected - applied_expected
    ledger_tolerance = 1e-9
    candidate = ReachForcingSupport(
        feature_ids=FEATURE_IDS,
        coverage_fractions=(1.0, PARTIAL_COVERAGE_FRACTION),
        support_method="unverified_length_fraction_assumption",
        provenance_id="candidate:partial-forcing-support",
        evidence_level="candidate",
        admitted_as_spatial_support=False,
    )
    return {
        "synthetic_forcing": {
            "values_m3s": list(forcing.values),
            "full_reach_semantics": True,
        },
        "support": support.as_dict(),
        "transition_result": result.as_dict(),
        "expected_raw_forcing_volume_m3": raw_expected,
        "expected_applied_forcing_volume_m3": applied_expected,
        "expected_excluded_forcing_volume_m3": excluded_expected,
        "forcing_ledger_passed": (
            abs(result.raw_forcing_volume_m3 - raw_expected) <= ledger_tolerance
            and abs(result.applied_forcing_volume_m3 - applied_expected)
            <= ledger_tolerance
            and abs(result.excluded_forcing_volume_m3 - excluded_expected)
            <= ledger_tolerance
            and abs(
                result.raw_forcing_volume_m3
                - result.applied_forcing_volume_m3
                - result.excluded_forcing_volume_m3
            )
            <= ledger_tolerance
        ),
        "projected_conservation_passed": (
            result.input_volume_m3 == result.applied_forcing_volume_m3
            and abs(result.global_mass_balance_residual_m3)
            <= result.numeric_mass_tolerance_m3
        ),
        "rejection_reasons": {
            "missing_support": _expect_value_error(
                lambda: operator.step(stock, geometry, forcing=forcing)
            ),
            "candidate_support": _expect_value_error(
                lambda: operator.step(
                    stock,
                    geometry,
                    forcing=forcing,
                    forcing_support=candidate,
                )
            ),
        },
    }


def _observation(
    *,
    discharge_m3s: float,
    valid_at: datetime,
    available_at: datetime,
    quality_status: str = "approved",
) -> CausalDischargeObservation:
    return CausalDischargeObservation(
        feature_id=FEATURE_IDS[1],
        discharge_m3s=discharge_m3s,
        valid_at=valid_at,
        available_at=available_at,
        quality_status=quality_status,
        provenance_id="synthetic:historical-discharge-probe",
        evidence_level="authoritative",
    )


def _storage_at_depth(
    *, depth_m: float, length_m: float, bottom_width_m: float, side_slope: float
) -> float:
    return float((bottom_width_m * depth_m + side_slope * depth_m**2) * length_m)


def _manning_discharge(
    storage_m3: float,
    *,
    length_m: float,
    bottom_width_m: float,
    side_slope: float,
    bed_slope: float,
    manning_n: float,
) -> float:
    area = storage_m3 / length_m
    depth = (
        -bottom_width_m
        + np.sqrt(bottom_width_m**2 + 4.0 * side_slope * area)
    ) / (2.0 * side_slope)
    wetted_perimeter = bottom_width_m + 2.0 * depth * np.sqrt(
        1.0 + side_slope**2
    )
    hydraulic_radius = area / wetted_perimeter
    return float(
        area
        * hydraulic_radius ** (2.0 / 3.0)
        * np.sqrt(bed_slope)
        / manning_n
    )


def _expect_value_error(call: Callable[[], object]) -> str:
    try:
        call()
    except ValueError as exc:
        return str(exc)
    raise RuntimeError("expected_fail_closed_value_error_not_raised")


def _fixture_descriptor(manifest: dict[str, Any]) -> dict[str, Any]:
    if (
        manifest.get("schema") != "gwm.geotransport.public_route_link_audit.v1"
        or manifest.get("mode") != "values"
    ):
        raise ValueError("causal_support_route_link_manifest_invalid")
    for audit in manifest.get("netcdf_audits") or []:
        if audit.get("source_id") == SOURCE_ID:
            if (
                audit.get("admitted_as_public_invariant_fixture") is not True
                or audit.get("admitted_as_center_hill_parameters") is not False
            ):
                raise ValueError("causal_support_route_link_fixture_not_admitted")
            return dict(audit["artifact"])
    raise ValueError("causal_support_route_link_fixture_missing")


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


def _read_verified(path: Path, descriptor: dict[str, Any]) -> bytes:
    resolved = path.resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("causal_support_artifact_outside_repository") from exc
    body = resolved.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("causal_support_artifact_identity_mismatch")
    return body


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
