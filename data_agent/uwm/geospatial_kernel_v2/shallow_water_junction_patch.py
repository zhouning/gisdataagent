"""Conforming multi-cell finite-area shallow-water junction patch."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .conservative_vector_junction import ConservativeVectorJunctionSolution
from .dynamic_wave_flux import STANDARD_GRAVITY_MPS2
from .dynamic_wave_junction import DynamicWaveJunctionTerminal


JUNCTION_PATCH_GEOMETRY_SCHEMA = (
    "gwm.geospatial_kernel.shallow_water_junction_patch_geometry.v1"
)
JUNCTION_PATCH_STEP_SCHEMA = (
    "gwm.geospatial_kernel.shallow_water_junction_patch_step.v1"
)
_FACE_TYPES = frozenset(("internal", "branch_opening", "solid_wall"))
_BRANCH_ROLES = frozenset(("upstream", "downstream"))
_GEOMETRY_TOLERANCE = 1e-10
_STATE_TOLERANCE = 1e-10


@dataclass(frozen=True)
class JunctionPatchVertex:
    vertex_id: str
    east_m: float
    north_m: float

    def __post_init__(self) -> None:
        east = float(self.east_m)
        north = float(self.north_m)
        if (
            not isinstance(self.vertex_id, str)
            or not self.vertex_id.strip()
            or not math.isfinite(east)
            or not math.isfinite(north)
        ):
            raise ValueError("junction_patch_vertex_invalid")
        object.__setattr__(self, "east_m", east)
        object.__setattr__(self, "north_m", north)

    def as_dict(self) -> dict[str, object]:
        return {
            "vertex_id": self.vertex_id,
            "east_north_m": [self.east_m, self.north_m],
        }


@dataclass(frozen=True)
class JunctionPatchCellGeometry:
    cell_id: str
    vertex_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        vertex_ids = tuple(self.vertex_ids)
        if (
            not isinstance(self.cell_id, str)
            or not self.cell_id.strip()
            or len(vertex_ids) < 3
            or len(vertex_ids) != len(set(vertex_ids))
            or any(
                not isinstance(value, str) or not value.strip()
                for value in vertex_ids
            )
        ):
            raise ValueError("junction_patch_cell_geometry_invalid")
        object.__setattr__(self, "vertex_ids", vertex_ids)

    @property
    def directed_edges(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (left, right)
            for left, right in zip(
                self.vertex_ids,
                (*self.vertex_ids[1:], self.vertex_ids[0]),
                strict=True,
            )
        )

    def as_dict(self, *, area_m2: float) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "vertex_ids_counterclockwise": list(self.vertex_ids),
            "plan_area_m2": area_m2,
        }


@dataclass(frozen=True)
class JunctionPatchFace:
    face_id: str
    left_cell_id: str
    start_vertex_id: str
    end_vertex_id: str
    boundary_type: str
    right_cell_id: str | None = None
    branch_id: str | None = None
    branch_role: str | None = None

    def __post_init__(self) -> None:
        internal = self.boundary_type == "internal"
        opening = self.boundary_type == "branch_opening"
        if (
            not isinstance(self.face_id, str)
            or not self.face_id.strip()
            or not isinstance(self.left_cell_id, str)
            or not self.left_cell_id.strip()
            or not isinstance(self.start_vertex_id, str)
            or not self.start_vertex_id.strip()
            or not isinstance(self.end_vertex_id, str)
            or not self.end_vertex_id.strip()
            or self.start_vertex_id == self.end_vertex_id
            or self.boundary_type not in _FACE_TYPES
            or (
                internal
                and (
                    not isinstance(self.right_cell_id, str)
                    or not self.right_cell_id.strip()
                    or self.right_cell_id == self.left_cell_id
                    or self.branch_id is not None
                    or self.branch_role is not None
                )
            )
            or (not internal and self.right_cell_id is not None)
            or (
                opening
                and (
                    not isinstance(self.branch_id, str)
                    or not self.branch_id.strip()
                    or self.branch_role not in _BRANCH_ROLES
                )
            )
            or (
                not opening
                and (self.branch_id is not None or self.branch_role is not None)
            )
        ):
            raise ValueError("junction_patch_face_invalid")


@dataclass(frozen=True)
class ShallowWaterJunctionPatchGeometry:
    junction_id: str
    bed_elevation_m: float
    vertices: tuple[JunctionPatchVertex, ...]
    cells: tuple[JunctionPatchCellGeometry, ...]
    faces: tuple[JunctionPatchFace, ...]
    provenance_id: str

    def __post_init__(self) -> None:
        bed = float(self.bed_elevation_m)
        vertices = tuple(self.vertices)
        cells = tuple(self.cells)
        faces = tuple(self.faces)
        if (
            not isinstance(self.junction_id, str)
            or not self.junction_id.strip()
            or not math.isfinite(bed)
            or len(vertices) < 4
            or len(cells) < 2
            or len(faces) < 5
            or any(not isinstance(value, JunctionPatchVertex) for value in vertices)
            or any(
                not isinstance(value, JunctionPatchCellGeometry)
                for value in cells
            )
            or any(not isinstance(value, JunctionPatchFace) for value in faces)
            or len({value.vertex_id for value in vertices}) != len(vertices)
            or len({value.cell_id for value in cells}) != len(cells)
            or len({value.face_id for value in faces}) != len(faces)
            or not isinstance(self.provenance_id, str)
            or not self.provenance_id.strip()
        ):
            raise ValueError("junction_patch_geometry_invalid")
        vertex_by_id = {value.vertex_id: value for value in vertices}
        cell_by_id = {value.cell_id: value for value in cells}
        if any(
            vertex_id not in vertex_by_id
            for cell in cells
            for vertex_id in cell.vertex_ids
        ):
            raise ValueError("junction_patch_cell_vertex_missing")
        for cell in cells:
            coordinates = tuple(
                vertex_by_id[value] for value in cell.vertex_ids
            )
            if _signed_polygon_area(coordinates) <= _GEOMETRY_TOLERANCE:
                raise ValueError(
                    "junction_patch_cell_not_counterclockwise_positive"
                )
            if not _simple_polygon(coordinates):
                raise ValueError("junction_patch_cell_polygon_not_simple")
        coverage = {
            (cell.cell_id, start, end): 0
            for cell in cells
            for start, end in cell.directed_edges
        }
        for face in faces:
            left_key = (
                face.left_cell_id,
                face.start_vertex_id,
                face.end_vertex_id,
            )
            if left_key not in coverage:
                raise ValueError("junction_patch_face_left_edge_mismatch")
            coverage[left_key] += 1
            if face.boundary_type == "internal":
                right_key = (
                    str(face.right_cell_id),
                    face.end_vertex_id,
                    face.start_vertex_id,
                )
                if right_key not in coverage:
                    raise ValueError(
                        "junction_patch_internal_face_pair_mismatch"
                    )
                coverage[right_key] += 1
            elif face.left_cell_id not in cell_by_id:
                raise ValueError("junction_patch_face_cell_missing")
        if any(value != 1 for value in coverage.values()):
            raise ValueError("junction_patch_cell_edge_coverage_invalid")
        internal_faces = tuple(
            value for value in faces if value.boundary_type == "internal"
        )
        if not _connected_cells(tuple(cell_by_id), internal_faces):
            raise ValueError("junction_patch_cells_not_connected")
        branch_faces = tuple(
            value
            for value in faces
            if value.boundary_type == "branch_opening"
        )
        upstream = tuple(
            value for value in branch_faces if value.branch_role == "upstream"
        )
        downstream = tuple(
            value
            for value in branch_faces
            if value.branch_role == "downstream"
        )
        external_faces = tuple(
            value for value in faces if value.boundary_type != "internal"
        )
        closure = _external_closure(external_faces, vertex_by_id)
        perimeter = sum(
            _face_measure(value, vertex_by_id)[0]
            for value in external_faces
        )
        if (
            len(upstream) < 2
            or len(downstream) != 1
            or len({value.branch_id for value in branch_faces})
            != len(branch_faces)
            or not any(
                value.boundary_type == "solid_wall" for value in faces
            )
            or math.hypot(*closure)
            > max(1e-12, perimeter * _GEOMETRY_TOLERANCE)
        ):
            raise ValueError("junction_patch_external_boundary_invalid")
        object.__setattr__(self, "bed_elevation_m", bed)
        object.__setattr__(self, "vertices", vertices)
        object.__setattr__(self, "cells", cells)
        object.__setattr__(self, "faces", faces)

    @property
    def vertex_by_id(self) -> dict[str, JunctionPatchVertex]:
        return {value.vertex_id: value for value in self.vertices}

    @property
    def cell_by_id(self) -> dict[str, JunctionPatchCellGeometry]:
        return {value.cell_id: value for value in self.cells}

    @property
    def branch_faces(self) -> tuple[JunctionPatchFace, ...]:
        return tuple(
            value
            for value in self.faces
            if value.boundary_type == "branch_opening"
        )

    @property
    def upstream_branch_ids(self) -> tuple[str, ...]:
        return tuple(
            str(value.branch_id)
            for value in self.branch_faces
            if value.branch_role == "upstream"
        )

    @property
    def downstream_branch_id(self) -> str:
        return next(
            str(value.branch_id)
            for value in self.branch_faces
            if value.branch_role == "downstream"
        )

    @property
    def cell_areas_m2(self) -> dict[str, float]:
        vertices = self.vertex_by_id
        return {
            cell.cell_id: _signed_polygon_area(
                tuple(vertices[value] for value in cell.vertex_ids)
            )
            for cell in self.cells
        }

    @property
    def total_plan_area_m2(self) -> float:
        return sum(self.cell_areas_m2.values())

    @property
    def external_closure_east_north_m(self) -> tuple[float, float]:
        return _external_closure(
            tuple(
                value
                for value in self.faces
                if value.boundary_type != "internal"
            ),
            self.vertex_by_id,
        )

    def face_measure(
        self, face: JunctionPatchFace
    ) -> tuple[float, tuple[float, float], tuple[float, float]]:
        return _face_measure(face, self.vertex_by_id)

    def as_dict(self) -> dict[str, object]:
        areas = self.cell_areas_m2
        vertices = self.vertex_by_id
        return {
            "schema": JUNCTION_PATCH_GEOMETRY_SCHEMA,
            "junction_id": self.junction_id,
            "bed_elevation_m": self.bed_elevation_m,
            "vertices": [value.as_dict() for value in self.vertices],
            "cells": [
                value.as_dict(area_m2=areas[value.cell_id])
                for value in self.cells
            ],
            "faces": [
                _face_dict(value, vertices) for value in self.faces
            ],
            "total_plan_area_m2": self.total_plan_area_m2,
            "external_closure_east_north_m": list(
                self.external_closure_east_north_m
            ),
            "upstream_branch_ids": list(self.upstream_branch_ids),
            "downstream_branch_id": self.downstream_branch_id,
            "provenance_id": self.provenance_id,
            "counterclockwise_cell_polygons_verified": True,
            "simple_cell_polygons_verified": True,
            "conforming_internal_edge_pairs_verified": True,
            "complete_cell_edge_coverage_verified": True,
            "connected_cell_graph_verified": True,
            "external_boundary_measure_closed": True,
            "pairwise_polygon_overlap_independently_verified": False,
        }


@dataclass(frozen=True)
class JunctionPatchCellState:
    cell_id: str
    volume_m3: float
    momentum_east_m4s: float
    momentum_north_m4s: float

    def __post_init__(self) -> None:
        volume = float(self.volume_m3)
        east = float(self.momentum_east_m4s)
        north = float(self.momentum_north_m4s)
        if (
            not isinstance(self.cell_id, str)
            or not self.cell_id.strip()
            or not math.isfinite(volume)
            or volume <= 0.0
            or not math.isfinite(east)
            or not math.isfinite(north)
        ):
            raise ValueError("junction_patch_cell_state_invalid")
        object.__setattr__(self, "volume_m3", volume)
        object.__setattr__(self, "momentum_east_m4s", east)
        object.__setattr__(self, "momentum_north_m4s", north)

    @property
    def velocity_east_mps(self) -> float:
        return self.momentum_east_m4s / self.volume_m3

    @property
    def velocity_north_mps(self) -> float:
        return self.momentum_north_m4s / self.volume_m3

    def depth_m(self, plan_area_m2: float) -> float:
        return self.volume_m3 / plan_area_m2

    def as_dict(self, *, plan_area_m2: float, bed_elevation_m: float):
        depth = self.depth_m(plan_area_m2)
        return {
            "cell_id": self.cell_id,
            "volume_m3": self.volume_m3,
            "momentum_east_north_m4s": [
                self.momentum_east_m4s,
                self.momentum_north_m4s,
            ],
            "velocity_east_north_mps": [
                self.velocity_east_mps,
                self.velocity_north_mps,
            ],
            "depth_m": depth,
            "free_surface_elevation_m": bed_elevation_m + depth,
        }


@dataclass(frozen=True)
class ShallowWaterJunctionPatchState:
    cells: tuple[JunctionPatchCellState, ...]

    def __post_init__(self) -> None:
        cells = tuple(self.cells)
        if (
            len(cells) < 2
            or any(not isinstance(value, JunctionPatchCellState) for value in cells)
            or len({value.cell_id for value in cells}) != len(cells)
        ):
            raise ValueError("junction_patch_state_invalid")
        object.__setattr__(self, "cells", cells)

    @property
    def cell_by_id(self) -> dict[str, JunctionPatchCellState]:
        return {value.cell_id: value for value in self.cells}

    @property
    def total_volume_m3(self) -> float:
        return sum(value.volume_m3 for value in self.cells)

    @property
    def total_momentum_east_m4s(self) -> float:
        return sum(value.momentum_east_m4s for value in self.cells)

    @property
    def total_momentum_north_m4s(self) -> float:
        return sum(value.momentum_north_m4s for value in self.cells)

    def as_dict(
        self, geometry: ShallowWaterJunctionPatchGeometry
    ) -> dict[str, object]:
        areas = geometry.cell_areas_m2
        return {
            "cells": [
                value.as_dict(
                    plan_area_m2=areas[value.cell_id],
                    bed_elevation_m=geometry.bed_elevation_m,
                )
                for value in self.cells
            ],
            "total_volume_m3": self.total_volume_m3,
            "total_momentum_east_north_m4s": [
                self.total_momentum_east_m4s,
                self.total_momentum_north_m4s,
            ],
        }


@dataclass(frozen=True)
class JunctionPatchFaceFlux:
    face_id: str
    boundary_type: str
    left_cell_id: str
    right_cell_id: str | None
    branch_id: str | None
    branch_role: str | None
    minimum_signal_speed_mps: float
    maximum_signal_speed_mps: float
    wave_regime: str
    outward_mass_flux_m3s: float
    outward_momentum_flux_east_m4s2: float
    outward_momentum_flux_north_m4s2: float

    @property
    def maximum_signal_magnitude_mps(self) -> float:
        return max(
            abs(self.minimum_signal_speed_mps),
            abs(self.maximum_signal_speed_mps),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "face_id": self.face_id,
            "boundary_type": self.boundary_type,
            "left_cell_id": self.left_cell_id,
            "right_cell_id": self.right_cell_id,
            "branch_id": self.branch_id,
            "branch_role": self.branch_role,
            "minimum_signal_speed_mps": self.minimum_signal_speed_mps,
            "maximum_signal_speed_mps": self.maximum_signal_speed_mps,
            "wave_regime": self.wave_regime,
            "outward_mass_flux_m3s": self.outward_mass_flux_m3s,
            "outward_momentum_flux_east_north_m4s2": [
                self.outward_momentum_flux_east_m4s2,
                self.outward_momentum_flux_north_m4s2,
            ],
        }


@dataclass(frozen=True)
class ShallowWaterJunctionPatchStep:
    geometry: ShallowWaterJunctionPatchGeometry
    state_before: ShallowWaterJunctionPatchState
    state_after: ShallowWaterJunctionPatchState
    face_fluxes: tuple[JunctionPatchFaceFlux, ...]
    timestep_seconds: float
    maximum_stable_timestep_seconds: float
    maximum_courant_number: float
    external_opening_mass_flux_m3s: float
    external_opening_momentum_flux_east_m4s2: float
    external_opening_momentum_flux_north_m4s2: float
    wall_pressure_flux_east_m4s2: float
    wall_pressure_flux_north_m4s2: float
    mass_ledger_error_m3: float
    momentum_ledger_error_east_m4s: float
    momentum_ledger_error_north_m4s: float
    maximum_internal_mass_cancellation_error_m3: float
    maximum_internal_momentum_cancellation_error_m4s: float
    maximum_cell_mass_ledger_error_m3: float
    maximum_cell_momentum_ledger_error_m4s: float
    minimum_cell_volume_m3: float
    diagnostic_only: bool = True

    @property
    def momentum_ledger_error_magnitude_m4s(self) -> float:
        return math.hypot(
            self.momentum_ledger_error_east_m4s,
            self.momentum_ledger_error_north_m4s,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": JUNCTION_PATCH_STEP_SCHEMA,
            "geometry": self.geometry.as_dict(),
            "state_before": self.state_before.as_dict(self.geometry),
            "state_after": self.state_after.as_dict(self.geometry),
            "face_fluxes": [value.as_dict() for value in self.face_fluxes],
            "timestep_seconds": self.timestep_seconds,
            "maximum_stable_timestep_seconds": (
                self.maximum_stable_timestep_seconds
            ),
            "maximum_courant_number": self.maximum_courant_number,
            "mass_ledger": {
                "volume_before_m3": self.state_before.total_volume_m3,
                "external_opening_mass_flux_m3s": (
                    self.external_opening_mass_flux_m3s
                ),
                "volume_after_m3": self.state_after.total_volume_m3,
                "error_m3": self.mass_ledger_error_m3,
            },
            "momentum_ledger": {
                "external_opening_flux_east_north_m4s2": [
                    self.external_opening_momentum_flux_east_m4s2,
                    self.external_opening_momentum_flux_north_m4s2,
                ],
                "wall_pressure_flux_east_north_m4s2": [
                    self.wall_pressure_flux_east_m4s2,
                    self.wall_pressure_flux_north_m4s2,
                ],
                "error_east_north_m4s": [
                    self.momentum_ledger_error_east_m4s,
                    self.momentum_ledger_error_north_m4s,
                ],
                "error_magnitude_m4s": (
                    self.momentum_ledger_error_magnitude_m4s
                ),
            },
            "maximum_internal_mass_cancellation_error_m3": (
                self.maximum_internal_mass_cancellation_error_m3
            ),
            "maximum_internal_momentum_cancellation_error_m4s": (
                self.maximum_internal_momentum_cancellation_error_m4s
            ),
            "maximum_cell_mass_ledger_error_m3": (
                self.maximum_cell_mass_ledger_error_m3
            ),
            "maximum_cell_momentum_ledger_error_m4s": (
                self.maximum_cell_momentum_ledger_error_m4s
            ),
            "minimum_cell_volume_m3": self.minimum_cell_volume_m3,
            "multi_cell_finite_area_patch": True,
            "internal_hll_exchange": True,
            "single_evaluation_equal_opposite_internal_flux": True,
            "polygon_edge_topology_verified": True,
            "branch_reach_states_updated": False,
            "flat_bed_wet_rectangular_openings_only": True,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class _ExteriorState:
    branch_id: str
    branch_role: str
    depth_m: float
    velocity_east_mps: float
    velocity_north_mps: float


def maximum_shallow_water_junction_patch_timestep_seconds(
    state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
    *,
    courant_number: float,
) -> float:
    limit = _courant_number(courant_number)
    fluxes = _calculate_fluxes(
        state, geometry, upstream, downstream, junction
    )
    return _stable_timestep(state, geometry, fluxes, limit)


def advance_shallow_water_junction_patch(
    state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
    *,
    timestep_seconds: float,
    maximum_courant_number: float,
) -> ShallowWaterJunctionPatchStep:
    timestep = float(timestep_seconds)
    limit = _courant_number(maximum_courant_number)
    if not math.isfinite(timestep) or timestep <= 0.0:
        raise ValueError("junction_patch_timestep_invalid")
    fluxes = _calculate_fluxes(
        state, geometry, upstream, downstream, junction
    )
    stable = _stable_timestep(state, geometry, fluxes, limit)
    if timestep > stable * (1.0 + 1e-12):
        raise ValueError("junction_patch_cfl_exceeded")
    net = {
        value.cell_id: [0.0, 0.0, 0.0] for value in state.cells
    }
    for flux in fluxes:
        values = (
            flux.outward_mass_flux_m3s,
            flux.outward_momentum_flux_east_m4s2,
            flux.outward_momentum_flux_north_m4s2,
        )
        for index, value in enumerate(values):
            net[flux.left_cell_id][index] += value
            if flux.right_cell_id is not None:
                net[flux.right_cell_id][index] -= value
    after_cells = []
    cell_mass_errors = []
    cell_momentum_errors = []
    for before in state.cells:
        outward = net[before.cell_id]
        volume = before.volume_m3 - timestep * outward[0]
        east = before.momentum_east_m4s - timestep * outward[1]
        north = before.momentum_north_m4s - timestep * outward[2]
        if volume <= 0.0:
            raise FloatingPointError("junction_patch_cell_drained")
        after = JunctionPatchCellState(before.cell_id, volume, east, north)
        after_cells.append(after)
        cell_mass_errors.append(
            volume - before.volume_m3 + timestep * outward[0]
        )
        cell_momentum_errors.append(
            math.hypot(
                east - before.momentum_east_m4s + timestep * outward[1],
                north - before.momentum_north_m4s + timestep * outward[2],
            )
        )
    state_after = ShallowWaterJunctionPatchState(tuple(after_cells))
    openings = tuple(
        value for value in fluxes if value.boundary_type == "branch_opening"
    )
    walls = tuple(
        value for value in fluxes if value.boundary_type == "solid_wall"
    )
    internal = tuple(
        value for value in fluxes if value.boundary_type == "internal"
    )
    opening_mass = sum(value.outward_mass_flux_m3s for value in openings)
    opening_east = sum(
        value.outward_momentum_flux_east_m4s2 for value in openings
    )
    opening_north = sum(
        value.outward_momentum_flux_north_m4s2 for value in openings
    )
    wall_east = sum(
        value.outward_momentum_flux_east_m4s2 for value in walls
    )
    wall_north = sum(
        value.outward_momentum_flux_north_m4s2 for value in walls
    )
    internal_mass_errors = [
        abs(-timestep * value.outward_mass_flux_m3s
            + timestep * value.outward_mass_flux_m3s)
        for value in internal
    ]
    internal_momentum_errors = [
        math.hypot(
            -timestep * value.outward_momentum_flux_east_m4s2
            + timestep * value.outward_momentum_flux_east_m4s2,
            -timestep * value.outward_momentum_flux_north_m4s2
            + timestep * value.outward_momentum_flux_north_m4s2,
        )
        for value in internal
    ]
    return ShallowWaterJunctionPatchStep(
        geometry=geometry,
        state_before=state,
        state_after=state_after,
        face_fluxes=fluxes,
        timestep_seconds=timestep,
        maximum_stable_timestep_seconds=stable,
        maximum_courant_number=limit,
        external_opening_mass_flux_m3s=opening_mass,
        external_opening_momentum_flux_east_m4s2=opening_east,
        external_opening_momentum_flux_north_m4s2=opening_north,
        wall_pressure_flux_east_m4s2=wall_east,
        wall_pressure_flux_north_m4s2=wall_north,
        mass_ledger_error_m3=(
            state_after.total_volume_m3
            - state.total_volume_m3
            + timestep * opening_mass
        ),
        momentum_ledger_error_east_m4s=(
            state_after.total_momentum_east_m4s
            - state.total_momentum_east_m4s
            + timestep * (opening_east + wall_east)
        ),
        momentum_ledger_error_north_m4s=(
            state_after.total_momentum_north_m4s
            - state.total_momentum_north_m4s
            + timestep * (opening_north + wall_north)
        ),
        maximum_internal_mass_cancellation_error_m3=max(
            internal_mass_errors, default=0.0
        ),
        maximum_internal_momentum_cancellation_error_m4s=max(
            internal_momentum_errors, default=0.0
        ),
        maximum_cell_mass_ledger_error_m3=max(
            abs(value) for value in cell_mass_errors
        ),
        maximum_cell_momentum_ledger_error_m4s=max(cell_momentum_errors),
        minimum_cell_volume_m3=min(value.volume_m3 for value in after_cells),
    )


def _calculate_fluxes(
    state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
) -> tuple[JunctionPatchFaceFlux, ...]:
    if not isinstance(state, ShallowWaterJunctionPatchState):
        raise TypeError("shallow_water_junction_patch_state_required")
    if not isinstance(geometry, ShallowWaterJunctionPatchGeometry):
        raise TypeError("shallow_water_junction_patch_geometry_required")
    if not isinstance(junction, ConservativeVectorJunctionSolution):
        raise TypeError("conservative_vector_junction_solution_required")
    terminals = tuple(upstream)
    _validate_binding(state, geometry, terminals, downstream, junction)
    states = state.cell_by_id
    areas = geometry.cell_areas_m2
    exterior = {
        value.branch_id: value
        for value in _exterior_states(terminals, downstream, junction)
    }
    fluxes = []
    for face in geometry.faces:
        length, normal, tangent = geometry.face_measure(face)
        left = states[face.left_cell_id]
        left_depth = left.depth_m(areas[left.cell_id])
        left_normal, left_tangential = _rotated_velocity(
            left.velocity_east_mps,
            left.velocity_north_mps,
            normal,
            tangent,
        )
        if face.boundary_type == "solid_wall":
            pressure = 0.5 * STANDARD_GRAVITY_MPS2 * left_depth**2 * length
            celerity = math.sqrt(STANDARD_GRAVITY_MPS2 * left_depth)
            fluxes.append(
                JunctionPatchFaceFlux(
                    face.face_id,
                    face.boundary_type,
                    face.left_cell_id,
                    None,
                    None,
                    None,
                    left_normal - celerity,
                    left_normal + celerity,
                    "reflective_slip_wall",
                    0.0,
                    pressure * normal[0],
                    pressure * normal[1],
                )
            )
            continue
        if face.boundary_type == "internal":
            right = states[str(face.right_cell_id)]
            right_depth = right.depth_m(areas[right.cell_id])
            right_normal, right_tangential = _rotated_velocity(
                right.velocity_east_mps,
                right.velocity_north_mps,
                normal,
                tangent,
            )
            branch_id = None
            branch_role = None
            right_cell_id = right.cell_id
        else:
            boundary = exterior[str(face.branch_id)]
            right_depth = boundary.depth_m
            right_normal, right_tangential = _rotated_velocity(
                boundary.velocity_east_mps,
                boundary.velocity_north_mps,
                normal,
                tangent,
            )
            branch_id = boundary.branch_id
            branch_role = boundary.branch_role
            right_cell_id = None
        values, minimum, maximum, regime = _hll_rotated_flux(
            left_depth,
            left_normal,
            left_tangential,
            right_depth,
            right_normal,
            right_tangential,
        )
        normal_momentum = values[1] * length
        tangential_momentum = values[2] * length
        fluxes.append(
            JunctionPatchFaceFlux(
                face.face_id,
                face.boundary_type,
                face.left_cell_id,
                right_cell_id,
                branch_id,
                branch_role,
                minimum,
                maximum,
                regime,
                values[0] * length,
                normal_momentum * normal[0]
                + tangential_momentum * tangent[0],
                normal_momentum * normal[1]
                + tangential_momentum * tangent[1],
            )
        )
    return tuple(fluxes)


def _validate_binding(
    state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
) -> None:
    contract = junction.contract
    hydraulic = junction.hydraulic_solution
    if (
        tuple(value.cell_id for value in state.cells)
        != tuple(value.cell_id for value in geometry.cells)
        or geometry.junction_id != contract.junction_id
        or geometry.upstream_branch_ids != contract.upstream_branch_ids
        or geometry.downstream_branch_id != contract.downstream_branch_id
        or tuple(value.branch_id for value in upstream)
        != contract.upstream_branch_ids
        or downstream.branch_id != contract.downstream_branch_id
    ):
        raise ValueError("junction_patch_binding_mismatch")
    face_by_branch = {
        str(value.branch_id): value for value in geometry.branch_faces
    }
    terminals = (*upstream, downstream)
    boundaries = (
        *tuple(value.state for value in hydraulic.upstream_boundaries),
        hydraulic.downstream_boundary.state,
    )
    azimuths = (
        *contract.upstream_flow_azimuth_degrees,
        contract.downstream_flow_azimuth_degrees,
    )
    roles = (*(("upstream",) * len(upstream)), "downstream")
    for terminal, boundary, azimuth, role in zip(
        terminals, boundaries, azimuths, roles, strict=True
    ):
        face = face_by_branch[terminal.branch_id]
        length, normal, _ = geometry.face_measure(face)
        normal_azimuth = math.degrees(math.atan2(normal[0], normal[1])) % 360.0
        expected = (azimuth + 180.0) % 360.0 if role == "upstream" else azimuth
        depth = boundary.area_m2 / length
        if (
            terminal.section.side_slope_horizontal_per_vertical != 0.0
            or abs(terminal.section.bottom_width_m - length) > _STATE_TOLERANCE
            or abs(terminal.bed_elevation_m - geometry.bed_elevation_m)
            > _STATE_TOLERANCE
            or depth <= 0.0
            or boundary.discharge_m3s < -_STATE_TOLERANCE
            or abs(
                terminal.bed_elevation_m
                + depth
                - hydraulic.common_free_surface_elevation_m
            )
            > _STATE_TOLERANCE
            or _azimuth_difference(normal_azimuth, expected) > 1e-8
            or face.branch_role != role
        ):
            raise ValueError("junction_patch_opening_contract_not_supported")


def _exterior_states(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
) -> tuple[_ExteriorState, ...]:
    contract = junction.contract
    hydraulic = junction.hydraulic_solution
    terminals = (*upstream, downstream)
    states = (
        *tuple(value.state for value in hydraulic.upstream_boundaries),
        hydraulic.downstream_boundary.state,
    )
    azimuths = (
        *contract.upstream_flow_azimuth_degrees,
        contract.downstream_flow_azimuth_degrees,
    )
    roles = (*(("upstream",) * len(upstream)), "downstream")
    result = []
    for terminal, state, azimuth, role in zip(
        terminals, states, azimuths, roles, strict=True
    ):
        velocity = state.discharge_m3s / state.area_m2
        angle = math.radians(azimuth)
        result.append(
            _ExteriorState(
                terminal.branch_id,
                role,
                terminal.section.depth_m(state.area_m2),
                velocity * math.sin(angle),
                velocity * math.cos(angle),
            )
        )
    return tuple(result)


def _stable_timestep(
    state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    fluxes: tuple[JunctionPatchFaceFlux, ...],
    courant_number: float,
) -> float:
    areas = geometry.cell_areas_m2
    incident = {value.cell_id: [] for value in geometry.cells}
    net_mass = {value.cell_id: 0.0 for value in geometry.cells}
    face_by_id = {value.face_id: value for value in geometry.faces}
    for flux in fluxes:
        length = geometry.face_measure(face_by_id[flux.face_id])[0]
        spectral = length * flux.maximum_signal_magnitude_mps
        incident[flux.left_cell_id].append(spectral)
        net_mass[flux.left_cell_id] += flux.outward_mass_flux_m3s
        if flux.right_cell_id is not None:
            incident[flux.right_cell_id].append(spectral)
            net_mass[flux.right_cell_id] -= flux.outward_mass_flux_m3s
    candidates = []
    for cell in state.cells:
        spectral_sum = sum(incident[cell.cell_id])
        if spectral_sum <= 0.0:
            raise RuntimeError("junction_patch_timestep_undefined")
        candidates.append(
            courant_number * areas[cell.cell_id] / spectral_sum
        )
        if net_mass[cell.cell_id] > 0.0:
            candidates.append(
                courant_number
                * cell.volume_m3
                / net_mass[cell.cell_id]
            )
    return min(candidates)


def _hll_rotated_flux(
    left_depth: float,
    left_normal_velocity: float,
    left_tangential_velocity: float,
    right_depth: float,
    right_normal_velocity: float,
    right_tangential_velocity: float,
) -> tuple[tuple[float, float, float], float, float, str]:
    left_celerity = math.sqrt(STANDARD_GRAVITY_MPS2 * left_depth)
    right_celerity = math.sqrt(STANDARD_GRAVITY_MPS2 * right_depth)
    minimum = min(
        left_normal_velocity - left_celerity,
        right_normal_velocity - right_celerity,
    )
    maximum = max(
        left_normal_velocity + left_celerity,
        right_normal_velocity + right_celerity,
    )
    left_state = (
        left_depth,
        left_depth * left_normal_velocity,
        left_depth * left_tangential_velocity,
    )
    right_state = (
        right_depth,
        right_depth * right_normal_velocity,
        right_depth * right_tangential_velocity,
    )
    left_flux = _physical_flux(
        left_depth, left_normal_velocity, left_tangential_velocity
    )
    right_flux = _physical_flux(
        right_depth, right_normal_velocity, right_tangential_velocity
    )
    if minimum >= 0.0:
        return left_flux, minimum, maximum, "outward_upwind"
    if maximum <= 0.0:
        return right_flux, minimum, maximum, "inward_upwind"
    values = tuple(
        (
            maximum * left_value
            - minimum * right_value
            + minimum * maximum * (right_state_value - left_state_value)
        )
        / (maximum - minimum)
        for left_value, right_value, left_state_value, right_state_value in zip(
            left_flux,
            right_flux,
            left_state,
            right_state,
            strict=True,
        )
    )
    return values, minimum, maximum, "hll_mixed"


def _physical_flux(
    depth: float,
    normal_velocity: float,
    tangential_velocity: float,
) -> tuple[float, float, float]:
    discharge = depth * normal_velocity
    return (
        discharge,
        discharge * normal_velocity
        + 0.5 * STANDARD_GRAVITY_MPS2 * depth**2,
        discharge * tangential_velocity,
    )


def _rotated_velocity(
    east: float,
    north: float,
    normal: tuple[float, float],
    tangent: tuple[float, float],
) -> tuple[float, float]:
    return (
        east * normal[0] + north * normal[1],
        east * tangent[0] + north * tangent[1],
    )


def _face_measure(
    face: JunctionPatchFace,
    vertices: dict[str, JunctionPatchVertex],
) -> tuple[float, tuple[float, float], tuple[float, float]]:
    start = vertices[face.start_vertex_id]
    end = vertices[face.end_vertex_id]
    delta_east = end.east_m - start.east_m
    delta_north = end.north_m - start.north_m
    length = math.hypot(delta_east, delta_north)
    if length <= _GEOMETRY_TOLERANCE:
        raise ValueError("junction_patch_face_length_invalid")
    tangent = (delta_east / length, delta_north / length)
    normal = (tangent[1], -tangent[0])
    return length, normal, tangent


def _face_dict(
    face: JunctionPatchFace,
    vertices: dict[str, JunctionPatchVertex],
) -> dict[str, object]:
    length, normal, tangent = _face_measure(face, vertices)
    return {
        "face_id": face.face_id,
        "left_cell_id": face.left_cell_id,
        "right_cell_id": face.right_cell_id,
        "start_vertex_id": face.start_vertex_id,
        "end_vertex_id": face.end_vertex_id,
        "boundary_type": face.boundary_type,
        "branch_id": face.branch_id,
        "branch_role": face.branch_role,
        "length_m": length,
        "outward_from_left_normal_east_north": list(normal),
        "oriented_tangent_east_north": list(tangent),
    }


def _signed_polygon_area(vertices: tuple[JunctionPatchVertex, ...]) -> float:
    return 0.5 * sum(
        left.east_m * right.north_m - right.east_m * left.north_m
        for left, right in zip(
            vertices, (*vertices[1:], vertices[0]), strict=True
        )
    )


def _simple_polygon(vertices: tuple[JunctionPatchVertex, ...]) -> bool:
    segments = tuple(
        (left, right)
        for left, right in zip(
            vertices, (*vertices[1:], vertices[0]), strict=True
        )
    )
    count = len(segments)
    for left_index, left in enumerate(segments):
        for right_index in range(left_index + 1, count):
            if (
                right_index == left_index + 1
                or (left_index == 0 and right_index == count - 1)
            ):
                continue
            if _segments_intersect(left, segments[right_index]):
                return False
    return True


def _segments_intersect(
    left: tuple[JunctionPatchVertex, JunctionPatchVertex],
    right: tuple[JunctionPatchVertex, JunctionPatchVertex],
) -> bool:
    def orientation(a, b, c):
        return (
            (b.east_m - a.east_m) * (c.north_m - a.north_m)
            - (b.north_m - a.north_m) * (c.east_m - a.east_m)
        )

    values = (
        orientation(left[0], left[1], right[0]),
        orientation(left[0], left[1], right[1]),
        orientation(right[0], right[1], left[0]),
        orientation(right[0], right[1], left[1]),
    )
    return values[0] * values[1] <= 0.0 and values[2] * values[3] <= 0.0


def _connected_cells(
    cell_ids: tuple[str, ...],
    faces: tuple[JunctionPatchFace, ...],
) -> bool:
    adjacency = {value: set() for value in cell_ids}
    for face in faces:
        right = str(face.right_cell_id)
        adjacency[face.left_cell_id].add(right)
        adjacency[right].add(face.left_cell_id)
    visited = {cell_ids[0]}
    frontier = [cell_ids[0]]
    while frontier:
        current = frontier.pop()
        for value in adjacency[current] - visited:
            visited.add(value)
            frontier.append(value)
    return len(visited) == len(cell_ids)


def _external_closure(
    faces: tuple[JunctionPatchFace, ...],
    vertices: dict[str, JunctionPatchVertex],
) -> tuple[float, float]:
    return (
        sum(_face_measure(value, vertices)[0]
            * _face_measure(value, vertices)[1][0] for value in faces),
        sum(_face_measure(value, vertices)[0]
            * _face_measure(value, vertices)[1][1] for value in faces),
    )


def _courant_number(value: float) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0.0 < result <= 1.0:
        raise ValueError("junction_patch_courant_invalid")
    return result


def _azimuth_difference(left: float, right: float) -> float:
    return abs((right - left + 180.0) % 360.0 - 180.0)
