"""Mass-conserving action responses from paired Manning-network rollouts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from .branching_network import BranchingManningNetworkTransportOperator
from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)

CONSERVATIVE_TWIN_ACTION_RESPONSE_SCHEMA = (
    "gwm.geospatial_kernel.conservative_twin_action_response.v1"
)
CONSERVATIVE_TWIN_ACTION_RESPONSE_STEP_SCHEMA = (
    "gwm.geospatial_kernel.conservative_twin_action_response_step.v1"
)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


@dataclass(frozen=True)
class ConservativeTwinActionStepInput:
    """One common-forcing step with explicit baseline and scenario actions."""

    support_start: datetime
    support_end: datetime
    inputs_available_at: datetime
    baseline_action: ActionBoundaryFlux
    scenario_action: ActionBoundaryFlux
    forcing: ForcingFlux
    forcing_support: ReachForcingSupport | None = None

    def __post_init__(self) -> None:
        if not all(
            _aware(value)
            for value in (
                self.support_start,
                self.support_end,
                self.inputs_available_at,
            )
        ):
            raise ValueError("conservative_twin_action_step_times_must_be_aware")
        if self.support_end <= self.support_start:
            raise ValueError("conservative_twin_action_step_support_invalid")
        if not isinstance(self.baseline_action, ActionBoundaryFlux) or not isinstance(
            self.scenario_action, ActionBoundaryFlux
        ):
            raise TypeError("conservative_twin_action_step_actions_required")
        if not isinstance(self.forcing, ForcingFlux):
            raise TypeError("conservative_twin_action_step_forcing_required")
        if self.forcing_support is not None and not isinstance(
            self.forcing_support, ReachForcingSupport
        ):
            raise TypeError("conservative_twin_action_step_forcing_support_invalid")


@dataclass(frozen=True)
class ConservativeTwinActionResponseStep:
    support_start: datetime
    support_end: datetime
    baseline_action_input_volume_m3: float
    scenario_action_input_volume_m3: float
    incremental_action_input_volume_m3: float
    baseline_outlet_mean_flow_m3s: float
    scenario_outlet_mean_flow_m3s: float
    incremental_outlet_mean_flow_m3s: float
    incremental_outlet_volume_m3: float
    initial_incremental_storage_m3: float
    final_incremental_storage_m3: float
    incremental_storage_change_m3: float
    differential_mass_balance_residual_m3: float
    differential_mass_balance_tolerance_m3: float
    baseline_mass_balance_residual_m3: float
    scenario_mass_balance_residual_m3: float
    individual_mass_balances_passed: bool
    differential_mass_balance_passed: bool
    source_operator_admitted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONSERVATIVE_TWIN_ACTION_RESPONSE_STEP_SCHEMA,
            "support_start": self.support_start.isoformat(),
            "support_end": self.support_end.isoformat(),
            "baseline_action_input_volume_m3": self.baseline_action_input_volume_m3,
            "scenario_action_input_volume_m3": self.scenario_action_input_volume_m3,
            "incremental_action_input_volume_m3": (self.incremental_action_input_volume_m3),
            "baseline_outlet_mean_flow_m3s": self.baseline_outlet_mean_flow_m3s,
            "scenario_outlet_mean_flow_m3s": self.scenario_outlet_mean_flow_m3s,
            "incremental_outlet_mean_flow_m3s": (self.incremental_outlet_mean_flow_m3s),
            "incremental_outlet_volume_m3": self.incremental_outlet_volume_m3,
            "initial_incremental_storage_m3": self.initial_incremental_storage_m3,
            "final_incremental_storage_m3": self.final_incremental_storage_m3,
            "incremental_storage_change_m3": self.incremental_storage_change_m3,
            "differential_mass_balance_residual_m3": (self.differential_mass_balance_residual_m3),
            "differential_mass_balance_tolerance_m3": (self.differential_mass_balance_tolerance_m3),
            "baseline_mass_balance_residual_m3": (self.baseline_mass_balance_residual_m3),
            "scenario_mass_balance_residual_m3": (self.scenario_mass_balance_residual_m3),
            "individual_mass_balances_passed": self.individual_mass_balances_passed,
            "differential_mass_balance_passed": self.differential_mass_balance_passed,
            "source_operator_admitted": self.source_operator_admitted,
        }


@dataclass(frozen=True)
class ConservativeTwinActionResponse:
    issue_time: datetime
    initial_state: StockState
    baseline_final_state: StockState
    scenario_final_state: StockState
    steps: tuple[ConservativeTwinActionResponseStep, ...]
    cumulative_incremental_action_input_volume_m3: float
    cumulative_incremental_outlet_volume_m3: float
    final_incremental_storage_m3: float
    cumulative_differential_mass_balance_residual_m3: float
    cumulative_differential_mass_balance_tolerance_m3: float
    all_mass_balances_passed: bool
    source_operator_admitted: bool

    def __post_init__(self) -> None:
        if not self.steps:
            raise ValueError("conservative_twin_action_response_requires_steps")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONSERVATIVE_TWIN_ACTION_RESPONSE_SCHEMA,
            "issue_time": self.issue_time.isoformat(),
            "operator": "paired_BranchingManningNetworkTransportOperator",
            "response_formula": "scenario_outlet_flow-baseline_outlet_flow",
            "continuity_formula": (
                "incremental_action_input=incremental_outlet+"
                "incremental_storage_change-differential_residual"
            ),
            "initial_state": _state_dict(self.initial_state),
            "baseline_final_state": _state_dict(self.baseline_final_state),
            "scenario_final_state": _state_dict(self.scenario_final_state),
            "steps": [value.as_dict() for value in self.steps],
            "cumulative_incremental_action_input_volume_m3": (
                self.cumulative_incremental_action_input_volume_m3
            ),
            "cumulative_incremental_outlet_volume_m3": (
                self.cumulative_incremental_outlet_volume_m3
            ),
            "final_incremental_storage_m3": self.final_incremental_storage_m3,
            "cumulative_differential_mass_balance_residual_m3": (
                self.cumulative_differential_mass_balance_residual_m3
            ),
            "cumulative_differential_mass_balance_tolerance_m3": (
                self.cumulative_differential_mass_balance_tolerance_m3
            ),
            "all_mass_balances_passed": self.all_mass_balances_passed,
            "source_operator_admitted": self.source_operator_admitted,
            "common_initial_state_used": True,
            "common_forcing_used": True,
            "output_response_clipped": False,
            "new_fitted_parameter_count": 0,
            "future_outcomes_used": False,
            "claim_boundary": {
                "mechanistic_action_response_computed": True,
                "counterfactual_release_effect_causally_validated": False,
                "hydrodynamic_response_validated": False,
                "candidate_promoted": False,
                "runtime_default_enabled": False,
            },
        }


class ConservativeTwinManningActionResponseKernel:
    """Route two action schedules through one common conservative network."""

    def __init__(self, operator: BranchingManningNetworkTransportOperator) -> None:
        if not isinstance(operator, BranchingManningNetworkTransportOperator):
            raise TypeError("branching_manning_network_transport_operator_required")
        self.operator = operator

    def forecast(
        self,
        initial_state: StockState,
        geometry: ReachHydraulicGeometry,
        steps: tuple[ConservativeTwinActionStepInput, ...],
        *,
        issue_time: datetime,
    ) -> ConservativeTwinActionResponse:
        if not isinstance(initial_state, StockState):
            raise TypeError("conservative_twin_initial_stock_state_required")
        if not isinstance(geometry, ReachHydraulicGeometry):
            raise TypeError("conservative_twin_geometry_required")
        if not _aware(issue_time):
            raise ValueError("conservative_twin_issue_time_must_be_aware")
        rollout_steps = tuple(steps)
        if not rollout_steps or any(
            not isinstance(value, ConservativeTwinActionStepInput) for value in rollout_steps
        ):
            raise ValueError("conservative_twin_steps_required")
        self._validate_time_axis(rollout_steps, issue_time=issue_time)

        baseline_state = initial_state
        scenario_state = initial_state
        result_steps: list[ConservativeTwinActionResponseStep] = []
        cumulative_input = 0.0
        cumulative_outlet = 0.0
        cumulative_residual = 0.0
        cumulative_tolerance = 0.0
        for index, step in enumerate(rollout_steps):
            initial_incremental_storage = float(
                sum(scenario_state.values) - sum(baseline_state.values)
            )
            baseline = self.operator.step(
                baseline_state,
                geometry,
                action=step.baseline_action,
                forcing=step.forcing,
                forcing_support=step.forcing_support,
            )
            scenario = self.operator.step(
                scenario_state,
                geometry,
                action=step.scenario_action,
                forcing=step.forcing,
                forcing_support=step.forcing_support,
            )
            final_incremental_storage = float(
                scenario.final_network_storage_m3 - baseline.final_network_storage_m3
            )
            incremental_input = float(
                scenario.action_input_volume_m3 - baseline.action_input_volume_m3
            )
            incremental_outlet = float(scenario.outlet_volume_m3 - baseline.outlet_volume_m3)
            storage_change = final_incremental_storage - initial_incremental_storage
            residual = float(
                final_incremental_storage
                + incremental_outlet
                - initial_incremental_storage
                - incremental_input
            )
            expected_residual = float(
                scenario.global_mass_balance_residual_m3 - baseline.global_mass_balance_residual_m3
            )
            tolerance = float(
                scenario.numeric_mass_tolerance_m3
                + baseline.numeric_mass_tolerance_m3
                + 32.0
                * math.ulp(
                    max(
                        1.0,
                        abs(final_incremental_storage),
                        abs(incremental_outlet),
                        abs(initial_incremental_storage),
                        abs(incremental_input),
                    )
                )
            )
            if not math.isclose(
                residual,
                expected_residual,
                rel_tol=0.0,
                abs_tol=tolerance,
            ):
                raise RuntimeError("conservative_twin_differential_identity_inconsistent")
            individual_passed = bool(
                abs(baseline.global_mass_balance_residual_m3) <= baseline.numeric_mass_tolerance_m3
                and abs(scenario.global_mass_balance_residual_m3)
                <= scenario.numeric_mass_tolerance_m3
            )
            differential_passed = abs(residual) <= tolerance
            source_admitted = bool(
                baseline.nonlinear_transport_admitted and scenario.nonlinear_transport_admitted
            )
            duration_seconds = (step.support_end - step.support_start).total_seconds()
            result_steps.append(
                ConservativeTwinActionResponseStep(
                    support_start=step.support_start,
                    support_end=step.support_end,
                    baseline_action_input_volume_m3=(baseline.action_input_volume_m3),
                    scenario_action_input_volume_m3=(scenario.action_input_volume_m3),
                    incremental_action_input_volume_m3=incremental_input,
                    baseline_outlet_mean_flow_m3s=baseline.outlet_mean_flow_m3s,
                    scenario_outlet_mean_flow_m3s=scenario.outlet_mean_flow_m3s,
                    incremental_outlet_mean_flow_m3s=(incremental_outlet / duration_seconds),
                    incremental_outlet_volume_m3=incremental_outlet,
                    initial_incremental_storage_m3=initial_incremental_storage,
                    final_incremental_storage_m3=final_incremental_storage,
                    incremental_storage_change_m3=storage_change,
                    differential_mass_balance_residual_m3=residual,
                    differential_mass_balance_tolerance_m3=tolerance,
                    baseline_mass_balance_residual_m3=(baseline.global_mass_balance_residual_m3),
                    scenario_mass_balance_residual_m3=(scenario.global_mass_balance_residual_m3),
                    individual_mass_balances_passed=individual_passed,
                    differential_mass_balance_passed=differential_passed,
                    source_operator_admitted=source_admitted,
                )
            )
            baseline_state = _tag_state(baseline.next_stock, role="baseline", step_index=index)
            scenario_state = _tag_state(scenario.next_stock, role="scenario", step_index=index)
            cumulative_input += incremental_input
            cumulative_outlet += incremental_outlet
            cumulative_residual += residual
            cumulative_tolerance += tolerance

        final_incremental_storage = float(sum(scenario_state.values) - sum(baseline_state.values))
        cumulative_identity_residual = float(
            final_incremental_storage + cumulative_outlet - cumulative_input
        )
        if not math.isclose(
            cumulative_identity_residual,
            cumulative_residual,
            rel_tol=0.0,
            abs_tol=cumulative_tolerance,
        ):
            raise RuntimeError("conservative_twin_cumulative_identity_inconsistent")
        all_passed = bool(
            all(
                value.individual_mass_balances_passed and value.differential_mass_balance_passed
                for value in result_steps
            )
            and abs(cumulative_identity_residual) <= cumulative_tolerance
        )
        return ConservativeTwinActionResponse(
            issue_time=issue_time,
            initial_state=initial_state,
            baseline_final_state=baseline_state,
            scenario_final_state=scenario_state,
            steps=tuple(result_steps),
            cumulative_incremental_action_input_volume_m3=cumulative_input,
            cumulative_incremental_outlet_volume_m3=cumulative_outlet,
            final_incremental_storage_m3=final_incremental_storage,
            cumulative_differential_mass_balance_residual_m3=(cumulative_identity_residual),
            cumulative_differential_mass_balance_tolerance_m3=(cumulative_tolerance),
            all_mass_balances_passed=all_passed,
            source_operator_admitted=all(value.source_operator_admitted for value in result_steps),
        )

    def _validate_time_axis(
        self,
        steps: tuple[ConservativeTwinActionStepInput, ...],
        *,
        issue_time: datetime,
    ) -> None:
        expected_seconds = float(self.operator.config.timestep_seconds)
        previous_end: datetime | None = None
        for step in steps:
            if (step.support_end - step.support_start).total_seconds() != expected_seconds:
                raise ValueError("conservative_twin_step_timestep_mismatch")
            if step.support_start < issue_time:
                raise ValueError("conservative_twin_support_before_issue_forbidden")
            if step.inputs_available_at > issue_time:
                raise ValueError("conservative_twin_future_input_forbidden")
            if previous_end is not None and step.support_start != previous_end:
                raise ValueError("conservative_twin_step_support_not_contiguous")
            previous_end = step.support_end


def _tag_state(state: StockState, *, role: str, step_index: int) -> StockState:
    return StockState(
        values=state.values,
        unit=state.unit,
        provenance_id=f"{state.provenance_id}|twin:{role}:{step_index}",
    )


def _state_dict(state: StockState) -> dict[str, object]:
    return {
        "values_m3": list(state.values),
        "total_storage_m3": float(sum(state.values)),
        "unit": state.unit,
        "provenance_id": state.provenance_id,
    }
