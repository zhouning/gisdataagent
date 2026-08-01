"""Outcome-free multi-scenario rollout for a directed reach chain."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

import numpy as np

from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    LinearReferencedPath,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)
from .nonlinear_reach_transport import (
    NonlinearManningReachTransportOperator,
    NonlinearReachTransportConfig,
)
from .troute_muskingum_cunge import (
    MuskingumCungeSegmentKernel,
    TrouteMuskingumCungeAdapter,
    TrouteMuskingumCungeParameters,
    TrouteMuskingumCungeState,
)


HOLDOUT_ROLLOUT_SCHEMA = "gwm.geotransport.outcome_free_holdout_rollout.v1"
NONLINEAR_SCENARIOS = (
    "nonlinear_central",
    "nonlinear_support_lower",
    "nonlinear_support_upper",
    "zero_action",
    "no_forcing",
    "state_only",
    "reversed_topology",
)
PREDICTION_SCENARIOS = NONLINEAR_SCENARIOS + ("t_route_mc", "direct_release")


@dataclass(frozen=True)
class HourlyReachInput:
    support_start_utc: datetime
    support_end_utc: datetime
    action_release_m3s: float
    q_lateral_m3s: tuple[float, ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            self.support_start_utc.tzinfo is None
            or self.support_end_utc.tzinfo is None
            or self.support_end_utc <= self.support_start_utc
        ):
            raise ValueError("hourly_reach_input_time_support_invalid")
        duration = (self.support_end_utc - self.support_start_utc).total_seconds()
        if duration != 3600.0:
            raise ValueError("hourly_reach_input_requires_one_hour_support")
        action = float(self.action_release_m3s)
        q_lateral = tuple(float(value) for value in self.q_lateral_m3s)
        values = np.asarray((action,) + q_lateral, dtype=float)
        if not q_lateral or not np.isfinite(values).all() or (values < 0.0).any():
            raise ValueError("hourly_reach_input_values_must_be_nonnegative_finite")
        if not self.provenance_id.strip():
            raise ValueError("hourly_reach_input_provenance_required")
        object.__setattr__(self, "action_release_m3s", action)
        object.__setattr__(self, "q_lateral_m3s", q_lateral)


@dataclass(frozen=True)
class HoldoutReachDomain:
    path: LinearReferencedPath
    geometry: ReachHydraulicGeometry
    initial_stock: StockState
    forcing_support_central: ReachForcingSupport
    forcing_support_lower: ReachForcingSupport
    forcing_support_upper: ReachForcingSupport
    t_route_parameters: TrouteMuskingumCungeParameters
    t_route_initial_state: TrouteMuskingumCungeState
    provenance_id: str

    def __post_init__(self) -> None:
        active_ids = tuple(
            feature_id
            for feature_id, length in zip(
                self.path.feature_ids,
                self.path.effective_lengths_m,
                strict=True,
            )
            if length > 1e-6
        )
        if self.geometry.feature_ids != active_ids:
            raise ValueError("holdout_domain_geometry_axis_mismatch")
        if len(self.initial_stock.values) != len(active_ids):
            raise ValueError("holdout_domain_stock_axis_mismatch")
        for support in (
            self.forcing_support_central,
            self.forcing_support_lower,
            self.forcing_support_upper,
        ):
            if support.feature_ids != active_ids:
                raise ValueError("holdout_domain_forcing_support_axis_mismatch")
            if support.admitted_as_spatial_support is not True:
                raise ValueError("holdout_domain_forcing_support_must_be_admitted")
        central = self.forcing_support_central.coverage_fractions
        lower = self.forcing_support_lower.coverage_fractions
        upper = self.forcing_support_upper.coverage_fractions
        if any(
            not (lower_value <= central_value <= upper_value)
            for lower_value, central_value, upper_value in zip(
                lower, central, upper, strict=True
            )
        ):
            raise ValueError("holdout_domain_forcing_support_bracket_invalid")
        if self.t_route_parameters.feature_ids != active_ids:
            raise ValueError("holdout_domain_t_route_parameter_axis_mismatch")
        if self.t_route_initial_state.feature_ids != active_ids:
            raise ValueError("holdout_domain_t_route_state_axis_mismatch")
        if not self.provenance_id.strip():
            raise ValueError("holdout_domain_provenance_required")


@dataclass(frozen=True)
class HoldoutRollout:
    rows: tuple[Mapping[str, object], ...]
    nonlinear_conservation: Mapping[str, Mapping[str, object]]
    final_t_route_state: TrouteMuskingumCungeState
    t_route_diagnostics: Mapping[str, object]
    input_provenance_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HOLDOUT_ROLLOUT_SCHEMA,
            "rows": [dict(row) for row in self.rows],
            "nonlinear_conservation": {
                name: dict(values)
                for name, values in self.nonlinear_conservation.items()
            },
            "final_t_route_state": {
                "feature_ids": list(self.final_t_route_state.feature_ids),
                "discharge_m3s": list(self.final_t_route_state.discharge_m3s),
                "velocity_mps": list(self.final_t_route_state.velocity_mps),
                "depth_m": list(self.final_t_route_state.depth_m),
                "provenance_id": self.final_t_route_state.provenance_id,
            },
            "t_route_diagnostics": dict(self.t_route_diagnostics),
            "input_provenance_ids": list(self.input_provenance_ids),
            "outcome_values_loaded": False,
        }


def execute_holdout_rollout(
    inputs: tuple[HourlyReachInput, ...],
    domain: HoldoutReachDomain,
    t_route_kernel: MuskingumCungeSegmentKernel,
    *,
    nonlinear_substep_seconds: float = 300.0,
    t_route_substep_seconds: float = 300.0,
) -> HoldoutRollout:
    """Execute fixed scenarios without accepting any outcome observations."""

    active_ids = domain.geometry.feature_ids
    _validate_hourly_inputs(inputs, len(active_ids))
    if 3600.0 % t_route_substep_seconds != 0.0:
        raise ValueError("t_route_substep_must_divide_one_hour")
    t_route_steps_per_hour = int(3600.0 / t_route_substep_seconds)

    admitted_config = NonlinearReachTransportConfig(
        timestep_seconds=3600.0,
        path_admitted=True,
        operator_form_admitted=True,
        integration_substep_seconds=nonlinear_substep_seconds,
    )
    reverse_config = NonlinearReachTransportConfig(
        timestep_seconds=3600.0,
        path_admitted=False,
        operator_form_admitted=True,
        allow_unadmitted_components_for_diagnostics=True,
        integration_substep_seconds=nonlinear_substep_seconds,
    )
    forward = NonlinearManningReachTransportOperator(domain.path, admitted_config)
    reverse_path = _reverse_path(domain.path)
    reverse = NonlinearManningReachTransportOperator(reverse_path, reverse_config)
    reverse_geometry = _reverse_geometry(domain.geometry)
    supports = {
        "nonlinear_central": domain.forcing_support_central,
        "nonlinear_support_lower": domain.forcing_support_lower,
        "nonlinear_support_upper": domain.forcing_support_upper,
        "zero_action": domain.forcing_support_central,
        "reversed_topology": _reverse_support(domain.forcing_support_central),
    }
    states = {
        name: domain.initial_stock
        for name in NONLINEAR_SCENARIOS
        if name != "reversed_topology"
    }
    states["reversed_topology"] = StockState(
        tuple(reversed(domain.initial_stock.values)),
        "m3",
        f"{domain.initial_stock.provenance_id}|reversed_topology",
    )
    initial_storage = {
        name: float(sum(state.values)) for name, state in states.items()
    }
    total_input = {name: 0.0 for name in NONLINEAR_SCENARIOS}
    total_outlet = {name: 0.0 for name in NONLINEAR_SCENARIOS}
    residuals = {name: [] for name in NONLINEAR_SCENARIOS}
    tolerances = {name: [] for name in NONLINEAR_SCENARIOS}

    t_route = TrouteMuskingumCungeAdapter(
        domain.t_route_parameters,
        t_route_kernel,
        timestep_seconds=t_route_substep_seconds,
    )
    t_route_state = domain.t_route_initial_state
    t_route_local_residual_max = 0.0
    rows: list[Mapping[str, object]] = []
    for hour in inputs:
        action_values = (hour.action_release_m3s,) + (0.0,) * (len(active_ids) - 1)
        action = ActionBoundaryFlux(
            action_values,
            "m3 s-1",
            f"{hour.provenance_id}|boundary_action",
        )
        forcing = ForcingFlux(
            hour.q_lateral_m3s,
            "m3 s-1",
            f"{hour.provenance_id}|modeled_forcing",
            modeled=True,
        )
        reverse_action = ActionBoundaryFlux(
            action_values,
            "m3 s-1",
            f"{hour.provenance_id}|boundary_action|reversed_topology",
        )
        reverse_forcing = ForcingFlux(
            tuple(reversed(hour.q_lateral_m3s)),
            "m3 s-1",
            f"{hour.provenance_id}|modeled_forcing|reversed_topology",
            modeled=True,
        )
        predictions: dict[str, float] = {}
        for scenario in NONLINEAR_SCENARIOS:
            operator = reverse if scenario == "reversed_topology" else forward
            geometry = reverse_geometry if scenario == "reversed_topology" else domain.geometry
            scenario_action = None if scenario in {"zero_action", "state_only"} else action
            scenario_forcing = None if scenario in {"no_forcing", "state_only"} else forcing
            if scenario == "reversed_topology":
                scenario_action = reverse_action
                scenario_forcing = reverse_forcing
            result = operator.step(
                states[scenario],
                geometry,
                action=scenario_action,
                forcing=scenario_forcing,
                forcing_support=supports.get(scenario),
            )
            states[scenario] = result.next_stock
            predictions[scenario] = result.outlet_mean_flow_m3s
            total_input[scenario] += result.input_volume_m3
            total_outlet[scenario] += result.outlet_volume_m3
            residuals[scenario].append(result.global_mass_balance_residual_m3)
            tolerances[scenario].append(result.numeric_mass_tolerance_m3)

        projected_q_lateral = tuple(
            value * fraction
            for value, fraction in zip(
                hour.q_lateral_m3s,
                domain.forcing_support_central.coverage_fractions,
                strict=True,
            )
        )
        t_route_samples: list[float] = []
        for substep_index in range(t_route_steps_per_hour):
            t_route_result = t_route.step(
                t_route_state,
                boundary_previous_m3s=hour.action_release_m3s,
                boundary_current_m3s=hour.action_release_m3s,
                lateral_inflow_m3s=projected_q_lateral,
                provenance_id=(
                    f"{hour.provenance_id}|t_route_mc|substep-{substep_index + 1}"
                ),
            )
            t_route_state = t_route_result.next_state
            t_route_samples.append(t_route_state.discharge_m3s[-1])
            t_route_local_residual_max = max(
                t_route_local_residual_max,
                max(
                    abs(value)
                    for value in t_route_result.local_reconstructed_equation_residual_m3
                ),
            )
        predictions["t_route_mc"] = float(np.mean(t_route_samples))
        predictions["direct_release"] = hour.action_release_m3s
        rows.append(
            {
                "support_start_utc": hour.support_start_utc.isoformat(),
                "support_end_utc": hour.support_end_utc.isoformat(),
                **{f"{name}_m3s": predictions[name] for name in PREDICTION_SCENARIOS},
            }
        )

    conservation = {
        name: _conservation_summary(
            initial_storage_m3=initial_storage[name],
            final_storage_m3=float(sum(states[name].values)),
            input_volume_m3=total_input[name],
            outlet_volume_m3=total_outlet[name],
            residuals=tuple(residuals[name]),
            tolerances=tuple(tolerances[name]),
        )
        for name in NONLINEAR_SCENARIOS
    }
    return HoldoutRollout(
        rows=tuple(rows),
        nonlinear_conservation=conservation,
        final_t_route_state=t_route_state,
        t_route_diagnostics={
            "substep_seconds": float(t_route_substep_seconds),
            "substeps_per_hour": t_route_steps_per_hour,
            "hourly_prediction_aggregation": "arithmetic_mean_of_12_end_of_substep_Q_values",
            "boundary_interpretation": "piecewise_constant_interval_mean_previous_equals_current",
            "q_lateral_interpretation": "piecewise_constant_reach_lateral_inflow_rate",
            "maximum_absolute_reconstructed_local_equation_residual_m3": (
                t_route_local_residual_max
            ),
            "conservation_gate_role": "not_a_conservation_oracle",
        },
        input_provenance_ids=tuple(hour.provenance_id for hour in inputs),
    )


def _validate_hourly_inputs(inputs: tuple[HourlyReachInput, ...], count: int) -> None:
    if not inputs:
        raise ValueError("holdout_rollout_inputs_required")
    for index, hour in enumerate(inputs):
        if len(hour.q_lateral_m3s) != count:
            raise ValueError("holdout_rollout_q_lateral_axis_mismatch")
        if index and inputs[index - 1].support_end_utc != hour.support_start_utc:
            raise ValueError("holdout_rollout_inputs_must_be_contiguous")


def _reverse_path(path: LinearReferencedPath) -> LinearReferencedPath:
    return LinearReferencedPath(
        path_id=f"{path.path_id}:reversed_topology_control",
        feature_ids=tuple(reversed(path.feature_ids)),
        full_lengths_m=tuple(reversed(path.full_lengths_m)),
        entry_offsets_m=tuple(
            full - exit_
            for full, exit_ in reversed(
                tuple(zip(path.full_lengths_m, path.exit_offsets_m, strict=True))
            )
        ),
        exit_offsets_m=tuple(
            full - entry
            for full, entry in reversed(
                tuple(zip(path.full_lengths_m, path.entry_offsets_m, strict=True))
            )
        ),
        provenance_id=f"{path.provenance_id}|reversed_topology_control",
        evidence_level="candidate",
    )


def _reverse_geometry(geometry: ReachHydraulicGeometry) -> ReachHydraulicGeometry:
    return ReachHydraulicGeometry(
        feature_ids=tuple(reversed(geometry.feature_ids)),
        bottom_width_m=tuple(reversed(geometry.bottom_width_m)),
        side_slope_horizontal_per_vertical=tuple(
            reversed(geometry.side_slope_horizontal_per_vertical)
        ),
        bed_slope=tuple(reversed(geometry.bed_slope)),
        manning_n=tuple(reversed(geometry.manning_n)),
        provenance_id=f"{geometry.provenance_id}|reversed_topology_control",
        evidence_level="candidate",
        admitted_as_hydraulic_geometry=False,
    )


def _reverse_support(support: ReachForcingSupport) -> ReachForcingSupport:
    return ReachForcingSupport(
        feature_ids=tuple(reversed(support.feature_ids)),
        coverage_fractions=tuple(reversed(support.coverage_fractions)),
        support_method=f"{support.support_method}|reversed_topology_control",
        provenance_id=f"{support.provenance_id}|reversed_topology_control",
        evidence_level=support.evidence_level,
        admitted_as_spatial_support=True,
    )


def _conservation_summary(
    *,
    initial_storage_m3: float,
    final_storage_m3: float,
    input_volume_m3: float,
    outlet_volume_m3: float,
    residuals: tuple[float, ...],
    tolerances: tuple[float, ...],
) -> dict[str, object]:
    rollout_residual = (
        final_storage_m3
        + outlet_volume_m3
        - initial_storage_m3
        - input_volume_m3
    )
    accumulated_tolerance = float(sum(tolerances))
    maximum_step_ratio = max(
        abs(residual) / tolerance
        for residual, tolerance in zip(residuals, tolerances, strict=True)
    )
    passed = (
        abs(rollout_residual) <= accumulated_tolerance
        and maximum_step_ratio <= 1.0
    )
    return {
        "initial_storage_m3": initial_storage_m3,
        "final_storage_m3": final_storage_m3,
        "input_volume_m3": input_volume_m3,
        "outlet_volume_m3": outlet_volume_m3,
        "rollout_mass_balance_residual_m3": rollout_residual,
        "accumulated_numeric_tolerance_m3": accumulated_tolerance,
        "maximum_step_residual_to_tolerance_ratio": maximum_step_ratio,
        "passed": passed,
    }
