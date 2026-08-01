#!/usr/bin/env python3
"""Verify the finite-volume kinematic wave against an analytic shock solution."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from scipy.optimize import brentq

from data_agent.uwm.geospatial_kernel_v2 import (
    FiniteVolumeKinematicWaveOperator,
    KinematicWaveConfig,
    LinearReferencedPath,
    ReachHydraulicGeometry,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    REPO_ROOT
    / "benchmarks/geotransport_v0_1/"
    "kinematic_wave_analytic_shock_report.json"
)
SCHEMA = "gwm.geotransport.kinematic_wave_analytic_shock.v1"
REACH_LENGTH_M = 10_000.0
BACKGROUND_FLOW_M3S = 2.0
STEP_FLOW_M3S = 10.0
HORIZON_SECONDS = 3600.0
TIMESTEP_SECONDS = 60.0
TARGET_CELL_LENGTHS_M = (2000.0, 1000.0, 500.0, 250.0)
BOTTOM_WIDTH_M = 10.0
SIDE_SLOPE = 2.0
BED_SLOPE = 0.002
MANNING_N = 0.035
CFL_NUMBER = 0.8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_diagnostic() -> dict[str, Any]:
    background_area = _area_for_discharge(BACKGROUND_FLOW_M3S)
    step_area = _area_for_discharge(STEP_FLOW_M3S)
    shock_speed = (STEP_FLOW_M3S - BACKGROUND_FLOW_M3S) / (
        step_area - background_area
    )
    shock_position = shock_speed * HORIZON_SECONDS
    if not 0.0 < shock_position < REACH_LENGTH_M:
        raise ValueError("kinematic_wave_analytic_shock_outside_reach")
    left_celerity = _numeric_flux_derivative(step_area)
    right_celerity = _numeric_flux_derivative(background_area)
    lax_entropy_condition = left_celerity > shock_speed > right_celerity

    resolutions = [
        _run_resolution(
            target_cell_length_m=target,
            background_area_m2=background_area,
            step_area_m2=step_area,
            analytic_shock_position_m=shock_position,
        )
        for target in TARGET_CELL_LENGTHS_M
    ]
    convergence = []
    for coarse, fine in zip(resolutions[:-1], resolutions[1:], strict=True):
        coarse_error = float(coarse["normalized_l1_area_error"])
        fine_error = float(fine["normalized_l1_area_error"])
        convergence.append(
            {
                "coarse_target_cell_length_m": coarse[
                    "target_cell_length_m"
                ],
                "fine_target_cell_length_m": fine["target_cell_length_m"],
                "coarse_normalized_l1_area_error": coarse_error,
                "fine_normalized_l1_area_error": fine_error,
                "observed_order": math.log(coarse_error / fine_error)
                / math.log(
                    float(coarse["actual_cell_length_m"])
                    / float(fine["actual_cell_length_m"])
                ),
                "passed": fine_error < coarse_error,
            }
        )
    gates = {
        "lax_entropy_condition": lax_entropy_condition,
        "analytic_front_remains_inside_domain": shock_position < REACH_LENGTH_M,
        "all_step_mass_identities_passed": all(
            item["maximum_step_mass_residual_to_tolerance_ratio"] <= 1.0
            for item in resolutions
        ),
        "all_cfl_limits_respected": all(
            item["maximum_courant_number"] <= CFL_NUMBER + 1e-12
            for item in resolutions
        ),
        "all_states_bounded_by_riemann_states": all(
            item["state_bounded_by_riemann_states"] for item in resolutions
        ),
        "normalized_l1_error_strictly_decreases": all(
            item["passed"] for item in convergence
        ),
        "outcome_isolation": True,
        "operator_remains_diagnostic_only": all(
            item["diagnostic_only"] for item in resolutions
        ),
    }
    gates["all_registered_analytic_gates_passed"] = all(gates.values())
    return {
        "schema": SCHEMA,
        "status": "analytic_riemann_shock_diagnostic_complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "registered_protocol": {
            "equation": "dA/dt + dQ(A)/dx = 0",
            "riemann_left_boundary_flow_m3s": STEP_FLOW_M3S,
            "riemann_right_initial_flow_m3s": BACKGROUND_FLOW_M3S,
            "reach_length_m": REACH_LENGTH_M,
            "horizon_seconds": HORIZON_SECONDS,
            "external_timestep_seconds": TIMESTEP_SECONDS,
            "target_cell_lengths_m": list(TARGET_CELL_LENGTHS_M),
            "cfl_number": CFL_NUMBER,
            "geometry": {
                "bottom_width_m": BOTTOM_WIDTH_M,
                "side_slope_horizontal_per_vertical": SIDE_SLOPE,
                "bed_slope": BED_SLOPE,
                "manning_n": MANNING_N,
            },
            "registration_phase": "before_execution",
        },
        "analytic_solution": {
            "solution_type": "entropy_satisfying_shock_for_convex_flux",
            "background_area_m2": background_area,
            "step_area_m2": step_area,
            "rankine_hugoniot_shock_speed_mps": shock_speed,
            "shock_position_at_horizon_m": shock_position,
            "right_characteristic_speed_mps": right_celerity,
            "left_characteristic_speed_mps": left_celerity,
            "lax_entropy_condition": lax_entropy_condition,
            "exact_cell_average_semantics": (
                "length-weighted left/right Riemann state split at analytic shock"
            ),
        },
        "resolutions": resolutions,
        "convergence": {
            "comparison_count": len(convergence),
            "comparisons": convergence,
            "all_comparisons_passed": all(
                item["passed"] for item in convergence
            ),
        },
        "gates": gates,
        "data_isolation": {
            "external_data_loaded": False,
            "observed_outcomes_loaded": False,
            "fitted_parameters": 0,
            "inputs": ["registered_geometry", "analytic_riemann_states"],
        },
        "claim_boundary": {
            "analytic_solution_is_independent_observed_evidence": False,
            "finite_volume_consistency_supported": gates[
                "all_registered_analytic_gates_passed"
            ],
            "operator_form_admitted": False,
            "real_world_transfer_validated": False,
            "professional_transfer_operator_certified": False,
            "geospatial_kernel_validated": False,
        },
    }


def _run_resolution(
    *,
    target_cell_length_m: float,
    background_area_m2: float,
    step_area_m2: float,
    analytic_shock_position_m: float,
) -> dict[str, Any]:
    feature_id = 900001
    path = LinearReferencedPath(
        "kinematic-wave-analytic-shock",
        (feature_id,),
        (REACH_LENGTH_M,),
        (0.0,),
        (REACH_LENGTH_M,),
        "analytic-riemann-protocol:v1",
        "derived",
    )
    geometry = ReachHydraulicGeometry(
        (feature_id,),
        (BOTTOM_WIDTH_M,),
        (SIDE_SLOPE,),
        (BED_SLOPE,),
        (MANNING_N,),
        "analytic-riemann-geometry:v1",
        "derived",
        True,
    )
    operator = FiniteVolumeKinematicWaveOperator(
        path,
        geometry,
        KinematicWaveConfig(
            timestep_seconds=TIMESTEP_SECONDS,
            target_cell_length_m=target_cell_length_m,
            cfl_number=CFL_NUMBER,
            path_admitted=True,
            operator_form_admitted=False,
            allow_unadmitted_components_for_diagnostics=True,
        ),
    )
    state = operator.uniform_discharge_state(
        BACKGROUND_FLOW_M3S,
        provenance_id="analytic-shock:initial-right-state",
    )
    maximum_mass_ratio = 0.0
    maximum_courant = 0.0
    total_substeps = 0
    steps = int(HORIZON_SECONDS / TIMESTEP_SECONDS)
    result = None
    for step in range(steps):
        result = operator.step(
            state,
            boundary_inflow_m3s=STEP_FLOW_M3S,
            provenance_id=f"analytic-shock:step:{step + 1}",
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
        raise RuntimeError("kinematic_wave_analytic_shock_empty_rollout")

    lengths = operator.cell_lengths_m
    numerical_area = np.asarray(state.cell_volume_m3, dtype=float) / lengths
    cell_left = np.concatenate(
        (np.asarray([0.0]), np.cumsum(lengths)[:-1])
    )
    left_fraction = np.clip(
        (analytic_shock_position_m - cell_left) / lengths, 0.0, 1.0
    )
    exact_area = background_area_m2 + left_fraction * (
        step_area_m2 - background_area_m2
    )
    l1_error = float(np.sum(np.abs(numerical_area - exact_area) * lengths))
    normalized_l1 = l1_error / (
        (step_area_m2 - background_area_m2) * REACH_LENGTH_M
    )
    numerical_shock_position = float(
        np.sum((numerical_area - background_area_m2) * lengths)
        / (step_area_m2 - background_area_m2)
    )
    bound_tolerance = 1e-10 * max(step_area_m2, 1.0)
    bounded = bool(
        numerical_area.min() >= background_area_m2 - bound_tolerance
        and numerical_area.max() <= step_area_m2 + bound_tolerance
    )
    return {
        "target_cell_length_m": target_cell_length_m,
        "actual_cell_count": operator.cell_count,
        "actual_cell_length_m": float(lengths[0]),
        "normalized_l1_area_error": normalized_l1,
        "l1_area_error_m3": l1_error,
        "numerical_excess_mass_shock_position_m": numerical_shock_position,
        "shock_position_absolute_error_m": abs(
            numerical_shock_position - analytic_shock_position_m
        ),
        "minimum_area_m2": float(numerical_area.min()),
        "maximum_area_m2": float(numerical_area.max()),
        "state_bounded_by_riemann_states": bounded,
        "maximum_step_mass_residual_to_tolerance_ratio": maximum_mass_ratio,
        "maximum_courant_number": maximum_courant,
        "configured_cfl_number": result.cfl_number,
        "integration_substep_count": total_substeps,
        "outlet_mean_flow_m3s_at_horizon": result.outlet_mean_flow_m3s,
        "operator_form_admitted": result.operator_form_admitted,
        "diagnostic_only": result.diagnostic_only,
    }


def _manning_discharge(area_m2: float) -> float:
    depth = (
        -BOTTOM_WIDTH_M
        + math.sqrt(BOTTOM_WIDTH_M**2 + 4.0 * SIDE_SLOPE * area_m2)
    ) / (2.0 * SIDE_SLOPE)
    perimeter = BOTTOM_WIDTH_M + 2.0 * depth * math.sqrt(
        1.0 + SIDE_SLOPE**2
    )
    radius = 0.0 if perimeter <= 0.0 else area_m2 / perimeter
    return (
        area_m2
        * radius ** (2.0 / 3.0)
        * math.sqrt(BED_SLOPE)
        / MANNING_N
    )


def _area_for_discharge(discharge_m3s: float) -> float:
    upper = max(1.0, discharge_m3s)
    while _manning_discharge(upper) < discharge_m3s:
        upper *= 2.0
    return float(
        brentq(
            lambda area: _manning_discharge(area) - discharge_m3s,
            0.0,
            upper,
            xtol=1e-13,
            rtol=1e-13,
        )
    )


def _numeric_flux_derivative(area_m2: float) -> float:
    delta = max(area_m2 * 1e-5, 1e-8)
    return (
        _manning_discharge(area_m2 + delta)
        - _manning_discharge(area_m2 - delta)
    ) / (2.0 * delta)


def _json_body(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def main() -> int:
    args = parse_args()
    if args.report.exists():
        raise ValueError("kinematic_wave_analytic_shock_refuses_overwrite")
    report = compile_diagnostic()
    body = _json_body(report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(body)
    print(args.report)
    print(hashlib.sha256(body).hexdigest())
    print(
        "all_registered_analytic_gates_passed="
        f"{report['gates']['all_registered_analytic_gates_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
