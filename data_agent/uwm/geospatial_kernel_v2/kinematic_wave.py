"""Conservative finite-volume kinematic wave over a linear-referenced path."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.optimize import brentq

from .contracts import LinearReferencedPath, ReachHydraulicGeometry


KINEMATIC_WAVE_OPERATOR_SCHEMA = (
    "gwm.geospatial_kernel.finite_volume_kinematic_wave.v1"
)


@dataclass(frozen=True)
class KinematicWaveConfig:
    timestep_seconds: float
    target_cell_length_m: float = 1000.0
    cfl_number: float = 0.8
    maximum_substeps: int = 100_000
    path_admitted: bool = False
    operator_form_admitted: bool = False
    allow_unadmitted_components_for_diagnostics: bool = False
    zero_effective_length_tolerance_m: float = 1e-6
    absolute_mass_tolerance_m3: float = 1e-6
    relative_mass_tolerance: float = 1e-10

    def __post_init__(self) -> None:
        for value, error in (
            (self.timestep_seconds, "kinematic_wave_timestep_must_be_positive"),
            (
                self.target_cell_length_m,
                "kinematic_wave_target_cell_length_must_be_positive",
            ),
            (self.cfl_number, "kinematic_wave_cfl_must_be_in_open_unit_interval"),
            (
                self.relative_mass_tolerance,
                "kinematic_wave_relative_mass_tolerance_must_be_positive",
            ),
        ):
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(error)
        if self.cfl_number >= 1.0:
            raise ValueError("kinematic_wave_cfl_must_be_in_open_unit_interval")
        if (
            not isinstance(self.maximum_substeps, int)
            or isinstance(self.maximum_substeps, bool)
            or self.maximum_substeps <= 0
        ):
            raise ValueError("kinematic_wave_maximum_substeps_must_be_positive_integer")
        if (
            not np.isfinite(self.zero_effective_length_tolerance_m)
            or self.zero_effective_length_tolerance_m < 0.0
        ):
            raise ValueError("kinematic_wave_length_tolerance_must_be_nonnegative")
        if (
            not np.isfinite(self.absolute_mass_tolerance_m3)
            or self.absolute_mass_tolerance_m3 < 0.0
        ):
            raise ValueError("kinematic_wave_mass_tolerance_must_be_nonnegative")
        flags = (
            self.path_admitted,
            self.operator_form_admitted,
            self.allow_unadmitted_components_for_diagnostics,
        )
        if any(not isinstance(value, bool) for value in flags):
            raise ValueError("kinematic_wave_admission_flags_must_be_boolean")
        if (
            not self.path_admitted or not self.operator_form_admitted
        ) and not self.allow_unadmitted_components_for_diagnostics:
            raise ValueError("kinematic_wave_unadmitted_component_not_allowed")


@dataclass(frozen=True)
class KinematicWaveState:
    cell_feature_ids: tuple[int, ...]
    cell_index_within_reach: tuple[int, ...]
    cell_volume_m3: tuple[float, ...]
    provenance_id: str

    def __post_init__(self) -> None:
        count = len(self.cell_feature_ids)
        if count == 0 or any(
            len(values) != count
            for values in (
                self.cell_index_within_reach,
                self.cell_volume_m3,
            )
        ):
            raise ValueError("kinematic_wave_state_axis_mismatch")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in self.cell_feature_ids
        ):
            raise ValueError("kinematic_wave_state_feature_ids_invalid")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in self.cell_index_within_reach
        ):
            raise ValueError("kinematic_wave_state_cell_indices_invalid")
        volume = np.asarray(self.cell_volume_m3, dtype=float)
        if not np.isfinite(volume).all() or (volume < 0.0).any():
            raise ValueError("kinematic_wave_state_volume_must_be_nonnegative_finite")
        if not self.provenance_id.strip():
            raise ValueError("kinematic_wave_state_provenance_required")


@dataclass(frozen=True)
class KinematicWaveStepResult:
    next_state: KinematicWaveState
    boundary_inflow_m3s: float
    lateral_inflow_m3s: tuple[float, ...]
    reach_mean_outflow_m3s: tuple[float, ...]
    reach_end_depth_m: tuple[float, ...]
    input_volume_m3: float
    outlet_volume_m3: float
    initial_storage_m3: float
    final_storage_m3: float
    global_mass_balance_residual_m3: float
    numeric_mass_tolerance_m3: float
    integration_substep_count: int
    minimum_substep_seconds: float
    maximum_celerity_mps: float
    maximum_courant_number: float
    cfl_number: float
    path_admitted: bool
    geometry_admitted: bool
    operator_form_admitted: bool
    kinematic_wave_admitted: bool
    diagnostic_only: bool

    @property
    def outlet_mean_flow_m3s(self) -> float:
        return self.reach_mean_outflow_m3s[-1]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": KINEMATIC_WAVE_OPERATOR_SCHEMA,
            "cell_feature_ids": list(self.next_state.cell_feature_ids),
            "cell_index_within_reach": list(
                self.next_state.cell_index_within_reach
            ),
            "cell_volume_m3": list(self.next_state.cell_volume_m3),
            "boundary_inflow_m3s": self.boundary_inflow_m3s,
            "lateral_inflow_m3s": list(self.lateral_inflow_m3s),
            "reach_mean_outflow_m3s": list(self.reach_mean_outflow_m3s),
            "reach_end_depth_m": list(self.reach_end_depth_m),
            "outlet_mean_flow_m3s": self.outlet_mean_flow_m3s,
            "input_volume_m3": self.input_volume_m3,
            "outlet_volume_m3": self.outlet_volume_m3,
            "initial_storage_m3": self.initial_storage_m3,
            "final_storage_m3": self.final_storage_m3,
            "global_mass_balance_residual_m3": (
                self.global_mass_balance_residual_m3
            ),
            "numeric_mass_tolerance_m3": self.numeric_mass_tolerance_m3,
            "integration_substep_count": self.integration_substep_count,
            "minimum_substep_seconds": self.minimum_substep_seconds,
            "maximum_celerity_mps": self.maximum_celerity_mps,
            "maximum_courant_number": self.maximum_courant_number,
            "cfl_number": self.cfl_number,
            "path_admitted": self.path_admitted,
            "geometry_admitted": self.geometry_admitted,
            "operator_form_admitted": self.operator_form_admitted,
            "kinematic_wave_admitted": self.kinematic_wave_admitted,
            "diagnostic_only": self.diagnostic_only,
        }


class FiniteVolumeKinematicWaveOperator:
    """Advance dA/dt + dQ(A)/dx = q using monotone downstream fluxes."""

    def __init__(
        self,
        path: LinearReferencedPath,
        geometry: ReachHydraulicGeometry,
        config: KinematicWaveConfig,
    ) -> None:
        if geometry.feature_ids != path.feature_ids:
            raise ValueError("kinematic_wave_geometry_feature_axis_mismatch")
        effective = np.asarray(path.effective_lengths_m, dtype=float)
        active = effective > config.zero_effective_length_tolerance_m
        if not active.all():
            raise ValueError("kinematic_wave_requires_positive_full_path_lengths")
        self.path = path
        self.geometry = geometry
        self.config = config
        reach_cell_counts = np.ceil(
            effective / config.target_cell_length_m
        ).astype(int)
        self.reach_cell_counts = tuple(int(value) for value in reach_cell_counts)
        cell_feature_ids: list[int] = []
        cell_indices: list[int] = []
        cell_reach_indices: list[int] = []
        cell_lengths: list[float] = []
        reach_end_cell_indices: list[int] = []
        for reach_index, (feature_id, length, count) in enumerate(
            zip(path.feature_ids, effective, reach_cell_counts, strict=True)
        ):
            for cell_index in range(int(count)):
                cell_feature_ids.append(feature_id)
                cell_indices.append(cell_index)
                cell_reach_indices.append(reach_index)
                cell_lengths.append(float(length / count))
            reach_end_cell_indices.append(len(cell_feature_ids) - 1)
        self.cell_feature_ids = tuple(cell_feature_ids)
        self.cell_index_within_reach = tuple(cell_indices)
        self.cell_reach_indices = np.asarray(cell_reach_indices, dtype=int)
        self.cell_lengths_m = np.asarray(cell_lengths, dtype=float)
        self.reach_end_cell_indices = np.asarray(reach_end_cell_indices, dtype=int)
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
        self._boundary_hydraulics_cache: dict[float, tuple[float, float]] = {}

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

    def uniform_discharge_state(
        self, discharge_m3s: float, *, provenance_id: str
    ) -> KinematicWaveState:
        if not np.isfinite(discharge_m3s) or discharge_m3s < 0.0:
            raise ValueError("kinematic_wave_uniform_discharge_must_be_nonnegative")
        if discharge_m3s == 0.0:
            return self.zero_state(provenance_id=provenance_id)
        areas = np.asarray(
            [
                _area_for_discharge(
                    discharge_m3s,
                    bottom_width_m=float(self.bottom_width_m[index]),
                    side_slope=float(self.side_slope[index]),
                    bed_slope=float(self.bed_slope[index]),
                    manning_n=float(self.manning_n[index]),
                )
                for index in range(self.cell_count)
            ],
            dtype=float,
        )
        return KinematicWaveState(
            self.cell_feature_ids,
            self.cell_index_within_reach,
            tuple(float(value) for value in areas * self.cell_lengths_m),
            provenance_id,
        )

    def step(
        self,
        state: KinematicWaveState,
        *,
        boundary_inflow_m3s: float,
        lateral_inflow_m3s: tuple[float, ...] | None = None,
        provenance_id: str,
    ) -> KinematicWaveStepResult:
        self._validate_state(state)
        if not np.isfinite(boundary_inflow_m3s) or boundary_inflow_m3s < 0.0:
            raise ValueError("kinematic_wave_boundary_must_be_nonnegative_finite")
        reach_count = len(self.path.feature_ids)
        lateral = (
            np.zeros(reach_count, dtype=float)
            if lateral_inflow_m3s is None
            else np.asarray(lateral_inflow_m3s, dtype=float)
        )
        if (
            lateral.shape != (reach_count,)
            or not np.isfinite(lateral).all()
            or (lateral < 0.0).any()
        ):
            raise ValueError("kinematic_wave_lateral_inflow_invalid")
        lateral_cell_rate = lateral[self.cell_reach_indices] / np.asarray(
            self.reach_cell_counts, dtype=float
        )[self.cell_reach_indices]
        volume = np.asarray(state.cell_volume_m3, dtype=float).copy()
        initial_storage = float(volume.sum())
        reach_outlet_volume = np.zeros(reach_count, dtype=float)
        outlet_volume = 0.0
        elapsed = 0.0
        substeps = 0
        minimum_substep = float(self.config.timestep_seconds)
        maximum_celerity = 0.0
        maximum_courant = 0.0
        dt = float(self.config.timestep_seconds)
        _, boundary_celerity = self._boundary_hydraulics(
            float(boundary_inflow_m3s)
        )
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
                float(celerity.max(initial=0.0)),
                float(boundary_celerity),
            )
            positive = celerity > 0.0
            stable_dt = (
                math.inf
                if not positive.any()
                else float(
                    np.min(
                        self.config.cfl_number
                        * self.cell_lengths_m[positive]
                        / celerity[positive]
                    )
                )
            )
            if boundary_celerity > 0.0:
                stable_dt = min(
                    stable_dt,
                    self.config.cfl_number
                    * float(self.cell_lengths_m[0])
                    / float(boundary_celerity),
                )
            substep = min(dt - elapsed, stable_dt)
            if not np.isfinite(substep) or substep <= 0.0:
                substep = dt - elapsed
            courant = np.divide(
                celerity * substep,
                self.cell_lengths_m,
                out=np.zeros_like(celerity),
                where=self.cell_lengths_m > 0.0,
            )
            maximum_courant = max(
                maximum_courant,
                float(courant.max(initial=0.0)),
                float(boundary_celerity * substep / self.cell_lengths_m[0]),
            )
            inflow = np.empty(self.cell_count, dtype=float)
            inflow[0] = float(boundary_inflow_m3s)
            inflow[1:] = discharge[:-1]
            next_volume = volume + substep * (
                inflow - discharge + lateral_cell_rate
            )
            numeric_scale = max(
                1.0,
                float(volume.max(initial=0.0)),
                float(np.abs(substep * (inflow - discharge)).max(initial=0.0)),
            )
            negative_tolerance = 64.0 * np.finfo(float).eps * numeric_scale
            if float(next_volume.min(initial=0.0)) < -negative_tolerance:
                raise RuntimeError("kinematic_wave_cfl_positivity_failure")
            next_volume = np.maximum(next_volume, 0.0)
            reach_outlet_volume += substep * discharge[self.reach_end_cell_indices]
            outlet_volume += substep * float(discharge[-1])
            volume = next_volume
            elapsed += substep
            substeps += 1
            minimum_substep = min(minimum_substep, substep)
            if substeps > self.config.maximum_substeps:
                raise RuntimeError("kinematic_wave_maximum_substeps_exceeded")
        if dt - elapsed > 0.0:
            elapsed = dt

        input_volume = float((boundary_inflow_m3s + lateral.sum()) * dt)
        final_storage = float(volume.sum())
        residual = final_storage + outlet_volume - initial_storage - input_volume
        numeric_scale = max(
            1.0,
            initial_storage,
            final_storage,
            input_volume,
            outlet_volume,
        )
        mass_tolerance = (
            self.config.absolute_mass_tolerance_m3
            + self.config.relative_mass_tolerance * numeric_scale
        )
        if abs(residual) > mass_tolerance:
            raise RuntimeError("kinematic_wave_global_mass_balance_exceeded")
        final_area = volume / self.cell_lengths_m
        _, final_depth = _manning_discharge_depth(
            final_area,
            self.bottom_width_m,
            self.side_slope,
            self.bed_slope,
            self.manning_n,
        )
        admitted = (
            self.config.path_admitted
            and self.geometry.admitted_as_hydraulic_geometry
            and self.config.operator_form_admitted
        )
        return KinematicWaveStepResult(
            next_state=KinematicWaveState(
                self.cell_feature_ids,
                self.cell_index_within_reach,
                tuple(float(value) for value in volume),
                provenance_id,
            ),
            boundary_inflow_m3s=float(boundary_inflow_m3s),
            lateral_inflow_m3s=tuple(float(value) for value in lateral),
            reach_mean_outflow_m3s=tuple(
                float(value / dt) for value in reach_outlet_volume
            ),
            reach_end_depth_m=tuple(
                float(value) for value in final_depth[self.reach_end_cell_indices]
            ),
            input_volume_m3=input_volume,
            outlet_volume_m3=float(outlet_volume),
            initial_storage_m3=initial_storage,
            final_storage_m3=final_storage,
            global_mass_balance_residual_m3=float(residual),
            numeric_mass_tolerance_m3=float(mass_tolerance),
            integration_substep_count=substeps,
            minimum_substep_seconds=float(minimum_substep),
            maximum_celerity_mps=float(maximum_celerity),
            maximum_courant_number=float(maximum_courant),
            cfl_number=float(self.config.cfl_number),
            path_admitted=self.config.path_admitted,
            geometry_admitted=self.geometry.admitted_as_hydraulic_geometry,
            operator_form_admitted=self.config.operator_form_admitted,
            kinematic_wave_admitted=admitted,
            diagnostic_only=not admitted,
        )

    def _validate_state(self, state: KinematicWaveState) -> None:
        if (
            state.cell_feature_ids != self.cell_feature_ids
            or state.cell_index_within_reach != self.cell_index_within_reach
        ):
            raise ValueError("kinematic_wave_state_cell_axis_mismatch")

    def _boundary_hydraulics(self, discharge_m3s: float) -> tuple[float, float]:
        cached = self._boundary_hydraulics_cache.get(discharge_m3s)
        if cached is not None:
            return cached
        area = _area_for_discharge(
            discharge_m3s,
            bottom_width_m=float(self.bottom_width_m[0]),
            side_slope=float(self.side_slope[0]),
            bed_slope=float(self.bed_slope[0]),
            manning_n=float(self.manning_n[0]),
        )
        celerity = float(
            _manning_celerity(
                np.asarray([area]),
                np.asarray([self.bottom_width_m[0]]),
                np.asarray([self.side_slope[0]]),
                np.asarray([self.bed_slope[0]]),
                np.asarray([self.manning_n[0]]),
            )[0]
        )
        result = (area, celerity)
        self._boundary_hydraulics_cache[discharge_m3s] = result
        return result


def _manning_discharge_depth(
    area_m2: np.ndarray,
    bottom_width_m: np.ndarray,
    side_slope: np.ndarray,
    bed_slope: np.ndarray,
    manning_n: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    area = np.asarray(area_m2, dtype=float)
    depth = (
        -bottom_width_m
        + np.sqrt(bottom_width_m**2 + 4.0 * side_slope * area)
    ) / (2.0 * side_slope)
    perimeter = bottom_width_m + 2.0 * depth * np.sqrt(1.0 + side_slope**2)
    radius = np.divide(
        area,
        perimeter,
        out=np.zeros_like(area),
        where=perimeter > 0.0,
    )
    discharge = (
        area
        * np.power(radius, 2.0 / 3.0)
        * np.sqrt(bed_slope)
        / manning_n
    )
    return discharge, depth


def _manning_celerity(
    area_m2: np.ndarray,
    bottom_width_m: np.ndarray,
    side_slope: np.ndarray,
    bed_slope: np.ndarray,
    manning_n: np.ndarray,
) -> np.ndarray:
    area = np.asarray(area_m2, dtype=float)
    _, depth = _manning_discharge_depth(
        area, bottom_width_m, side_slope, bed_slope, manning_n
    )
    top_width = bottom_width_m + 2.0 * side_slope * depth
    perimeter = bottom_width_m + 2.0 * depth * np.sqrt(1.0 + side_slope**2)
    radius = np.divide(
        area,
        perimeter,
        out=np.zeros_like(area),
        where=perimeter > 0.0,
    )
    discharge_per_area = (
        np.power(radius, 2.0 / 3.0) * np.sqrt(bed_slope) / manning_n
    )
    area_correction = np.divide(
        (4.0 / 3.0) * area * np.sqrt(1.0 + side_slope**2),
        perimeter * top_width,
        out=np.zeros_like(area),
        where=(perimeter > 0.0) & (top_width > 0.0),
    )
    return np.maximum(
        discharge_per_area * (5.0 / 3.0 - area_correction), 0.0
    )


def _area_for_discharge(
    discharge_m3s: float,
    *,
    bottom_width_m: float,
    side_slope: float,
    bed_slope: float,
    manning_n: float,
) -> float:
    if discharge_m3s <= 0.0:
        return 0.0

    def residual(area: float) -> float:
        value, _ = _manning_discharge_depth(
            np.asarray([area]),
            np.asarray([bottom_width_m]),
            np.asarray([side_slope]),
            np.asarray([bed_slope]),
            np.asarray([manning_n]),
        )
        return float(value[0] - discharge_m3s)

    upper = max(1.0, discharge_m3s)
    while residual(upper) < 0.0:
        upper *= 2.0
        if upper > 1e12:
            raise RuntimeError("kinematic_wave_discharge_area_bracket_failed")
    return float(brentq(residual, 0.0, upper, xtol=1e-12, rtol=1e-12))
