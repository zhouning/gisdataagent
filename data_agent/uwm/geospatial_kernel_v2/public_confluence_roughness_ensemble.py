"""Stage 22 public-confluence roughness and support uncertainty ensemble."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any

from .coupled_junction_patch_reach_patch_friction import (
    JunctionPatchCellManningRoughness,
    JunctionPatchManningRoughnessField,
    JunctionPatchManningFrictionStep,
    apply_junction_patch_manning_friction,
)
from .public_confluence_fixture import (
    DEFAULT_SOURCE_ROOT,
    LAND_COVER_ROUGHNESS_PRIORS,
    REPO_ROOT,
    TARGET_JUNCTION_COORDINATE,
    PublicConfluenceFixture,
    _wgs84_to_local,
    compile_public_confluence_fixture,
)
from .shallow_water_junction_patch import (
    JunctionPatchCellState,
    ShallowWaterJunctionPatchState,
)


PUBLIC_CONFLUENCE_ROUGHNESS_ENSEMBLE_SCHEMA = (
    "gwm.geospatial_kernel.public_confluence_roughness_ensemble.v1"
)
PUBLIC_CONFLUENCE_ROUGHNESS_PROPAGATION_SCHEMA = (
    "gwm.geospatial_kernel.public_confluence_roughness_propagation.v1"
)
EXPECTED_LAND_COVER_SCHEMA = (
    "gwm.geotransport.public_land_cover_samples.v1"
)
SPATIAL_SUPPORT_RULE_POINT = "pixel_center_or_nearest_valid_pixel"
SPATIAL_SUPPORT_RULE_FOOTPRINT = "pixel_footprint_cell_intersection_area"
ENSEMBLE_MEMBER_ORDER = (
    "joint_lower",
    "point_lower",
    "footprint_lower",
    "point_center",
    "footprint_center",
    "point_upper",
    "footprint_upper",
    "joint_upper",
)
SUPPORT_AREA_TOLERANCE_M2 = 1e-6


@dataclass(frozen=True)
class CellRoughnessSupportUncertainty:
    cell_id: str
    support_area_m2: float
    point_class_area_fractions: tuple[tuple[int, float], ...]
    point_nearest_fallback: bool
    point_lower: float
    point_center: float
    point_upper: float
    footprint_class_area_fractions: tuple[tuple[int, float], ...]
    footprint_covered_area_m2: float
    footprint_coverage_fraction: float
    footprint_lower: float
    footprint_center: float
    footprint_upper: float
    joint_lower: float
    joint_upper: float

    def __post_init__(self) -> None:
        scalars = (
            self.support_area_m2,
            self.footprint_covered_area_m2,
            self.footprint_coverage_fraction,
            self.point_lower,
            self.point_center,
            self.point_upper,
            self.footprint_lower,
            self.footprint_center,
            self.footprint_upper,
            self.joint_lower,
            self.joint_upper,
        )
        if (
            not self.cell_id
            or any(not math.isfinite(float(value)) for value in scalars)
            or self.support_area_m2 <= 0.0
            or self.footprint_covered_area_m2 <= 0.0
            or not 0.0 < self.footprint_coverage_fraction <= 1.0 + 1e-9
            or not self.point_lower <= self.point_center <= self.point_upper
            or not (
                self.footprint_lower
                <= self.footprint_center
                <= self.footprint_upper
            )
            or self.joint_lower
            != min(self.point_lower, self.footprint_lower)
            or self.joint_upper
            != max(self.point_upper, self.footprint_upper)
        ):
            raise ValueError("cell_roughness_support_uncertainty_invalid")

    @property
    def support_rule_center_difference(self) -> float:
        return self.footprint_center - self.point_center

    @property
    def joint_interval_width(self) -> float:
        return self.joint_upper - self.joint_lower

    def value_for_member(self, member_id: str) -> float:
        values = {
            "joint_lower": self.joint_lower,
            "point_lower": self.point_lower,
            "footprint_lower": self.footprint_lower,
            "point_center": self.point_center,
            "footprint_center": self.footprint_center,
            "point_upper": self.point_upper,
            "footprint_upper": self.footprint_upper,
            "joint_upper": self.joint_upper,
        }
        if member_id not in values:
            raise ValueError("public_roughness_ensemble_member_unknown")
        return values[member_id]

    def as_dict(self) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "support_area_m2": self.support_area_m2,
            "point_assignment": {
                "rule": SPATIAL_SUPPORT_RULE_POINT,
                "nearest_valid_pixel_fallback": self.point_nearest_fallback,
                "class_area_fractions": {
                    str(code): fraction
                    for code, fraction in self.point_class_area_fractions
                },
                "manning_n_interval": {
                    "lower": self.point_lower,
                    "center": self.point_center,
                    "upper": self.point_upper,
                },
            },
            "footprint_assignment": {
                "rule": SPATIAL_SUPPORT_RULE_FOOTPRINT,
                "covered_area_m2": self.footprint_covered_area_m2,
                "coverage_fraction": self.footprint_coverage_fraction,
                "class_area_fractions": {
                    str(code): fraction
                    for code, fraction in self.footprint_class_area_fractions
                },
                "manning_n_interval": {
                    "lower": self.footprint_lower,
                    "center": self.footprint_center,
                    "upper": self.footprint_upper,
                },
            },
            "joint_interval": {
                "lower": self.joint_lower,
                "upper": self.joint_upper,
                "width": self.joint_interval_width,
                "construction": (
                    "envelope_of_parameter_intervals_across_support_rules"
                ),
            },
            "support_rule_center_difference": (
                self.support_rule_center_difference
            ),
        }


@dataclass(frozen=True)
class PublicConfluenceRoughnessEnsemble:
    fixture: PublicConfluenceFixture
    cells: tuple[CellRoughnessSupportUncertainty, ...]
    members: tuple[JunctionPatchManningRoughnessField, ...]
    land_cover_pixel_width_m: float
    land_cover_pixel_height_m: float
    land_cover_pixel_area_m2: float
    provenance_id: str

    def __post_init__(self) -> None:
        geometry_ids = tuple(
            value.cell_id
            for value in self.fixture.diagnostic_horizontal_geometry.cells
        )
        cell_ids = tuple(value.cell_id for value in self.cells)
        if (
            cell_ids != geometry_ids
            or tuple(_member_id(value) for value in self.members)
            != ENSEMBLE_MEMBER_ORDER
            or any(
                tuple(cell.cell_id for cell in value.cells) != geometry_ids
                for value in self.members
            )
        ):
            raise ValueError("public_confluence_roughness_ensemble_invalid")

    @property
    def member_by_id(self) -> dict[str, JunctionPatchManningRoughnessField]:
        return {_member_id(value): value for value in self.members}

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PUBLIC_CONFLUENCE_ROUGHNESS_ENSEMBLE_SCHEMA,
            "junction_id": self.fixture.junction_id,
            "geometry_provenance_id": (
                self.fixture.diagnostic_horizontal_geometry.provenance_id
            ),
            "land_cover_raster_support": {
                "classification": "USDA_NASS_CDL_2024",
                "resampled_pixel_width_m": self.land_cover_pixel_width_m,
                "resampled_pixel_height_m": self.land_cover_pixel_height_m,
                "resampled_pixel_area_m2": self.land_cover_pixel_area_m2,
                "native_pixel_size_m": 30.0,
                "pixel_footprints_inferred_from_adjacent_sample_centers": True,
            },
            "spatial_support_rules": [
                SPATIAL_SUPPORT_RULE_POINT,
                SPATIAL_SUPPORT_RULE_FOOTPRINT,
            ],
            "cells": [value.as_dict() for value in self.cells],
            "members": [
                {
                    "member_id": _member_id(value),
                    "roughness_field": value.as_dict(),
                }
                for value in self.members
            ],
            "provenance_id": self.provenance_id,
            "uncertainty_sources": [
                "land_cover_class_to_manning_lookup_interval",
                "point_or_nearest_pixel_vs_pixel_footprint_aggregation",
            ],
            "excluded_uncertainty_sources": [
                "bathymetry",
                "cross_section_geometry",
                "water_depth",
                "velocity_initial_condition",
                "subgrid_turbulence",
            ],
            "roughness_calibrated": False,
            "runtime_hydraulic_geometry_admitted": False,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class RoughnessPropagationMember:
    member_id: str
    step: JunctionPatchManningFrictionStep

    def as_dict(self) -> dict[str, object]:
        return {
            "member_id": self.member_id,
            "roughness_values": {
                value.cell_id: value.manning_n
                for value in self.step.roughness_field.cells
            },
            "mass_ledger_error_m3": self.step.volume_ledger_error_m3,
            "momentum_ledger_error_magnitude_m4s": (
                self.step.momentum_ledger_error_magnitude_m4s
            ),
            "kinetic_energy_dissipation_m5s2": (
                self.step.kinetic_energy_dissipation_m5s2
            ),
            "friction_impulse_east_north_m4s": [
                self.step.friction_impulse_east_m4s,
                self.step.friction_impulse_north_m4s,
            ],
            "cell_damping_factors": {
                value.cell_id: value.damping_factor
                for value in self.step.cell_traces
            },
            "cell_energy_dissipation_m5s2": {
                value.cell_id: value.kinetic_energy_dissipation_m5s2
                for value in self.step.cell_traces
            },
        }


@dataclass(frozen=True)
class PublicConfluenceRoughnessPropagation:
    ensemble: PublicConfluenceRoughnessEnsemble
    state: ShallowWaterJunctionPatchState
    timestep_seconds: float
    members: tuple[RoughnessPropagationMember, ...]

    def as_dict(self) -> dict[str, object]:
        member_by_id = {value.member_id: value for value in self.members}
        lower = member_by_id["joint_lower"].step
        upper = member_by_id["joint_upper"].step
        dissipation_values = [
            value.step.kinetic_energy_dissipation_m5s2
            for value in self.members
        ]
        return {
            "schema": PUBLIC_CONFLUENCE_ROUGHNESS_PROPAGATION_SCHEMA,
            "junction_id": self.ensemble.fixture.junction_id,
            "timestep_seconds": self.timestep_seconds,
            "diagnostic_state": self.state.as_dict(
                self.ensemble.fixture.diagnostic_horizontal_geometry
            ),
            "members": [value.as_dict() for value in self.members],
            "dissipation_envelope_m5s2": {
                "minimum": min(dissipation_values),
                "maximum": max(dissipation_values),
                "joint_lower_member": (
                    lower.kinetic_energy_dissipation_m5s2
                ),
                "joint_upper_member": (
                    upper.kinetic_energy_dissipation_m5s2
                ),
            },
            "diagnostic_state_is_observed": False,
            "diagnostic_state_role": (
                "fixed_manufactured_state_for_parameter_propagation_only"
            ),
            "runtime_hydraulic_rollout": False,
            "public_vector_momentum_validation_completed": False,
            "operator_admitted": False,
        }


def compile_public_confluence_roughness_ensemble(
    source_root: Path = DEFAULT_SOURCE_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicConfluenceRoughnessEnsemble:
    fixture = compile_public_confluence_fixture(
        source_root, repo_root=repo_root
    )
    samples_path = Path(source_root) / "derived/cdl_2024_samples.json"
    samples = json.loads(samples_path.read_text(encoding="utf-8"))
    if (
        samples.get("schema") != EXPECTED_LAND_COVER_SCHEMA
        or samples.get("classification") != "USDA_NASS_CDL_2024"
        or float(samples.get("native_pixel_size_m", 0.0)) != 30.0
    ):
        raise ValueError("public_roughness_land_cover_samples_invalid")
    pixel_support = _compile_pixel_support(samples)
    geometry = fixture.diagnostic_horizontal_geometry
    vertices = geometry.vertex_by_id
    cell_by_id = {value.cell_id: value for value in fixture.cell_evidence}
    uncertainties = []
    for cell in geometry.cells:
        evidence = cell_by_id[cell.cell_id]
        polygon = tuple(
            (vertices[value].east_m, vertices[value].north_m)
            for value in cell.vertex_ids
        )
        footprint_areas = _class_intersection_areas(polygon, pixel_support)
        covered_area = sum(footprint_areas.values())
        area = geometry.cell_areas_m2[cell.cell_id]
        if abs(covered_area - area) > SUPPORT_AREA_TOLERANCE_M2:
            raise ValueError(
                "public_roughness_pixel_footprints_do_not_cover_cell"
            )
        footprint_fractions = tuple(
            sorted(
                (code, value / covered_area)
                for code, value in footprint_areas.items()
                if value > 0.0
            )
        )
        point_fractions = tuple(
            sorted(
                (code, count / evidence.land_cover_sample_count)
                for code, count in evidence.land_cover_counts
            )
        )
        point_interval = _roughness_interval(point_fractions)
        footprint_interval = _roughness_interval(footprint_fractions)
        uncertainties.append(
            CellRoughnessSupportUncertainty(
                cell.cell_id,
                area,
                point_fractions,
                evidence.land_cover_nearest_fallback,
                *point_interval,
                footprint_fractions,
                covered_area,
                covered_area / area,
                *footprint_interval,
                min(point_interval[0], footprint_interval[0]),
                max(point_interval[2], footprint_interval[2]),
            )
        )
    provenance = (
        f"{fixture.provenance_id}:cdl-support-and-lookup-uncertainty-v1"
    )
    members = tuple(
        _compile_member(
            member_id,
            fixture=fixture,
            cells=tuple(uncertainties),
            provenance_id=provenance,
        )
        for member_id in ENSEMBLE_MEMBER_ORDER
    )
    return PublicConfluenceRoughnessEnsemble(
        fixture,
        tuple(uncertainties),
        members,
        pixel_support["pixel_width_m"],
        pixel_support["pixel_height_m"],
        pixel_support["pixel_area_m2"],
        provenance,
    )


def diagnostic_patch_state(
    ensemble: PublicConfluenceRoughnessEnsemble,
    *,
    depth_m: float = 1.25,
) -> ShallowWaterJunctionPatchState:
    depth = float(depth_m)
    if not math.isfinite(depth) or depth <= 0.0:
        raise ValueError("public_roughness_diagnostic_depth_invalid")
    geometry = ensemble.fixture.diagnostic_horizontal_geometry
    vertices = geometry.vertex_by_id
    values = []
    for index, cell in enumerate(geometry.cells):
        area = geometry.cell_areas_m2[cell.cell_id]
        volume = area * depth
        polygon = tuple(
            (vertices[value].east_m, vertices[value].north_m)
            for value in cell.vertex_ids
        )
        centroid_east = sum(value[0] for value in polygon) / len(polygon)
        centroid_north = sum(value[1] for value in polygon) / len(polygon)
        speed = 0.35 + 0.04 * index
        magnitude = math.hypot(centroid_east, centroid_north)
        if magnitude <= 1e-12:
            direction = (1.0, 0.0)
        else:
            direction = (centroid_east / magnitude, centroid_north / magnitude)
        values.append(
            JunctionPatchCellState(
                cell.cell_id,
                volume,
                volume * speed * direction[0],
                volume * speed * direction[1],
            )
        )
    return ShallowWaterJunctionPatchState(tuple(values))


def propagate_public_confluence_roughness_ensemble(
    ensemble: PublicConfluenceRoughnessEnsemble,
    *,
    state: ShallowWaterJunctionPatchState | None = None,
    timestep_seconds: float = 1.0,
) -> PublicConfluenceRoughnessPropagation:
    timestep = float(timestep_seconds)
    if not math.isfinite(timestep) or timestep <= 0.0:
        raise ValueError("public_roughness_propagation_timestep_invalid")
    current = diagnostic_patch_state(ensemble) if state is None else state
    if tuple(value.cell_id for value in current.cells) != tuple(
        value.cell_id
        for value in ensemble.fixture.diagnostic_horizontal_geometry.cells
    ):
        raise ValueError("public_roughness_propagation_state_mismatch")
    members = tuple(
        RoughnessPropagationMember(
            _member_id(field),
            apply_junction_patch_manning_friction(
                current,
                ensemble.fixture.diagnostic_horizontal_geometry,
                field,
                timestep_seconds=timestep,
            ),
        )
        for field in ensemble.members
    )
    return PublicConfluenceRoughnessPropagation(
        ensemble, current, timestep, members
    )


def _compile_member(
    member_id: str,
    *,
    fixture: PublicConfluenceFixture,
    cells: tuple[CellRoughnessSupportUncertainty, ...],
    provenance_id: str,
) -> JunctionPatchManningRoughnessField:
    if member_id not in ENSEMBLE_MEMBER_ORDER:
        raise ValueError("public_roughness_ensemble_member_unknown")
    geometry = fixture.diagnostic_horizontal_geometry
    return JunctionPatchManningRoughnessField(
        fixture.junction_id,
        geometry.provenance_id,
        tuple(
            JunctionPatchCellManningRoughness(
                value.cell_id,
                value.value_for_member(member_id),
                value.support_area_m2,
                f"{provenance_id}:{member_id}:{value.cell_id}",
            )
            for value in cells
        ),
        f"{provenance_id}:member-{member_id}",
    )


def _member_id(field: JunctionPatchManningRoughnessField) -> str:
    marker = ":member-"
    if marker not in field.provenance_id:
        raise ValueError("public_roughness_ensemble_member_identity_missing")
    return field.provenance_id.rsplit(marker, 1)[1]


def _roughness_interval(
    fractions: tuple[tuple[int, float], ...]
) -> tuple[float, float, float]:
    if (
        not fractions
        or abs(sum(value for _, value in fractions) - 1.0) > 1e-9
    ):
        raise ValueError("public_roughness_class_fractions_invalid")
    unknown = sorted(
        code for code, _ in fractions if code not in LAND_COVER_ROUGHNESS_PRIORS
    )
    if unknown:
        raise ValueError(
            "public_roughness_land_cover_class_unmapped:"
            + ",".join(str(value) for value in unknown)
        )

    def weighted(key: str) -> float:
        return sum(
            float(LAND_COVER_ROUGHNESS_PRIORS[code][key]) * fraction
            for code, fraction in fractions
        )

    return weighted("lower"), weighted("manning_n"), weighted("upper")


def _compile_pixel_support(samples: dict[str, Any]) -> dict[str, Any]:
    values = [
        (
            *_wgs84_to_local(
                float(value["longitude"]),
                float(value["latitude"]),
                TARGET_JUNCTION_COORDINATE,
            ),
            int(value["class_code"]),
        )
        for value in samples["samples"]
    ]
    xs = _clustered_unique(tuple(value[0] for value in values))
    ys = _clustered_unique(tuple(value[1] for value in values))
    if len(xs) < 2 or len(ys) < 2:
        raise ValueError("public_roughness_pixel_grid_undefined")
    x_spacing = _uniform_spacing(xs)
    y_spacing = _uniform_spacing(ys)
    pixels = tuple(
        {
            "minimum_east_m": east - x_spacing / 2.0,
            "maximum_east_m": east + x_spacing / 2.0,
            "minimum_north_m": north - y_spacing / 2.0,
            "maximum_north_m": north + y_spacing / 2.0,
            "class_code": code,
        }
        for east, north, code in values
    )
    return {
        "pixel_width_m": x_spacing,
        "pixel_height_m": y_spacing,
        "pixel_area_m2": x_spacing * y_spacing,
        "pixels": pixels,
    }


def _class_intersection_areas(
    polygon: tuple[tuple[float, float], ...],
    pixel_support: dict[str, Any],
) -> dict[int, float]:
    areas: dict[int, float] = {}
    for pixel in pixel_support["pixels"]:
        code = int(pixel["class_code"])
        clipped = _clip_polygon_to_rectangle(
            polygon,
            minimum_east=float(pixel["minimum_east_m"]),
            maximum_east=float(pixel["maximum_east_m"]),
            minimum_north=float(pixel["minimum_north_m"]),
            maximum_north=float(pixel["maximum_north_m"]),
        )
        area = abs(_signed_area(clipped)) if len(clipped) >= 3 else 0.0
        if area <= 1e-12:
            continue
        if code <= 0:
            raise ValueError("public_roughness_nodata_intersects_patch")
        areas[code] = areas.get(code, 0.0) + area
    return areas


def _clip_polygon_to_rectangle(
    polygon: tuple[tuple[float, float], ...],
    *,
    minimum_east: float,
    maximum_east: float,
    minimum_north: float,
    maximum_north: float,
) -> tuple[tuple[float, float], ...]:
    result = polygon
    boundaries = (
        (lambda point: point[0] >= minimum_east, 0, minimum_east),
        (lambda point: point[0] <= maximum_east, 0, maximum_east),
        (lambda point: point[1] >= minimum_north, 1, minimum_north),
        (lambda point: point[1] <= maximum_north, 1, maximum_north),
    )
    for inside, axis, boundary in boundaries:
        if not result:
            break
        output = []
        for start, end in zip(
            (result[-1], *result[:-1]), result, strict=True
        ):
            start_inside = inside(start)
            end_inside = inside(end)
            if end_inside:
                if not start_inside:
                    output.append(_boundary_intersection(start, end, axis, boundary))
                output.append(end)
            elif start_inside:
                output.append(_boundary_intersection(start, end, axis, boundary))
        result = tuple(output)
    return result


def _boundary_intersection(
    start: tuple[float, float],
    end: tuple[float, float],
    axis: int,
    boundary: float,
) -> tuple[float, float]:
    delta = end[axis] - start[axis]
    if abs(delta) <= 1e-15:
        return start
    fraction = (boundary - start[axis]) / delta
    return (
        start[0] + fraction * (end[0] - start[0]),
        start[1] + fraction * (end[1] - start[1]),
    )


def _signed_area(polygon: tuple[tuple[float, float], ...]) -> float:
    if len(polygon) < 3:
        return 0.0
    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(
            polygon, (*polygon[1:], polygon[0]), strict=True
        )
    )


def _clustered_unique(values: tuple[float, ...]) -> tuple[float, ...]:
    ordered = sorted(values)
    clusters: list[list[float]] = []
    for value in ordered:
        if not clusters or abs(value - clusters[-1][-1]) > 1e-5:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return tuple(sum(value) / len(value) for value in clusters)


def _uniform_spacing(values: tuple[float, ...]) -> float:
    differences = tuple(
        right - left
        for left, right in zip(values[:-1], values[1:], strict=True)
    )
    spacing = sum(differences) / len(differences)
    if (
        not math.isfinite(spacing)
        or spacing <= 0.0
        or max(abs(value - spacing) for value in differences) > 1e-4
    ):
        raise ValueError("public_roughness_pixel_grid_not_uniform")
    return spacing
