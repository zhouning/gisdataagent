"""Piecewise-linear irregular cross-section hydraulics for reference kernels."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .dynamic_wave_flux import STANDARD_GRAVITY_MPS2


IRREGULAR_SECTION_SCHEMA = "gwm.geospatial_kernel.irregular_section.v1"
CONVEYANCE_MOMENTUM_DISTRIBUTION_SCHEMA = (
    "gwm.geospatial_kernel.conveyance_momentum_distribution.v1"
)
_GEOMETRY_TOLERANCE_M = 1e-12


@dataclass(frozen=True)
class WetSectionProperties:
    water_surface_elevation_m: float
    area_m2: float
    top_width_m: float
    wetted_perimeter_m: float
    hydrostatic_pressure_integral_m3: float

    @property
    def hydraulic_radius_m(self) -> float:
        if self.wetted_perimeter_m <= 0.0:
            return 0.0
        return self.area_m2 / self.wetted_perimeter_m

    def as_dict(self) -> dict[str, float]:
        return {
            "water_surface_elevation_m": self.water_surface_elevation_m,
            "area_m2": self.area_m2,
            "top_width_m": self.top_width_m,
            "wetted_perimeter_m": self.wetted_perimeter_m,
            "hydraulic_radius_m": self.hydraulic_radius_m,
            "hydrostatic_pressure_integral_m3": (
                self.hydrostatic_pressure_integral_m3
            ),
        }


@dataclass(frozen=True)
class PiecewiseLinearChannelSection:
    """Open irregular section bounded by surveyed station/elevation points."""

    stations_m: tuple[float, ...]
    elevations_m: tuple[float, ...]

    def __post_init__(self) -> None:
        stations = tuple(float(value) for value in self.stations_m)
        elevations = tuple(float(value) for value in self.elevations_m)
        if (
            len(stations) < 2
            or len(stations) != len(elevations)
            or not all(math.isfinite(value) for value in (*stations, *elevations))
            or any(right < left for left, right in zip(stations, stations[1:]))
            or stations[-1] - stations[0] <= _GEOMETRY_TOLERANCE_M
            or min(elevations) >= min(elevations[0], elevations[-1])
        ):
            raise ValueError("irregular_section_geometry_invalid")
        object.__setattr__(self, "stations_m", stations)
        object.__setattr__(self, "elevations_m", elevations)

    @property
    def minimum_elevation_m(self) -> float:
        return min(self.elevations_m)

    @property
    def maximum_closed_water_surface_elevation_m(self) -> float:
        return min(self.elevations_m[0], self.elevations_m[-1])

    def wet_properties_at_elevation(
        self,
        water_surface_elevation_m: float,
        *,
        minimum_station_m: float | None = None,
        maximum_station_m: float | None = None,
    ) -> WetSectionProperties:
        elevation = float(water_surface_elevation_m)
        lower = self.stations_m[0] if minimum_station_m is None else float(
            minimum_station_m
        )
        upper = self.stations_m[-1] if maximum_station_m is None else float(
            maximum_station_m
        )
        if (
            not math.isfinite(elevation)
            or not math.isfinite(lower)
            or not math.isfinite(upper)
            or lower < self.stations_m[0] - _GEOMETRY_TOLERANCE_M
            or upper > self.stations_m[-1] + _GEOMETRY_TOLERANCE_M
            or upper <= lower
            or elevation
            > self.maximum_closed_water_surface_elevation_m
            + _GEOMETRY_TOLERANCE_M
        ):
            raise ValueError("irregular_section_wet_state_invalid")

        area = 0.0
        width = 0.0
        perimeter = 0.0
        pressure_integral = 0.0
        for x0, z0, x1, z1 in zip(
            self.stations_m[:-1],
            self.elevations_m[:-1],
            self.stations_m[1:],
            self.elevations_m[1:],
            strict=True,
        ):
            if x0 == x1:
                if lower <= x0 < upper or (
                    x0 == upper == self.stations_m[-1]
                ):
                    perimeter += _vertical_wet_length(z0, z1, elevation)
                continue
            clipped_lower = max(x0, lower)
            clipped_upper = min(x1, upper)
            if clipped_upper <= clipped_lower:
                continue
            clipped_z0 = _linear_elevation(x0, z0, x1, z1, clipped_lower)
            clipped_z1 = _linear_elevation(x0, z0, x1, z1, clipped_upper)
            values = _integrate_segment(
                clipped_lower,
                clipped_z0,
                clipped_upper,
                clipped_z1,
                elevation,
            )
            area += values[0]
            width += values[1]
            perimeter += values[2]
            pressure_integral += values[3]
        return WetSectionProperties(
            water_surface_elevation_m=elevation,
            area_m2=area,
            top_width_m=width,
            wetted_perimeter_m=perimeter,
            hydrostatic_pressure_integral_m3=pressure_integral,
        )

    def depth_m(self, area_m2: float) -> float:
        area = float(area_m2)
        if not math.isfinite(area) or area < 0.0:
            raise ValueError("irregular_section_area_invalid")
        if area == 0.0:
            return 0.0
        lower = self.minimum_elevation_m
        upper = self.maximum_closed_water_surface_elevation_m
        maximum = self.wet_properties_at_elevation(upper).area_m2
        if area > maximum + max(_GEOMETRY_TOLERANCE_M, maximum * 1e-12):
            raise ValueError("irregular_section_area_exceeds_closed_geometry")
        for _ in range(100):
            middle = 0.5 * (lower + upper)
            middle_area = self.wet_properties_at_elevation(middle).area_m2
            if middle_area < area:
                lower = middle
            else:
                upper = middle
        return 0.5 * (lower + upper) - self.minimum_elevation_m

    def area_m2(self, depth_m: float) -> float:
        depth = float(depth_m)
        if not math.isfinite(depth) or depth < 0.0:
            raise ValueError("irregular_section_depth_invalid")
        return self.wet_properties_at_elevation(
            self.minimum_elevation_m + depth
        ).area_m2

    def top_width_m(self, area_m2: float) -> float:
        elevation = self.minimum_elevation_m + self.depth_m(area_m2)
        return self.wet_properties_at_elevation(elevation).top_width_m

    def wetted_perimeter_m(self, area_m2: float) -> float:
        elevation = self.minimum_elevation_m + self.depth_m(area_m2)
        return self.wet_properties_at_elevation(elevation).wetted_perimeter_m

    def hydrostatic_pressure_integral_m3(self, area_m2: float) -> float:
        elevation = self.minimum_elevation_m + self.depth_m(area_m2)
        return self.wet_properties_at_elevation(
            elevation
        ).hydrostatic_pressure_integral_m3

    def gravity_wave_celerity_mps(self, area_m2: float) -> float:
        area = float(area_m2)
        if area == 0.0:
            return 0.0
        width = self.top_width_m(area)
        if width <= 0.0:
            raise ValueError("irregular_section_top_width_invalid")
        return math.sqrt(STANDARD_GRAVITY_MPS2 * area / width)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": IRREGULAR_SECTION_SCHEMA,
            "stations_m": list(self.stations_m),
            "elevations_m": list(self.elevations_m),
            "minimum_elevation_m": self.minimum_elevation_m,
            "maximum_closed_water_surface_elevation_m": (
                self.maximum_closed_water_surface_elevation_m
            ),
            "piecewise_linear_geometry": True,
            "artificial_vertical_subsection_walls_in_perimeter": False,
        }


@dataclass(frozen=True)
class ManningRoughnessZone:
    minimum_station_m: float
    manning_n: float

    def __post_init__(self) -> None:
        station = float(self.minimum_station_m)
        roughness = float(self.manning_n)
        if (
            not math.isfinite(station)
            or not math.isfinite(roughness)
            or roughness <= 0.0
        ):
            raise ValueError("irregular_section_roughness_zone_invalid")
        object.__setattr__(self, "minimum_station_m", station)
        object.__setattr__(self, "manning_n", roughness)


@dataclass(frozen=True)
class ConveyanceSubsection:
    minimum_station_m: float
    maximum_station_m: float
    manning_n: float
    area_m2: float
    wetted_perimeter_m: float
    hydraulic_radius_m: float
    conveyance_m3s: float
    discharge_m3s: float

    def as_dict(self) -> dict[str, float]:
        return {
            "minimum_station_m": self.minimum_station_m,
            "maximum_station_m": self.maximum_station_m,
            "manning_n": self.manning_n,
            "area_m2": self.area_m2,
            "wetted_perimeter_m": self.wetted_perimeter_m,
            "hydraulic_radius_m": self.hydraulic_radius_m,
            "conveyance_m3s": self.conveyance_m3s,
            "discharge_m3s": self.discharge_m3s,
        }


@dataclass(frozen=True)
class ConveyanceMomentumDistribution:
    water_surface_elevation_m: float
    total_area_m2: float
    total_discharge_m3s: float
    total_conveyance_m3s: float
    momentum_coefficient_beta: float
    subsections: tuple[ConveyanceSubsection, ...]

    @property
    def friction_slope(self) -> float:
        return (self.total_discharge_m3s / self.total_conveyance_m3s) ** 2

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONVEYANCE_MOMENTUM_DISTRIBUTION_SCHEMA,
            "water_surface_elevation_m": self.water_surface_elevation_m,
            "total_area_m2": self.total_area_m2,
            "total_discharge_m3s": self.total_discharge_m3s,
            "total_conveyance_m3s": self.total_conveyance_m3s,
            "momentum_coefficient_beta": self.momentum_coefficient_beta,
            "friction_slope": self.friction_slope,
            "subsections": [value.as_dict() for value in self.subsections],
            "discharge_partition": "Manning_conveyance_fraction",
            "beta_equation": "A/Q^2*sum(Q_i^2/A_i)",
        }


def conveyance_momentum_distribution(
    section: PiecewiseLinearChannelSection,
    roughness_zones: tuple[ManningRoughnessZone, ...],
    *,
    water_surface_elevation_m: float,
    discharge_m3s: float,
) -> ConveyanceMomentumDistribution:
    discharge = float(discharge_m3s)
    zones = tuple(roughness_zones)
    if (
        not isinstance(section, PiecewiseLinearChannelSection)
        or not math.isfinite(discharge)
        or discharge <= 0.0
        or not zones
        or any(not isinstance(value, ManningRoughnessZone) for value in zones)
        or any(
            right.minimum_station_m <= left.minimum_station_m
            for left, right in zip(zones, zones[1:])
        )
        or abs(zones[0].minimum_station_m - section.stations_m[0])
        > _GEOMETRY_TOLERANCE_M
        or zones[-1].minimum_station_m >= section.stations_m[-1]
    ):
        raise ValueError("conveyance_momentum_distribution_contract_invalid")
    properties = section.wet_properties_at_elevation(water_surface_elevation_m)
    provisional: list[
        tuple[
            float,
            float,
            ManningRoughnessZone,
            WetSectionProperties,
            float,
        ]
    ] = []
    for index, zone in enumerate(zones):
        upper = (
            zones[index + 1].minimum_station_m
            if index + 1 < len(zones)
            else section.stations_m[-1]
        )
        wet = section.wet_properties_at_elevation(
            water_surface_elevation_m,
            minimum_station_m=zone.minimum_station_m,
            maximum_station_m=upper,
        )
        radius = wet.hydraulic_radius_m
        conveyance = (
            0.0
            if wet.area_m2 == 0.0 or radius == 0.0
            else wet.area_m2 * radius ** (2.0 / 3.0) / zone.manning_n
        )
        provisional.append((zone.minimum_station_m, upper, zone, wet, conveyance))
    total_conveyance = sum(value[4] for value in provisional)
    if properties.area_m2 <= 0.0 or total_conveyance <= 0.0:
        raise ValueError("conveyance_momentum_distribution_dry")
    subsections = tuple(
        ConveyanceSubsection(
            minimum_station_m=lower,
            maximum_station_m=upper,
            manning_n=zone.manning_n,
            area_m2=wet.area_m2,
            wetted_perimeter_m=wet.wetted_perimeter_m,
            hydraulic_radius_m=wet.hydraulic_radius_m,
            conveyance_m3s=conveyance,
            discharge_m3s=discharge * conveyance / total_conveyance,
        )
        for lower, upper, zone, wet, conveyance in provisional
    )
    beta = properties.area_m2 / discharge**2 * sum(
        value.discharge_m3s**2 / value.area_m2
        for value in subsections
        if value.area_m2 > 0.0
    )
    if not math.isfinite(beta) or beta < 1.0 - 1e-12:
        raise ValueError("conveyance_momentum_distribution_beta_invalid")
    return ConveyanceMomentumDistribution(
        water_surface_elevation_m=float(water_surface_elevation_m),
        total_area_m2=properties.area_m2,
        total_discharge_m3s=discharge,
        total_conveyance_m3s=total_conveyance,
        momentum_coefficient_beta=max(1.0, beta),
        subsections=subsections,
    )


def _linear_elevation(
    x0: float, z0: float, x1: float, z1: float, x: float
) -> float:
    return z0 + (z1 - z0) * (x - x0) / (x1 - x0)


def _vertical_wet_length(z0: float, z1: float, stage: float) -> float:
    lower = min(z0, z1)
    upper = min(max(z0, z1), stage)
    return max(0.0, upper - lower)


def _integrate_segment(
    x0: float, z0: float, x1: float, z1: float, stage: float
) -> tuple[float, float, float, float]:
    h0 = stage - z0
    h1 = stage - z1
    if h0 <= 0.0 and h1 <= 0.0:
        return 0.0, 0.0, 0.0, 0.0
    if h0 < 0.0 or h1 < 0.0:
        fraction = h0 / (h0 - h1)
        intersection = x0 + fraction * (x1 - x0)
        if h0 > 0.0:
            return _integrate_wet_linear_segment(x0, h0, intersection, 0.0)
        return _integrate_wet_linear_segment(intersection, 0.0, x1, h1)
    return _integrate_wet_linear_segment(x0, max(0.0, h0), x1, max(0.0, h1))


def _integrate_wet_linear_segment(
    x0: float, h0: float, x1: float, h1: float
) -> tuple[float, float, float, float]:
    horizontal = x1 - x0
    area = 0.5 * (h0 + h1) * horizontal
    width = horizontal
    perimeter = math.hypot(horizontal, h1 - h0)
    pressure_integral = horizontal * (h0**2 + h0 * h1 + h1**2) / 6.0
    return area, width, perimeter, pressure_integral
