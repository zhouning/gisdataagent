"""State-dependent conservative transport over a linear-referenced reach path."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.linalg import expm

from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    LinearReferencedPath,
    ReachHydraulicState,
    StockState,
)


REACH_TRANSPORT_OPERATOR_SCHEMA = (
    "gwm.geospatial_kernel.state_dependent_reach_transport.v1"
)


@dataclass(frozen=True)
class ReachTransportConfig:
    timestep_seconds: float
    path_admitted: bool = False
    operator_form_admitted: bool = False
    allow_unadmitted_components_for_diagnostics: bool = False
    zero_effective_length_tolerance_m: float = 1e-6
    absolute_mass_tolerance_m3: float = 1e-6

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, bool)
            for value in (
                self.path_admitted,
                self.operator_form_admitted,
                self.allow_unadmitted_components_for_diagnostics,
            )
        ):
            raise ValueError("reach_transport_admission_flags_must_be_boolean")
        for value, error in (
            (self.timestep_seconds, "reach_transport_timestep_must_be_positive"),
            (
                self.zero_effective_length_tolerance_m,
                "reach_transport_length_tolerance_must_be_nonnegative",
            ),
            (
                self.absolute_mass_tolerance_m3,
                "reach_transport_mass_tolerance_must_be_nonnegative",
            ),
        ):
            if not np.isfinite(value):
                raise ValueError(error)
        if self.timestep_seconds <= 0.0:
            raise ValueError("reach_transport_timestep_must_be_positive")
        if self.zero_effective_length_tolerance_m < 0.0:
            raise ValueError("reach_transport_length_tolerance_must_be_nonnegative")
        if self.absolute_mass_tolerance_m3 < 0.0:
            raise ValueError("reach_transport_mass_tolerance_must_be_nonnegative")


@dataclass(frozen=True)
class ReachTransportResult:
    next_stock: StockState
    active_feature_ids: tuple[int, ...]
    excluded_zero_length_feature_ids: tuple[int, ...]
    reach_residence_time_seconds: tuple[float, ...]
    reach_mean_outflow_m3s: tuple[float, ...]
    input_volume_m3: float
    outlet_volume_m3: float
    global_mass_balance_residual_m3: float
    hydraulic_quantity: str
    path_admitted: bool
    hydraulics_admitted: bool
    operator_form_admitted: bool
    flood_wave_transport_admitted: bool
    diagnostic_only: bool

    @property
    def outlet_mean_flow_m3s(self) -> float:
        return self.reach_mean_outflow_m3s[-1]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": REACH_TRANSPORT_OPERATOR_SCHEMA,
            "next_stock_m3": list(self.next_stock.values),
            "active_feature_ids": list(self.active_feature_ids),
            "excluded_zero_length_feature_ids": list(
                self.excluded_zero_length_feature_ids
            ),
            "reach_residence_time_seconds": list(
                self.reach_residence_time_seconds
            ),
            "reach_mean_outflow_m3s": list(self.reach_mean_outflow_m3s),
            "outlet_mean_flow_m3s": self.outlet_mean_flow_m3s,
            "input_volume_m3": self.input_volume_m3,
            "outlet_volume_m3": self.outlet_volume_m3,
            "global_mass_balance_residual_m3": (
                self.global_mass_balance_residual_m3
            ),
            "hydraulic_quantity": self.hydraulic_quantity,
            "path_admitted": self.path_admitted,
            "hydraulics_admitted": self.hydraulics_admitted,
            "operator_form_admitted": self.operator_form_admitted,
            "flood_wave_transport_admitted": self.flood_wave_transport_admitted,
            "diagnostic_only": self.diagnostic_only,
        }


class StateDependentReachTransportOperator:
    """Route nonnegative flux through an ordered cascade of reach storages.

    Each active linear-referenced reach is a first-order conservative reservoir
    with state-specific residence time ``K_i = length_i / speed_i``. The exact
    matrix exponential advances storage and integrated outflow for a constant
    input over the step. This is a diagnostic response kernel, not a claim that
    river velocity is flood-wave celerity or that a linear-reservoir cascade is
    a validated hydrodynamic model.
    """

    def __init__(
        self,
        path: LinearReferencedPath,
        config: ReachTransportConfig,
    ) -> None:
        self.path = path
        self.config = config
        effective = np.asarray(path.effective_lengths_m, dtype=float)
        active_mask = effective > config.zero_effective_length_tolerance_m
        if not bool(active_mask.any()):
            raise ValueError("reach_transport_active_path_required")
        self.active_indices = tuple(int(value) for value in np.flatnonzero(active_mask))
        self.active_feature_ids = tuple(path.feature_ids[index] for index in self.active_indices)
        self.excluded_zero_length_feature_ids = tuple(
            feature_id
            for feature_id, active in zip(path.feature_ids, active_mask, strict=True)
            if not active
        )
        self.effective_lengths_m = tuple(
            float(effective[index]) for index in self.active_indices
        )

    def zero_state(self, *, provenance_id: str) -> StockState:
        return StockState(
            values=(0.0,) * len(self.active_feature_ids),
            unit="m3",
            provenance_id=provenance_id,
        )

    def step(
        self,
        stock: StockState,
        hydraulics: ReachHydraulicState,
        *,
        action: ActionBoundaryFlux | None = None,
        forcing: ForcingFlux | None = None,
    ) -> ReachTransportResult:
        self._validate_inputs(
            stock=stock,
            hydraulics=hydraulics,
            action=action,
            forcing=forcing,
        )
        count = len(self.active_feature_ids)
        dt = float(self.config.timestep_seconds)
        initial = np.asarray(stock.values, dtype=float)
        action_rate = _values_or_zeros(action, count)
        forcing_rate = _values_or_zeros(forcing, count)
        input_rate = action_rate + forcing_rate
        speeds = np.asarray(hydraulics.propagation_speed_mps, dtype=float)
        residence_time = np.asarray(self.effective_lengths_m, dtype=float) / speeds

        generator = np.zeros((2 * count + 1, 2 * count + 1), dtype=float)
        constant_index = 2 * count
        inverse_residence = 1.0 / residence_time
        state_indices = np.arange(count)
        cumulative_indices = count + state_indices
        generator[state_indices, state_indices] = -inverse_residence
        if count > 1:
            generator[state_indices[1:], state_indices[:-1]] = inverse_residence[:-1]
        generator[state_indices, constant_index] = input_rate
        generator[cumulative_indices, state_indices] = inverse_residence

        initial_augmented = np.zeros(2 * count + 1, dtype=float)
        initial_augmented[:count] = initial
        initial_augmented[constant_index] = 1.0
        advanced = expm(generator * dt) @ initial_augmented
        next_values = advanced[:count]
        transferred_volume = advanced[count : 2 * count]

        numeric_scale = max(
            1.0,
            float(initial.sum()),
            float(input_rate.sum() * dt),
        )
        numeric_tolerance = (
            self.config.absolute_mass_tolerance_m3
            + np.finfo(float).eps * 1_000.0 * numeric_scale
        )
        if bool((next_values < -numeric_tolerance).any()) or bool(
            (transferred_volume < -numeric_tolerance).any()
        ):
            raise RuntimeError("reach_transport_exponential_produced_negative_volume")
        next_values[np.abs(next_values) <= numeric_tolerance] = 0.0
        transferred_volume[np.abs(transferred_volume) <= numeric_tolerance] = 0.0
        next_values = np.maximum(next_values, 0.0)
        transferred_volume = np.maximum(transferred_volume, 0.0)

        input_volume = float(input_rate.sum() * dt)
        outlet_volume = float(transferred_volume[-1])
        residual = float(
            next_values.sum() + outlet_volume - initial.sum() - input_volume
        )
        if abs(residual) > numeric_tolerance:
            raise RuntimeError("reach_transport_global_mass_balance_exceeded")

        admitted = (
            self.config.path_admitted
            and hydraulics.admitted_as_flood_wave_celerity
            and self.config.operator_form_admitted
        )
        provenance = (
            f"state_dependent_reach_transport|{self.path.provenance_id}|"
            f"{stock.provenance_id}|{hydraulics.provenance_id}"
        )
        return ReachTransportResult(
            next_stock=StockState(
                values=tuple(float(value) for value in next_values),
                unit="m3",
                provenance_id=provenance,
            ),
            active_feature_ids=self.active_feature_ids,
            excluded_zero_length_feature_ids=(
                self.excluded_zero_length_feature_ids
            ),
            reach_residence_time_seconds=tuple(
                float(value) for value in residence_time
            ),
            reach_mean_outflow_m3s=tuple(
                float(value / dt) for value in transferred_volume
            ),
            input_volume_m3=input_volume,
            outlet_volume_m3=outlet_volume,
            global_mass_balance_residual_m3=residual,
            hydraulic_quantity=hydraulics.quantity,
            path_admitted=self.config.path_admitted,
            hydraulics_admitted=hydraulics.admitted_as_flood_wave_celerity,
            operator_form_admitted=self.config.operator_form_admitted,
            flood_wave_transport_admitted=admitted,
            diagnostic_only=not admitted,
        )

    def _validate_inputs(
        self,
        *,
        stock: StockState,
        hydraulics: ReachHydraulicState,
        action: ActionBoundaryFlux | None,
        forcing: ForcingFlux | None,
    ) -> None:
        if not isinstance(stock, StockState):
            raise TypeError("stock_state_required")
        if not isinstance(hydraulics, ReachHydraulicState):
            raise TypeError("reach_hydraulic_state_required")
        if action is not None and not isinstance(action, ActionBoundaryFlux):
            raise TypeError("action_boundary_flux_required")
        if forcing is not None and not isinstance(forcing, ForcingFlux):
            raise TypeError("forcing_flux_required")
        count = len(self.active_feature_ids)
        if stock.unit != "m3" or len(stock.values) != count:
            raise ValueError("reach_transport_stock_contract_mismatch")
        if hydraulics.feature_ids != self.active_feature_ids:
            raise ValueError("reach_hydraulic_feature_order_mismatch")
        components_admitted = (
            self.config.path_admitted
            and hydraulics.admitted_as_flood_wave_celerity
            and self.config.operator_form_admitted
        )
        if (
            not components_admitted
            and not self.config.allow_unadmitted_components_for_diagnostics
        ):
            raise ValueError(
                "unadmitted_reach_transport_components_require_explicit_diagnostic_mode"
            )
        for name, field in (("action", action), ("forcing", forcing)):
            if field is None:
                continue
            if field.unit != "m3 s-1" or len(field.values) != count:
                raise ValueError(f"reach_transport_{name}_contract_mismatch")
            if (np.asarray(field.values, dtype=float) < 0.0).any():
                raise ValueError(f"reach_transport_{name}_must_be_nonnegative")
        if action is not None and any(
            value != 0.0 for value in action.values[1:]
        ):
            raise ValueError("reach_transport_action_must_enter_path_boundary")


def _values_or_zeros(
    field: ActionBoundaryFlux | ForcingFlux | None,
    count: int,
) -> np.ndarray:
    if field is None:
        return np.zeros(count, dtype=float)
    return np.asarray(field.values, dtype=float)
