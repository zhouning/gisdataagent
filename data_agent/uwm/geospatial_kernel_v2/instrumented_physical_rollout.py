"""Outcome-free physical rollout with first-class internal telemetry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .branching_kinematic_wave import (
    BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA,
    BranchingFiniteVolumeKinematicWaveOperator,
)
from .branching_network import (
    BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
    BranchingManningNetworkTransportOperator,
    ModeledTributaryBoundaryFlux,
)
from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)
from .internal_innovation_instrumentation import (
    InternalInnovationTelemetryBundle,
    InternalInnovationTelemetryConfig,
    InternalInnovationTelemetryRecorder,
)
from .kinematic_wave import KinematicWaveState

INSTRUMENTED_PHYSICAL_ROLLOUT_SCHEMA = "gwm.geospatial_kernel.instrumented_physical_rollout.v1"


@dataclass(frozen=True)
class InstrumentedManningStepInput:
    support_start: datetime
    support_end: datetime
    inputs_available_at: datetime
    action: ActionBoundaryFlux | None = None
    forcing: ForcingFlux | None = None
    forcing_support: ReachForcingSupport | None = None
    tributary_boundary: ModeledTributaryBoundaryFlux | None = None


@dataclass(frozen=True)
class InstrumentedKinematicStepInput:
    support_start: datetime
    support_end: datetime
    inputs_available_at: datetime
    next_state_provenance_id: str
    action: ActionBoundaryFlux | None = None
    forcing: ForcingFlux | None = None
    forcing_support: ReachForcingSupport | None = None

    def __post_init__(self) -> None:
        if not self.next_state_provenance_id.strip():
            raise ValueError("instrumented_rollout_next_state_provenance_required")


@dataclass(frozen=True)
class InstrumentedPhysicalRolloutResult:
    operator_schema: str
    final_state: StockState | KinematicWaveState
    prediction_rows: tuple[dict[str, object], ...]
    telemetry: InternalInnovationTelemetryBundle

    def __post_init__(self) -> None:
        if not self.prediction_rows:
            raise ValueError("instrumented_rollout_requires_predictions")
        if len(self.prediction_rows) != self.telemetry.step_count:
            raise ValueError("instrumented_rollout_prediction_telemetry_count_mismatch")
        if self.operator_schema != self.telemetry.operator_schema:
            raise ValueError("instrumented_rollout_operator_telemetry_mismatch")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": INSTRUMENTED_PHYSICAL_ROLLOUT_SCHEMA,
            "operator_schema": self.operator_schema,
            "prediction_count": len(self.prediction_rows),
            "prediction_rows": list(self.prediction_rows),
            "final_state_provenance_id": self.final_state.provenance_id,
            "telemetry": self.telemetry.as_dict(),
            "data_isolation": {
                "outcome_argument_accepted": False,
                "outcome_values_loaded": False,
                "prediction_reexecution_for_scoring": False,
            },
        }


def run_instrumented_manning_rollout(
    operator: BranchingManningNetworkTransportOperator,
    geometry: ReachHydraulicGeometry,
    initial_state: StockState,
    steps: tuple[InstrumentedManningStepInput, ...],
    *,
    telemetry_config: InternalInnovationTelemetryConfig,
) -> InstrumentedPhysicalRolloutResult:
    if not isinstance(operator, BranchingManningNetworkTransportOperator):
        raise TypeError("branching_manning_operator_required")
    if not isinstance(geometry, ReachHydraulicGeometry):
        raise TypeError("reach_hydraulic_geometry_required")
    if not isinstance(initial_state, StockState):
        raise TypeError("stock_state_required")
    if telemetry_config.operator_schema != BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA:
        raise ValueError("instrumented_manning_telemetry_operator_mismatch")
    if not steps or any(not isinstance(step, InstrumentedManningStepInput) for step in steps):
        raise ValueError("instrumented_manning_steps_required")

    recorder = InternalInnovationTelemetryRecorder(operator.network, telemetry_config)
    state = initial_state
    rows: list[dict[str, object]] = []
    for step_index, step in enumerate(steps):
        result = operator.step(
            state,
            geometry,
            action=step.action,
            forcing=step.forcing,
            forcing_support=step.forcing_support,
            tributary_boundary=step.tributary_boundary,
        )
        recorder.record_step(
            state,
            result,
            support_start=step.support_start,
            support_end=step.support_end,
            inputs_available_at=step.inputs_available_at,
            input_provenance_ids=_input_provenance_ids(
                state,
                step.action,
                step.forcing,
                step.forcing_support,
                step.tributary_boundary,
            ),
        )
        rows.append(
            _prediction_row(
                step_index=step_index,
                support_start=step.support_start,
                support_end=step.support_end,
                outlet_mean_flow_m3s=result.outlet_mean_flow_m3s,
                residual_m3=result.global_mass_balance_residual_m3,
                tolerance_m3=result.numeric_mass_tolerance_m3,
                diagnostic_only=result.diagnostic_only,
            )
        )
        state = result.next_stock
    return InstrumentedPhysicalRolloutResult(
        operator_schema=BRANCHING_NETWORK_TRANSPORT_OPERATOR_SCHEMA,
        final_state=state,
        prediction_rows=tuple(rows),
        telemetry=recorder.compile(),
    )


def run_instrumented_kinematic_rollout(
    operator: BranchingFiniteVolumeKinematicWaveOperator,
    initial_state: KinematicWaveState,
    steps: tuple[InstrumentedKinematicStepInput, ...],
    *,
    telemetry_config: InternalInnovationTelemetryConfig,
) -> InstrumentedPhysicalRolloutResult:
    if not isinstance(operator, BranchingFiniteVolumeKinematicWaveOperator):
        raise TypeError("branching_kinematic_operator_required")
    if not isinstance(initial_state, KinematicWaveState):
        raise TypeError("kinematic_wave_state_required")
    if telemetry_config.operator_schema != BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA:
        raise ValueError("instrumented_kinematic_telemetry_operator_mismatch")
    if not steps or any(not isinstance(step, InstrumentedKinematicStepInput) for step in steps):
        raise ValueError("instrumented_kinematic_steps_required")

    recorder = InternalInnovationTelemetryRecorder(operator.network, telemetry_config)
    state = initial_state
    rows: list[dict[str, object]] = []
    for step_index, step in enumerate(steps):
        result = operator.step(
            state,
            action=step.action,
            forcing=step.forcing,
            forcing_support=step.forcing_support,
            provenance_id=step.next_state_provenance_id,
        )
        recorder.record_step(
            state,
            result,
            support_start=step.support_start,
            support_end=step.support_end,
            inputs_available_at=step.inputs_available_at,
            input_provenance_ids=_input_provenance_ids(
                state,
                step.action,
                step.forcing,
                step.forcing_support,
            ),
        )
        rows.append(
            _prediction_row(
                step_index=step_index,
                support_start=step.support_start,
                support_end=step.support_end,
                outlet_mean_flow_m3s=result.outlet_mean_flow_m3s,
                residual_m3=result.global_mass_balance_residual_m3,
                tolerance_m3=result.numeric_mass_tolerance_m3,
                diagnostic_only=result.diagnostic_only,
            )
        )
        state = result.next_state
    return InstrumentedPhysicalRolloutResult(
        operator_schema=BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA,
        final_state=state,
        prediction_rows=tuple(rows),
        telemetry=recorder.compile(),
    )


def _input_provenance_ids(
    state: StockState | KinematicWaveState,
    *values: object,
) -> tuple[str, ...]:
    provenance = [state.provenance_id]
    for value in values:
        if value is None:
            continue
        provenance_id = getattr(value, "provenance_id", None)
        if not isinstance(provenance_id, str) or not provenance_id.strip():
            raise ValueError("instrumented_rollout_input_provenance_missing")
        provenance.append(provenance_id)
    return tuple(dict.fromkeys(provenance))


def _prediction_row(
    *,
    step_index: int,
    support_start: datetime,
    support_end: datetime,
    outlet_mean_flow_m3s: float,
    residual_m3: float,
    tolerance_m3: float,
    diagnostic_only: bool,
) -> dict[str, object]:
    return {
        "step_index": step_index,
        "support_start_utc": support_start.isoformat(),
        "support_end_utc": support_end.isoformat(),
        "physical_outlet_mean_flow_m3s": float(outlet_mean_flow_m3s),
        "global_mass_balance_residual_m3": float(residual_m3),
        "numeric_mass_tolerance_m3": float(tolerance_m3),
        "diagnostic_only": bool(diagnostic_only),
    }
