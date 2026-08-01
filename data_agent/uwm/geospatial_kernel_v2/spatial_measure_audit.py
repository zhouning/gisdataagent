"""Typed spatial-measure audits for directed linear references.

Geometric projection and evidential admission are deliberately separate.  A
nearest point can always be computed, but a large cross-channel snap must not
silently become an accepted action or observation measure.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


DIRECTED_PATH_GEOMETRY_AUDIT_SCHEMA = (
    "gwm.geospatial_kernel.directed_path_geometry_audit.v1"
)
ENDPOINT_SPATIAL_MEASURE_AUDIT_SCHEMA = (
    "gwm.geospatial_kernel.endpoint_spatial_measure_audit.v1"
)

_EARTH_RADIUS_M = 6_371_008.8
_EVIDENCE_LEVELS = {"authoritative", "derived", "candidate"}
_ENDPOINT_ROLES = {"action_boundary", "observation_gauge"}

LonLat = tuple[float, float]
LineString = tuple[LonLat, ...]


def _point(value: Iterable[float]) -> LonLat:
    coordinates = tuple(float(item) for item in value)
    if (
        len(coordinates) != 2
        or not all(math.isfinite(item) for item in coordinates)
        or not -180.0 <= coordinates[0] <= 180.0
        or not -90.0 <= coordinates[1] <= 90.0
    ):
        raise ValueError("spatial_measure_lonlat_invalid")
    return coordinates


def _line(value: Iterable[Iterable[float]]) -> LineString:
    coordinates = tuple(_point(item) for item in value)
    if len(coordinates) < 2 or geometry_length_m(coordinates) <= 0.0:
        raise ValueError("spatial_measure_line_invalid")
    return coordinates


def haversine_m(first: LonLat, second: LonLat) -> float:
    lon1, lat1 = map(math.radians, first)
    lon2, lat2 = map(math.radians, second)
    delta_lon = lon2 - lon1
    delta_lat = lat2 - lat1
    value = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return _EARTH_RADIUS_M * 2.0 * math.asin(min(1.0, math.sqrt(value)))


def geometry_length_m(line: Iterable[Iterable[float]]) -> float:
    coordinates = tuple(_point(item) for item in line)
    return float(
        sum(
            haversine_m(first, second)
            for first, second in zip(coordinates, coordinates[1:], strict=False)
        )
    )


def project_point_to_line(point: LonLat, line: LineString) -> tuple[float, float]:
    """Return local planar snap distance and geodesic along-line measure."""

    point = _point(point)
    line = _line(line)
    lon_scale = 111_195.08 * math.cos(math.radians(point[1]))
    lat_scale = 111_195.08
    px, py = point[0] * lon_scale, point[1] * lat_scale
    best_distance = math.inf
    best_measure = 0.0
    measure = 0.0
    for first, second in zip(line, line[1:], strict=False):
        ax, ay = first[0] * lon_scale, first[1] * lat_scale
        bx, by = second[0] * lon_scale, second[1] * lat_scale
        dx, dy = bx - ax, by - ay
        length_squared = dx * dx + dy * dy
        ratio = 0.0 if length_squared == 0.0 else (
            ((px - ax) * dx + (py - ay) * dy) / length_squared
        )
        ratio = min(1.0, max(0.0, ratio))
        qx, qy = ax + ratio * dx, ay + ratio * dy
        distance = math.hypot(px - qx, py - qy)
        segment_length = haversine_m(first, second)
        if distance < best_distance:
            best_distance = distance
            best_measure = measure + ratio * segment_length
        measure += segment_length
    return float(best_distance), float(best_measure)


@dataclass(frozen=True)
class DirectedPathGeometryAudit:
    path_id: str
    feature_ids: tuple[int, ...]
    oriented_lines: tuple[LineString, ...]
    orientations: tuple[str, ...]
    full_lengths_m: tuple[float, ...]
    connection_gaps_m: tuple[float, ...]
    maximum_connection_gap_m: float
    provenance_id: str
    evidence_level: str

    @property
    def continuous(self) -> bool:
        return all(
            value <= self.maximum_connection_gap_m
            for value in self.connection_gaps_m
        )

    @property
    def total_full_length_m(self) -> float:
        return float(sum(self.full_lengths_m))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": DIRECTED_PATH_GEOMETRY_AUDIT_SCHEMA,
            "path_id": self.path_id,
            "feature_ids": list(self.feature_ids),
            "orientation_by_feature": [
                {"feature_id": feature_id, "coordinate_order": orientation}
                for feature_id, orientation in zip(
                    self.feature_ids, self.orientations, strict=True
                )
            ],
            "full_lengths_m": list(self.full_lengths_m),
            "total_full_length_m": self.total_full_length_m,
            "connection_gaps_m": list(self.connection_gaps_m),
            "maximum_connection_gap_m": self.maximum_connection_gap_m,
            "continuous": self.continuous,
            "projection_method": (
                "local_equirectangular_segment_projection_with_"
                "haversine_along_line_measure"
            ),
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
        }


@dataclass(frozen=True)
class EndpointSpatialMeasureAudit:
    endpoint_role: str
    feature_id: int
    point_lonlat: LonLat
    full_length_m: float
    candidate_measure_from_oriented_start_m: float
    snap_distance_m: float
    maximum_resolved_snap_distance_m: float
    distance_to_oriented_start_m: float
    distance_to_oriented_end_m: float
    provenance_id: str
    evidence_level: str

    @property
    def measure_resolved(self) -> bool:
        return self.snap_distance_m <= self.maximum_resolved_snap_distance_m

    @property
    def candidate_measure_fraction(self) -> float:
        return self.candidate_measure_from_oriented_start_m / self.full_length_m

    @property
    def candidate_remaining_to_oriented_end_m(self) -> float:
        return self.full_length_m - self.candidate_measure_from_oriented_start_m

    def as_dict(self) -> dict[str, object]:
        admitted_measure = (
            self.candidate_measure_from_oriented_start_m
            if self.measure_resolved
            else None
        )
        admitted_remaining = (
            self.candidate_remaining_to_oriented_end_m
            if self.measure_resolved
            else None
        )
        return {
            "schema": ENDPOINT_SPATIAL_MEASURE_AUDIT_SCHEMA,
            "endpoint_role": self.endpoint_role,
            "feature_id": self.feature_id,
            "point_lonlat": list(self.point_lonlat),
            "full_length_m": self.full_length_m,
            "candidate_measure_from_oriented_start_m": (
                self.candidate_measure_from_oriented_start_m
            ),
            "candidate_measure_fraction": self.candidate_measure_fraction,
            "candidate_remaining_to_oriented_end_m": (
                self.candidate_remaining_to_oriented_end_m
            ),
            "snap_distance_m": self.snap_distance_m,
            "maximum_resolved_snap_distance_m": (
                self.maximum_resolved_snap_distance_m
            ),
            "distance_to_oriented_start_m": self.distance_to_oriented_start_m,
            "distance_to_oriented_end_m": self.distance_to_oriented_end_m,
            "measure_resolved": self.measure_resolved,
            "admitted_measure_from_oriented_start_m": admitted_measure,
            "admitted_remaining_to_oriented_end_m": admitted_remaining,
            "provenance_id": self.provenance_id,
            "evidence_level": self.evidence_level,
        }


def audit_directed_path_geometry(
    *,
    path_id: str,
    feature_ids: tuple[int, ...],
    raw_lines: Iterable[Iterable[Iterable[float]]],
    maximum_connection_gap_m: float,
    provenance_id: str,
    evidence_level: str,
) -> DirectedPathGeometryAudit:
    if not path_id.strip() or not provenance_id.strip():
        raise ValueError("directed_path_geometry_audit_identity_required")
    if evidence_level not in _EVIDENCE_LEVELS:
        raise ValueError("directed_path_geometry_audit_evidence_level_invalid")
    if (
        not feature_ids
        or len(feature_ids) != len(set(feature_ids))
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in feature_ids
        )
    ):
        raise ValueError("directed_path_geometry_audit_feature_ids_invalid")
    maximum_gap = float(maximum_connection_gap_m)
    if not math.isfinite(maximum_gap) or maximum_gap < 0.0:
        raise ValueError("directed_path_geometry_audit_gap_limit_invalid")
    source_lines = tuple(_line(value) for value in raw_lines)
    if len(source_lines) != len(feature_ids):
        raise ValueError("directed_path_geometry_audit_axis_mismatch")

    candidates = tuple((line, tuple(reversed(line))) for line in source_lines)
    costs = [0.0, 0.0]
    parents: list[list[int]] = []
    for index in range(1, len(candidates)):
        next_costs: list[float] = []
        next_parents: list[int] = []
        for orientation in range(2):
            options = [
                costs[previous]
                + haversine_m(
                    candidates[index - 1][previous][-1],
                    candidates[index][orientation][0],
                )
                for previous in range(2)
            ]
            parent = min(range(2), key=options.__getitem__)
            next_costs.append(options[parent])
            next_parents.append(parent)
        costs = next_costs
        parents.append(next_parents)
    selected = [0] * len(candidates)
    selected[-1] = min(range(2), key=costs.__getitem__)
    for index in range(len(candidates) - 1, 0, -1):
        selected[index - 1] = parents[index - 1][selected[index]]
    lines = tuple(candidates[index][value] for index, value in enumerate(selected))
    gaps = tuple(
        haversine_m(first[-1], second[0])
        for first, second in zip(lines, lines[1:], strict=False)
    )
    return DirectedPathGeometryAudit(
        path_id=path_id,
        feature_ids=feature_ids,
        oriented_lines=lines,
        orientations=tuple(
            "source_order" if value == 0 else "reversed" for value in selected
        ),
        full_lengths_m=tuple(geometry_length_m(line) for line in lines),
        connection_gaps_m=gaps,
        maximum_connection_gap_m=maximum_gap,
        provenance_id=provenance_id,
        evidence_level=evidence_level,
    )


def audit_endpoint_spatial_measure(
    *,
    endpoint_role: str,
    feature_id: int,
    point_lonlat: Iterable[float],
    oriented_line: Iterable[Iterable[float]],
    maximum_resolved_snap_distance_m: float,
    provenance_id: str,
    evidence_level: str,
) -> EndpointSpatialMeasureAudit:
    if endpoint_role not in _ENDPOINT_ROLES:
        raise ValueError("endpoint_spatial_measure_role_invalid")
    if not isinstance(feature_id, int) or isinstance(feature_id, bool) or feature_id <= 0:
        raise ValueError("endpoint_spatial_measure_feature_id_invalid")
    if not provenance_id.strip():
        raise ValueError("endpoint_spatial_measure_provenance_required")
    if evidence_level not in _EVIDENCE_LEVELS:
        raise ValueError("endpoint_spatial_measure_evidence_level_invalid")
    maximum_snap = float(maximum_resolved_snap_distance_m)
    if not math.isfinite(maximum_snap) or maximum_snap <= 0.0:
        raise ValueError("endpoint_spatial_measure_snap_limit_invalid")
    point = _point(point_lonlat)
    line = _line(oriented_line)
    snap_distance, measure = project_point_to_line(point, line)
    full_length = geometry_length_m(line)
    return EndpointSpatialMeasureAudit(
        endpoint_role=endpoint_role,
        feature_id=feature_id,
        point_lonlat=point,
        full_length_m=full_length,
        candidate_measure_from_oriented_start_m=measure,
        snap_distance_m=snap_distance,
        maximum_resolved_snap_distance_m=maximum_snap,
        distance_to_oriented_start_m=haversine_m(point, line[0]),
        distance_to_oriented_end_m=haversine_m(point, line[-1]),
        provenance_id=provenance_id,
        evidence_level=evidence_level,
    )
