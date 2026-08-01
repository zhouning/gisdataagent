"""Well-balanced dynamic-wave fluxes for spatially varying sections."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .dynamic_wave_boundaries import (
    CharacteristicDynamicWaveBoundary,
    ResolvedCharacteristicDynamicWaveBoundary,
    resolve_characteristic_dynamic_wave_boundary,
)
from .dynamic_wave_coupled import FixedDynamicWaveBoundary
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
from .dynamic_wave_sources import (
    ManningSlopeFrictionStep,
    apply_lateral_inflow_source,
    manning_friction_slope,
)


VARIABLE_GEOMETRY_HYDROSTATIC_FLUX_SCHEMA = (
    "gwm.geospatial_kernel.variable_geometry_hydrostatic_flux.v1"
)
VARIABLE_GEOMETRY_HYDROSTATIC_OPEN_STEP_SCHEMA = (
    "gwm.geospatial_kernel.variable_geometry_hydrostatic_open_step.v1"
)
COUPLED_VARIABLE_GEOMETRY_OPEN_STEP_SCHEMA = (
    "gwm.geospatial_kernel.coupled_variable_geometry_open_step.v1"
)


VariableGeometryOpenBoundary = (
    FixedDynamicWaveBoundary | CharacteristicDynamicWaveBoundary
)


@dataclass(frozen=True)
class _ResolvedVariableGeometryBoundary:
    state: DynamicWaveCellState
    bed_elevation_m: float
    characteristic: ResolvedCharacteristicDynamicWaveBoundary | None


@dataclass(frozen=True)
class VariableGeometryHydrostaticFlux:
    left_cell_flux: DynamicWaveFlux
    right_cell_flux: DynamicWaveFlux
    interface_section: TrapezoidalChannelSection
    reconstructed_left_state: DynamicWaveCellState
    reconstructed_right_state: DynamicWaveCellState
    interface_bed_elevation_m: float
    hll: DynamicWaveHLLFluxResult
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": VARIABLE_GEOMETRY_HYDROSTATIC_FLUX_SCHEMA,
            "left_cell_flux": {
                "area_flux_m3s": self.left_cell_flux.area_flux_m3s,
                "momentum_flux_m4s2": self.left_cell_flux.momentum_flux_m4s2,
            },
            "right_cell_flux": {
                "area_flux_m3s": self.right_cell_flux.area_flux_m3s,
                "momentum_flux_m4s2": self.right_cell_flux.momentum_flux_m4s2,
            },
            "interface_section": _section_dict(self.interface_section),
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
            "interface_geometry_rule": "arithmetic_parameter_midpoint",
            "velocity_preserving_state_projection": True,
            "lake_at_rest_balance_intended": True,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class VariableGeometryHydrostaticOpenStep:
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
            "schema": VARIABLE_GEOMETRY_HYDROSTATIC_OPEN_STEP_SCHEMA,
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
            "discharge_integral_before_m4s": (
                self.discharge_integral_before_m4s
            ),
            "discharge_integral_after_m4s": (
                self.discharge_integral_after_m4s
            ),
            "discharge_integral_change_m4s": (
                self.discharge_integral_change_m4s
            ),
            "maximum_free_surface_change_m": (
                self.maximum_free_surface_change_m
            ),
            "minimum_area_m2": self.minimum_area_m2,
            "finite_state": True,
            "nonnegative_area": self.minimum_area_m2 >= 0.0,
            "interface_geometry_rule": "arithmetic_parameter_midpoint",
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class CoupledVariableGeometryOpenStep:
    state: PrismaticDynamicWaveState
    timestep_seconds: float
    cell_length_m: float
    maximum_courant_number: float
    momentum_convention: str
    boundary_semantics: str
    volume_before_m3: float
    lateral_volume_change_m3: float
    boundary_volume_change_m3: float
    volume_after_m3: float
    volume_balance_error_m3: float
    discharge_integral_before_m4s: float
    lateral_momentum_change_m4s: float
    friction_momentum_change_m4s: float
    boundary_geometry_and_bed_momentum_change_m4s: float
    discharge_integral_after_m4s: float
    momentum_ledger_error_m4s: float
    minimum_area_m2: float
    left_characteristic_boundary: (
        ResolvedCharacteristicDynamicWaveBoundary | None
    )
    right_characteristic_boundary: (
        ResolvedCharacteristicDynamicWaveBoundary | None
    )
    hydrostatic_step: VariableGeometryHydrostaticOpenStep
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": COUPLED_VARIABLE_GEOMETRY_OPEN_STEP_SCHEMA,
            "timestep_seconds": self.timestep_seconds,
            "cell_length_m": self.cell_length_m,
            "maximum_courant_number": self.maximum_courant_number,
            "momentum_convention": self.momentum_convention,
            "boundary_semantics": self.boundary_semantics,
            "volume_before_m3": self.volume_before_m3,
            "lateral_volume_change_m3": self.lateral_volume_change_m3,
            "boundary_volume_change_m3": self.boundary_volume_change_m3,
            "volume_after_m3": self.volume_after_m3,
            "volume_balance_error_m3": self.volume_balance_error_m3,
            "discharge_integral_before_m4s": (
                self.discharge_integral_before_m4s
            ),
            "lateral_momentum_change_m4s": self.lateral_momentum_change_m4s,
            "friction_momentum_change_m4s": self.friction_momentum_change_m4s,
            "boundary_geometry_and_bed_momentum_change_m4s": (
                self.boundary_geometry_and_bed_momentum_change_m4s
            ),
            "discharge_integral_after_m4s": (
                self.discharge_integral_after_m4s
            ),
            "momentum_ledger_error_m4s": self.momentum_ledger_error_m4s,
            "minimum_area_m2": self.minimum_area_m2,
            "finite_state": True,
            "nonnegative_area": self.minimum_area_m2 >= 0.0,
            "interface_geometry_rule": "arithmetic_parameter_midpoint",
            "bed_and_geometry_source": "hydrostatic_reconstruction_only",
            "friction_source": "cell_section_fixed_area_minus_gA_Sf_only",
            "source_split_order": (
                "lateral_half,variable_friction_half,"
                "variable_hydrostatic_flux_full,variable_friction_half,"
                "lateral_half"
            ),
            "left_characteristic_boundary": (
                None
                if self.left_characteristic_boundary is None
                else self.left_characteristic_boundary.as_dict()
            ),
            "right_characteristic_boundary": (
                None
                if self.right_characteristic_boundary is None
                else self.right_characteristic_boundary.as_dict()
            ),
            "hydrostatic_step": self.hydrostatic_step.as_dict(),
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


def arithmetic_interface_section(
    left: TrapezoidalChannelSection,
    right: TrapezoidalChannelSection,
) -> TrapezoidalChannelSection:
    return TrapezoidalChannelSection(
        bottom_width_m=0.5 * (left.bottom_width_m + right.bottom_width_m),
        side_slope_horizontal_per_vertical=0.5
        * (
            left.side_slope_horizontal_per_vertical
            + right.side_slope_horizontal_per_vertical
        ),
    )


def variable_geometry_hydrostatic_hll_flux(
    left: DynamicWaveCellState,
    right: DynamicWaveCellState,
    *,
    left_bed_elevation_m: float,
    right_bed_elevation_m: float,
    left_section: TrapezoidalChannelSection,
    right_section: TrapezoidalChannelSection,
) -> VariableGeometryHydrostaticFlux:
    left_bed = _finite(
        left_bed_elevation_m, "variable_geometry_bed_elevation_invalid"
    )
    right_bed = _finite(
        right_bed_elevation_m, "variable_geometry_bed_elevation_invalid"
    )
    interface_section = arithmetic_interface_section(
        left_section, right_section
    )
    left_depth = left_section.depth_m(left.area_m2)
    right_depth = right_section.depth_m(right.area_m2)
    interface_bed = max(left_bed, right_bed)
    reconstructed_left_depth = max(
        0.0, left_bed + left_depth - interface_bed
    )
    reconstructed_right_depth = max(
        0.0, right_bed + right_depth - interface_bed
    )
    reconstructed_left_area = interface_section.area_m2(
        reconstructed_left_depth
    )
    reconstructed_right_area = interface_section.area_m2(
        reconstructed_right_depth
    )
    reconstructed_left = DynamicWaveCellState(
        reconstructed_left_area,
        0.0
        if left.area_m2 == 0.0
        else left.discharge_m3s * reconstructed_left_area / left.area_m2,
    )
    reconstructed_right = DynamicWaveCellState(
        reconstructed_right_area,
        0.0
        if right.area_m2 == 0.0
        else right.discharge_m3s * reconstructed_right_area / right.area_m2,
    )
    hll = hll_dynamic_wave_flux(
        reconstructed_left, reconstructed_right, interface_section
    )
    interface_left_pressure = (
        STANDARD_GRAVITY_MPS2
        * interface_section.hydrostatic_pressure_integral_m3(
            reconstructed_left_area
        )
    )
    interface_right_pressure = (
        STANDARD_GRAVITY_MPS2
        * interface_section.hydrostatic_pressure_integral_m3(
            reconstructed_right_area
        )
    )
    left_pressure = (
        STANDARD_GRAVITY_MPS2
        * left_section.hydrostatic_pressure_integral_m3(left.area_m2)
    )
    right_pressure = (
        STANDARD_GRAVITY_MPS2
        * right_section.hydrostatic_pressure_integral_m3(right.area_m2)
    )
    return VariableGeometryHydrostaticFlux(
        left_cell_flux=DynamicWaveFlux(
            hll.flux.area_flux_m3s,
            hll.flux.momentum_flux_m4s2
            + left_pressure
            - interface_left_pressure,
        ),
        right_cell_flux=DynamicWaveFlux(
            hll.flux.area_flux_m3s,
            hll.flux.momentum_flux_m4s2
            + right_pressure
            - interface_right_pressure,
        ),
        interface_section=interface_section,
        reconstructed_left_state=reconstructed_left,
        reconstructed_right_state=reconstructed_right,
        interface_bed_elevation_m=interface_bed,
        hll=hll,
    )


def maximum_variable_geometry_open_stable_timestep_seconds(
    state: PrismaticDynamicWaveState,
    sections: tuple[TrapezoidalChannelSection, ...],
    *,
    left_boundary_state: DynamicWaveCellState,
    right_boundary_state: DynamicWaveCellState,
    left_boundary_section: TrapezoidalChannelSection,
    right_boundary_section: TrapezoidalChannelSection,
    cell_length_m: float,
    courant_number: float,
) -> float | None:
    length = _positive(
        cell_length_m, "variable_geometry_open_cfl_length_invalid"
    )
    courant = _positive(
        courant_number, "variable_geometry_open_cfl_number_invalid"
    )
    _validate_sections(state, sections)
    if courant > 1.0:
        raise ValueError("variable_geometry_open_cfl_contract_invalid")
    state_sections = (
        ((left_boundary_state, left_boundary_section),)
        + tuple(
            (
                DynamicWaveCellState(area, discharge),
                section,
            )
            for area, discharge, section in zip(
                state.area_m2, state.discharge_m3s, sections, strict=True
            )
        )
        + ((right_boundary_state, right_boundary_section),)
    )
    maximum_speed = max(
        max(
            abs(speed)
            for speed in dynamic_wave_characteristic_speeds_mps(
                cell, section
            )
        )
        for cell, section in state_sections
    )
    return None if maximum_speed == 0.0 else courant * length / maximum_speed


def maximum_coupled_variable_geometry_open_stable_timestep_seconds(
    state: PrismaticDynamicWaveState,
    sections: tuple[TrapezoidalChannelSection, ...],
    *,
    left_boundary: VariableGeometryOpenBoundary,
    right_boundary: VariableGeometryOpenBoundary,
    left_boundary_section: TrapezoidalChannelSection,
    right_boundary_section: TrapezoidalChannelSection,
    cell_length_m: float,
    courant_number: float,
) -> float | None:
    _validate_sections(state, sections)
    left = _resolve_variable_geometry_boundary(
        left_boundary,
        expected_side="left",
        interior_state=DynamicWaveCellState(
            state.area_m2[0], state.discharge_m3s[0]
        ),
        interior_section=sections[0],
        boundary_section=left_boundary_section,
    )
    right = _resolve_variable_geometry_boundary(
        right_boundary,
        expected_side="right",
        interior_state=DynamicWaveCellState(
            state.area_m2[-1], state.discharge_m3s[-1]
        ),
        interior_section=sections[-1],
        boundary_section=right_boundary_section,
    )
    return maximum_variable_geometry_open_stable_timestep_seconds(
        state,
        sections,
        left_boundary_state=left.state,
        right_boundary_state=right.state,
        left_boundary_section=left_boundary_section,
        right_boundary_section=right_boundary_section,
        cell_length_m=cell_length_m,
        courant_number=courant_number,
    )


def apply_variable_geometry_manning_friction_only_source(
    state: PrismaticDynamicWaveState,
    sections: tuple[TrapezoidalChannelSection, ...],
    *,
    manning_n: tuple[float, ...],
    timestep_seconds: float,
    cell_length_m: float,
) -> ManningSlopeFrictionStep:
    _validate_sections(state, sections)
    roughness = np.asarray(manning_n, dtype=float)
    timestep = _positive(
        timestep_seconds, "variable_geometry_friction_timestep_invalid"
    )
    length = _positive(
        cell_length_m, "variable_geometry_friction_length_invalid"
    )
    area = np.asarray(state.area_m2, dtype=float)
    discharge = np.asarray(state.discharge_m3s, dtype=float)
    if (
        roughness.shape != area.shape
        or not np.isfinite(roughness).all()
        or (roughness <= 0.0).any()
    ):
        raise ValueError("variable_geometry_friction_contract_invalid")
    updated = np.empty_like(discharge)
    friction_slopes = []
    for index, (cell_area, flow, section, roughness_value) in enumerate(
        zip(area, discharge, sections, roughness, strict=True)
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
            * math.sqrt(
                1.0 + section.side_slope_horizontal_per_vertical**2
            )
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
    direction_preserved = all(
        after == 0.0
        or before == 0.0
        or math.copysign(1.0, after) == math.copysign(1.0, before)
        for before, after in zip(discharge, updated, strict=True)
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
        flow_direction_preserved=bool(direction_preserved),
    )


def advance_variable_geometry_hydrostatic_open(
    state: PrismaticDynamicWaveState,
    bed_elevation_m: tuple[float, ...],
    sections: tuple[TrapezoidalChannelSection, ...],
    *,
    left_boundary_state: DynamicWaveCellState,
    right_boundary_state: DynamicWaveCellState,
    left_boundary_bed_elevation_m: float,
    right_boundary_bed_elevation_m: float,
    left_boundary_section: TrapezoidalChannelSection,
    right_boundary_section: TrapezoidalChannelSection,
    cell_length_m: float,
    timestep_seconds: float,
    maximum_courant_number: float,
    negative_area_tolerance_m2: float = 1e-12,
    left_boundary_cell_flux_override: DynamicWaveFlux | None = None,
    right_boundary_cell_flux_override: DynamicWaveFlux | None = None,
) -> VariableGeometryHydrostaticOpenStep:
    bed = np.asarray(bed_elevation_m, dtype=float)
    length = _positive(
        cell_length_m, "variable_geometry_open_step_length_invalid"
    )
    timestep = _positive(
        timestep_seconds, "variable_geometry_open_step_timestep_invalid"
    )
    limit = _positive(
        maximum_courant_number, "variable_geometry_open_step_cfl_invalid"
    )
    left_bed = _finite(
        left_boundary_bed_elevation_m,
        "variable_geometry_open_boundary_bed_invalid",
    )
    right_bed = _finite(
        right_boundary_bed_elevation_m,
        "variable_geometry_open_boundary_bed_invalid",
    )
    negative_tolerance = float(negative_area_tolerance_m2)
    _validate_sections(state, sections)
    if (
        bed.shape != (state.cell_count,)
        or not np.isfinite(bed).all()
        or limit > 1.0
        or not math.isfinite(negative_tolerance)
        or negative_tolerance < 0.0
    ):
        raise ValueError("variable_geometry_open_step_contract_invalid")
    area = np.asarray(state.area_m2, dtype=float)
    discharge = np.asarray(state.discharge_m3s, dtype=float)
    maximum_timestep = maximum_variable_geometry_open_stable_timestep_seconds(
        state,
        sections,
        left_boundary_state=left_boundary_state,
        right_boundary_state=right_boundary_state,
        left_boundary_section=left_boundary_section,
        right_boundary_section=right_boundary_section,
        cell_length_m=length,
        courant_number=limit,
    )
    if maximum_timestep is not None and timestep > (
        maximum_timestep + 2.0 * np.finfo(float).eps * max(1.0, timestep)
    ):
        raise ValueError("variable_geometry_open_step_cfl_exceeded")
    cells = tuple(
        DynamicWaveCellState(float(a), float(q))
        for a, q in zip(area, discharge, strict=True)
    )
    interfaces = [
        variable_geometry_hydrostatic_hll_flux(
            left_boundary_state,
            cells[0],
            left_bed_elevation_m=left_bed,
            right_bed_elevation_m=float(bed[0]),
            left_section=left_boundary_section,
            right_section=sections[0],
        )
    ]
    for index in range(state.cell_count - 1):
        interfaces.append(
            variable_geometry_hydrostatic_hll_flux(
                cells[index],
                cells[index + 1],
                left_bed_elevation_m=float(bed[index]),
                right_bed_elevation_m=float(bed[index + 1]),
                left_section=sections[index],
                right_section=sections[index + 1],
            )
        )
    interfaces.append(
        variable_geometry_hydrostatic_hll_flux(
            cells[-1],
            right_boundary_state,
            left_bed_elevation_m=float(bed[-1]),
            right_bed_elevation_m=right_bed,
            left_section=sections[-1],
            right_section=right_boundary_section,
        )
    )
    updated = np.empty((state.cell_count, 2), dtype=float)
    for index in range(state.cell_count):
        current = np.asarray([area[index], discharge[index]], dtype=float)
        left_cell_flux = (
            left_boundary_cell_flux_override
            if index == 0 and left_boundary_cell_flux_override is not None
            else interfaces[index].right_cell_flux
        )
        right_cell_flux = (
            right_boundary_cell_flux_override
            if index == state.cell_count - 1
            and right_boundary_cell_flux_override is not None
            else interfaces[index + 1].left_cell_flux
        )
        updated[index] = current - (timestep / length) * (
            right_cell_flux.as_array() - left_cell_flux.as_array()
        )
    if not np.isfinite(updated).all():
        raise FloatingPointError("variable_geometry_open_step_nonfinite_state")
    if (updated[:, 0] < -negative_tolerance).any():
        raise FloatingPointError("variable_geometry_open_step_negative_area")
    tiny = (updated[:, 0] < 0.0) & (updated[:, 0] >= -negative_tolerance)
    updated[tiny, 0] = 0.0
    updated[tiny & (np.abs(updated[:, 1]) <= negative_tolerance), 1] = 0.0
    next_state = PrismaticDynamicWaveState(
        area_m2=tuple(float(value) for value in updated[:, 0]),
        discharge_m3s=tuple(float(value) for value in updated[:, 1]),
    )
    before_surface = bed + np.asarray(
        [
            section.depth_m(cell_area)
            for section, cell_area in zip(sections, area, strict=True)
        ],
        dtype=float,
    )
    after_surface = bed + np.asarray(
        [
            section.depth_m(cell_area)
            for section, cell_area in zip(
                sections, updated[:, 0], strict=True
            )
        ],
        dtype=float,
    )
    left_boundary_cell_flux = (
        interfaces[0].right_cell_flux
        if left_boundary_cell_flux_override is None
        else left_boundary_cell_flux_override
    )
    right_boundary_cell_flux = (
        interfaces[-1].left_cell_flux
        if right_boundary_cell_flux_override is None
        else right_boundary_cell_flux_override
    )
    left_flux = left_boundary_cell_flux.area_flux_m3s
    right_flux = right_boundary_cell_flux.area_flux_m3s
    boundary_volume = timestep * (left_flux - right_flux)
    volume_before = float(area.sum() * length)
    volume_after = float(updated[:, 0].sum() * length)
    momentum_before = float(discharge.sum() * length)
    momentum_after = float(updated[:, 1].sum() * length)
    return VariableGeometryHydrostaticOpenStep(
        state=next_state,
        timestep_seconds=timestep,
        cell_length_m=length,
        maximum_courant_number=(
            0.0
            if maximum_timestep is None
            else limit * timestep / maximum_timestep
        ),
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


def advance_coupled_variable_geometry_open(
    state: PrismaticDynamicWaveState,
    bed_elevation_m: tuple[float, ...],
    sections: tuple[TrapezoidalChannelSection, ...],
    *,
    left_boundary: VariableGeometryOpenBoundary,
    right_boundary: VariableGeometryOpenBoundary,
    left_boundary_section: TrapezoidalChannelSection,
    right_boundary_section: TrapezoidalChannelSection,
    manning_n: tuple[float, ...],
    lateral_inflow_m2s: tuple[float, ...],
    lateral_momentum_convention: str,
    cell_length_m: float,
    timestep_seconds: float,
    maximum_courant_number: float,
) -> CoupledVariableGeometryOpenStep:
    _validate_sections(state, sections)
    length = _positive(
        cell_length_m, "coupled_variable_geometry_step_length_invalid"
    )
    timestep = _positive(
        timestep_seconds, "coupled_variable_geometry_step_timestep_invalid"
    )
    half_timestep = 0.5 * timestep
    before_volume = _volume(state, length)
    before_momentum = _momentum_integral(state, length)

    lateral_first = apply_lateral_inflow_source(
        state,
        lateral_inflow_m2s=lateral_inflow_m2s,
        timestep_seconds=half_timestep,
        cell_length_m=length,
        momentum_convention=lateral_momentum_convention,
    )
    momentum_after_lateral_first = _momentum_integral(
        lateral_first.state, length
    )
    friction_first = apply_variable_geometry_manning_friction_only_source(
        lateral_first.state,
        sections,
        manning_n=manning_n,
        timestep_seconds=half_timestep,
        cell_length_m=length,
    )
    momentum_after_friction_first = _momentum_integral(
        friction_first.state, length
    )
    resolved_left = _resolve_variable_geometry_boundary(
        left_boundary,
        expected_side="left",
        interior_state=DynamicWaveCellState(
            friction_first.state.area_m2[0],
            friction_first.state.discharge_m3s[0],
        ),
        interior_section=sections[0],
        boundary_section=left_boundary_section,
    )
    resolved_right = _resolve_variable_geometry_boundary(
        right_boundary,
        expected_side="right",
        interior_state=DynamicWaveCellState(
            friction_first.state.area_m2[-1],
            friction_first.state.discharge_m3s[-1],
        ),
        interior_section=sections[-1],
        boundary_section=right_boundary_section,
    )
    hydrostatic = advance_variable_geometry_hydrostatic_open(
        friction_first.state,
        bed_elevation_m,
        sections,
        left_boundary_state=resolved_left.state,
        right_boundary_state=resolved_right.state,
        left_boundary_bed_elevation_m=resolved_left.bed_elevation_m,
        right_boundary_bed_elevation_m=resolved_right.bed_elevation_m,
        left_boundary_section=left_boundary_section,
        right_boundary_section=right_boundary_section,
        cell_length_m=length,
        timestep_seconds=timestep,
        maximum_courant_number=maximum_courant_number,
    )
    momentum_after_hydrostatic = _momentum_integral(
        hydrostatic.state, length
    )
    friction_second = apply_variable_geometry_manning_friction_only_source(
        hydrostatic.state,
        sections,
        manning_n=manning_n,
        timestep_seconds=half_timestep,
        cell_length_m=length,
    )
    momentum_after_friction_second = _momentum_integral(
        friction_second.state, length
    )
    lateral_second = apply_lateral_inflow_source(
        friction_second.state,
        lateral_inflow_m2s=lateral_inflow_m2s,
        timestep_seconds=half_timestep,
        cell_length_m=length,
        momentum_convention=lateral_momentum_convention,
    )
    final_state = lateral_second.state
    after_volume = _volume(final_state, length)
    after_momentum = _momentum_integral(final_state, length)
    lateral_volume = (
        lateral_first.prescribed_lateral_volume_m3
        + lateral_second.prescribed_lateral_volume_m3
    )
    boundary_volume = hydrostatic.prescribed_boundary_volume_change_m3
    lateral_momentum = (
        momentum_after_lateral_first
        - before_momentum
        + after_momentum
        - momentum_after_friction_second
    )
    friction_momentum = (
        momentum_after_friction_first
        - momentum_after_lateral_first
        + momentum_after_friction_second
        - momentum_after_hydrostatic
    )
    boundary_geometry_and_bed_momentum = (
        momentum_after_hydrostatic - momentum_after_friction_first
    )
    momentum_ledger_error = (
        after_momentum
        - before_momentum
        - lateral_momentum
        - friction_momentum
        - boundary_geometry_and_bed_momentum
    )
    if (
        resolved_left.characteristic is None
        and resolved_right.characteristic is None
    ):
        boundary_semantics = "fixed_ghost_state"
    elif (
        resolved_left.characteristic is not None
        and resolved_right.characteristic is not None
    ):
        boundary_semantics = "characteristic_ghost_state"
    else:
        boundary_semantics = "mixed_fixed_and_characteristic_ghost_state"
    return CoupledVariableGeometryOpenStep(
        state=final_state,
        timestep_seconds=timestep,
        cell_length_m=length,
        maximum_courant_number=hydrostatic.maximum_courant_number,
        momentum_convention=lateral_momentum_convention,
        boundary_semantics=boundary_semantics,
        volume_before_m3=before_volume,
        lateral_volume_change_m3=lateral_volume,
        boundary_volume_change_m3=boundary_volume,
        volume_after_m3=after_volume,
        volume_balance_error_m3=(
            after_volume - before_volume - lateral_volume - boundary_volume
        ),
        discharge_integral_before_m4s=before_momentum,
        lateral_momentum_change_m4s=lateral_momentum,
        friction_momentum_change_m4s=friction_momentum,
        boundary_geometry_and_bed_momentum_change_m4s=(
            boundary_geometry_and_bed_momentum
        ),
        discharge_integral_after_m4s=after_momentum,
        momentum_ledger_error_m4s=momentum_ledger_error,
        minimum_area_m2=min(final_state.area_m2),
        left_characteristic_boundary=resolved_left.characteristic,
        right_characteristic_boundary=resolved_right.characteristic,
        hydrostatic_step=hydrostatic,
    )


def _resolve_variable_geometry_boundary(
    boundary: VariableGeometryOpenBoundary,
    *,
    expected_side: str,
    interior_state: DynamicWaveCellState,
    interior_section: TrapezoidalChannelSection,
    boundary_section: TrapezoidalChannelSection,
) -> _ResolvedVariableGeometryBoundary:
    if isinstance(boundary, FixedDynamicWaveBoundary):
        return _ResolvedVariableGeometryBoundary(
            state=boundary.state,
            bed_elevation_m=boundary.bed_elevation_m,
            characteristic=None,
        )
    if boundary.side != expected_side:
        raise ValueError("variable_geometry_boundary_side_mismatch")
    resolved = resolve_characteristic_dynamic_wave_boundary(
        boundary,
        interior_state,
        interior_section,
        boundary_section=boundary_section,
    )
    return _ResolvedVariableGeometryBoundary(
        state=resolved.state,
        bed_elevation_m=resolved.bed_elevation_m,
        characteristic=resolved,
    )


def _volume(state: PrismaticDynamicWaveState, cell_length_m: float) -> float:
    return float(sum(state.area_m2) * cell_length_m)


def _momentum_integral(
    state: PrismaticDynamicWaveState, cell_length_m: float
) -> float:
    return float(sum(state.discharge_m3s) * cell_length_m)


def _validate_sections(
    state: PrismaticDynamicWaveState,
    sections: tuple[TrapezoidalChannelSection, ...],
) -> None:
    if (
        len(sections) != state.cell_count
        or not all(
            isinstance(section, TrapezoidalChannelSection)
            for section in sections
        )
    ):
        raise ValueError("variable_geometry_sections_contract_invalid")


def _section_dict(section: TrapezoidalChannelSection) -> dict[str, float]:
    return {
        "bottom_width_m": section.bottom_width_m,
        "side_slope_horizontal_per_vertical": (
            section.side_slope_horizontal_per_vertical
        ),
    }


def _positive(value: float, error: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(error)
    return result


def _finite(value: float, error: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(error)
    return result
