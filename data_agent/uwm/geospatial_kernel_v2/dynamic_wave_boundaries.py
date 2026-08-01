"""Characteristic open-boundary contracts for prismatic dynamic waves."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    TrapezoidalChannelSection,
    dynamic_wave_characteristic_speeds_mps,
)


DYNAMIC_WAVE_CHARACTERISTIC_BOUNDARY_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_wave_characteristic_boundary.v1"
)
_BOUNDARY_SIDES = {"left", "right"}
_PRESCRIBED_QUANTITIES = {
    "area_m2",
    "discharge_m3s",
    "free_surface_elevation_m",
}
_QUADRATURE_NODES, _QUADRATURE_WEIGHTS = np.polynomial.legendre.leggauss(24)


@dataclass(frozen=True)
class CharacteristicDynamicWaveBoundary:
    side: str
    prescribed_quantity: str
    prescribed_value: float
    bed_elevation_m: float

    def __post_init__(self) -> None:
        value = float(self.prescribed_value)
        bed = float(self.bed_elevation_m)
        if (
            self.side not in _BOUNDARY_SIDES
            or self.prescribed_quantity not in _PRESCRIBED_QUANTITIES
            or not math.isfinite(value)
            or not math.isfinite(bed)
        ):
            raise ValueError("dynamic_wave_characteristic_boundary_invalid")
        if self.prescribed_quantity == "area_m2" and value <= 0.0:
            raise ValueError("dynamic_wave_characteristic_boundary_invalid")
        if (
            self.prescribed_quantity == "free_surface_elevation_m"
            and value <= bed
        ):
            raise ValueError("dynamic_wave_characteristic_boundary_invalid")
        object.__setattr__(self, "prescribed_value", value)
        object.__setattr__(self, "bed_elevation_m", bed)


@dataclass(frozen=True)
class ResolvedCharacteristicDynamicWaveBoundary:
    state: DynamicWaveCellState
    bed_elevation_m: float
    side: str
    prescribed_quantity: str
    prescribed_value: float
    outgoing_characteristic: str
    incoming_characteristic: str
    interior_outgoing_invariant_mps: float
    boundary_outgoing_invariant_mps: float
    outgoing_invariant_residual_mps: float
    interior_characteristic_speeds_mps: tuple[float, float]
    boundary_characteristic_speeds_mps: tuple[float, float]
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": DYNAMIC_WAVE_CHARACTERISTIC_BOUNDARY_SCHEMA,
            "side": self.side,
            "prescribed_quantity": self.prescribed_quantity,
            "prescribed_value": self.prescribed_value,
            "state": {
                "area_m2": self.state.area_m2,
                "discharge_m3s": self.state.discharge_m3s,
            },
            "bed_elevation_m": self.bed_elevation_m,
            "outgoing_characteristic": self.outgoing_characteristic,
            "incoming_characteristic": self.incoming_characteristic,
            "interior_outgoing_invariant_mps": (
                self.interior_outgoing_invariant_mps
            ),
            "boundary_outgoing_invariant_mps": (
                self.boundary_outgoing_invariant_mps
            ),
            "outgoing_invariant_residual_mps": (
                self.outgoing_invariant_residual_mps
            ),
            "interior_characteristic_speeds_mps": list(
                self.interior_characteristic_speeds_mps
            ),
            "boundary_characteristic_speeds_mps": list(
                self.boundary_characteristic_speeds_mps
            ),
            "incoming_characteristic_count": 1,
            "outgoing_characteristic_count": 1,
            "subcritical_only": True,
            "quadrature": "dry_regularized_gauss_legendre_24",
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


def dynamic_wave_characteristic_potential_mps(
    area_m2: float,
    section: TrapezoidalChannelSection,
) -> float:
    """Return integral from zero to A of c(a)/a da for the section."""

    area = float(area_m2)
    if not math.isfinite(area) or area < 0.0:
        raise ValueError("dynamic_wave_characteristic_potential_area_invalid")
    if area == 0.0:
        return 0.0
    depth = section.depth_m(area)
    if section.side_slope_horizontal_per_vertical == 0.0:
        return 2.0 * math.sqrt(STANDARD_GRAVITY_MPS2 * depth)

    upper = math.sqrt(depth)
    sample = 0.5 * upper * (_QUADRATURE_NODES + 1.0)
    width = section.bottom_width_m
    side = section.side_slope_horizontal_per_vertical
    transformed_integrand = 2.0 * math.sqrt(STANDARD_GRAVITY_MPS2) * np.sqrt(
        (width + 2.0 * side * sample**2)
        / (width + side * sample**2)
    )
    return float(
        0.5 * upper * np.dot(_QUADRATURE_WEIGHTS, transformed_integrand)
    )


def resolve_characteristic_dynamic_wave_boundary(
    boundary: CharacteristicDynamicWaveBoundary,
    interior_state: DynamicWaveCellState,
    interior_section: TrapezoidalChannelSection,
    *,
    boundary_section: TrapezoidalChannelSection | None = None,
) -> ResolvedCharacteristicDynamicWaveBoundary:
    resolved_section = (
        interior_section if boundary_section is None else boundary_section
    )
    if interior_state.area_m2 == 0.0:
        raise ValueError("dynamic_wave_characteristic_boundary_dry_interior")
    interior_speeds = dynamic_wave_characteristic_speeds_mps(
        interior_state, interior_section
    )
    if not interior_speeds[0] < 0.0 < interior_speeds[1]:
        raise ValueError(
            "dynamic_wave_characteristic_boundary_interior_not_subcritical"
        )
    interior_invariant = _outgoing_invariant_mps(
        interior_state, interior_section, boundary.side
    )
    if boundary.prescribed_quantity == "area_m2":
        area = boundary.prescribed_value
        discharge = _discharge_from_area_and_invariant(
            area, interior_invariant, resolved_section, boundary.side
        )
    elif boundary.prescribed_quantity == "free_surface_elevation_m":
        depth = boundary.prescribed_value - boundary.bed_elevation_m
        area = resolved_section.area_m2(depth)
        discharge = _discharge_from_area_and_invariant(
            area, interior_invariant, resolved_section, boundary.side
        )
    else:
        discharge = boundary.prescribed_value
        area = _subcritical_area_for_discharge(
            discharge,
            interior_invariant,
            resolved_section.area_m2(
                interior_section.depth_m(interior_state.area_m2)
            ),
            resolved_section,
            boundary.side,
        )
    resolved_state = DynamicWaveCellState(area, discharge)
    boundary_speeds = dynamic_wave_characteristic_speeds_mps(
        resolved_state, resolved_section
    )
    if not boundary_speeds[0] < 0.0 < boundary_speeds[1]:
        raise ValueError(
            "dynamic_wave_characteristic_boundary_solution_not_subcritical"
        )
    boundary_invariant = _outgoing_invariant_mps(
        resolved_state, resolved_section, boundary.side
    )
    return ResolvedCharacteristicDynamicWaveBoundary(
        state=resolved_state,
        bed_elevation_m=boundary.bed_elevation_m,
        side=boundary.side,
        prescribed_quantity=boundary.prescribed_quantity,
        prescribed_value=boundary.prescribed_value,
        outgoing_characteristic=(
            "u_minus_c" if boundary.side == "left" else "u_plus_c"
        ),
        incoming_characteristic=(
            "u_plus_c" if boundary.side == "left" else "u_minus_c"
        ),
        interior_outgoing_invariant_mps=interior_invariant,
        boundary_outgoing_invariant_mps=boundary_invariant,
        outgoing_invariant_residual_mps=(
            boundary_invariant - interior_invariant
        ),
        interior_characteristic_speeds_mps=interior_speeds,
        boundary_characteristic_speeds_mps=boundary_speeds,
    )


def _outgoing_invariant_mps(
    state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
    side: str,
) -> float:
    potential = dynamic_wave_characteristic_potential_mps(
        state.area_m2, section
    )
    if side == "left":
        return state.mean_velocity_mps - potential
    return state.mean_velocity_mps + potential


def _discharge_from_area_and_invariant(
    area_m2: float,
    invariant_mps: float,
    section: TrapezoidalChannelSection,
    side: str,
) -> float:
    potential = dynamic_wave_characteristic_potential_mps(area_m2, section)
    velocity = (
        invariant_mps + potential
        if side == "left"
        else invariant_mps - potential
    )
    return area_m2 * velocity


def _subcritical_area_for_discharge(
    discharge_m3s: float,
    invariant_mps: float,
    interior_area_m2: float,
    section: TrapezoidalChannelSection,
    side: str,
) -> float:
    def residual(area: float) -> float:
        state = DynamicWaveCellState(area, discharge_m3s)
        return _outgoing_invariant_mps(state, section, side) - invariant_mps

    area = interior_area_m2
    for _ in range(30):
        value = residual(area)
        if abs(value) <= 1e-12:
            speeds = dynamic_wave_characteristic_speeds_mps(
                DynamicWaveCellState(area, discharge_m3s), section
            )
            if speeds[0] < 0.0 < speeds[1]:
                return area
            break
        celerity = section.gravity_wave_celerity_mps(area)
        potential_derivative = celerity / area
        derivative = -discharge_m3s / area**2 + (
            -potential_derivative if side == "left" else potential_derivative
        )
        if not math.isfinite(derivative) or abs(derivative) < 1e-14:
            break
        candidate = area - value / derivative
        if (
            not math.isfinite(candidate)
            or candidate <= 0.0
            or candidate / area < 0.1
            or candidate / area > 10.0
        ):
            break
        area = candidate

    logarithmic_offsets = np.linspace(-6.0, 6.0, 481)
    samples = interior_area_m2 * np.power(10.0, logarithmic_offsets)
    samples[240] = interior_area_m2
    values = [residual(float(area)) for area in samples]
    candidates: list[float] = []
    invariant_tolerance = 1e-12
    for index, value in enumerate(values):
        if abs(value) <= invariant_tolerance:
            candidates.append(float(samples[index]))
        if index == len(values) - 1 or value * values[index + 1] >= 0.0:
            continue
        lower = float(samples[index])
        upper = float(samples[index + 1])
        lower_value = value
        for _ in range(100):
            middle = 0.5 * (lower + upper)
            middle_value = residual(middle)
            if abs(middle_value) <= invariant_tolerance:
                lower = middle
                upper = middle
                break
            if lower_value * middle_value <= 0.0:
                upper = middle
            else:
                lower = middle
                lower_value = middle_value
        candidates.append(0.5 * (lower + upper))

    subcritical_candidates = []
    for area in candidates:
        state = DynamicWaveCellState(area, discharge_m3s)
        speeds = dynamic_wave_characteristic_speeds_mps(state, section)
        if speeds[0] < 0.0 < speeds[1]:
            subcritical_candidates.append(area)
    if not subcritical_candidates:
        raise ValueError(
            "dynamic_wave_characteristic_discharge_no_subcritical_root"
        )
    return min(
        subcritical_candidates,
        key=lambda value: abs(math.log(value / interior_area_m2)),
    )
