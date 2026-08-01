"""Run controlled local perturbations around public observed reach states."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .dynamic_wave_flux import (
    DynamicWaveHomogeneousStep,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
    advance_prismatic_dynamic_wave_periodic,
    maximum_stable_timestep_seconds,
)
from .public_reach_geometry_response import (
    PublicReachGeometryResponseAudit,
    compile_public_reach_geometry_response_audit,
)


PUBLIC_REACH_LOCAL_PERTURBATION_SCHEMA = (
    "gwm.geospatial_kernel.public_reach_local_perturbation.v1"
)
AREA_MULTIPLIERS = (1.05, 1.0, 0.95, 1.0)
DISCHARGE_MULTIPLIERS = (1.0, 1.05, 1.0, 0.95)
REVERSAL_SHIFT_CELLS = 2
NUMERICAL_CELL_LENGTH_M = 100.0
TARGET_COURANT_NUMBER = 0.4
LEDGER_TOLERANCE = 1e-10
REVERSAL_TOLERANCE = 1e-12
TRANSITION_RESPONSE_MATERIALITY = 0.01


@dataclass(frozen=True)
class GeometryPerturbationStep:
    geometry_id: str
    geometry_stable_timestep_seconds: float
    shared_timestep_seconds: float
    forward: DynamicWaveHomogeneousStep
    reversed_perturbation: DynamicWaveHomogeneousStep
    reversal_area_covariance_error_m2: float
    reversal_discharge_covariance_error_m3s: float
    area_amplitude_retention_ratio: float
    discharge_amplitude_retention_ratio: float

    def __post_init__(self) -> None:
        scalars = (
            self.geometry_stable_timestep_seconds,
            self.shared_timestep_seconds,
            self.reversal_area_covariance_error_m2,
            self.reversal_discharge_covariance_error_m3s,
            self.area_amplitude_retention_ratio,
            self.discharge_amplitude_retention_ratio,
        )
        if (
            not self.geometry_id
            or any(not math.isfinite(value) for value in scalars)
            or self.geometry_stable_timestep_seconds <= 0.0
            or self.shared_timestep_seconds <= 0.0
            or self.shared_timestep_seconds
            > self.geometry_stable_timestep_seconds + 1e-12
            or self.forward.maximum_courant_number
            > TARGET_COURANT_NUMBER + 1e-12
            or not self.forward.finite_state
            or not self.forward.nonnegative_area
            or abs(self.forward.volume_balance_error_m3) > LEDGER_TOLERANCE
            or abs(self.forward.discharge_integral_balance_error_m4s)
            > LEDGER_TOLERANCE
            or self.reversal_area_covariance_error_m2 > REVERSAL_TOLERANCE
            or self.reversal_discharge_covariance_error_m3s
            > REVERSAL_TOLERANCE
        ):
            raise ValueError("public_reach_geometry_perturbation_step_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "geometry_id": self.geometry_id,
            "geometry_stable_timestep_seconds": (
                self.geometry_stable_timestep_seconds
            ),
            "shared_timestep_seconds": self.shared_timestep_seconds,
            "maximum_courant_number": self.forward.maximum_courant_number,
            "state_after": {
                "area_m2": list(self.forward.state.area_m2),
                "discharge_m3s": list(self.forward.state.discharge_m3s),
                "minimum_area_m2": self.forward.minimum_area_m2,
            },
            "periodic_ledgers": {
                "volume_balance_error_m3": self.forward.volume_balance_error_m3,
                "discharge_integral_balance_error_m4s": (
                    self.forward.discharge_integral_balance_error_m4s
                ),
            },
            "perturbation_reversal": {
                "shift_cells": REVERSAL_SHIFT_CELLS,
                "area_covariance_error_m2": (
                    self.reversal_area_covariance_error_m2
                ),
                "discharge_covariance_error_m3s": (
                    self.reversal_discharge_covariance_error_m3s
                ),
            },
            "amplitude_retention": {
                "area_ratio": self.area_amplitude_retention_ratio,
                "discharge_ratio": self.discharge_amplitude_retention_ratio,
            },
            "diagnostic_only": True,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class ObservedAnchorLocalPerturbation:
    measurement_id: str
    time: str
    anchor_area_m2: float
    anchor_discharge_m3s: float
    input_state: PrismaticDynamicWaveState
    reversed_input_state: PrismaticDynamicWaveState
    shared_timestep_seconds: float
    limiting_geometry_id: str
    state_conditioned_rectangle: GeometryPerturbationStep
    bridge_trapezoid_candidate: GeometryPerturbationStep
    area_geometry_response_l2_relative: float
    discharge_geometry_response_l2_relative: float
    maximum_area_geometry_response_relative: float
    maximum_discharge_geometry_response_relative: float

    def __post_init__(self) -> None:
        values = (
            self.anchor_area_m2,
            self.anchor_discharge_m3s,
            self.shared_timestep_seconds,
            self.area_geometry_response_l2_relative,
            self.discharge_geometry_response_l2_relative,
            self.maximum_area_geometry_response_relative,
            self.maximum_discharge_geometry_response_relative,
        )
        if (
            not self.measurement_id
            or any(not math.isfinite(value) or value < 0.0 for value in values)
            or self.anchor_area_m2 <= 0.0
            or self.anchor_discharge_m3s <= 0.0
            or self.shared_timestep_seconds <= 0.0
            or self.limiting_geometry_id
            not in {
                "state_conditioned_observed_rectangle",
                "stage24_bridge_trapezoid_candidate",
            }
            or self.state_conditioned_rectangle.shared_timestep_seconds
            != self.shared_timestep_seconds
            or self.bridge_trapezoid_candidate.shared_timestep_seconds
            != self.shared_timestep_seconds
        ):
            raise ValueError("public_reach_observed_anchor_perturbation_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "measurement_id": self.measurement_id,
            "time": self.time,
            "observed_anchor": {
                "area_m2": self.anchor_area_m2,
                "discharge_m3s": self.anchor_discharge_m3s,
            },
            "manufactured_periodic_input": {
                "area_m2": list(self.input_state.area_m2),
                "discharge_m3s": list(self.input_state.discharge_m3s),
                "area_multipliers": list(AREA_MULTIPLIERS),
                "discharge_multipliers": list(DISCHARGE_MULTIPLIERS),
                "reversed_area_m2": list(self.reversed_input_state.area_m2),
                "reversed_discharge_m3s": list(
                    self.reversed_input_state.discharge_m3s
                ),
            },
            "shared_timestep_seconds": self.shared_timestep_seconds,
            "limiting_geometry_id": self.limiting_geometry_id,
            "state_conditioned_rectangle": (
                self.state_conditioned_rectangle.as_dict()
            ),
            "bridge_trapezoid_candidate": (
                self.bridge_trapezoid_candidate.as_dict()
            ),
            "geometry_response_after_one_step": {
                "area_l2_relative": self.area_geometry_response_l2_relative,
                "discharge_l2_relative": (
                    self.discharge_geometry_response_l2_relative
                ),
                "maximum_area_relative": (
                    self.maximum_area_geometry_response_relative
                ),
                "maximum_discharge_relative": (
                    self.maximum_discharge_geometry_response_relative
                ),
            },
        }


@dataclass(frozen=True)
class PublicReachLocalPerturbationAudit:
    source: PublicReachGeometryResponseAudit
    perturbations: tuple[ObservedAnchorLocalPerturbation, ...]

    def __post_init__(self) -> None:
        source_ids = tuple(value.measurement_id for value in self.source.responses)
        if (
            len(self.perturbations) != 20
            or tuple(value.measurement_id for value in self.perturbations)
            != source_ids
        ):
            raise ValueError("public_reach_local_perturbation_audit_invalid")

    def require_observed_spatial_rollout(self) -> None:
        raise ValueError("public_reach_local_perturbation_is_manufactured")

    def require_real_reach_discretization(self) -> None:
        raise ValueError("public_reach_local_perturbation_grid_is_numerical")

    def require_runtime_operator(self) -> None:
        raise ValueError("public_reach_local_perturbation_operator_unadmitted")

    def as_dict(self) -> dict[str, object]:
        distributions = {
            "shared_timestep_seconds": _distribution(
                [value.shared_timestep_seconds for value in self.perturbations]
            ),
            "area_geometry_response_l2_relative": _distribution(
                [
                    value.area_geometry_response_l2_relative
                    for value in self.perturbations
                ]
            ),
            "discharge_geometry_response_l2_relative": _distribution(
                [
                    value.discharge_geometry_response_l2_relative
                    for value in self.perturbations
                ]
            ),
            "maximum_area_geometry_response_relative": _distribution(
                [
                    value.maximum_area_geometry_response_relative
                    for value in self.perturbations
                ]
            ),
            "maximum_discharge_geometry_response_relative": _distribution(
                [
                    value.maximum_discharge_geometry_response_relative
                    for value in self.perturbations
                ]
            ),
            "stable_timestep_candidate_relative_to_rectangle": _distribution(
                [
                    value.bridge_trapezoid_candidate
                    .geometry_stable_timestep_seconds
                    / value.state_conditioned_rectangle
                    .geometry_stable_timestep_seconds
                    - 1.0
                    for value in self.perturbations
                ]
            ),
        }
        steps = [
            step
            for value in self.perturbations
            for step in (
                value.state_conditioned_rectangle,
                value.bridge_trapezoid_candidate,
            )
        ]
        return {
            "schema": PUBLIC_REACH_LOCAL_PERTURBATION_SCHEMA,
            "source_schema": self.source.as_dict()["schema"],
            "monitoring_location_id": (
                self.source.source.source.monitoring_location_id
            ),
            "reach_id": self.source.source.source.reach_id,
            "observed_anchor_count": len(self.perturbations),
            "perturbation_contract": {
                "area_multipliers": list(AREA_MULTIPLIERS),
                "discharge_multipliers": list(DISCHARGE_MULTIPLIERS),
                "area_and_discharge_perturbation_fraction": 0.05,
                "reversal_shift_cells": REVERSAL_SHIFT_CELLS,
                "cell_count": 4,
                "numerical_cell_length_m": NUMERICAL_CELL_LENGTH_M,
                "cell_length_is_observed_reach_discretization": False,
                "periodic_ring_is_real_reach_topology": False,
                "target_courant_number": TARGET_COURANT_NUMBER,
                "shared_timestep_is_minimum_across_geometries": True,
                "anchor_state_observed": True,
                "perturbed_states_observed": False,
            },
            "response_distributions": distributions,
            "limiting_geometry_counts": _counts(
                value.limiting_geometry_id for value in self.perturbations
            ),
            "maximum_absolute_volume_ledger_error_m3": max(
                abs(value.forward.volume_balance_error_m3) for value in steps
            ),
            "maximum_absolute_discharge_ledger_error_m4s": max(
                abs(value.forward.discharge_integral_balance_error_m4s)
                for value in steps
            ),
            "maximum_reversal_area_covariance_error_m2": max(
                value.reversal_area_covariance_error_m2 for value in steps
            ),
            "maximum_reversal_discharge_covariance_error_m3s": max(
                value.reversal_discharge_covariance_error_m3s for value in steps
            ),
            "maximum_courant_number": max(
                value.forward.maximum_courant_number for value in steps
            ),
            "minimum_area_after_m2": min(
                value.forward.minimum_area_m2 for value in steps
            ),
            "transition_response_is_material_for_at_least_one_anchor": (
                distributions["maximum_discharge_geometry_response_relative"][
                    "maximum"
                ]
                > TRANSITION_RESPONSE_MATERIALITY
            ),
            "perturbations": [value.as_dict() for value in self.perturbations],
            "decision": {
                "local_hll_transition_exercised": True,
                "periodic_mass_and_momentum_conserved": True,
                "perturbation_reversal_covariant": True,
                "geometry_changes_local_transition": True,
                "observed_spatial_rollout_completed": False,
                "real_reach_grid_admitted": False,
                "runtime_operator_admitted": False,
                "operator_admitted": False,
            },
            "claim_boundary": {
                "observed_states_used_as_anchors": True,
                "perturbed_states_observed": False,
                "periodic_ring_represents_real_reach": False,
                "reach_boundary_conditions_observed": False,
                "confluence_geometry_completed": False,
                "operator_admitted": False,
            },
        }


def compile_public_reach_local_perturbation_audit(
    source: PublicReachGeometryResponseAudit | None = None,
) -> PublicReachLocalPerturbationAudit:
    if source is None:
        source = compile_public_reach_geometry_response_audit()
    measurement_by_id = {
        value.measurement_id: value
        for value in source.source.source.measurements
    }
    candidate_section = source.source.candidate.section
    perturbations = []
    for response in source.responses:
        measurement = measurement_by_id[response.measurement_id]
        state = _perturbed_state(
            measurement.flow_area_m2, measurement.flow_m3s
        )
        reversed_state = _rotate_state(state, REVERSAL_SHIFT_CELLS)
        sections = (
            (
                "state_conditioned_observed_rectangle",
                measurement.equivalent_section,
            ),
            ("stage24_bridge_trapezoid_candidate", candidate_section),
        )
        stable = {
            geometry_id: maximum_stable_timestep_seconds(
                state,
                section,
                cell_length_m=NUMERICAL_CELL_LENGTH_M,
                courant_number=TARGET_COURANT_NUMBER,
            )
            for geometry_id, section in sections
        }
        shared_timestep = min(stable.values())
        limiting_geometry = min(stable, key=stable.__getitem__)
        steps = {
            geometry_id: _advance_geometry(
                geometry_id,
                state,
                reversed_state,
                section,
                stable[geometry_id],
                shared_timestep,
                measurement.flow_area_m2,
                measurement.flow_m3s,
            )
            for geometry_id, section in sections
        }
        rectangle = steps["state_conditioned_observed_rectangle"]
        candidate = steps["stage24_bridge_trapezoid_candidate"]
        area_differences = tuple(
            candidate_value - rectangle_value
            for candidate_value, rectangle_value in zip(
                candidate.forward.state.area_m2,
                rectangle.forward.state.area_m2,
                strict=True,
            )
        )
        discharge_differences = tuple(
            candidate_value - rectangle_value
            for candidate_value, rectangle_value in zip(
                candidate.forward.state.discharge_m3s,
                rectangle.forward.state.discharge_m3s,
                strict=True,
            )
        )
        perturbations.append(
            ObservedAnchorLocalPerturbation(
                measurement_id=response.measurement_id,
                time=response.time,
                anchor_area_m2=measurement.flow_area_m2,
                anchor_discharge_m3s=measurement.flow_m3s,
                input_state=state,
                reversed_input_state=reversed_state,
                shared_timestep_seconds=shared_timestep,
                limiting_geometry_id=limiting_geometry,
                state_conditioned_rectangle=rectangle,
                bridge_trapezoid_candidate=candidate,
                area_geometry_response_l2_relative=(
                    _root_mean_square(area_differences)
                    / measurement.flow_area_m2
                ),
                discharge_geometry_response_l2_relative=(
                    _root_mean_square(discharge_differences)
                    / measurement.flow_m3s
                ),
                maximum_area_geometry_response_relative=(
                    max(abs(value) for value in area_differences)
                    / measurement.flow_area_m2
                ),
                maximum_discharge_geometry_response_relative=(
                    max(abs(value) for value in discharge_differences)
                    / measurement.flow_m3s
                ),
            )
        )
    return PublicReachLocalPerturbationAudit(source, tuple(perturbations))


def _advance_geometry(
    geometry_id: str,
    state: PrismaticDynamicWaveState,
    reversed_state: PrismaticDynamicWaveState,
    section: TrapezoidalChannelSection,
    stable_timestep: float,
    shared_timestep: float,
    anchor_area: float,
    anchor_discharge: float,
) -> GeometryPerturbationStep:
    forward = _advance(state, section, shared_timestep)
    reversed_result = _advance(reversed_state, section, shared_timestep)
    expected_reversed = _rotate_state(forward.state, REVERSAL_SHIFT_CELLS)
    area_error = max(
        abs(actual - expected)
        for actual, expected in zip(
            reversed_result.state.area_m2,
            expected_reversed.area_m2,
            strict=True,
        )
    )
    discharge_error = max(
        abs(actual - expected)
        for actual, expected in zip(
            reversed_result.state.discharge_m3s,
            expected_reversed.discharge_m3s,
            strict=True,
        )
    )
    return GeometryPerturbationStep(
        geometry_id=geometry_id,
        geometry_stable_timestep_seconds=stable_timestep,
        shared_timestep_seconds=shared_timestep,
        forward=forward,
        reversed_perturbation=reversed_result,
        reversal_area_covariance_error_m2=area_error,
        reversal_discharge_covariance_error_m3s=discharge_error,
        area_amplitude_retention_ratio=(
            (max(forward.state.area_m2) - min(forward.state.area_m2))
            / (0.1 * anchor_area)
        ),
        discharge_amplitude_retention_ratio=(
            (
                max(forward.state.discharge_m3s)
                - min(forward.state.discharge_m3s)
            )
            / (0.1 * anchor_discharge)
        ),
    )


def _advance(
    state: PrismaticDynamicWaveState,
    section: TrapezoidalChannelSection,
    timestep: float,
) -> DynamicWaveHomogeneousStep:
    return advance_prismatic_dynamic_wave_periodic(
        state,
        section,
        cell_length_m=NUMERICAL_CELL_LENGTH_M,
        timestep_seconds=timestep,
        maximum_courant_number=TARGET_COURANT_NUMBER,
    )


def _perturbed_state(area: float, discharge: float) -> PrismaticDynamicWaveState:
    return PrismaticDynamicWaveState(
        area_m2=tuple(area * value for value in AREA_MULTIPLIERS),
        discharge_m3s=tuple(
            discharge * value for value in DISCHARGE_MULTIPLIERS
        ),
    )


def _rotate_state(
    state: PrismaticDynamicWaveState, shift: int
) -> PrismaticDynamicWaveState:
    offset = shift % state.cell_count
    return PrismaticDynamicWaveState(
        area_m2=state.area_m2[-offset:] + state.area_m2[:-offset],
        discharge_m3s=(
            state.discharge_m3s[-offset:] + state.discharge_m3s[:-offset]
        ),
    )


def _root_mean_square(values: tuple[float, ...]) -> float:
    return math.sqrt(sum(value**2 for value in values) / len(values))


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "minimum": ordered[0],
        "p05": _quantile(ordered, 0.05),
        "median": _quantile(ordered, 0.5),
        "p95": _quantile(ordered, 0.95),
        "maximum": ordered[-1],
        "maximum_absolute": max(abs(value) for value in ordered),
    }


def _quantile(ordered: list[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _counts(values) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))
