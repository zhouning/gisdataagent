"""Nonlinear conservative reach storage driven by admitted Manning geometry."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    LinearReferencedPath,
    ReachForcingSupport,
    ReachHydraulicGeometry,
    StockState,
)


NONLINEAR_REACH_TRANSPORT_OPERATOR_SCHEMA = (
    "gwm.geospatial_kernel.nonlinear_manning_reach_storage.v2"
)


@dataclass(frozen=True)
class NonlinearReachTransportConfig:
    timestep_seconds: float
    path_admitted: bool = False
    operator_form_admitted: bool = False
    allow_unadmitted_components_for_diagnostics: bool = False
    zero_effective_length_tolerance_m: float = 1e-6
    partial_reach_tolerance_m: float = 1e-6
    root_relative_tolerance: float = 1e-12
    root_absolute_tolerance_m3: float = 1e-10
    integration_substep_seconds: float = 300.0
    absolute_mass_tolerance_m3: float = 1e-6
    relative_mass_tolerance: float = 1e-9

    def __post_init__(self) -> None:
        flags = (
            self.path_admitted,
            self.operator_form_admitted,
            self.allow_unadmitted_components_for_diagnostics,
        )
        if any(not isinstance(value, bool) for value in flags):
            raise ValueError("nonlinear_reach_transport_admission_flags_must_be_boolean")
        positive = (
            (self.timestep_seconds, "nonlinear_reach_transport_timestep_must_be_positive"),
            (
                self.root_relative_tolerance,
                "nonlinear_reach_transport_root_rtol_must_be_positive",
            ),
            (
                self.root_absolute_tolerance_m3,
                "nonlinear_reach_transport_root_atol_must_be_positive",
            ),
            (
                self.integration_substep_seconds,
                "nonlinear_reach_transport_substep_must_be_positive",
            ),
            (
                self.relative_mass_tolerance,
                "nonlinear_reach_transport_relative_mass_tolerance_must_be_positive",
            ),
        )
        for value, error in positive:
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(error)
        nonnegative = (
            (
                self.zero_effective_length_tolerance_m,
                "nonlinear_reach_transport_length_tolerance_must_be_nonnegative",
            ),
            (
                self.partial_reach_tolerance_m,
                "nonlinear_reach_transport_partial_tolerance_must_be_nonnegative",
            ),
            (
                self.absolute_mass_tolerance_m3,
                "nonlinear_reach_transport_mass_tolerance_must_be_nonnegative",
            ),
        )
        for value, error in nonnegative:
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(error)


@dataclass(frozen=True)
class NonlinearReachTransportResult:
    next_stock: StockState
    active_feature_ids: tuple[int, ...]
    excluded_zero_length_feature_ids: tuple[int, ...]
    partial_reach_feature_ids: tuple[int, ...]
    reach_mean_outflow_m3s: tuple[float, ...]
    reach_end_depth_m: tuple[float, ...]
    input_volume_m3: float
    outlet_volume_m3: float
    global_mass_balance_residual_m3: float
    numeric_mass_tolerance_m3: float
    solver_function_evaluation_count: int
    solver_root_iteration_count: int
    path_admitted: bool
    geometry_admitted: bool
    operator_form_admitted: bool
    forcing_support_required: bool
    forcing_support_admitted: bool
    forcing_coverage_fractions: tuple[float, ...]
    raw_forcing_volume_m3: float
    applied_forcing_volume_m3: float
    excluded_forcing_volume_m3: float
    nonlinear_transport_admitted: bool
    diagnostic_only: bool

    @property
    def outlet_mean_flow_m3s(self) -> float:
        return self.reach_mean_outflow_m3s[-1]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": NONLINEAR_REACH_TRANSPORT_OPERATOR_SCHEMA,
            "next_stock_m3": list(self.next_stock.values),
            "active_feature_ids": list(self.active_feature_ids),
            "excluded_zero_length_feature_ids": list(
                self.excluded_zero_length_feature_ids
            ),
            "partial_reach_feature_ids": list(self.partial_reach_feature_ids),
            "reach_mean_outflow_m3s": list(self.reach_mean_outflow_m3s),
            "reach_end_depth_m": list(self.reach_end_depth_m),
            "outlet_mean_flow_m3s": self.outlet_mean_flow_m3s,
            "input_volume_m3": self.input_volume_m3,
            "outlet_volume_m3": self.outlet_volume_m3,
            "global_mass_balance_residual_m3": (
                self.global_mass_balance_residual_m3
            ),
            "numeric_mass_tolerance_m3": self.numeric_mass_tolerance_m3,
            "solver_function_evaluation_count": (
                self.solver_function_evaluation_count
            ),
            "solver_root_iteration_count": (
                self.solver_root_iteration_count
            ),
            "path_admitted": self.path_admitted,
            "geometry_admitted": self.geometry_admitted,
            "operator_form_admitted": self.operator_form_admitted,
            "forcing_support_required": self.forcing_support_required,
            "forcing_support_admitted": self.forcing_support_admitted,
            "forcing_coverage_fractions": list(self.forcing_coverage_fractions),
            "raw_forcing_volume_m3": self.raw_forcing_volume_m3,
            "applied_forcing_volume_m3": self.applied_forcing_volume_m3,
            "excluded_forcing_volume_m3": self.excluded_forcing_volume_m3,
            "nonlinear_transport_admitted": self.nonlinear_transport_admitted,
            "diagnostic_only": self.diagnostic_only,
        }


class NonlinearManningReachTransportOperator:
    """Advance a directed chain of nonlinear Manning reach storages.

    This is a research response operator, not Muskingum-Cunge, a kinematic-wave
    PDE, or a hydrodynamic solver. Geometry controls a nonlinear state-discharge
    relation; topology controls which upstream outflow enters each reach.
    """

    def __init__(
        self,
        path: LinearReferencedPath,
        config: NonlinearReachTransportConfig,
    ) -> None:
        self.path = path
        self.config = config
        effective = np.asarray(path.effective_lengths_m, dtype=float)
        full = np.asarray(path.full_lengths_m, dtype=float)
        active_mask = effective > config.zero_effective_length_tolerance_m
        if not bool(active_mask.any()):
            raise ValueError("nonlinear_reach_transport_active_path_required")
        self.active_indices = tuple(int(value) for value in np.flatnonzero(active_mask))
        self.active_feature_ids = tuple(path.feature_ids[index] for index in self.active_indices)
        self.excluded_zero_length_feature_ids = tuple(
            feature_id
            for feature_id, active in zip(path.feature_ids, active_mask, strict=True)
            if not active
        )
        self.effective_lengths_m = np.asarray(
            [effective[index] for index in self.active_indices], dtype=float
        )
        self.partial_reach_feature_ids = tuple(
            path.feature_ids[index]
            for index in self.active_indices
            if full[index] - effective[index] > config.partial_reach_tolerance_m
        )
        partial = set(self.partial_reach_feature_ids)
        self.partial_reach_active_indices = tuple(
            index
            for index, feature_id in enumerate(self.active_feature_ids)
            if feature_id in partial
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
        geometry: ReachHydraulicGeometry,
        *,
        action: ActionBoundaryFlux | None = None,
        forcing: ForcingFlux | None = None,
        forcing_support: ReachForcingSupport | None = None,
    ) -> NonlinearReachTransportResult:
        self._validate_inputs(
            stock=stock,
            geometry=geometry,
            action=action,
            forcing=forcing,
            forcing_support=forcing_support,
        )
        count = len(self.active_feature_ids)
        dt = float(self.config.timestep_seconds)
        initial = np.asarray(stock.values, dtype=float)
        action_rate = _values_or_zeros(action, count)
        raw_forcing_rate = _values_or_zeros(forcing, count)
        forcing_required = bool(
            self.partial_reach_active_indices
            and np.any(
                raw_forcing_rate[list(self.partial_reach_active_indices)] != 0.0
            )
        )
        forcing_fractions = (
            np.asarray(forcing_support.coverage_fractions, dtype=float)
            if forcing_support is not None
            else np.ones(count, dtype=float)
        )
        forcing_rate = raw_forcing_rate * forcing_fractions
        external_rate = action_rate + forcing_rate
        bottom_width = np.asarray(geometry.bottom_width_m, dtype=float)
        side_slope = np.asarray(
            geometry.side_slope_horizontal_per_vertical, dtype=float
        )
        bed_slope = np.asarray(geometry.bed_slope, dtype=float)
        manning_n = np.asarray(geometry.manning_n, dtype=float)

        def hydraulic_state(storage_m3: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            area = storage_m3 / self.effective_lengths_m
            discriminant = bottom_width**2 + 4.0 * side_slope * area
            depth = (
                -bottom_width + np.sqrt(discriminant)
            ) / (2.0 * side_slope)
            wetted_perimeter = bottom_width + 2.0 * depth * np.sqrt(
                1.0 + side_slope**2
            )
            hydraulic_radius = np.divide(
                area,
                wetted_perimeter,
                out=np.zeros_like(area),
                where=wetted_perimeter > 0.0,
            )
            discharge = (
                area
                * np.power(hydraulic_radius, 2.0 / 3.0)
                * np.sqrt(bed_slope)
                / manning_n
            )
            return discharge, depth

        next_storage = initial.copy()
        transferred_volume = np.zeros(count, dtype=float)
        function_evaluations = 0
        root_iterations = 0
        elapsed = 0.0
        while elapsed < dt:
            substep = min(self.config.integration_substep_seconds, dt - elapsed)
            previous_storage = next_storage
            advanced_storage = np.empty(count, dtype=float)
            upstream_discharge = 0.0
            for index in range(count):
                available_volume = float(
                    previous_storage[index]
                    + substep * (external_rate[index] + upstream_discharge)
                )
                if available_volume < 0.0 or not np.isfinite(available_volume):
                    raise RuntimeError(
                        "nonlinear_reach_transport_nonfinite_available_volume"
                    )
                if available_volume == 0.0:
                    storage_value = 0.0
                    discharge_value = 0.0
                else:
                    def residual(storage_value: float) -> float:
                        candidate = np.zeros(count, dtype=float)
                        candidate[index] = storage_value
                        discharge, _ = hydraulic_state(candidate)
                        return (
                            storage_value
                            + substep * float(discharge[index])
                            - available_volume
                        )

                    storage_value, root_result = brentq(
                        residual,
                        0.0,
                        available_volume,
                        xtol=self.config.root_absolute_tolerance_m3,
                        rtol=self.config.root_relative_tolerance,
                        full_output=True,
                        disp=False,
                    )
                    if not root_result.converged:
                        raise RuntimeError(
                            "nonlinear_reach_transport_root_solver_failed"
                        )
                    function_evaluations += int(root_result.function_calls)
                    root_iterations += int(root_result.iterations)
                    candidate = np.zeros(count, dtype=float)
                    candidate[index] = storage_value
                    discharge, _ = hydraulic_state(candidate)
                    discharge_value = float(discharge[index])
                advanced_storage[index] = storage_value
                transferred_volume[index] += substep * discharge_value
                upstream_discharge = discharge_value
            next_storage = advanced_storage
            elapsed += substep
        advanced = np.concatenate((next_storage, transferred_volume))
        if not np.isfinite(advanced).all():
            raise RuntimeError("nonlinear_reach_transport_solver_nonfinite_state")
        if bool((next_storage < 0.0).any()) or bool(
            (transferred_volume < 0.0).any()
        ):
            raise RuntimeError("nonlinear_reach_transport_solver_negative_state")

        input_volume = float(external_rate.sum() * dt)
        outlet_volume = float(transferred_volume[-1])
        residual = float(
            next_storage.sum() + outlet_volume - initial.sum() - input_volume
        )
        numeric_scale = max(
            1.0,
            float(initial.sum()),
            input_volume,
            float(next_storage.sum()),
            outlet_volume,
        )
        mass_tolerance = (
            self.config.absolute_mass_tolerance_m3
            + self.config.relative_mass_tolerance * numeric_scale
        )
        if abs(residual) > mass_tolerance:
            raise RuntimeError("nonlinear_reach_transport_global_mass_balance_exceeded")

        _, end_depth = hydraulic_state(next_storage)
        admitted = (
            self.config.path_admitted
            and geometry.admitted_as_hydraulic_geometry
            and self.config.operator_form_admitted
            and (
                not forcing_required
                or (
                    forcing_support is not None
                    and forcing_support.admitted_as_spatial_support
                )
            )
        )
        provenance = (
            f"nonlinear_manning_reach_storage|{self.path.provenance_id}|"
            f"{stock.provenance_id}|{geometry.provenance_id}"
        )
        return NonlinearReachTransportResult(
            next_stock=StockState(
                tuple(float(value) for value in next_storage),
                "m3",
                provenance,
            ),
            active_feature_ids=self.active_feature_ids,
            excluded_zero_length_feature_ids=(
                self.excluded_zero_length_feature_ids
            ),
            partial_reach_feature_ids=self.partial_reach_feature_ids,
            reach_mean_outflow_m3s=tuple(
                float(value / dt) for value in transferred_volume
            ),
            reach_end_depth_m=tuple(float(value) for value in end_depth),
            input_volume_m3=input_volume,
            outlet_volume_m3=outlet_volume,
            global_mass_balance_residual_m3=residual,
            numeric_mass_tolerance_m3=float(mass_tolerance),
            solver_function_evaluation_count=function_evaluations,
            solver_root_iteration_count=root_iterations,
            path_admitted=self.config.path_admitted,
            geometry_admitted=geometry.admitted_as_hydraulic_geometry,
            operator_form_admitted=self.config.operator_form_admitted,
            forcing_support_required=forcing_required,
            forcing_support_admitted=(
                not forcing_required
                or bool(
                    forcing_support is not None
                    and forcing_support.admitted_as_spatial_support
                )
            ),
            forcing_coverage_fractions=tuple(
                float(value) for value in forcing_fractions
            ),
            raw_forcing_volume_m3=float(raw_forcing_rate.sum() * dt),
            applied_forcing_volume_m3=float(forcing_rate.sum() * dt),
            excluded_forcing_volume_m3=float(
                (raw_forcing_rate.sum() - forcing_rate.sum()) * dt
            ),
            nonlinear_transport_admitted=admitted,
            diagnostic_only=not admitted,
        )

    def _validate_inputs(
        self,
        *,
        stock: StockState,
        geometry: ReachHydraulicGeometry,
        action: ActionBoundaryFlux | None,
        forcing: ForcingFlux | None,
        forcing_support: ReachForcingSupport | None,
    ) -> None:
        if not isinstance(stock, StockState):
            raise TypeError("stock_state_required")
        if not isinstance(geometry, ReachHydraulicGeometry):
            raise TypeError("reach_hydraulic_geometry_required")
        if action is not None and not isinstance(action, ActionBoundaryFlux):
            raise TypeError("action_boundary_flux_required")
        if forcing is not None and not isinstance(forcing, ForcingFlux):
            raise TypeError("forcing_flux_required")
        if forcing_support is not None and not isinstance(
            forcing_support, ReachForcingSupport
        ):
            raise TypeError("reach_forcing_support_required")
        count = len(self.active_feature_ids)
        if stock.unit != "m3" or len(stock.values) != count:
            raise ValueError("nonlinear_reach_transport_stock_contract_mismatch")
        if geometry.feature_ids != self.active_feature_ids:
            raise ValueError("nonlinear_reach_geometry_feature_order_mismatch")
        components_admitted = (
            self.config.path_admitted
            and geometry.admitted_as_hydraulic_geometry
            and self.config.operator_form_admitted
        )
        if (
            not components_admitted
            and not self.config.allow_unadmitted_components_for_diagnostics
        ):
            raise ValueError(
                "unadmitted_nonlinear_reach_components_require_explicit_diagnostic_mode"
            )
        for name, field in (("action", action), ("forcing", forcing)):
            if field is None:
                continue
            if field.unit != "m3 s-1" or len(field.values) != count:
                raise ValueError(
                    f"nonlinear_reach_transport_{name}_contract_mismatch"
                )
            if (np.asarray(field.values, dtype=float) < 0.0).any():
                raise ValueError(
                    f"nonlinear_reach_transport_{name}_must_be_nonnegative"
                )
        if action is not None and any(value != 0.0 for value in action.values[1:]):
            raise ValueError(
                "nonlinear_reach_transport_action_must_enter_path_boundary"
            )
        forcing_required = bool(
            forcing is not None
            and self.partial_reach_active_indices
            and any(
                forcing.values[index] != 0.0
                for index in self.partial_reach_active_indices
            )
        )
        if forcing_required and forcing_support is None:
            raise ValueError(
                "partial_reach_forcing_requires_admitted_spatial_support"
            )
        if forcing_support is not None:
            if forcing_support.feature_ids != self.active_feature_ids:
                raise ValueError("reach_forcing_support_feature_order_mismatch")
            partial = set(self.partial_reach_feature_ids)
            for feature_id, fraction in zip(
                forcing_support.feature_ids,
                forcing_support.coverage_fractions,
                strict=True,
            ):
                if feature_id not in partial and abs(fraction - 1.0) > 1e-12:
                    raise ValueError(
                        "full_reach_forcing_support_fraction_must_equal_one"
                    )
            if (
                forcing_required
                and not forcing_support.admitted_as_spatial_support
                and not self.config.allow_unadmitted_components_for_diagnostics
            ):
                raise ValueError(
                    "unadmitted_partial_reach_forcing_support_requires_explicit_diagnostic_mode"
                )


def _values_or_zeros(
    field: ActionBoundaryFlux | ForcingFlux | None,
    count: int,
) -> np.ndarray:
    if field is None:
        return np.zeros(count, dtype=float)
    return np.asarray(field.values, dtype=float)
