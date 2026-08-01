"""Strict HEC-RAS steady-junction reference parsing and conformance solving."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import zipfile

from .dynamic_wave_flux import STANDARD_GRAVITY_MPS2
from .irregular_section import (
    ConveyanceMomentumDistribution,
    ManningRoughnessZone,
    PiecewiseLinearChannelSection,
    conveyance_momentum_distribution,
)


HEC_RAS_GEOMETRY_SCHEMA = "gwm.geospatial_kernel.hec_ras_geometry.v1"
HEC_RAS_STEADY_FLOW_SCHEMA = "gwm.geospatial_kernel.hec_ras_steady_flow.v1"
HEC_RAS_PLAN_SCHEMA = "gwm.geospatial_kernel.hec_ras_plan.v1"
HEC_RAS_PROJECTED_MOMENTUM_REFERENCE_SCHEMA = (
    "gwm.geospatial_kernel.hec_ras_projected_momentum_reference.v1"
)
FEET_TO_METRES = 0.3048
CFS_TO_CUBIC_METRES_PER_SECOND = 0.028316846592
_ROOT_SCAN_INTERVALS = 4096
_FLOW_TOLERANCE_M3S = 1e-9


ReachKey = tuple[str, str]


@dataclass(frozen=True)
class HecRasCrossSection:
    river_name: str
    reach_name: str
    river_station: str
    downstream_reach_lengths_m: tuple[float, float, float]
    section: PiecewiseLinearChannelSection
    roughness_zones: tuple[ManningRoughnessZone, ...]
    bank_stations_m: tuple[float, float]

    def __post_init__(self) -> None:
        lengths = tuple(float(value) for value in self.downstream_reach_lengths_m)
        banks = tuple(float(value) for value in self.bank_stations_m)
        zones = tuple(self.roughness_zones)
        if (
            not self.river_name
            or not self.reach_name
            or not self.river_station
            or not isinstance(self.section, PiecewiseLinearChannelSection)
            or len(lengths) != 3
            or any(not math.isfinite(value) or value < 0.0 for value in lengths)
            or not zones
            or any(not isinstance(value, ManningRoughnessZone) for value in zones)
            or len(banks) != 2
            or any(not math.isfinite(value) for value in banks)
            or not self.section.stations_m[0] <= banks[0] < banks[1]
            <= self.section.stations_m[-1]
        ):
            raise ValueError("hec_ras_cross_section_contract_invalid")
        object.__setattr__(self, "downstream_reach_lengths_m", lengths)
        object.__setattr__(self, "roughness_zones", zones)
        object.__setattr__(self, "bank_stations_m", (banks[0], banks[1]))

    @property
    def reach_key(self) -> ReachKey:
        return self.river_name, self.reach_name

    @property
    def invert_elevation_m(self) -> float:
        return self.section.minimum_elevation_m

    def distribution(
        self, water_surface_elevation_m: float, discharge_m3s: float
    ) -> ConveyanceMomentumDistribution:
        return conveyance_momentum_distribution(
            self.section,
            self.roughness_zones,
            water_surface_elevation_m=water_surface_elevation_m,
            discharge_m3s=discharge_m3s,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "river_name": self.river_name,
            "reach_name": self.reach_name,
            "river_station": self.river_station,
            "downstream_reach_lengths_m": list(
                self.downstream_reach_lengths_m
            ),
            "section": self.section.as_dict(),
            "roughness_zones": [
                {
                    "minimum_station_m": value.minimum_station_m,
                    "manning_n": value.manning_n,
                }
                for value in self.roughness_zones
            ],
            "bank_stations_m": list(self.bank_stations_m),
        }


@dataclass(frozen=True)
class HecRasJunction:
    name: str
    upstream_reaches: tuple[ReachKey, ...]
    downstream_reach: ReachKey
    reach_lengths_m: tuple[float, ...]
    deflection_degrees: tuple[float, ...]
    raw_description_flags: tuple[int, int, int]

    def __post_init__(self) -> None:
        count = len(self.upstream_reaches)
        if (
            not self.name
            or count < 2
            or len(set(self.upstream_reaches)) != count
            or self.downstream_reach in self.upstream_reaches
            or len(self.reach_lengths_m) != count
            or len(self.deflection_degrees) != count
            or any(
                not math.isfinite(value) or value <= 0.0
                for value in self.reach_lengths_m
            )
            or any(
                not math.isfinite(value) or not 0.0 <= value <= 90.0
                for value in self.deflection_degrees
            )
            or len(self.raw_description_flags) != 3
            or any(not isinstance(value, int) for value in self.raw_description_flags)
        ):
            raise ValueError("hec_ras_junction_contract_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "upstream_reaches": [list(value) for value in self.upstream_reaches],
            "downstream_reach": list(self.downstream_reach),
            "reach_lengths_m": list(self.reach_lengths_m),
            "deflection_degrees": list(self.deflection_degrees),
            "raw_description_flags": list(self.raw_description_flags),
        }


@dataclass(frozen=True)
class HecRasGeometry:
    title: str
    junction: HecRasJunction
    cross_sections: tuple[HecRasCrossSection, ...]

    def sections_for_reach(self, reach_key: ReachKey) -> tuple[HecRasCrossSection, ...]:
        values = tuple(
            value for value in self.cross_sections if value.reach_key == reach_key
        )
        if not values:
            raise ValueError("hec_ras_geometry_reach_missing")
        return values

    def junction_terminal_sections(
        self,
    ) -> tuple[tuple[HecRasCrossSection, ...], HecRasCrossSection]:
        upstream = tuple(
            self.sections_for_reach(value)[-1]
            for value in self.junction.upstream_reaches
        )
        downstream = self.sections_for_reach(self.junction.downstream_reach)[0]
        return upstream, downstream

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HEC_RAS_GEOMETRY_SCHEMA,
            "title": self.title,
            "junction": self.junction.as_dict(),
            "cross_section_count": len(self.cross_sections),
            "cross_sections": [value.as_dict() for value in self.cross_sections],
            "source_units": "US_customary",
            "kernel_units": "SI",
        }


@dataclass(frozen=True)
class HecRasSteadyFlow:
    title: str
    profile_name: str
    discharges_m3s: tuple[tuple[ReachKey, float], ...]
    downstream_normal_depth_slope: float

    def __post_init__(self) -> None:
        discharges = tuple(
            (key, float(value)) for key, value in self.discharges_m3s
        )
        slope = float(self.downstream_normal_depth_slope)
        if (
            not self.title
            or not self.profile_name
            or len(discharges) < 3
            or len(dict(discharges)) != len(discharges)
            or any(
                len(key) != 2
                or any(not part for part in key)
                or not math.isfinite(value)
                or value <= 0.0
                for key, value in discharges
            )
            or not math.isfinite(slope)
            or slope <= 0.0
        ):
            raise ValueError("hec_ras_steady_flow_contract_invalid")
        object.__setattr__(self, "discharges_m3s", discharges)
        object.__setattr__(self, "downstream_normal_depth_slope", slope)

    def discharge_for_reach(self, reach_key: ReachKey) -> float:
        values = dict(self.discharges_m3s)
        if reach_key not in values:
            raise ValueError("hec_ras_steady_flow_reach_missing")
        return values[reach_key]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HEC_RAS_STEADY_FLOW_SCHEMA,
            "title": self.title,
            "profile_name": self.profile_name,
            "discharges_m3s": {
                f"{key[0]}::{key[1]}": value
                for key, value in self.discharges_m3s
            },
            "downstream_normal_depth_slope": self.downstream_normal_depth_slope,
            "source_units": "cfs",
            "kernel_units": "m3/s",
        }


@dataclass(frozen=True)
class HecRasPlan:
    title: str
    short_identifier: str
    geometry_file: str
    flow_file: str
    subcritical_flow: bool
    friction_slope_method: int

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HEC_RAS_PLAN_SCHEMA,
            "title": self.title,
            "short_identifier": self.short_identifier,
            "geometry_file": self.geometry_file,
            "flow_file": self.flow_file,
            "subcritical_flow": self.subcritical_flow,
            "friction_slope_method": self.friction_slope_method,
        }


@dataclass(frozen=True)
class HecRasExampleArchive:
    geometry_text: str
    flow_text: str
    plan_text: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class HecRasReferenceBranchBalance:
    reach_key: ReachKey
    river_station: str
    discharge_m3s: float
    froude_number: float
    deflection_degrees: float
    section_spacing_m: float
    bed_slope: float
    distribution: ConveyanceMomentumDistribution
    specific_force_m3: float
    projected_specific_force_m3: float
    representative_friction_slope: float
    friction_force_m3: float
    water_weight_force_m3: float
    downstream_area_fraction: float
    contribution_m3: float

    def as_dict(self) -> dict[str, object]:
        return {
            "reach_key": list(self.reach_key),
            "river_station": self.river_station,
            "discharge_m3s": self.discharge_m3s,
            "froude_number": self.froude_number,
            "deflection_degrees": self.deflection_degrees,
            "section_spacing_m": self.section_spacing_m,
            "bed_slope": self.bed_slope,
            "distribution": self.distribution.as_dict(),
            "specific_force_m3": self.specific_force_m3,
            "projected_specific_force_m3": self.projected_specific_force_m3,
            "representative_friction_slope": (
                self.representative_friction_slope
            ),
            "friction_force_m3": self.friction_force_m3,
            "water_weight_force_m3": self.water_weight_force_m3,
            "downstream_area_fraction": self.downstream_area_fraction,
            "contribution_m3": self.contribution_m3,
        }


@dataclass(frozen=True)
class HecRasReferenceBalance:
    common_upstream_water_surface_elevation_m: float
    downstream_water_surface_elevation_m: float
    downstream_distribution: ConveyanceMomentumDistribution
    downstream_froude_number: float
    downstream_specific_force_m3: float
    branches: tuple[HecRasReferenceBranchBalance, ...]
    residual_m3: float

    def as_dict(self) -> dict[str, object]:
        return {
            "common_upstream_water_surface_elevation_m": (
                self.common_upstream_water_surface_elevation_m
            ),
            "downstream_water_surface_elevation_m": (
                self.downstream_water_surface_elevation_m
            ),
            "downstream_distribution": self.downstream_distribution.as_dict(),
            "downstream_froude_number": self.downstream_froude_number,
            "downstream_specific_force_m3": self.downstream_specific_force_m3,
            "branches": [value.as_dict() for value in self.branches],
            "upstream_contribution_sum_m3": sum(
                value.contribution_m3 for value in self.branches
            ),
            "residual_m3": self.residual_m3,
            "equation": (
                "SF_down=sum(SF_up*cos(theta)-F_friction+W_bed_slope)"
            ),
        }


@dataclass(frozen=True)
class HecRasProjectedMomentumReferenceSolution:
    geometry: HecRasGeometry
    flow: HecRasSteadyFlow
    plan: HecRasPlan
    upstream_sections: tuple[HecRasCrossSection, ...]
    downstream_section: HecRasCrossSection
    balance: HecRasReferenceBalance
    root_bracket_m: tuple[float, float]
    reference_upstream_water_surface_elevation_m: float | None = None

    @property
    def reference_stage_error_m(self) -> float | None:
        if self.reference_upstream_water_surface_elevation_m is None:
            return None
        return (
            self.balance.common_upstream_water_surface_elevation_m
            - self.reference_upstream_water_surface_elevation_m
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HEC_RAS_PROJECTED_MOMENTUM_REFERENCE_SCHEMA,
            "geometry_title": self.geometry.title,
            "flow_title": self.flow.title,
            "plan": self.plan.as_dict(),
            "junction": self.geometry.junction.as_dict(),
            "upstream_terminal_sections": [
                {
                    "reach_key": list(value.reach_key),
                    "river_station": value.river_station,
                }
                for value in self.upstream_sections
            ],
            "downstream_terminal_section": {
                "reach_key": list(self.downstream_section.reach_key),
                "river_station": self.downstream_section.river_station,
            },
            "balance": self.balance.as_dict(),
            "root_bracket_m": list(self.root_bracket_m),
            "reference_upstream_water_surface_elevation_m": (
                self.reference_upstream_water_surface_elevation_m
            ),
            "reference_stage_error_m": self.reference_stage_error_m,
            "friction_slope_method": "average_conveyance",
            "momentum_coefficient_source": "subsection_Manning_conveyance",
            "calibrated_to_reference_stage": False,
            "predictive_validation": False,
            "diagnostic_only": True,
            "operator_admitted": False,
        }


def load_hec_ras_example_archive(path: Path) -> HecRasExampleArchive:
    source = Path(path)
    if not source.is_file():
        raise ValueError("hec_ras_example_archive_missing")
    with zipfile.ZipFile(source) as archive:
        members = tuple(sorted(archive.namelist()))
        geometry_name = _unique_member(members, "JUNCTION.G02")
        flow_name = _unique_member(members, "JUNCTION.F01")
        plan_name = _unique_member(members, "JUNCTION.P02")
        geometry = archive.read(geometry_name).decode("ascii")
        flow = archive.read(flow_name).decode("ascii")
        plan = archive.read(plan_name).decode("ascii")
    return HecRasExampleArchive(geometry, flow, plan, members)


def parse_hec_ras_geometry(text: str) -> HecRasGeometry:
    lines = text.splitlines()
    title = _single_value(lines, "Geom Title=")
    junction_name = _single_value(lines, "Junct Name=")
    description = _single_value(lines, "Junct Desc=")
    description_parts = [value.strip() for value in description.split(",")]
    try:
        flags = tuple(int(value) for value in description_parts[-3:])
    except (TypeError, ValueError) as exc:
        raise ValueError("hec_ras_junction_description_flags_invalid") from exc
    if len(flags) != 3:
        raise ValueError("hec_ras_junction_description_flags_invalid")
    upstream_reaches = tuple(
        _reach_key(value)
        for value in _all_values_before_first_reach(lines, "Up River,Reach=")
    )
    downstream_values = _all_values_before_first_reach(lines, "Dn River,Reach=")
    if len(downstream_values) != 1:
        raise ValueError("hec_ras_junction_downstream_reach_invalid")
    downstream_reach = _reach_key(downstream_values[0])
    length_angle_values = _all_values_before_first_reach(lines, "Junc L&A=")
    lengths: list[float] = []
    angles: list[float] = []
    for value in length_angle_values:
        parts = [part.strip() for part in value.split(",")]
        if not parts or not parts[0]:
            raise ValueError("hec_ras_junction_length_angle_invalid")
        lengths.append(float(parts[0]) * FEET_TO_METRES)
        angles.append(0.0 if len(parts) < 2 or not parts[1] else float(parts[1]))
    junction = HecRasJunction(
        name=junction_name.strip(),
        upstream_reaches=upstream_reaches,
        downstream_reach=downstream_reach,
        reach_lengths_m=tuple(lengths),
        deflection_degrees=tuple(angles),
        raw_description_flags=(flags[0], flags[1], flags[2]),
    )

    cross_sections: list[HecRasCrossSection] = []
    current_reach: ReachKey | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("River Reach="):
            current_reach = _reach_key(line.split("=", 1)[1])
            index += 1
            continue
        if not line.startswith("Type RM Length L Ch R ="):
            index += 1
            continue
        if current_reach is None:
            raise ValueError("hec_ras_cross_section_reach_missing")
        end = index + 1
        while end < len(lines) and not (
            lines[end].startswith("Type RM Length L Ch R =")
            or lines[end].startswith("River Reach=")
        ):
            end += 1
        cross_sections.append(
            _parse_cross_section(lines[index:end], current_reach)
        )
        index = end
    if len(cross_sections) < 3:
        raise ValueError("hec_ras_geometry_cross_sections_missing")
    geometry = HecRasGeometry(title.strip(), junction, tuple(cross_sections))
    geometry.junction_terminal_sections()
    return geometry


def parse_hec_ras_steady_flow(text: str) -> HecRasSteadyFlow:
    lines = text.splitlines()
    title = _single_value(lines, "Flow Title=").strip()
    profile_count = int(_single_value(lines, "Number of Profiles=").strip())
    profile_name = _single_value(lines, "Profile Names=").strip()
    if profile_count != 1 or not profile_name:
        raise ValueError("hec_ras_steady_flow_profiles_not_supported")
    discharges: list[tuple[ReachKey, float]] = []
    for index, line in enumerate(lines):
        if not line.startswith("River Rch & RM="):
            continue
        parts = [value.strip() for value in line.split("=", 1)[1].split(",")]
        if len(parts) != 3 or index + 1 >= len(lines):
            raise ValueError("hec_ras_steady_flow_record_invalid")
        values = _numeric_tokens(lines[index + 1])
        if len(values) != 1 or values[0] <= 0.0:
            raise ValueError("hec_ras_steady_flow_discharge_invalid")
        discharges.append(
            ((parts[0], parts[1]), values[0] * CFS_TO_CUBIC_METRES_PER_SECOND)
        )
    if len(discharges) < 3 or len(dict(discharges)) != len(discharges):
        raise ValueError("hec_ras_steady_flow_reaches_invalid")
    slope = float(_single_value(lines, "Dn Slope=").strip())
    if not math.isfinite(slope) or slope <= 0.0:
        raise ValueError("hec_ras_steady_flow_boundary_invalid")
    return HecRasSteadyFlow(
        title=title,
        profile_name=profile_name,
        discharges_m3s=tuple(discharges),
        downstream_normal_depth_slope=slope,
    )


def parse_hec_ras_plan(text: str) -> HecRasPlan:
    lines = text.splitlines()
    friction_method = int(_single_value(lines, "Friction Slope Method=").strip())
    plan = HecRasPlan(
        title=_single_value(lines, "Plan Title=").strip(),
        short_identifier=_single_value(lines, "Short Identifier=").strip(),
        geometry_file=_single_value(lines, "Geom File=").strip().lower(),
        flow_file=_single_value(lines, "Flow File=").strip().lower(),
        subcritical_flow=any(line.strip() == "Subcritical Flow" for line in lines),
        friction_slope_method=friction_method,
    )
    if (
        not plan.title
        or not plan.short_identifier
        or not plan.geometry_file
        or not plan.flow_file
        or not plan.subcritical_flow
        or plan.friction_slope_method != 1
    ):
        raise ValueError("hec_ras_plan_not_supported")
    return plan


def evaluate_hec_ras_projected_momentum_reference(
    geometry: HecRasGeometry,
    flow: HecRasSteadyFlow,
    plan: HecRasPlan,
    *,
    common_upstream_water_surface_elevation_m: float,
    downstream_water_surface_elevation_m: float,
) -> HecRasReferenceBalance:
    _validate_reference_inputs(geometry, flow, plan)
    upstream_sections, downstream_section = geometry.junction_terminal_sections()
    upstream_discharges = tuple(
        flow.discharge_for_reach(value.reach_key) for value in upstream_sections
    )
    downstream_discharge = flow.discharge_for_reach(downstream_section.reach_key)
    if abs(sum(upstream_discharges) - downstream_discharge) > _FLOW_TOLERANCE_M3S:
        raise ValueError("hec_ras_reference_mass_balance_invalid")
    downstream_distribution = downstream_section.distribution(
        downstream_water_surface_elevation_m, downstream_discharge
    )
    downstream_froude = _froude_number(
        downstream_distribution, downstream_section
    )
    if downstream_froude >= 1.0:
        raise ValueError("hec_ras_reference_state_not_subcritical")
    downstream_force = _specific_force(
        downstream_distribution, downstream_section
    )
    branches: list[HecRasReferenceBranchBalance] = []
    for section, discharge, length, angle in zip(
        upstream_sections,
        upstream_discharges,
        geometry.junction.reach_lengths_m,
        geometry.junction.deflection_degrees,
        strict=True,
    ):
        distribution = section.distribution(
            common_upstream_water_surface_elevation_m, discharge
        )
        froude = _froude_number(distribution, section)
        if froude >= 1.0:
            raise ValueError("hec_ras_reference_state_not_subcritical")
        force = _specific_force(distribution, section)
        cosine = math.cos(math.radians(angle))
        fraction = discharge / downstream_discharge
        representative_sf = (
            (discharge + downstream_discharge)
            / (
                distribution.total_conveyance_m3s
                + downstream_distribution.total_conveyance_m3s
            )
        ) ** 2
        bed_slope = (
            section.invert_elevation_m - downstream_section.invert_elevation_m
        ) / length
        if bed_slope < -1e-12:
            raise ValueError("hec_ras_reference_adverse_junction_slope_not_supported")
        bed_slope = max(0.0, bed_slope)
        projected_area = (
            distribution.total_area_m2 * cosine
            + downstream_distribution.total_area_m2 * fraction
        )
        friction = representative_sf * 0.5 * length * projected_area
        weight = bed_slope * 0.5 * length * projected_area
        projected_force = force * cosine
        contribution = projected_force - friction + weight
        branches.append(
            HecRasReferenceBranchBalance(
                reach_key=section.reach_key,
                river_station=section.river_station,
                discharge_m3s=discharge,
                froude_number=froude,
                deflection_degrees=angle,
                section_spacing_m=length,
                bed_slope=bed_slope,
                distribution=distribution,
                specific_force_m3=force,
                projected_specific_force_m3=projected_force,
                representative_friction_slope=representative_sf,
                friction_force_m3=friction,
                water_weight_force_m3=weight,
                downstream_area_fraction=fraction,
                contribution_m3=contribution,
            )
        )
    residual = downstream_force - sum(value.contribution_m3 for value in branches)
    return HecRasReferenceBalance(
        common_upstream_water_surface_elevation_m=float(
            common_upstream_water_surface_elevation_m
        ),
        downstream_water_surface_elevation_m=float(
            downstream_water_surface_elevation_m
        ),
        downstream_distribution=downstream_distribution,
        downstream_froude_number=downstream_froude,
        downstream_specific_force_m3=downstream_force,
        branches=tuple(branches),
        residual_m3=residual,
    )


def solve_hec_ras_projected_momentum_reference(
    geometry: HecRasGeometry,
    flow: HecRasSteadyFlow,
    plan: HecRasPlan,
    *,
    downstream_water_surface_elevation_m: float,
    reference_upstream_water_surface_elevation_m: float | None = None,
    momentum_tolerance_m3: float = 1e-11,
) -> HecRasProjectedMomentumReferenceSolution:
    tolerance = float(momentum_tolerance_m3)
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("hec_ras_reference_solver_tolerance_invalid")
    _validate_reference_inputs(geometry, flow, plan)
    upstream_sections, downstream_section = geometry.junction_terminal_sections()
    lower = max(value.section.minimum_elevation_m for value in upstream_sections)
    upper = min(
        value.section.maximum_closed_water_surface_elevation_m
        for value in upstream_sections
    )
    span = upper - lower
    if span <= 0.0:
        raise ValueError("hec_ras_reference_root_domain_invalid")
    previous: tuple[float, HecRasReferenceBalance] | None = None
    bracket: tuple[float, float, HecRasReferenceBalance] | None = None
    for index in range(_ROOT_SCAN_INTERVALS + 1):
        elevation = lower + span * max(index, 1e-9) / _ROOT_SCAN_INTERVALS
        try:
            balance = evaluate_hec_ras_projected_momentum_reference(
                geometry,
                flow,
                plan,
                common_upstream_water_surface_elevation_m=elevation,
                downstream_water_surface_elevation_m=(
                    downstream_water_surface_elevation_m
                ),
            )
        except ValueError:
            previous = None
            continue
        if abs(balance.residual_m3) <= tolerance:
            return HecRasProjectedMomentumReferenceSolution(
                geometry,
                flow,
                plan,
                upstream_sections,
                downstream_section,
                balance,
                (elevation, elevation),
                reference_upstream_water_surface_elevation_m,
            )
        if previous is not None and previous[1].residual_m3 * balance.residual_m3 < 0.0:
            bracket = (previous[0], elevation, previous[1])
            break
        previous = elevation, balance
    if bracket is None:
        raise ValueError("hec_ras_reference_no_momentum_root")
    bracket_lower, bracket_upper, lower_balance = bracket
    original_bracket = bracket_lower, bracket_upper
    lower_residual = lower_balance.residual_m3
    balance = lower_balance
    for _ in range(120):
        elevation = 0.5 * (bracket_lower + bracket_upper)
        balance = evaluate_hec_ras_projected_momentum_reference(
            geometry,
            flow,
            plan,
            common_upstream_water_surface_elevation_m=elevation,
            downstream_water_surface_elevation_m=downstream_water_surface_elevation_m,
        )
        if abs(balance.residual_m3) <= tolerance:
            break
        if lower_residual * balance.residual_m3 <= 0.0:
            bracket_upper = elevation
        else:
            bracket_lower = elevation
            lower_residual = balance.residual_m3
    if abs(balance.residual_m3) > tolerance:
        raise ValueError("hec_ras_reference_root_tolerance_not_met")
    return HecRasProjectedMomentumReferenceSolution(
        geometry,
        flow,
        plan,
        upstream_sections,
        downstream_section,
        balance,
        original_bracket,
        reference_upstream_water_surface_elevation_m,
    )


def _specific_force(
    distribution: ConveyanceMomentumDistribution,
    section: HecRasCrossSection,
) -> float:
    wet = section.section.wet_properties_at_elevation(
        distribution.water_surface_elevation_m
    )
    return (
        distribution.momentum_coefficient_beta
        * distribution.total_discharge_m3s**2
        / (STANDARD_GRAVITY_MPS2 * distribution.total_area_m2)
        + wet.hydrostatic_pressure_integral_m3
    )


def _froude_number(
    distribution: ConveyanceMomentumDistribution,
    section: HecRasCrossSection,
) -> float:
    wet = section.section.wet_properties_at_elevation(
        distribution.water_surface_elevation_m
    )
    if wet.top_width_m <= 0.0:
        raise ValueError("hec_ras_reference_top_width_invalid")
    velocity = distribution.total_discharge_m3s / distribution.total_area_m2
    celerity = math.sqrt(
        STANDARD_GRAVITY_MPS2 * distribution.total_area_m2 / wet.top_width_m
    )
    return velocity / celerity


def _validate_reference_inputs(
    geometry: HecRasGeometry, flow: HecRasSteadyFlow, plan: HecRasPlan
) -> None:
    if (
        not isinstance(geometry, HecRasGeometry)
        or not isinstance(flow, HecRasSteadyFlow)
        or not isinstance(plan, HecRasPlan)
        or not plan.subcritical_flow
        or plan.friction_slope_method != 1
        or "momentum" not in plan.short_identifier.lower()
    ):
        raise ValueError("hec_ras_reference_contract_invalid")


def _parse_cross_section(
    lines: list[str], reach_key: ReachKey
) -> HecRasCrossSection:
    header = [value.strip() for value in lines[0].split("=", 1)[1].split(",")]
    if len(header) != 5 or int(header[0]) != 1:
        raise ValueError("hec_ras_cross_section_type_not_supported")
    river_station = header[1]
    reach_lengths = tuple(float(value) * FEET_TO_METRES for value in header[2:])
    if len(reach_lengths) != 3 or any(value < 0.0 for value in reach_lengths):
        raise ValueError("hec_ras_cross_section_reach_lengths_invalid")
    coordinates: tuple[float, ...] | None = None
    mannings: tuple[float, ...] | None = None
    banks: tuple[float, ...] | None = None
    for index, line in enumerate(lines):
        if line.startswith("#Sta/Elev="):
            count = int(line.split("=", 1)[1].strip())
            coordinates = _collect_numeric_values(lines, index + 1, count * 2)
        elif line.startswith("#Mann="):
            count = int(line.split("=", 1)[1].split(",", 1)[0].strip())
            mannings = _collect_numeric_values(lines, index + 1, count * 3)
        elif line.startswith("Bank Sta="):
            banks = tuple(
                float(value.strip())
                for value in line.split("=", 1)[1].split(",")
            )
    if coordinates is None or mannings is None or banks is None or len(banks) != 2:
        raise ValueError("hec_ras_cross_section_fields_missing")
    stations = tuple(coordinates[0::2])
    elevations = tuple(coordinates[1::2])
    roughness_zones = tuple(
        ManningRoughnessZone(mannings[index] * FEET_TO_METRES, mannings[index + 1])
        for index in range(0, len(mannings), 3)
    )
    if any(mannings[index + 2] != 0.0 for index in range(0, len(mannings), 3)):
        raise ValueError("hec_ras_cross_section_horizontal_variation_not_supported")
    return HecRasCrossSection(
        river_name=reach_key[0],
        reach_name=reach_key[1],
        river_station=river_station,
        downstream_reach_lengths_m=(
            reach_lengths[0], reach_lengths[1], reach_lengths[2]
        ),
        section=PiecewiseLinearChannelSection(
            tuple(value * FEET_TO_METRES for value in stations),
            tuple(value * FEET_TO_METRES for value in elevations),
        ),
        roughness_zones=roughness_zones,
        bank_stations_m=(banks[0] * FEET_TO_METRES, banks[1] * FEET_TO_METRES),
    )


def _collect_numeric_values(
    lines: list[str], start: int, count: int
) -> tuple[float, ...]:
    values: list[float] = []
    index = start
    while len(values) < count and index < len(lines):
        if lines[index].lstrip().startswith(
            ("#", "Bank Sta=", "Type RM", "River Reach=")
        ):
            break
        values.extend(_numeric_tokens(lines[index]))
        index += 1
    if len(values) != count:
        raise ValueError("hec_ras_numeric_array_length_invalid")
    return tuple(values)


def _numeric_tokens(value: str) -> list[float]:
    try:
        return [float(token) for token in value.split()]
    except ValueError as exc:
        raise ValueError("hec_ras_numeric_value_invalid") from exc


def _single_value(lines: list[str], prefix: str) -> str:
    values = [line.split("=", 1)[1] for line in lines if line.startswith(prefix)]
    if len(values) != 1:
        raise ValueError("hec_ras_required_field_invalid")
    return values[0]


def _all_values_before_first_reach(lines: list[str], prefix: str) -> tuple[str, ...]:
    values: list[str] = []
    for line in lines:
        if line.startswith("River Reach="):
            break
        if line.startswith(prefix):
            values.append(line.split("=", 1)[1])
    return tuple(values)


def _reach_key(value: str) -> ReachKey:
    parts = tuple(part.strip() for part in value.split(","))
    if len(parts) != 2 or any(not part for part in parts):
        raise ValueError("hec_ras_reach_key_invalid")
    return parts[0], parts[1]


def _unique_member(members: tuple[str, ...], suffix: str) -> str:
    values = [value for value in members if value.endswith(suffix)]
    if len(values) != 1:
        raise ValueError("hec_ras_example_archive_member_invalid")
    return values[0]
