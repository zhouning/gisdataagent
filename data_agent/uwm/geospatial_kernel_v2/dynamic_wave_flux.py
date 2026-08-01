"""Prismatic homogeneous dynamic-wave flux for Geospatial Kernel candidates."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


DYNAMIC_WAVE_HLL_FLUX_SCHEMA = "gwm.geospatial_kernel.dynamic_wave_hll_flux.v1"
DYNAMIC_WAVE_HOMOGENEOUS_STEP_SCHEMA = (
    "gwm.geospatial_kernel.dynamic_wave_homogeneous_step.v1"
)
STANDARD_GRAVITY_MPS2 = 9.80665


@dataclass(frozen=True)
class TrapezoidalChannelSection:
    bottom_width_m: float
    side_slope_horizontal_per_vertical: float

    def __post_init__(self) -> None:
        width = float(self.bottom_width_m)
        side = float(self.side_slope_horizontal_per_vertical)
        if (
            not math.isfinite(width)
            or not math.isfinite(side)
            or width <= 0.0
            or side < 0.0
        ):
            raise ValueError("dynamic_wave_section_geometry_invalid")
        object.__setattr__(self, "bottom_width_m", width)
        object.__setattr__(self, "side_slope_horizontal_per_vertical", side)

    def depth_m(self, area_m2: float) -> float:
        area = _nonnegative_area(area_m2)
        if self.side_slope_horizontal_per_vertical == 0.0:
            return area / self.bottom_width_m
        top_width = self.top_width_m(area)
        return 2.0 * area / (self.bottom_width_m + top_width)

    def area_m2(self, depth_m: float) -> float:
        depth = float(depth_m)
        if not math.isfinite(depth) or depth < 0.0:
            raise ValueError("dynamic_wave_depth_invalid")
        return depth * (
            self.bottom_width_m
            + self.side_slope_horizontal_per_vertical * depth
        )

    def top_width_m(self, area_m2: float) -> float:
        area = _nonnegative_area(area_m2)
        return math.sqrt(
            self.bottom_width_m**2
            + 4.0 * self.side_slope_horizontal_per_vertical * area
        )

    def hydrostatic_pressure_integral_m3(self, area_m2: float) -> float:
        depth = self.depth_m(area_m2)
        return (
            0.5 * self.bottom_width_m * depth**2
            + (self.side_slope_horizontal_per_vertical * depth**3) / 3.0
        )

    def gravity_wave_celerity_mps(self, area_m2: float) -> float:
        area = _nonnegative_area(area_m2)
        if area == 0.0:
            return 0.0
        return math.sqrt(STANDARD_GRAVITY_MPS2 * area / self.top_width_m(area))


@dataclass(frozen=True)
class DynamicWaveCellState:
    area_m2: float
    discharge_m3s: float

    def __post_init__(self) -> None:
        area = _nonnegative_area(self.area_m2)
        discharge = float(self.discharge_m3s)
        if not math.isfinite(discharge) or (area == 0.0 and discharge != 0.0):
            raise ValueError("dynamic_wave_cell_state_invalid")
        object.__setattr__(self, "area_m2", area)
        object.__setattr__(self, "discharge_m3s", discharge)

    @property
    def mean_velocity_mps(self) -> float:
        return 0.0 if self.area_m2 == 0.0 else self.discharge_m3s / self.area_m2


@dataclass(frozen=True)
class DynamicWaveFlux:
    area_flux_m3s: float
    momentum_flux_m4s2: float

    def as_array(self) -> np.ndarray:
        return np.asarray([self.area_flux_m3s, self.momentum_flux_m4s2], dtype=float)


@dataclass(frozen=True)
class DynamicWaveHLLFluxResult:
    flux: DynamicWaveFlux
    minimum_signal_speed_mps: float
    maximum_signal_speed_mps: float
    wave_regime: str
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": DYNAMIC_WAVE_HLL_FLUX_SCHEMA,
            "area_flux_m3s": self.flux.area_flux_m3s,
            "momentum_flux_m4s2": self.flux.momentum_flux_m4s2,
            "minimum_signal_speed_mps": self.minimum_signal_speed_mps,
            "maximum_signal_speed_mps": self.maximum_signal_speed_mps,
            "wave_regime": self.wave_regime,
            "convective_momentum_retained": True,
            "hydrostatic_pressure_retained": True,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class PrismaticDynamicWaveState:
    area_m2: tuple[float, ...]
    discharge_m3s: tuple[float, ...]

    def __post_init__(self) -> None:
        area = np.asarray(self.area_m2, dtype=float)
        discharge = np.asarray(self.discharge_m3s, dtype=float)
        if (
            area.ndim != 1
            or area.size < 2
            or discharge.shape != area.shape
            or not np.isfinite(area).all()
            or not np.isfinite(discharge).all()
            or (area < 0.0).any()
            or ((area == 0.0) & (discharge != 0.0)).any()
        ):
            raise ValueError("prismatic_dynamic_wave_state_invalid")
        object.__setattr__(self, "area_m2", tuple(float(value) for value in area))
        object.__setattr__(
            self, "discharge_m3s", tuple(float(value) for value in discharge)
        )

    @property
    def cell_count(self) -> int:
        return len(self.area_m2)


@dataclass(frozen=True)
class DynamicWaveHomogeneousStep:
    state: PrismaticDynamicWaveState
    timestep_seconds: float
    cell_length_m: float
    maximum_courant_number: float
    volume_before_m3: float
    volume_after_m3: float
    volume_balance_error_m3: float
    discharge_integral_before_m4s: float
    discharge_integral_after_m4s: float
    discharge_integral_balance_error_m4s: float
    minimum_area_m2: float
    finite_state: bool
    nonnegative_area: bool
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": DYNAMIC_WAVE_HOMOGENEOUS_STEP_SCHEMA,
            "timestep_seconds": self.timestep_seconds,
            "cell_length_m": self.cell_length_m,
            "maximum_courant_number": self.maximum_courant_number,
            "volume_before_m3": self.volume_before_m3,
            "volume_after_m3": self.volume_after_m3,
            "volume_balance_error_m3": self.volume_balance_error_m3,
            "discharge_integral_before_m4s": self.discharge_integral_before_m4s,
            "discharge_integral_after_m4s": self.discharge_integral_after_m4s,
            "discharge_integral_balance_error_m4s": (
                self.discharge_integral_balance_error_m4s
            ),
            "minimum_area_m2": self.minimum_area_m2,
            "finite_state": self.finite_state,
            "nonnegative_area": self.nonnegative_area,
            "periodic_homogeneous_volume_conserved": (
                abs(self.volume_balance_error_m3) <= 1e-10
            ),
            "periodic_homogeneous_momentum_conserved": (
                abs(self.discharge_integral_balance_error_m4s) <= 1e-10
            ),
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


def dynamic_wave_characteristic_speeds_mps(
    state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
) -> tuple[float, float]:
    velocity = state.mean_velocity_mps
    celerity = section.gravity_wave_celerity_mps(state.area_m2)
    return velocity - celerity, velocity + celerity


def dynamic_wave_physical_flux(
    state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
) -> DynamicWaveFlux:
    if state.area_m2 == 0.0:
        return DynamicWaveFlux(0.0, 0.0)
    pressure = (
        STANDARD_GRAVITY_MPS2
        * section.hydrostatic_pressure_integral_m3(state.area_m2)
    )
    return DynamicWaveFlux(
        area_flux_m3s=state.discharge_m3s,
        momentum_flux_m4s2=(
            state.discharge_m3s**2 / state.area_m2 + pressure
        ),
    )


def local_inertial_physical_flux(
    state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
) -> DynamicWaveFlux:
    pressure = (
        STANDARD_GRAVITY_MPS2
        * section.hydrostatic_pressure_integral_m3(state.area_m2)
    )
    return DynamicWaveFlux(state.discharge_m3s, pressure)


def hll_dynamic_wave_flux(
    left: DynamicWaveCellState,
    right: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
) -> DynamicWaveHLLFluxResult:
    left_speeds = dynamic_wave_characteristic_speeds_mps(left, section)
    right_speeds = dynamic_wave_characteristic_speeds_mps(right, section)
    minimum_speed = min(left_speeds[0], right_speeds[0])
    maximum_speed = max(left_speeds[1], right_speeds[1])
    left_flux = dynamic_wave_physical_flux(left, section)
    right_flux = dynamic_wave_physical_flux(right, section)
    if minimum_speed >= 0.0:
        flux = left_flux
        regime = "right_going_supercritical"
    elif maximum_speed <= 0.0:
        flux = right_flux
        regime = "left_going_supercritical"
    elif maximum_speed == minimum_speed:
        flux = DynamicWaveFlux(0.0, 0.0)
        regime = "stationary_dry"
    else:
        left_state = np.asarray([left.area_m2, left.discharge_m3s], dtype=float)
        right_state = np.asarray([right.area_m2, right.discharge_m3s], dtype=float)
        values = (
            maximum_speed * left_flux.as_array()
            - minimum_speed * right_flux.as_array()
            + minimum_speed * maximum_speed * (right_state - left_state)
        ) / (maximum_speed - minimum_speed)
        flux = DynamicWaveFlux(float(values[0]), float(values[1]))
        regime = "subcritical_or_transcritical"
    return DynamicWaveHLLFluxResult(
        flux=flux,
        minimum_signal_speed_mps=float(minimum_speed),
        maximum_signal_speed_mps=float(maximum_speed),
        wave_regime=regime,
    )


def maximum_stable_timestep_seconds(
    state: PrismaticDynamicWaveState,
    section: TrapezoidalChannelSection,
    *,
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
        raise ValueError("dynamic_wave_cfl_contract_invalid")
    maximum_speed = _maximum_state_signal_speed(state, section)
    return None if maximum_speed == 0.0 else courant * length / maximum_speed


def advance_prismatic_dynamic_wave_periodic(
    state: PrismaticDynamicWaveState,
    section: TrapezoidalChannelSection,
    *,
    cell_length_m: float,
    timestep_seconds: float,
    maximum_courant_number: float,
    negative_area_tolerance_m2: float = 1e-12,
) -> DynamicWaveHomogeneousStep:
    length = float(cell_length_m)
    timestep = float(timestep_seconds)
    limit = float(maximum_courant_number)
    negative_tolerance = float(negative_area_tolerance_m2)
    if (
        not all(math.isfinite(value) for value in (length, timestep, limit, negative_tolerance))
        or length <= 0.0
        or timestep <= 0.0
        or not 0.0 < limit <= 1.0
        or negative_tolerance < 0.0
    ):
        raise ValueError("dynamic_wave_step_contract_invalid")
    maximum_signal = _maximum_state_signal_speed(state, section)
    courant = maximum_signal * timestep / length
    if courant > limit + 2.0 * np.finfo(float).eps:
        raise ValueError("dynamic_wave_step_cfl_exceeded")

    area = np.asarray(state.area_m2, dtype=float)
    discharge = np.asarray(state.discharge_m3s, dtype=float)
    fluxes = np.empty((state.cell_count, 2), dtype=float)
    for index in range(state.cell_count):
        right = (index + 1) % state.cell_count
        fluxes[index] = hll_dynamic_wave_flux(
            DynamicWaveCellState(area[index], discharge[index]),
            DynamicWaveCellState(area[right], discharge[right]),
            section,
        ).flux.as_array()
    updated = np.column_stack((area, discharge)) - (timestep / length) * (
        fluxes - np.roll(fluxes, 1, axis=0)
    )
    if not np.isfinite(updated).all():
        raise FloatingPointError("dynamic_wave_step_nonfinite_state")
    if (updated[:, 0] < -negative_tolerance).any():
        raise FloatingPointError("dynamic_wave_step_negative_area")
    tiny = (updated[:, 0] < 0.0) & (updated[:, 0] >= -negative_tolerance)
    updated[tiny, 0] = 0.0
    updated[tiny & (np.abs(updated[:, 1]) <= negative_tolerance), 1] = 0.0
    next_state = PrismaticDynamicWaveState(
        area_m2=tuple(float(value) for value in updated[:, 0]),
        discharge_m3s=tuple(float(value) for value in updated[:, 1]),
    )
    volume_before = float(area.sum() * length)
    volume_after = float(updated[:, 0].sum() * length)
    momentum_before = float(discharge.sum() * length)
    momentum_after = float(updated[:, 1].sum() * length)
    return DynamicWaveHomogeneousStep(
        state=next_state,
        timestep_seconds=timestep,
        cell_length_m=length,
        maximum_courant_number=float(courant),
        volume_before_m3=volume_before,
        volume_after_m3=volume_after,
        volume_balance_error_m3=volume_after - volume_before,
        discharge_integral_before_m4s=momentum_before,
        discharge_integral_after_m4s=momentum_after,
        discharge_integral_balance_error_m4s=momentum_after - momentum_before,
        minimum_area_m2=float(updated[:, 0].min()),
        finite_state=True,
        nonnegative_area=bool((updated[:, 0] >= 0.0).all()),
    )


def _maximum_state_signal_speed(
    state: PrismaticDynamicWaveState,
    section: TrapezoidalChannelSection,
) -> float:
    return float(
        max(
            max(abs(value) for value in dynamic_wave_characteristic_speeds_mps(
                DynamicWaveCellState(area, discharge), section
            ))
            for area, discharge in zip(
                state.area_m2, state.discharge_m3s, strict=True
            )
        )
    )


def _nonnegative_area(value: float) -> float:
    area = float(value)
    if not math.isfinite(area) or area < 0.0:
        raise ValueError("dynamic_wave_area_invalid")
    return area
