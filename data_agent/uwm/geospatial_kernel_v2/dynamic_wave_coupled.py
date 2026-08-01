"""Source-split open-boundary dynamic-wave single-reach candidate."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .dynamic_wave_boundaries import (
    CharacteristicDynamicWaveBoundary,
    ResolvedCharacteristicDynamicWaveBoundary,
    resolve_characteristic_dynamic_wave_boundary,
)
from .dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
    dynamic_wave_characteristic_speeds_mps,
)
from .dynamic_wave_sources import (
    HydrostaticOpenStep,
    advance_hydrostatic_reconstruction_open,
    apply_lateral_inflow_source,
    apply_manning_friction_only_source,
)


DYNAMIC_WAVE_COUPLED_OPEN_STEP_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_wave_coupled_open_step.v1"
)
DYNAMIC_WAVE_CHARACTERISTIC_COUPLED_OPEN_STEP_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_wave_coupled_open_step.v2"
)


@dataclass(frozen=True)
class FixedDynamicWaveBoundary:
    state: DynamicWaveCellState
    bed_elevation_m: float

    def __post_init__(self) -> None:
        elevation = float(self.bed_elevation_m)
        if not math.isfinite(elevation):
            raise ValueError("dynamic_wave_fixed_boundary_bed_invalid")
        object.__setattr__(self, "bed_elevation_m", elevation)


DynamicWaveOpenBoundary = (
    FixedDynamicWaveBoundary | CharacteristicDynamicWaveBoundary
)


@dataclass(frozen=True)
class _ResolvedOpenBoundary:
    state: DynamicWaveCellState
    bed_elevation_m: float
    characteristic: ResolvedCharacteristicDynamicWaveBoundary | None


@dataclass(frozen=True)
class CoupledDynamicWaveOpenStep:
    state: PrismaticDynamicWaveState
    timestep_seconds: float
    cell_length_m: float
    maximum_courant_number: float
    momentum_convention: str
    volume_before_m3: float
    lateral_volume_change_m3: float
    boundary_volume_change_m3: float
    volume_after_m3: float
    volume_balance_error_m3: float
    discharge_integral_before_m4s: float
    lateral_momentum_change_m4s: float
    friction_momentum_change_m4s: float
    boundary_and_bed_momentum_change_m4s: float
    discharge_integral_after_m4s: float
    momentum_ledger_error_m4s: float
    minimum_area_m2: float
    boundary_semantics: str
    left_characteristic_boundary: (
        ResolvedCharacteristicDynamicWaveBoundary | None
    )
    right_characteristic_boundary: (
        ResolvedCharacteristicDynamicWaveBoundary | None
    )
    hydrostatic_step: HydrostaticOpenStep
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema": (
                DYNAMIC_WAVE_COUPLED_OPEN_STEP_SCHEMA
                if self.boundary_semantics == "fixed_ghost_state"
                else DYNAMIC_WAVE_CHARACTERISTIC_COUPLED_OPEN_STEP_SCHEMA
            ),
            "timestep_seconds": self.timestep_seconds,
            "cell_length_m": self.cell_length_m,
            "maximum_courant_number": self.maximum_courant_number,
            "momentum_convention": self.momentum_convention,
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
            "boundary_and_bed_momentum_change_m4s": (
                self.boundary_and_bed_momentum_change_m4s
            ),
            "discharge_integral_after_m4s": self.discharge_integral_after_m4s,
            "momentum_ledger_error_m4s": self.momentum_ledger_error_m4s,
            "minimum_area_m2": self.minimum_area_m2,
            "finite_state": True,
            "nonnegative_area": self.minimum_area_m2 >= 0.0,
            "bed_acceleration_source": "hydrostatic_reconstruction_only",
            "friction_source": "fixed_area_minus_gA_Sf_only",
            "boundary_semantics": self.boundary_semantics,
            "source_split_order": (
                "lateral_half,friction_half,hydrostatic_flux_full,"
                "friction_half,lateral_half"
            ),
            "hydrostatic_step": self.hydrostatic_step.as_dict(),
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }
        if self.boundary_semantics != "fixed_ghost_state":
            payload["left_characteristic_boundary"] = (
                None
                if self.left_characteristic_boundary is None
                else self.left_characteristic_boundary.as_dict()
            )
            payload["right_characteristic_boundary"] = (
                None
                if self.right_characteristic_boundary is None
                else self.right_characteristic_boundary.as_dict()
            )
        return payload


def maximum_open_stable_timestep_seconds(
    state: PrismaticDynamicWaveState,
    section: TrapezoidalChannelSection,
    *,
    left_boundary: DynamicWaveOpenBoundary,
    right_boundary: DynamicWaveOpenBoundary,
    cell_length_m: float,
    courant_number: float,
) -> float | None:
    length = float(cell_length_m)
    courant = float(courant_number)
    if (
        not math.isfinite(length)
        or not math.isfinite(courant)
        or length <= 0.0
        or not 0.0 < courant <= 1.0
    ):
        raise ValueError("dynamic_wave_open_cfl_contract_invalid")
    left = _resolve_open_boundary(
        left_boundary,
        expected_side="left",
        interior_state=DynamicWaveCellState(
            state.area_m2[0], state.discharge_m3s[0]
        ),
        section=section,
    )
    right = _resolve_open_boundary(
        right_boundary,
        expected_side="right",
        interior_state=DynamicWaveCellState(
            state.area_m2[-1], state.discharge_m3s[-1]
        ),
        section=section,
    )
    states = (
        (left.state,)
        + tuple(
            DynamicWaveCellState(area, discharge)
            for area, discharge in zip(
                state.area_m2, state.discharge_m3s, strict=True
            )
        )
        + (right.state,)
    )
    maximum_speed = max(
        max(
            abs(value)
            for value in dynamic_wave_characteristic_speeds_mps(value, section)
        )
        for value in states
    )
    return None if maximum_speed == 0.0 else courant * length / maximum_speed


def advance_coupled_dynamic_wave_open(
    state: PrismaticDynamicWaveState,
    bed_elevation_m: tuple[float, ...],
    section: TrapezoidalChannelSection,
    *,
    left_boundary: DynamicWaveOpenBoundary,
    right_boundary: DynamicWaveOpenBoundary,
    manning_n: tuple[float, ...],
    lateral_inflow_m2s: tuple[float, ...],
    lateral_momentum_convention: str,
    cell_length_m: float,
    timestep_seconds: float,
    maximum_courant_number: float,
) -> CoupledDynamicWaveOpenStep:
    length = float(cell_length_m)
    timestep = float(timestep_seconds)
    if (
        not math.isfinite(length)
        or not math.isfinite(timestep)
        or length <= 0.0
        or timestep <= 0.0
    ):
        raise ValueError("dynamic_wave_coupled_step_contract_invalid")
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
    friction_first = apply_manning_friction_only_source(
        lateral_first.state,
        section,
        manning_n=manning_n,
        timestep_seconds=half_timestep,
        cell_length_m=length,
    )
    momentum_after_friction_first = _momentum_integral(
        friction_first.state, length
    )
    resolved_left = _resolve_open_boundary(
        left_boundary,
        expected_side="left",
        interior_state=DynamicWaveCellState(
            friction_first.state.area_m2[0],
            friction_first.state.discharge_m3s[0],
        ),
        section=section,
    )
    resolved_right = _resolve_open_boundary(
        right_boundary,
        expected_side="right",
        interior_state=DynamicWaveCellState(
            friction_first.state.area_m2[-1],
            friction_first.state.discharge_m3s[-1],
        ),
        section=section,
    )
    hydrostatic = advance_hydrostatic_reconstruction_open(
        friction_first.state,
        bed_elevation_m,
        section,
        left_boundary_state=resolved_left.state,
        right_boundary_state=resolved_right.state,
        left_boundary_bed_elevation_m=resolved_left.bed_elevation_m,
        right_boundary_bed_elevation_m=resolved_right.bed_elevation_m,
        cell_length_m=length,
        timestep_seconds=timestep,
        maximum_courant_number=maximum_courant_number,
    )
    momentum_after_hydrostatic = _momentum_integral(
        hydrostatic.state, length
    )
    friction_second = apply_manning_friction_only_source(
        hydrostatic.state,
        section,
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
    after_momentum = _momentum_integral(final_state, length)
    after_volume = _volume(final_state, length)

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
    hydrostatic_momentum = (
        momentum_after_hydrostatic - momentum_after_friction_first
    )
    ledger_error = (
        after_momentum
        - before_momentum
        - lateral_momentum
        - friction_momentum
        - hydrostatic_momentum
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
    return CoupledDynamicWaveOpenStep(
        state=final_state,
        timestep_seconds=timestep,
        cell_length_m=length,
        maximum_courant_number=hydrostatic.maximum_courant_number,
        momentum_convention=lateral_momentum_convention,
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
        boundary_and_bed_momentum_change_m4s=hydrostatic_momentum,
        discharge_integral_after_m4s=after_momentum,
        momentum_ledger_error_m4s=ledger_error,
        minimum_area_m2=min(final_state.area_m2),
        boundary_semantics=boundary_semantics,
        left_characteristic_boundary=resolved_left.characteristic,
        right_characteristic_boundary=resolved_right.characteristic,
        hydrostatic_step=hydrostatic,
    )


def _resolve_open_boundary(
    boundary: DynamicWaveOpenBoundary,
    *,
    expected_side: str,
    interior_state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
) -> _ResolvedOpenBoundary:
    if isinstance(boundary, FixedDynamicWaveBoundary):
        return _ResolvedOpenBoundary(
            state=boundary.state,
            bed_elevation_m=boundary.bed_elevation_m,
            characteristic=None,
        )
    if boundary.side != expected_side:
        raise ValueError("dynamic_wave_characteristic_boundary_side_mismatch")
    resolved = resolve_characteristic_dynamic_wave_boundary(
        boundary, interior_state, section
    )
    return _ResolvedOpenBoundary(
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
