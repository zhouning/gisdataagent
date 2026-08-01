"""Conservative finite-volume kinematic wave over a dendritic reach DAG."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .branching_network import DirectedReachNetwork
from .contracts import (
    ActionBoundaryFlux,
    ForcingFlux,
    ReachForcingSupport,
    ReachHydraulicGeometry,
)
from .kinematic_wave import (
    KinematicWaveState,
    _area_for_discharge,
    _manning_celerity,
    _manning_discharge_depth,
)


BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA = (
    "gwm.geospatial_kernel.branching_finite_volume_kinematic_wave.v1"
)


@dataclass(frozen=True)
class BranchingKinematicWaveConfig:
    timestep_seconds: float
    target_cell_length_m: float = 1000.0
    cfl_number: float = 0.8
    maximum_substeps: int = 100_000
    operator_form_admitted: bool = False
    allow_unadmitted_components_for_diagnostics: bool = False
    absolute_mass_tolerance_m3: float = 1e-6
    relative_mass_tolerance: float = 1e-10

    def __post_init__(self) -> None:
        for value, error in (
            (self.timestep_seconds, "branching_kinematic_timestep_must_be_positive"),
            (
                self.target_cell_length_m,
                "branching_kinematic_target_cell_length_must_be_positive",
            ),
            (self.relative_mass_tolerance, "branching_kinematic_mass_rtol_positive"),
        ):
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(error)
        if not np.isfinite(self.cfl_number) or not 0.0 < self.cfl_number < 1.0:
            raise ValueError("branching_kinematic_cfl_must_be_in_open_unit_interval")
        if (
            not isinstance(self.maximum_substeps, int)
            or isinstance(self.maximum_substeps, bool)
            or self.maximum_substeps <= 0
        ):
            raise ValueError(
                "branching_kinematic_maximum_substeps_must_be_positive_integer"
            )
        if (
            not np.isfinite(self.absolute_mass_tolerance_m3)
            or self.absolute_mass_tolerance_m3 < 0.0
        ):
            raise ValueError("branching_kinematic_mass_atol_must_be_nonnegative")
        flags = (
            self.operator_form_admitted,
            self.allow_unadmitted_components_for_diagnostics,
        )
        if any(not isinstance(value, bool) for value in flags):
            raise ValueError("branching_kinematic_admission_flags_must_be_boolean")


@dataclass(frozen=True)
class BranchingKinematicWaveStepResult:
    next_state: KinematicWaveState
    feature_ids: tuple[int, ...]
    reach_mean_outflow_m3s: tuple[float, ...]
    reach_end_depth_m: tuple[float, ...]
    action_input_volume_m3: float
    distributed_forcing_volume_m3: float
    total_input_volume_m3: float
    outlet_volume_m3: float
    outlet_mean_flow_m3s: float
    initial_network_storage_m3: float
    final_network_storage_m3: float
    global_mass_balance_residual_m3: float
    numeric_mass_tolerance_m3: float
    integration_substep_count: int
    minimum_substep_seconds: float
    maximum_celerity_mps: float
    maximum_courant_number: float
    cfl_number: float
    network_admitted: bool
    geometry_admitted: bool
    forcing_support_admitted: bool
    operator_form_admitted: bool
    branching_kinematic_wave_admitted: bool
    independent_end_to_end_prediction: bool
    diagnostic_only: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": BRANCHING_KINEMATIC_WAVE_OPERATOR_SCHEMA,
            "cell_feature_ids": list(self.next_state.cell_feature_ids),
            "cell_index_within_reach": list(
                self.next_state.cell_index_within_reach
            ),
            "cell_volume_m3": list(self.next_state.cell_volume_m3),
            "feature_ids": list(self.feature_ids),
            "reach_mean_outflow_m3s": list(self.reach_mean_outflow_m3s),
            "reach_end_depth_m": list(self.reach_end_depth_m),
            "action_input_volume_m3": self.action_input_volume_m3,
            "distributed_forcing_volume_m3": (
                self.distributed_forcing_volume_m3
            ),
            "total_input_volume_m3": self.total_input_volume_m3,
            "outlet_volume_m3": self.outlet_volume_m3,
            "outlet_mean_flow_m3s": self.outlet_mean_flow_m3s,
            "initial_network_storage_m3": self.initial_network_storage_m3,
            "final_network_storage_m3": self.final_network_storage_m3,
            "global_mass_balance_residual_m3": (
                self.global_mass_balance_residual_m3
            ),
            "numeric_mass_tolerance_m3": self.numeric_mass_tolerance_m3,
            "integration_substep_count": self.integration_substep_count,
            "minimum_substep_seconds": self.minimum_substep_seconds,
            "maximum_celerity_mps": self.maximum_celerity_mps,
            "maximum_courant_number": self.maximum_courant_number,
            "cfl_number": self.cfl_number,
            "network_admitted": self.network_admitted,
            "geometry_admitted": self.geometry_admitted,
            "forcing_support_admitted": self.forcing_support_admitted,
            "operator_form_admitted": self.operator_form_admitted,
            "branching_kinematic_wave_admitted": (
                self.branching_kinematic_wave_admitted
            ),
            "independent_end_to_end_prediction": (
                self.independent_end_to_end_prediction
            ),
            "diagnostic_only": self.diagnostic_only,
        }


class BranchingFiniteVolumeKinematicWaveOperator:
    """Advance a dendritic network with simultaneous conservative cell fluxes."""

    def __init__(
        self,
        network: DirectedReachNetwork,
        geometry: ReachHydraulicGeometry,
        config: BranchingKinematicWaveConfig,
    ) -> None:
        if geometry.feature_ids != network.feature_ids:
            raise ValueError("branching_kinematic_geometry_feature_axis_mismatch")
        admitted = (
            network.admitted
            and geometry.admitted_as_hydraulic_geometry
            and config.operator_form_admitted
        )
        if not admitted and not config.allow_unadmitted_components_for_diagnostics:
            raise ValueError("branching_kinematic_unadmitted_component_not_allowed")
        self.network = network
        self.geometry = geometry
        self.config = config
        self._reach_index = {
            feature: index for index, feature in enumerate(network.feature_ids)
        }
        upstream: list[list[int]] = [[] for _ in network.feature_ids]
        for source_index, target in enumerate(network.downstream_feature_ids):
            if target is not None:
                upstream[self._reach_index[target]].append(source_index)
        self.upstream_reach_indices = tuple(tuple(values) for values in upstream)
        self.action_reach_indices = frozenset(
            self._reach_index[feature]
            for feature in network.action_entry_feature_ids
        )
        self.outlet_reach_index = self._reach_index[network.outlet_feature_id]

        reach_lengths = np.asarray(network.effective_lengths_m, dtype=float)
        reach_cell_counts = np.ceil(
            reach_lengths / config.target_cell_length_m
        ).astype(int)
        self.reach_cell_counts = tuple(int(value) for value in reach_cell_counts)
        cell_feature_ids: list[int] = []
        cell_indices: list[int] = []
        cell_reach_indices: list[int] = []
        cell_lengths: list[float] = []
        reach_start_indices: list[int] = []
        reach_end_indices: list[int] = []
        for reach_index, (feature, length, count) in enumerate(
            zip(
                network.feature_ids,
                reach_lengths,
                reach_cell_counts,
                strict=True,
            )
        ):
            reach_start_indices.append(len(cell_feature_ids))
            for cell_index in range(int(count)):
                cell_feature_ids.append(feature)
                cell_indices.append(cell_index)
                cell_reach_indices.append(reach_index)
                cell_lengths.append(float(length / count))
            reach_end_indices.append(len(cell_feature_ids) - 1)
        self.cell_feature_ids = tuple(cell_feature_ids)
        self.cell_index_within_reach = tuple(cell_indices)
        self.cell_reach_indices = np.asarray(cell_reach_indices, dtype=int)
        self.cell_lengths_m = np.asarray(cell_lengths, dtype=float)
        self.reach_start_cell_indices = np.asarray(reach_start_indices, dtype=int)
        self.reach_end_cell_indices = np.asarray(reach_end_indices, dtype=int)
        self._is_reach_start = np.zeros(len(cell_feature_ids), dtype=bool)
        self._is_reach_start[self.reach_start_cell_indices] = True
        self._internal_cell_indices = np.flatnonzero(~self._is_reach_start)
        self.bottom_width_m = np.asarray(geometry.bottom_width_m, dtype=float)[
            self.cell_reach_indices
        ]
        self.side_slope = np.asarray(
            geometry.side_slope_horizontal_per_vertical, dtype=float
        )[self.cell_reach_indices]
        self.bed_slope = np.asarray(geometry.bed_slope, dtype=float)[
            self.cell_reach_indices
        ]
        self.manning_n = np.asarray(geometry.manning_n, dtype=float)[
            self.cell_reach_indices
        ]
        self._hydraulics_cache: dict[tuple[int, float], tuple[float, float]] = {}

    @property
    def cell_count(self) -> int:
        return len(self.cell_feature_ids)

    def zero_state(self, *, provenance_id: str) -> KinematicWaveState:
        return KinematicWaveState(
            self.cell_feature_ids,
            self.cell_index_within_reach,
            (0.0,) * self.cell_count,
            provenance_id,
        )

    def discharge_state(
        self,
        reach_discharge_m3s: tuple[float, ...],
        *,
        provenance_id: str,
    ) -> KinematicWaveState:
        discharge = np.asarray(reach_discharge_m3s, dtype=float)
        if (
            discharge.shape != (len(self.network.feature_ids),)
            or not np.isfinite(discharge).all()
            or (discharge < 0.0).any()
        ):
            raise ValueError("branching_kinematic_initial_discharge_invalid")
        reach_area = np.asarray(
            [
                self._reach_hydraulics(index, float(value))[0]
                for index, value in enumerate(discharge)
            ],
            dtype=float,
        )
        volume = reach_area[self.cell_reach_indices] * self.cell_lengths_m
        return KinematicWaveState(
            self.cell_feature_ids,
            self.cell_index_within_reach,
            tuple(float(value) for value in volume),
            provenance_id,
        )

    def step(
        self,
        state: KinematicWaveState,
        *,
        action: ActionBoundaryFlux | None = None,
        forcing: ForcingFlux | None = None,
        forcing_support: ReachForcingSupport | None = None,
        provenance_id: str,
    ) -> BranchingKinematicWaveStepResult:
        self._validate_inputs(
            state=state,
            action=action,
            forcing=forcing,
            forcing_support=forcing_support,
        )
        reach_count = len(self.network.feature_ids)
        action_rate = (
            np.zeros(reach_count, dtype=float)
            if action is None
            else np.asarray(action.values, dtype=float)
        )
        raw_forcing_rate = (
            np.zeros(reach_count, dtype=float)
            if forcing is None
            else np.asarray(forcing.values, dtype=float)
        )
        forcing_fraction = (
            np.ones(reach_count, dtype=float)
            if forcing_support is None
            else np.asarray(forcing_support.coverage_fractions, dtype=float)
        )
        forcing_rate = raw_forcing_rate * forcing_fraction
        forcing_cell_rate = forcing_rate[self.cell_reach_indices] / np.asarray(
            self.reach_cell_counts, dtype=float
        )[self.cell_reach_indices]
        volume = np.asarray(state.cell_volume_m3, dtype=float).copy()
        initial_storage = float(volume.sum())
        transferred_volume = np.zeros(reach_count, dtype=float)
        outlet_volume = 0.0
        elapsed = 0.0
        substeps = 0
        dt = float(self.config.timestep_seconds)
        minimum_substep = dt
        maximum_celerity = 0.0
        maximum_courant = 0.0
        action_celerity = np.zeros(reach_count, dtype=float)
        for index in self.action_reach_indices:
            action_celerity[index] = self._reach_hydraulics(
                index, float(action_rate[index])
            )[1]
        epsilon = max(np.finfo(float).eps * dt * 16.0, 1e-12)
        while dt - elapsed > epsilon:
            area = volume / self.cell_lengths_m
            discharge, _ = _manning_discharge_depth(
                area,
                self.bottom_width_m,
                self.side_slope,
                self.bed_slope,
                self.manning_n,
            )
            celerity = _manning_celerity(
                area,
                self.bottom_width_m,
                self.side_slope,
                self.bed_slope,
                self.manning_n,
            )
            maximum_celerity = max(
                maximum_celerity,
                float(np.max(celerity, initial=0.0)),
                float(np.max(action_celerity, initial=0.0)),
            )
            stable_dt = math.inf
            positive = celerity > 0.0
            if positive.any():
                stable_dt = float(
                    np.min(
                        self.config.cfl_number
                        * self.cell_lengths_m[positive]
                        / celerity[positive]
                    )
                )
            for reach_index in self.action_reach_indices:
                boundary_speed = action_celerity[reach_index]
                if boundary_speed > 0.0:
                    first_cell = self.reach_start_cell_indices[reach_index]
                    stable_dt = min(
                        stable_dt,
                        self.config.cfl_number
                        * self.cell_lengths_m[first_cell]
                        / boundary_speed,
                    )
            substep = min(dt - elapsed, stable_dt)
            if not np.isfinite(substep) or substep <= 0.0:
                substep = dt - elapsed
            courant = celerity * substep / self.cell_lengths_m
            maximum_courant = max(
                maximum_courant, float(np.max(courant, initial=0.0))
            )
            for reach_index in self.action_reach_indices:
                first_cell = self.reach_start_cell_indices[reach_index]
                maximum_courant = max(
                    maximum_courant,
                    float(
                        action_celerity[reach_index]
                        * substep
                        / self.cell_lengths_m[first_cell]
                    ),
                )

            inflow = np.zeros(self.cell_count, dtype=float)
            inflow[self._internal_cell_indices] = discharge[
                self._internal_cell_indices - 1
            ]
            reach_end_discharge = discharge[self.reach_end_cell_indices]
            for reach_index, first_cell in enumerate(
                self.reach_start_cell_indices
            ):
                inflow[first_cell] = action_rate[reach_index] + sum(
                    reach_end_discharge[source]
                    for source in self.upstream_reach_indices[reach_index]
                )
            next_volume = volume + substep * (
                inflow - discharge + forcing_cell_rate
            )
            numeric_scale = max(
                1.0,
                float(np.max(volume, initial=0.0)),
                float(
                    np.max(
                        np.abs(substep * (inflow - discharge)), initial=0.0
                    )
                ),
            )
            negative_tolerance = 64.0 * np.finfo(float).eps * numeric_scale
            if float(np.min(next_volume, initial=0.0)) < -negative_tolerance:
                raise RuntimeError("branching_kinematic_cfl_positivity_failure")
            next_volume = np.maximum(next_volume, 0.0)
            transferred_volume += substep * reach_end_discharge
            outlet_volume += substep * float(
                reach_end_discharge[self.outlet_reach_index]
            )
            volume = next_volume
            elapsed += substep
            substeps += 1
            minimum_substep = min(minimum_substep, substep)
            if substeps > self.config.maximum_substeps:
                raise RuntimeError("branching_kinematic_maximum_substeps_exceeded")

        action_volume = float(action_rate.sum() * dt)
        forcing_volume = float(forcing_rate.sum() * dt)
        total_input = action_volume + forcing_volume
        final_storage = float(volume.sum())
        residual = (
            final_storage + outlet_volume - initial_storage - total_input
        )
        numeric_scale = max(
            1.0,
            initial_storage,
            final_storage,
            total_input,
            outlet_volume,
        )
        mass_tolerance = (
            self.config.absolute_mass_tolerance_m3
            + self.config.relative_mass_tolerance * numeric_scale
        )
        if abs(residual) > mass_tolerance:
            raise RuntimeError("branching_kinematic_global_mass_balance_exceeded")
        final_area = volume / self.cell_lengths_m
        _, final_depth = _manning_discharge_depth(
            final_area,
            self.bottom_width_m,
            self.side_slope,
            self.bed_slope,
            self.manning_n,
        )
        support_admitted = self._forcing_support_admitted(
            raw_forcing_rate, forcing_support
        )
        admitted = (
            self.network.admitted
            and self.geometry.admitted_as_hydraulic_geometry
            and support_admitted
            and self.config.operator_form_admitted
        )
        return BranchingKinematicWaveStepResult(
            next_state=KinematicWaveState(
                self.cell_feature_ids,
                self.cell_index_within_reach,
                tuple(float(value) for value in volume),
                provenance_id,
            ),
            feature_ids=self.network.feature_ids,
            reach_mean_outflow_m3s=tuple(
                float(value / dt) for value in transferred_volume
            ),
            reach_end_depth_m=tuple(
                float(value) for value in final_depth[self.reach_end_cell_indices]
            ),
            action_input_volume_m3=action_volume,
            distributed_forcing_volume_m3=forcing_volume,
            total_input_volume_m3=total_input,
            outlet_volume_m3=float(outlet_volume),
            outlet_mean_flow_m3s=float(outlet_volume / dt),
            initial_network_storage_m3=initial_storage,
            final_network_storage_m3=final_storage,
            global_mass_balance_residual_m3=float(residual),
            numeric_mass_tolerance_m3=float(mass_tolerance),
            integration_substep_count=substeps,
            minimum_substep_seconds=float(minimum_substep),
            maximum_celerity_mps=float(maximum_celerity),
            maximum_courant_number=float(maximum_courant),
            cfl_number=float(self.config.cfl_number),
            network_admitted=self.network.admitted,
            geometry_admitted=self.geometry.admitted_as_hydraulic_geometry,
            forcing_support_admitted=support_admitted,
            operator_form_admitted=self.config.operator_form_admitted,
            branching_kinematic_wave_admitted=admitted,
            independent_end_to_end_prediction=True,
            diagnostic_only=not admitted,
        )

    def _reach_hydraulics(
        self, reach_index: int, discharge_m3s: float
    ) -> tuple[float, float]:
        key = (reach_index, discharge_m3s)
        cached = self._hydraulics_cache.get(key)
        if cached is not None:
            return cached
        area = _area_for_discharge(
            discharge_m3s,
            bottom_width_m=float(self.geometry.bottom_width_m[reach_index]),
            side_slope=float(
                self.geometry.side_slope_horizontal_per_vertical[reach_index]
            ),
            bed_slope=float(self.geometry.bed_slope[reach_index]),
            manning_n=float(self.geometry.manning_n[reach_index]),
        )
        celerity = float(
            _manning_celerity(
                np.asarray([area]),
                np.asarray([self.geometry.bottom_width_m[reach_index]]),
                np.asarray(
                    [
                        self.geometry.side_slope_horizontal_per_vertical[
                            reach_index
                        ]
                    ]
                ),
                np.asarray([self.geometry.bed_slope[reach_index]]),
                np.asarray([self.geometry.manning_n[reach_index]]),
            )[0]
        )
        result = (area, celerity)
        self._hydraulics_cache[key] = result
        return result

    def _validate_inputs(
        self,
        *,
        state: KinematicWaveState,
        action: ActionBoundaryFlux | None,
        forcing: ForcingFlux | None,
        forcing_support: ReachForcingSupport | None,
    ) -> None:
        if (
            state.cell_feature_ids != self.cell_feature_ids
            or state.cell_index_within_reach != self.cell_index_within_reach
        ):
            raise ValueError("branching_kinematic_state_cell_axis_mismatch")
        count = len(self.network.feature_ids)
        for name, field in (("action", action), ("forcing", forcing)):
            if field is None:
                continue
            expected = ActionBoundaryFlux if name == "action" else ForcingFlux
            if not isinstance(field, expected):
                raise TypeError(f"branching_kinematic_{name}_flux_required")
            values = np.asarray(field.values, dtype=float)
            if (
                field.unit != "m3 s-1"
                or values.shape != (count,)
                or (values < 0.0).any()
            ):
                raise ValueError(f"branching_kinematic_{name}_invalid")
        if action is not None:
            nonzero = set(np.flatnonzero(np.asarray(action.values) > 0.0))
            if not nonzero.issubset(self.action_reach_indices):
                raise ValueError("branching_kinematic_action_outside_entry")
        if forcing is not None and forcing.modeled is not True:
            raise ValueError("branching_kinematic_forcing_must_be_modeled")
        if forcing_support is not None:
            if not isinstance(forcing_support, ReachForcingSupport):
                raise TypeError("branching_kinematic_forcing_support_required")
            if forcing_support.feature_ids != self.network.feature_ids:
                raise ValueError("branching_kinematic_forcing_support_axis_mismatch")
            partial = set(self.network.partial_feature_ids)
            for feature, fraction in zip(
                forcing_support.feature_ids,
                forcing_support.coverage_fractions,
                strict=True,
            ):
                if feature not in partial and abs(fraction - 1.0) > 1e-12:
                    raise ValueError(
                        "branching_kinematic_full_reach_support_must_equal_one"
                    )
        raw_forcing = (
            np.zeros(count, dtype=float)
            if forcing is None
            else np.asarray(forcing.values, dtype=float)
        )
        support_admitted = self._forcing_support_admitted(
            raw_forcing, forcing_support
        )
        admitted = (
            self.network.admitted
            and self.geometry.admitted_as_hydraulic_geometry
            and support_admitted
            and self.config.operator_form_admitted
        )
        if not admitted and not self.config.allow_unadmitted_components_for_diagnostics:
            raise ValueError("branching_kinematic_unadmitted_component_not_allowed")

    def _forcing_support_admitted(
        self,
        raw_forcing_rate: np.ndarray,
        forcing_support: ReachForcingSupport | None,
    ) -> bool:
        partial_indices = {
            self._reach_index[feature]
            for feature in self.network.partial_feature_ids
        }
        support_required = any(
            raw_forcing_rate[index] != 0.0 for index in partial_indices
        )
        if support_required and forcing_support is None:
            return False
        return bool(
            not support_required
            or (
                forcing_support is not None
                and forcing_support.admitted_as_spatial_support
            )
        )
