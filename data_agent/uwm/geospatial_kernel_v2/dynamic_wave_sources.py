"""Well-balanced bed and Manning source primitives for dynamic-wave work."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    DynamicWaveFlux,
    DynamicWaveHLLFluxResult,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
    dynamic_wave_characteristic_speeds_mps,
    hll_dynamic_wave_flux,
)


HYDROSTATIC_RECONSTRUCTION_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_wave_hydrostatic_reconstruction.v1"
)
HYDROSTATIC_PERIODIC_STEP_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_wave_hydrostatic_periodic_step.v1"
)
HYDROSTATIC_OPEN_STEP_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_wave_hydrostatic_open_step.v1"
)
MANNING_SOURCE_STEP_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_wave_manning_source_step.v1"
)
LATERAL_INFLOW_SOURCE_STEP_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_wave_lateral_inflow_source_step.v1"
)
_LATERAL_MOMENTUM_CONVENTIONS = {
    "zero_longitudinal_momentum",
    "matched_local_velocity",
}


@dataclass(frozen=True)
class HydrostaticReconstructionFlux:
    left_cell_flux: DynamicWaveFlux
    right_cell_flux: DynamicWaveFlux
    reconstructed_left_state: DynamicWaveCellState
    reconstructed_right_state: DynamicWaveCellState
    interface_bed_elevation_m: float
    hll: DynamicWaveHLLFluxResult

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HYDROSTATIC_RECONSTRUCTION_SCHEMA,
            "left_cell_flux": {
                "area_flux_m3s": self.left_cell_flux.area_flux_m3s,
                "momentum_flux_m4s2": self.left_cell_flux.momentum_flux_m4s2,
            },
            "right_cell_flux": {
                "area_flux_m3s": self.right_cell_flux.area_flux_m3s,
                "momentum_flux_m4s2": self.right_cell_flux.momentum_flux_m4s2,
            },
            "reconstructed_left_state": {
                "area_m2": self.reconstructed_left_state.area_m2,
                "discharge_m3s": self.reconstructed_left_state.discharge_m3s,
            },
            "reconstructed_right_state": {
                "area_m2": self.reconstructed_right_state.area_m2,
                "discharge_m3s": self.reconstructed_right_state.discharge_m3s,
            },
            "interface_bed_elevation_m": self.interface_bed_elevation_m,
            "hll": self.hll.as_dict(),
            "lake_at_rest_balance_intended": True,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class HydrostaticPeriodicStep:
    state: PrismaticDynamicWaveState
    timestep_seconds: float
    cell_length_m: float
    maximum_courant_number: float
    volume_before_m3: float
    volume_after_m3: float
    volume_balance_error_m3: float
    maximum_absolute_discharge_m3s: float
    maximum_free_surface_change_m: float
    minimum_area_m2: float
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HYDROSTATIC_PERIODIC_STEP_SCHEMA,
            "timestep_seconds": self.timestep_seconds,
            "cell_length_m": self.cell_length_m,
            "maximum_courant_number": self.maximum_courant_number,
            "volume_before_m3": self.volume_before_m3,
            "volume_after_m3": self.volume_after_m3,
            "volume_balance_error_m3": self.volume_balance_error_m3,
            "maximum_absolute_discharge_m3s": (
                self.maximum_absolute_discharge_m3s
            ),
            "maximum_free_surface_change_m": (
                self.maximum_free_surface_change_m
            ),
            "minimum_area_m2": self.minimum_area_m2,
            "finite_state": True,
            "nonnegative_area": self.minimum_area_m2 >= 0.0,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class HydrostaticOpenStep:
    state: PrismaticDynamicWaveState
    timestep_seconds: float
    cell_length_m: float
    maximum_courant_number: float
    left_boundary_area_flux_m3s: float
    right_boundary_area_flux_m3s: float
    prescribed_boundary_volume_change_m3: float
    volume_before_m3: float
    volume_after_m3: float
    volume_balance_error_m3: float
    discharge_integral_before_m4s: float
    discharge_integral_after_m4s: float
    discharge_integral_change_m4s: float
    maximum_free_surface_change_m: float
    minimum_area_m2: float
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HYDROSTATIC_OPEN_STEP_SCHEMA,
            "timestep_seconds": self.timestep_seconds,
            "cell_length_m": self.cell_length_m,
            "maximum_courant_number": self.maximum_courant_number,
            "left_boundary_area_flux_m3s": self.left_boundary_area_flux_m3s,
            "right_boundary_area_flux_m3s": self.right_boundary_area_flux_m3s,
            "prescribed_boundary_volume_change_m3": (
                self.prescribed_boundary_volume_change_m3
            ),
            "volume_before_m3": self.volume_before_m3,
            "volume_after_m3": self.volume_after_m3,
            "volume_balance_error_m3": self.volume_balance_error_m3,
            "discharge_integral_before_m4s": self.discharge_integral_before_m4s,
            "discharge_integral_after_m4s": self.discharge_integral_after_m4s,
            "discharge_integral_change_m4s": self.discharge_integral_change_m4s,
            "maximum_free_surface_change_m": self.maximum_free_surface_change_m,
            "minimum_area_m2": self.minimum_area_m2,
            "boundary_semantics": "fixed_ghost_state",
            "finite_state": True,
            "nonnegative_area": self.minimum_area_m2 >= 0.0,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class ManningSlopeFrictionStep:
    state: PrismaticDynamicWaveState
    timestep_seconds: float
    volume_before_m3: float
    volume_after_m3: float
    volume_balance_error_m3: float
    discharge_sum_before_m3s: float
    discharge_sum_after_m3s: float
    maximum_absolute_equilibrium_residual: float
    flow_direction_preserved: bool
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": MANNING_SOURCE_STEP_SCHEMA,
            "timestep_seconds": self.timestep_seconds,
            "volume_before_m3": self.volume_before_m3,
            "volume_after_m3": self.volume_after_m3,
            "volume_balance_error_m3": self.volume_balance_error_m3,
            "discharge_sum_before_m3s": self.discharge_sum_before_m3s,
            "discharge_sum_after_m3s": self.discharge_sum_after_m3s,
            "maximum_absolute_equilibrium_residual": (
                self.maximum_absolute_equilibrium_residual
            ),
            "flow_direction_preserved": self.flow_direction_preserved,
            "area_unchanged": True,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class LateralInflowSourceStep:
    state: PrismaticDynamicWaveState
    timestep_seconds: float
    cell_length_m: float
    momentum_convention: str
    volume_before_m3: float
    prescribed_lateral_volume_m3: float
    volume_after_m3: float
    volume_balance_error_m3: float
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": LATERAL_INFLOW_SOURCE_STEP_SCHEMA,
            "timestep_seconds": self.timestep_seconds,
            "cell_length_m": self.cell_length_m,
            "momentum_convention": self.momentum_convention,
            "volume_before_m3": self.volume_before_m3,
            "prescribed_lateral_volume_m3": self.prescribed_lateral_volume_m3,
            "volume_after_m3": self.volume_after_m3,
            "volume_balance_error_m3": self.volume_balance_error_m3,
            "negative_lateral_inflow_supported": False,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


def hydrostatic_reconstruction_hll_flux(
    left: DynamicWaveCellState,
    right: DynamicWaveCellState,
    *,
    left_bed_elevation_m: float,
    right_bed_elevation_m: float,
    section: TrapezoidalChannelSection,
) -> HydrostaticReconstructionFlux:
    left_bed = _finite(left_bed_elevation_m, "dynamic_wave_bed_elevation_invalid")
    right_bed = _finite(right_bed_elevation_m, "dynamic_wave_bed_elevation_invalid")
    left_depth = section.depth_m(left.area_m2)
    right_depth = section.depth_m(right.area_m2)
    interface_bed = max(left_bed, right_bed)
    left_reconstructed_depth = max(0.0, left_bed + left_depth - interface_bed)
    right_reconstructed_depth = max(0.0, right_bed + right_depth - interface_bed)
    left_area = section.area_m2(left_reconstructed_depth)
    right_area = section.area_m2(right_reconstructed_depth)
    left_discharge = (
        0.0 if left.area_m2 == 0.0 else left.discharge_m3s * left_area / left.area_m2
    )
    right_discharge = (
        0.0
        if right.area_m2 == 0.0
        else right.discharge_m3s * right_area / right.area_m2
    )
    reconstructed_left = DynamicWaveCellState(left_area, left_discharge)
    reconstructed_right = DynamicWaveCellState(right_area, right_discharge)
    hll = hll_dynamic_wave_flux(reconstructed_left, reconstructed_right, section)
    left_pressure_correction = STANDARD_GRAVITY_MPS2 * (
        section.hydrostatic_pressure_integral_m3(left.area_m2)
        - section.hydrostatic_pressure_integral_m3(left_area)
    )
    right_pressure_correction = STANDARD_GRAVITY_MPS2 * (
        section.hydrostatic_pressure_integral_m3(right.area_m2)
        - section.hydrostatic_pressure_integral_m3(right_area)
    )
    return HydrostaticReconstructionFlux(
        left_cell_flux=DynamicWaveFlux(
            hll.flux.area_flux_m3s,
            hll.flux.momentum_flux_m4s2 + left_pressure_correction,
        ),
        right_cell_flux=DynamicWaveFlux(
            hll.flux.area_flux_m3s,
            hll.flux.momentum_flux_m4s2 + right_pressure_correction,
        ),
        reconstructed_left_state=reconstructed_left,
        reconstructed_right_state=reconstructed_right,
        interface_bed_elevation_m=interface_bed,
        hll=hll,
    )


def advance_hydrostatic_reconstruction_periodic(
    state: PrismaticDynamicWaveState,
    bed_elevation_m: tuple[float, ...],
    section: TrapezoidalChannelSection,
    *,
    cell_length_m: float,
    timestep_seconds: float,
    maximum_courant_number: float,
    negative_area_tolerance_m2: float = 1e-12,
) -> HydrostaticPeriodicStep:
    bed = np.asarray(bed_elevation_m, dtype=float)
    length = _positive(cell_length_m, "hydrostatic_step_length_invalid")
    timestep = _positive(timestep_seconds, "hydrostatic_step_timestep_invalid")
    limit = _positive(maximum_courant_number, "hydrostatic_step_cfl_invalid")
    negative_tolerance = float(negative_area_tolerance_m2)
    if (
        bed.shape != (state.cell_count,)
        or not np.isfinite(bed).all()
        or limit > 1.0
        or not math.isfinite(negative_tolerance)
        or negative_tolerance < 0.0
    ):
        raise ValueError("hydrostatic_step_contract_invalid")
    area = np.asarray(state.area_m2, dtype=float)
    discharge = np.asarray(state.discharge_m3s, dtype=float)
    maximum_signal = max(
        max(
            abs(value)
            for value in dynamic_wave_characteristic_speeds_mps(
                DynamicWaveCellState(a, q), section
            )
        )
        for a, q in zip(area, discharge, strict=True)
    )
    courant = maximum_signal * timestep / length
    if courant > limit + 2.0 * np.finfo(float).eps:
        raise ValueError("hydrostatic_step_cfl_exceeded")

    interfaces = []
    for index in range(state.cell_count):
        right = (index + 1) % state.cell_count
        interfaces.append(
            hydrostatic_reconstruction_hll_flux(
                DynamicWaveCellState(area[index], discharge[index]),
                DynamicWaveCellState(area[right], discharge[right]),
                left_bed_elevation_m=float(bed[index]),
                right_bed_elevation_m=float(bed[right]),
                section=section,
            )
        )
    updated = np.empty((state.cell_count, 2), dtype=float)
    for index in range(state.cell_count):
        left_interface = interfaces[(index - 1) % state.cell_count]
        right_interface = interfaces[index]
        current = np.asarray([area[index], discharge[index]], dtype=float)
        updated[index] = current - (timestep / length) * (
            right_interface.left_cell_flux.as_array()
            - left_interface.right_cell_flux.as_array()
        )
    if not np.isfinite(updated).all():
        raise FloatingPointError("hydrostatic_step_nonfinite_state")
    if (updated[:, 0] < -negative_tolerance).any():
        raise FloatingPointError("hydrostatic_step_negative_area")
    tiny = (updated[:, 0] < 0.0) & (updated[:, 0] >= -negative_tolerance)
    updated[tiny, 0] = 0.0
    updated[tiny & (np.abs(updated[:, 1]) <= negative_tolerance), 1] = 0.0
    next_state = PrismaticDynamicWaveState(
        area_m2=tuple(float(value) for value in updated[:, 0]),
        discharge_m3s=tuple(float(value) for value in updated[:, 1]),
    )
    before_surface = bed + np.asarray(
        [section.depth_m(value) for value in area], dtype=float
    )
    after_surface = bed + np.asarray(
        [section.depth_m(value) for value in updated[:, 0]], dtype=float
    )
    volume_before = float(area.sum() * length)
    volume_after = float(updated[:, 0].sum() * length)
    return HydrostaticPeriodicStep(
        state=next_state,
        timestep_seconds=timestep,
        cell_length_m=length,
        maximum_courant_number=float(courant),
        volume_before_m3=volume_before,
        volume_after_m3=volume_after,
        volume_balance_error_m3=volume_after - volume_before,
        maximum_absolute_discharge_m3s=float(np.abs(updated[:, 1]).max()),
        maximum_free_surface_change_m=float(
            np.abs(after_surface - before_surface).max()
        ),
        minimum_area_m2=float(updated[:, 0].min()),
    )


def advance_hydrostatic_reconstruction_open(
    state: PrismaticDynamicWaveState,
    bed_elevation_m: tuple[float, ...],
    section: TrapezoidalChannelSection,
    *,
    left_boundary_state: DynamicWaveCellState,
    right_boundary_state: DynamicWaveCellState,
    left_boundary_bed_elevation_m: float,
    right_boundary_bed_elevation_m: float,
    cell_length_m: float,
    timestep_seconds: float,
    maximum_courant_number: float,
    negative_area_tolerance_m2: float = 1e-12,
) -> HydrostaticOpenStep:
    bed = np.asarray(bed_elevation_m, dtype=float)
    length = _positive(cell_length_m, "hydrostatic_open_step_length_invalid")
    timestep = _positive(
        timestep_seconds, "hydrostatic_open_step_timestep_invalid"
    )
    limit = _positive(
        maximum_courant_number, "hydrostatic_open_step_cfl_invalid"
    )
    left_bed = _finite(
        left_boundary_bed_elevation_m,
        "hydrostatic_open_step_boundary_bed_invalid",
    )
    right_bed = _finite(
        right_boundary_bed_elevation_m,
        "hydrostatic_open_step_boundary_bed_invalid",
    )
    negative_tolerance = float(negative_area_tolerance_m2)
    if (
        bed.shape != (state.cell_count,)
        or not np.isfinite(bed).all()
        or limit > 1.0
        or not math.isfinite(negative_tolerance)
        or negative_tolerance < 0.0
    ):
        raise ValueError("hydrostatic_open_step_contract_invalid")
    area = np.asarray(state.area_m2, dtype=float)
    discharge = np.asarray(state.discharge_m3s, dtype=float)
    signal_states = (
        (left_boundary_state,)
        + tuple(
            DynamicWaveCellState(float(a), float(q))
            for a, q in zip(area, discharge, strict=True)
        )
        + (right_boundary_state,)
    )
    maximum_signal = max(
        max(
            abs(value)
            for value in dynamic_wave_characteristic_speeds_mps(value, section)
        )
        for value in signal_states
    )
    courant = maximum_signal * timestep / length
    if courant > limit + 2.0 * np.finfo(float).eps:
        raise ValueError("hydrostatic_open_step_cfl_exceeded")

    cells = tuple(
        DynamicWaveCellState(float(a), float(q))
        for a, q in zip(area, discharge, strict=True)
    )
    interfaces = [
        hydrostatic_reconstruction_hll_flux(
            left_boundary_state,
            cells[0],
            left_bed_elevation_m=left_bed,
            right_bed_elevation_m=float(bed[0]),
            section=section,
        )
    ]
    for index in range(state.cell_count - 1):
        interfaces.append(
            hydrostatic_reconstruction_hll_flux(
                cells[index],
                cells[index + 1],
                left_bed_elevation_m=float(bed[index]),
                right_bed_elevation_m=float(bed[index + 1]),
                section=section,
            )
        )
    interfaces.append(
        hydrostatic_reconstruction_hll_flux(
            cells[-1],
            right_boundary_state,
            left_bed_elevation_m=float(bed[-1]),
            right_bed_elevation_m=right_bed,
            section=section,
        )
    )
    updated = np.empty((state.cell_count, 2), dtype=float)
    for index in range(state.cell_count):
        current = np.asarray([area[index], discharge[index]], dtype=float)
        updated[index] = current - (timestep / length) * (
            interfaces[index + 1].left_cell_flux.as_array()
            - interfaces[index].right_cell_flux.as_array()
        )
    if not np.isfinite(updated).all():
        raise FloatingPointError("hydrostatic_open_step_nonfinite_state")
    if (updated[:, 0] < -negative_tolerance).any():
        raise FloatingPointError("hydrostatic_open_step_negative_area")
    tiny = (updated[:, 0] < 0.0) & (updated[:, 0] >= -negative_tolerance)
    updated[tiny, 0] = 0.0
    updated[tiny & (np.abs(updated[:, 1]) <= negative_tolerance), 1] = 0.0
    next_state = PrismaticDynamicWaveState(
        area_m2=tuple(float(value) for value in updated[:, 0]),
        discharge_m3s=tuple(float(value) for value in updated[:, 1]),
    )
    before_surface = bed + np.asarray(
        [section.depth_m(value) for value in area], dtype=float
    )
    after_surface = bed + np.asarray(
        [section.depth_m(value) for value in updated[:, 0]], dtype=float
    )
    left_flux = interfaces[0].right_cell_flux.area_flux_m3s
    right_flux = interfaces[-1].left_cell_flux.area_flux_m3s
    boundary_volume = timestep * (left_flux - right_flux)
    volume_before = float(area.sum() * length)
    volume_after = float(updated[:, 0].sum() * length)
    momentum_before = float(discharge.sum() * length)
    momentum_after = float(updated[:, 1].sum() * length)
    return HydrostaticOpenStep(
        state=next_state,
        timestep_seconds=timestep,
        cell_length_m=length,
        maximum_courant_number=float(courant),
        left_boundary_area_flux_m3s=float(left_flux),
        right_boundary_area_flux_m3s=float(right_flux),
        prescribed_boundary_volume_change_m3=float(boundary_volume),
        volume_before_m3=volume_before,
        volume_after_m3=volume_after,
        volume_balance_error_m3=(volume_after - volume_before - boundary_volume),
        discharge_integral_before_m4s=momentum_before,
        discharge_integral_after_m4s=momentum_after,
        discharge_integral_change_m4s=momentum_after - momentum_before,
        maximum_free_surface_change_m=float(
            np.abs(after_surface - before_surface).max()
        ),
        minimum_area_m2=float(updated[:, 0].min()),
    )


def manning_friction_slope(
    state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
    *,
    manning_n: float,
) -> float:
    roughness = _positive(manning_n, "dynamic_wave_manning_n_invalid")
    if state.area_m2 == 0.0:
        return 0.0
    depth = section.depth_m(state.area_m2)
    wetted_perimeter = (
        section.bottom_width_m
        + 2.0
        * depth
        * math.sqrt(1.0 + section.side_slope_horizontal_per_vertical**2)
    )
    hydraulic_radius = state.area_m2 / wetted_perimeter
    return (
        roughness**2
        * state.discharge_m3s
        * abs(state.discharge_m3s)
        / (state.area_m2**2 * hydraulic_radius ** (4.0 / 3.0))
    )


def manning_uniform_discharge_m3s(
    *,
    area_m2: float,
    bed_slope: float,
    manning_n: float,
    section: TrapezoidalChannelSection,
) -> float:
    area = _positive(area_m2, "manning_uniform_area_invalid")
    slope = float(bed_slope)
    roughness = _positive(manning_n, "dynamic_wave_manning_n_invalid")
    if not math.isfinite(slope) or slope < 0.0:
        raise ValueError("manning_uniform_bed_slope_invalid")
    depth = section.depth_m(area)
    wetted_perimeter = (
        section.bottom_width_m
        + 2.0
        * depth
        * math.sqrt(1.0 + section.side_slope_horizontal_per_vertical**2)
    )
    hydraulic_radius = area / wetted_perimeter
    return (area / roughness) * hydraulic_radius ** (2.0 / 3.0) * math.sqrt(
        slope
    )


def apply_manning_slope_friction_source(
    state: PrismaticDynamicWaveState,
    section: TrapezoidalChannelSection,
    *,
    bed_slope: tuple[float, ...],
    manning_n: tuple[float, ...],
    timestep_seconds: float,
    cell_length_m: float,
) -> ManningSlopeFrictionStep:
    slopes = np.asarray(bed_slope, dtype=float)
    roughness = np.asarray(manning_n, dtype=float)
    timestep = _positive(timestep_seconds, "manning_source_timestep_invalid")
    length = _positive(cell_length_m, "manning_source_length_invalid")
    area = np.asarray(state.area_m2, dtype=float)
    discharge = np.asarray(state.discharge_m3s, dtype=float)
    if (
        slopes.shape != area.shape
        or roughness.shape != area.shape
        or not np.isfinite(slopes).all()
        or not np.isfinite(roughness).all()
        or (slopes < 0.0).any()
        or (roughness <= 0.0).any()
        or (discharge < 0.0).any()
    ):
        raise ValueError("manning_source_contract_invalid")
    updated = np.empty_like(discharge)
    residuals = []
    for index, (cell_area, flow, slope, roughness_value) in enumerate(
        zip(area, discharge, slopes, roughness, strict=True)
    ):
        if cell_area == 0.0:
            updated[index] = 0.0
            residuals.append(0.0)
            continue
        cell = DynamicWaveCellState(float(cell_area), float(flow))
        friction_slope = manning_friction_slope(
            cell, section, manning_n=float(roughness_value)
        )
        residuals.append(float(slope - friction_slope))
        if math.isclose(
            friction_slope,
            float(slope),
            rel_tol=1e-13,
            abs_tol=1e-15,
        ):
            updated[index] = flow
            continue
        depth = section.depth_m(float(cell_area))
        wetted_perimeter = (
            section.bottom_width_m
            + 2.0
            * depth
            * math.sqrt(1.0 + section.side_slope_horizontal_per_vertical**2)
        )
        hydraulic_radius = cell_area / wetted_perimeter
        acceleration = STANDARD_GRAVITY_MPS2 * cell_area * float(slope)
        drag = (
            STANDARD_GRAVITY_MPS2
            * float(roughness_value) ** 2
            / (cell_area * hydraulic_radius ** (4.0 / 3.0))
        )
        if acceleration == 0.0:
            updated[index] = flow / (1.0 + drag * flow * timestep)
            continue
        equilibrium = math.sqrt(acceleration / drag)
        ratio = flow / equilibrium
        rate = math.sqrt(acceleration * drag)
        if ratio < 1.0:
            updated[index] = equilibrium * math.tanh(
                rate * timestep + math.atanh(ratio)
            )
        elif ratio > 1.0:
            acoth = 0.5 * math.log((ratio + 1.0) / (ratio - 1.0))
            updated[index] = equilibrium / math.tanh(rate * timestep + acoth)
        else:
            updated[index] = flow
    next_state = PrismaticDynamicWaveState(
        area_m2=state.area_m2,
        discharge_m3s=tuple(float(value) for value in updated),
    )
    volume = float(area.sum() * length)
    return ManningSlopeFrictionStep(
        state=next_state,
        timestep_seconds=timestep,
        volume_before_m3=volume,
        volume_after_m3=volume,
        volume_balance_error_m3=0.0,
        discharge_sum_before_m3s=float(discharge.sum()),
        discharge_sum_after_m3s=float(updated.sum()),
        maximum_absolute_equilibrium_residual=float(
            max(abs(value) for value in residuals)
        ),
        flow_direction_preserved=bool((updated >= 0.0).all()),
    )


def apply_manning_friction_only_source(
    state: PrismaticDynamicWaveState,
    section: TrapezoidalChannelSection,
    *,
    manning_n: tuple[float, ...],
    timestep_seconds: float,
    cell_length_m: float,
) -> ManningSlopeFrictionStep:
    roughness = np.asarray(manning_n, dtype=float)
    timestep = _positive(
        timestep_seconds, "manning_friction_source_timestep_invalid"
    )
    length = _positive(cell_length_m, "manning_friction_source_length_invalid")
    area = np.asarray(state.area_m2, dtype=float)
    discharge = np.asarray(state.discharge_m3s, dtype=float)
    if (
        roughness.shape != area.shape
        or not np.isfinite(roughness).all()
        or (roughness <= 0.0).any()
    ):
        raise ValueError("manning_friction_source_contract_invalid")
    updated = np.empty_like(discharge)
    friction_slopes = []
    for index, (cell_area, flow, roughness_value) in enumerate(
        zip(area, discharge, roughness, strict=True)
    ):
        if cell_area == 0.0:
            updated[index] = 0.0
            friction_slopes.append(0.0)
            continue
        cell = DynamicWaveCellState(float(cell_area), float(flow))
        friction_slopes.append(
            manning_friction_slope(
                cell, section, manning_n=float(roughness_value)
            )
        )
        depth = section.depth_m(float(cell_area))
        wetted_perimeter = (
            section.bottom_width_m
            + 2.0
            * depth
            * math.sqrt(1.0 + section.side_slope_horizontal_per_vertical**2)
        )
        hydraulic_radius = cell_area / wetted_perimeter
        drag = (
            STANDARD_GRAVITY_MPS2
            * float(roughness_value) ** 2
            / (cell_area * hydraulic_radius ** (4.0 / 3.0))
        )
        updated[index] = flow / (1.0 + drag * abs(flow) * timestep)
    next_state = PrismaticDynamicWaveState(
        area_m2=state.area_m2,
        discharge_m3s=tuple(float(value) for value in updated),
    )
    volume = float(area.sum() * length)
    direction_preserved = bool(
        all(
            after == 0.0
            or before == 0.0
            or math.copysign(1.0, after) == math.copysign(1.0, before)
            for before, after in zip(discharge, updated, strict=True)
        )
    )
    return ManningSlopeFrictionStep(
        state=next_state,
        timestep_seconds=timestep,
        volume_before_m3=volume,
        volume_after_m3=volume,
        volume_balance_error_m3=0.0,
        discharge_sum_before_m3s=float(discharge.sum()),
        discharge_sum_after_m3s=float(updated.sum()),
        maximum_absolute_equilibrium_residual=float(
            max(abs(value) for value in friction_slopes)
        ),
        flow_direction_preserved=direction_preserved,
    )


def apply_lateral_inflow_source(
    state: PrismaticDynamicWaveState,
    *,
    lateral_inflow_m2s: tuple[float, ...],
    timestep_seconds: float,
    cell_length_m: float,
    momentum_convention: str,
) -> LateralInflowSourceStep:
    lateral = np.asarray(lateral_inflow_m2s, dtype=float)
    timestep = _positive(timestep_seconds, "lateral_source_timestep_invalid")
    length = _positive(cell_length_m, "lateral_source_length_invalid")
    area = np.asarray(state.area_m2, dtype=float)
    discharge = np.asarray(state.discharge_m3s, dtype=float)
    if (
        lateral.shape != area.shape
        or not np.isfinite(lateral).all()
        or (lateral < 0.0).any()
        or momentum_convention not in _LATERAL_MOMENTUM_CONVENTIONS
    ):
        raise ValueError("lateral_source_contract_invalid")
    added_area = timestep * lateral
    updated_area = area + added_area
    if momentum_convention == "zero_longitudinal_momentum":
        updated_discharge = discharge.copy()
    else:
        velocity = np.divide(
            discharge,
            area,
            out=np.zeros_like(discharge),
            where=area > 0.0,
        )
        updated_discharge = discharge + velocity * added_area
    next_state = PrismaticDynamicWaveState(
        area_m2=tuple(float(value) for value in updated_area),
        discharge_m3s=tuple(float(value) for value in updated_discharge),
    )
    before = float(area.sum() * length)
    prescribed = float(lateral.sum() * timestep * length)
    after = float(updated_area.sum() * length)
    return LateralInflowSourceStep(
        state=next_state,
        timestep_seconds=timestep,
        cell_length_m=length,
        momentum_convention=momentum_convention,
        volume_before_m3=before,
        prescribed_lateral_volume_m3=prescribed,
        volume_after_m3=after,
        volume_balance_error_m3=after - before - prescribed,
    )


def _finite(value: float, message: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(message)
    return result


def _positive(value: float, message: str) -> float:
    result = _finite(value, message)
    if result <= 0.0:
        raise ValueError(message)
    return result
