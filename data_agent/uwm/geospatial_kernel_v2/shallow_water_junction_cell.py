"""Finite-area two-dimensional shallow-water junction control cell."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .conservative_vector_junction import (
    ConservativeVectorJunctionSolution,
)
from .dynamic_wave_flux import STANDARD_GRAVITY_MPS2
from .dynamic_wave_junction import DynamicWaveJunctionTerminal


SHALLOW_WATER_JUNCTION_CELL_GEOMETRY_SCHEMA = (
    "gwm.geospatial_kernel.shallow_water_junction_cell_geometry.v1"
)
SHALLOW_WATER_JUNCTION_CELL_STEP_SCHEMA = (
    "gwm.geospatial_kernel.shallow_water_junction_cell_step.v1"
)
_BOUNDARY_TYPES = frozenset(("branch_opening", "solid_wall"))
_BRANCH_ROLES = frozenset(("upstream", "downstream"))
_GEOMETRY_RELATIVE_TOLERANCE = 1e-10
_STATE_TOLERANCE = 1e-10


@dataclass(frozen=True)
class JunctionCellBoundaryFace:
    """One oriented face in a closed junction-cell boundary measure."""

    face_id: str
    boundary_type: str
    length_m: float
    outward_normal_azimuth_degrees: float
    branch_id: str | None = None
    branch_role: str | None = None

    def __post_init__(self) -> None:
        length = float(self.length_m)
        azimuth = float(self.outward_normal_azimuth_degrees)
        branch_face = self.boundary_type == "branch_opening"
        if (
            not isinstance(self.face_id, str)
            or not self.face_id.strip()
            or self.boundary_type not in _BOUNDARY_TYPES
            or not math.isfinite(length)
            or length <= 0.0
            or not math.isfinite(azimuth)
            or not 0.0 <= azimuth < 360.0
            or (
                branch_face
                and (
                    not isinstance(self.branch_id, str)
                    or not self.branch_id.strip()
                    or self.branch_role not in _BRANCH_ROLES
                )
            )
            or (
                not branch_face
                and (self.branch_id is not None or self.branch_role is not None)
            )
        ):
            raise ValueError("shallow_water_junction_cell_face_invalid")
        object.__setattr__(self, "length_m", length)
        object.__setattr__(
            self, "outward_normal_azimuth_degrees", azimuth
        )

    @property
    def outward_unit_normal_east_north(self) -> tuple[float, float]:
        angle = math.radians(self.outward_normal_azimuth_degrees)
        return math.sin(angle), math.cos(angle)

    @property
    def unit_tangent_east_north(self) -> tuple[float, float]:
        normal_east, normal_north = self.outward_unit_normal_east_north
        return -normal_north, normal_east

    def as_dict(self) -> dict[str, object]:
        return {
            "face_id": self.face_id,
            "boundary_type": self.boundary_type,
            "length_m": self.length_m,
            "outward_normal_azimuth_degrees": (
                self.outward_normal_azimuth_degrees
            ),
            "outward_unit_normal_east_north": list(
                self.outward_unit_normal_east_north
            ),
            "branch_id": self.branch_id,
            "branch_role": self.branch_role,
        }


@dataclass(frozen=True)
class ShallowWaterJunctionCellGeometry:
    """Plan area and closed oriented boundary of one lumped 2D cell."""

    junction_id: str
    plan_area_m2: float
    bed_elevation_m: float
    faces: tuple[JunctionCellBoundaryFace, ...]
    provenance_id: str

    def __post_init__(self) -> None:
        area = float(self.plan_area_m2)
        bed = float(self.bed_elevation_m)
        faces = tuple(self.faces)
        branch_faces = tuple(
            value for value in faces if value.boundary_type == "branch_opening"
        )
        wall_faces = tuple(
            value for value in faces if value.boundary_type == "solid_wall"
        )
        upstream = tuple(
            value for value in branch_faces if value.branch_role == "upstream"
        )
        downstream = tuple(
            value
            for value in branch_faces
            if value.branch_role == "downstream"
        )
        if (
            not isinstance(self.junction_id, str)
            or not self.junction_id.strip()
            or not math.isfinite(area)
            or area <= 0.0
            or not math.isfinite(bed)
            or len(faces) < 4
            or any(
                not isinstance(value, JunctionCellBoundaryFace)
                for value in faces
            )
            or len({value.face_id for value in faces}) != len(faces)
            or len(upstream) < 2
            or len(downstream) != 1
            or not wall_faces
            or len({value.branch_id for value in branch_faces})
            != len(branch_faces)
            or not isinstance(self.provenance_id, str)
            or not self.provenance_id.strip()
        ):
            raise ValueError("shallow_water_junction_cell_geometry_invalid")
        closure_east, closure_north = _boundary_closure_vector(faces)
        perimeter = sum(value.length_m for value in faces)
        tolerance = max(1e-12, perimeter * _GEOMETRY_RELATIVE_TOLERANCE)
        if math.hypot(closure_east, closure_north) > tolerance:
            raise ValueError(
                "shallow_water_junction_cell_boundary_not_closed"
            )
        object.__setattr__(self, "plan_area_m2", area)
        object.__setattr__(self, "bed_elevation_m", bed)
        object.__setattr__(self, "faces", faces)

    @property
    def branch_faces(self) -> tuple[JunctionCellBoundaryFace, ...]:
        return tuple(
            value
            for value in self.faces
            if value.boundary_type == "branch_opening"
        )

    @property
    def wall_faces(self) -> tuple[JunctionCellBoundaryFace, ...]:
        return tuple(
            value
            for value in self.faces
            if value.boundary_type == "solid_wall"
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
    def perimeter_m(self) -> float:
        return sum(value.length_m for value in self.faces)

    @property
    def closure_residual_east_north_m(self) -> tuple[float, float]:
        return _boundary_closure_vector(self.faces)

    def as_dict(self) -> dict[str, object]:
        closure = self.closure_residual_east_north_m
        return {
            "schema": SHALLOW_WATER_JUNCTION_CELL_GEOMETRY_SCHEMA,
            "junction_id": self.junction_id,
            "plan_area_m2": self.plan_area_m2,
            "bed_elevation_m": self.bed_elevation_m,
            "faces": [value.as_dict() for value in self.faces],
            "perimeter_m": self.perimeter_m,
            "closure_residual_east_north_m": list(closure),
            "closure_residual_magnitude_m": math.hypot(*closure),
            "upstream_branch_ids": list(self.upstream_branch_ids),
            "downstream_branch_id": self.downstream_branch_id,
            "provenance_id": self.provenance_id,
            "boundary_measure_closed": True,
            "polygon_vertex_topology_verified": False,
        }


@dataclass(frozen=True)
class ShallowWaterJunctionCellState:
    """Cell-integrated water volume and horizontal momenta per density."""

    volume_m3: float
    momentum_east_m4s: float
    momentum_north_m4s: float

    def __post_init__(self) -> None:
        volume = float(self.volume_m3)
        east = float(self.momentum_east_m4s)
        north = float(self.momentum_north_m4s)
        if (
            not math.isfinite(volume)
            or volume <= 0.0
            or not math.isfinite(east)
            or not math.isfinite(north)
        ):
            raise ValueError("shallow_water_junction_cell_state_invalid")
        object.__setattr__(self, "volume_m3", volume)
        object.__setattr__(self, "momentum_east_m4s", east)
        object.__setattr__(self, "momentum_north_m4s", north)

    @property
    def velocity_east_mps(self) -> float:
        return self.momentum_east_m4s / self.volume_m3

    @property
    def velocity_north_mps(self) -> float:
        return self.momentum_north_m4s / self.volume_m3

    def depth_m(self, geometry: ShallowWaterJunctionCellGeometry) -> float:
        return self.volume_m3 / geometry.plan_area_m2

    def free_surface_elevation_m(
        self, geometry: ShallowWaterJunctionCellGeometry
    ) -> float:
        return geometry.bed_elevation_m + self.depth_m(geometry)

    def as_dict(
        self, geometry: ShallowWaterJunctionCellGeometry
    ) -> dict[str, object]:
        return {
            "volume_m3": self.volume_m3,
            "momentum_east_north_m4s": [
                self.momentum_east_m4s,
                self.momentum_north_m4s,
            ],
            "velocity_east_north_mps": [
                self.velocity_east_mps,
                self.velocity_north_mps,
            ],
            "depth_m": self.depth_m(geometry),
            "free_surface_elevation_m": self.free_surface_elevation_m(
                geometry
            ),
        }


@dataclass(frozen=True)
class JunctionCellOpeningFlux:
    face_id: str
    branch_id: str
    branch_role: str
    minimum_signal_speed_mps: float
    maximum_signal_speed_mps: float
    wave_regime: str
    outward_mass_flux_m3s: float
    outward_normal_momentum_flux_m4s2: float
    outward_tangential_momentum_flux_m4s2: float
    outward_momentum_flux_east_m4s2: float
    outward_momentum_flux_north_m4s2: float
    cell_depth_m: float
    exterior_depth_m: float
    cell_normal_velocity_mps: float
    exterior_normal_velocity_mps: float

    def as_dict(self) -> dict[str, object]:
        return {
            "face_id": self.face_id,
            "branch_id": self.branch_id,
            "branch_role": self.branch_role,
            "minimum_signal_speed_mps": self.minimum_signal_speed_mps,
            "maximum_signal_speed_mps": self.maximum_signal_speed_mps,
            "wave_regime": self.wave_regime,
            "outward_mass_flux_m3s": self.outward_mass_flux_m3s,
            "outward_normal_momentum_flux_m4s2": (
                self.outward_normal_momentum_flux_m4s2
            ),
            "outward_tangential_momentum_flux_m4s2": (
                self.outward_tangential_momentum_flux_m4s2
            ),
            "outward_momentum_flux_east_north_m4s2": [
                self.outward_momentum_flux_east_m4s2,
                self.outward_momentum_flux_north_m4s2,
            ],
            "cell_depth_m": self.cell_depth_m,
            "exterior_depth_m": self.exterior_depth_m,
            "cell_normal_velocity_mps": self.cell_normal_velocity_mps,
            "exterior_normal_velocity_mps": (
                self.exterior_normal_velocity_mps
            ),
        }


@dataclass(frozen=True)
class JunctionCellWallPressureFlux:
    face_id: str
    outward_pressure_flux_east_m4s2: float
    outward_pressure_flux_north_m4s2: float

    def as_dict(self) -> dict[str, object]:
        return {
            "face_id": self.face_id,
            "outward_pressure_flux_east_north_m4s2": [
                self.outward_pressure_flux_east_m4s2,
                self.outward_pressure_flux_north_m4s2,
            ],
        }


@dataclass(frozen=True)
class ShallowWaterJunctionCellStep:
    geometry: ShallowWaterJunctionCellGeometry
    state_before: ShallowWaterJunctionCellState
    state_after: ShallowWaterJunctionCellState
    opening_fluxes: tuple[JunctionCellOpeningFlux, ...]
    wall_pressure_fluxes: tuple[JunctionCellWallPressureFlux, ...]
    timestep_seconds: float
    maximum_stable_timestep_seconds: float
    maximum_courant_number: float
    net_outward_opening_mass_flux_m3s: float
    mass_ledger_error_m3: float
    opening_momentum_flux_east_m4s2: float
    opening_momentum_flux_north_m4s2: float
    wall_pressure_flux_east_m4s2: float
    wall_pressure_flux_north_m4s2: float
    momentum_ledger_error_east_m4s: float
    momentum_ledger_error_north_m4s: float
    diagnostic_only: bool = True

    @property
    def momentum_ledger_error_magnitude_m4s(self) -> float:
        return math.hypot(
            self.momentum_ledger_error_east_m4s,
            self.momentum_ledger_error_north_m4s,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SHALLOW_WATER_JUNCTION_CELL_STEP_SCHEMA,
            "geometry": self.geometry.as_dict(),
            "state_before": self.state_before.as_dict(self.geometry),
            "state_after": self.state_after.as_dict(self.geometry),
            "opening_fluxes": [
                value.as_dict() for value in self.opening_fluxes
            ],
            "wall_pressure_fluxes": [
                value.as_dict() for value in self.wall_pressure_fluxes
            ],
            "timestep_seconds": self.timestep_seconds,
            "maximum_stable_timestep_seconds": (
                self.maximum_stable_timestep_seconds
            ),
            "maximum_courant_number": self.maximum_courant_number,
            "mass_ledger": {
                "volume_before_m3": self.state_before.volume_m3,
                "net_outward_opening_mass_flux_m3s": (
                    self.net_outward_opening_mass_flux_m3s
                ),
                "volume_after_m3": self.state_after.volume_m3,
                "error_m3": self.mass_ledger_error_m3,
            },
            "momentum_ledger": {
                "opening_flux_east_north_m4s2": [
                    self.opening_momentum_flux_east_m4s2,
                    self.opening_momentum_flux_north_m4s2,
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
            "finite_area_cell": True,
            "finite_storage_state": True,
            "two_horizontal_momentum_components": True,
            "opening_flux_solver": "two_dimensional_rotated_HLL",
            "wall_boundary": "hydrostatic_reflective_slip",
            "stage13_inferred_reaction_used": False,
            "branch_reach_states_updated": False,
            "flat_bed_rectangular_openings_only": True,
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


def maximum_shallow_water_junction_cell_timestep_seconds(
    state: ShallowWaterJunctionCellState,
    geometry: ShallowWaterJunctionCellGeometry,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
    *,
    courant_number: float,
) -> float:
    limit = _courant_number(courant_number)
    opening_fluxes, wall_fluxes, maximum_speeds = _calculate_fluxes(
        state, geometry, upstream, downstream, junction
    )
    return _stable_timestep(
        state,
        geometry,
        opening_fluxes,
        wall_fluxes,
        maximum_speeds,
        limit,
    )


def advance_shallow_water_junction_cell(
    state: ShallowWaterJunctionCellState,
    geometry: ShallowWaterJunctionCellGeometry,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
    *,
    timestep_seconds: float,
    maximum_courant_number: float,
) -> ShallowWaterJunctionCellStep:
    timestep = float(timestep_seconds)
    limit = _courant_number(maximum_courant_number)
    if not math.isfinite(timestep) or timestep <= 0.0:
        raise ValueError("shallow_water_junction_cell_timestep_invalid")
    opening_fluxes, wall_fluxes, maximum_speeds = _calculate_fluxes(
        state, geometry, upstream, downstream, junction
    )
    stable = _stable_timestep(
        state,
        geometry,
        opening_fluxes,
        wall_fluxes,
        maximum_speeds,
        limit,
    )
    if timestep > stable * (1.0 + 1e-12):
        raise ValueError("shallow_water_junction_cell_cfl_exceeded")
    net_mass = sum(value.outward_mass_flux_m3s for value in opening_fluxes)
    opening_east = sum(
        value.outward_momentum_flux_east_m4s2
        for value in opening_fluxes
    )
    opening_north = sum(
        value.outward_momentum_flux_north_m4s2
        for value in opening_fluxes
    )
    wall_east = sum(
        value.outward_pressure_flux_east_m4s2 for value in wall_fluxes
    )
    wall_north = sum(
        value.outward_pressure_flux_north_m4s2 for value in wall_fluxes
    )
    volume_after = state.volume_m3 - timestep * net_mass
    east_after = state.momentum_east_m4s - timestep * (
        opening_east + wall_east
    )
    north_after = state.momentum_north_m4s - timestep * (
        opening_north + wall_north
    )
    if volume_after <= 0.0:
        raise FloatingPointError("shallow_water_junction_cell_drained")
    state_after = ShallowWaterJunctionCellState(
        volume_after, east_after, north_after
    )
    return ShallowWaterJunctionCellStep(
        geometry=geometry,
        state_before=state,
        state_after=state_after,
        opening_fluxes=opening_fluxes,
        wall_pressure_fluxes=wall_fluxes,
        timestep_seconds=timestep,
        maximum_stable_timestep_seconds=stable,
        maximum_courant_number=limit,
        net_outward_opening_mass_flux_m3s=net_mass,
        mass_ledger_error_m3=(
            volume_after - state.volume_m3 + timestep * net_mass
        ),
        opening_momentum_flux_east_m4s2=opening_east,
        opening_momentum_flux_north_m4s2=opening_north,
        wall_pressure_flux_east_m4s2=wall_east,
        wall_pressure_flux_north_m4s2=wall_north,
        momentum_ledger_error_east_m4s=(
            east_after
            - state.momentum_east_m4s
            + timestep * (opening_east + wall_east)
        ),
        momentum_ledger_error_north_m4s=(
            north_after
            - state.momentum_north_m4s
            + timestep * (opening_north + wall_north)
        ),
    )


def _calculate_fluxes(
    state: ShallowWaterJunctionCellState,
    geometry: ShallowWaterJunctionCellGeometry,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
) -> tuple[
    tuple[JunctionCellOpeningFlux, ...],
    tuple[JunctionCellWallPressureFlux, ...],
    tuple[float, ...],
]:
    if not isinstance(state, ShallowWaterJunctionCellState):
        raise TypeError("shallow_water_junction_cell_state_required")
    if not isinstance(geometry, ShallowWaterJunctionCellGeometry):
        raise TypeError("shallow_water_junction_cell_geometry_required")
    if not isinstance(junction, ConservativeVectorJunctionSolution):
        raise TypeError("conservative_vector_junction_solution_required")
    terminals = tuple(upstream)
    _validate_binding(geometry, terminals, downstream, junction, state)
    exterior = _exterior_states(terminals, downstream, junction)
    by_branch = {value.branch_id: value for value in exterior}
    cell_depth = state.depth_m(geometry)
    opening_fluxes = []
    maximum_speeds = []
    for face in geometry.branch_faces:
        flux = _opening_hll_flux(
            face,
            cell_depth=cell_depth,
            cell_velocity_east_mps=state.velocity_east_mps,
            cell_velocity_north_mps=state.velocity_north_mps,
            exterior=by_branch[str(face.branch_id)],
        )
        opening_fluxes.append(flux)
        maximum_speeds.append(
            max(
                abs(flux.minimum_signal_speed_mps),
                abs(flux.maximum_signal_speed_mps),
            )
        )
    pressure = 0.5 * STANDARD_GRAVITY_MPS2 * cell_depth**2
    wall_fluxes = []
    cell_celerity = math.sqrt(STANDARD_GRAVITY_MPS2 * cell_depth)
    for face in geometry.wall_faces:
        normal_east, normal_north = (
            face.outward_unit_normal_east_north
        )
        wall_fluxes.append(
            JunctionCellWallPressureFlux(
                face_id=face.face_id,
                outward_pressure_flux_east_m4s2=(
                    pressure * face.length_m * normal_east
                ),
                outward_pressure_flux_north_m4s2=(
                    pressure * face.length_m * normal_north
                ),
            )
        )
        cell_normal_velocity = (
            state.velocity_east_mps * normal_east
            + state.velocity_north_mps * normal_north
        )
        maximum_speeds.append(abs(cell_normal_velocity) + cell_celerity)
    return tuple(opening_fluxes), tuple(wall_fluxes), tuple(maximum_speeds)


def _validate_binding(
    geometry: ShallowWaterJunctionCellGeometry,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
    state: ShallowWaterJunctionCellState,
) -> None:
    contract = junction.contract
    hydraulic = junction.hydraulic_solution
    if (
        geometry.junction_id != contract.junction_id
        or geometry.upstream_branch_ids != contract.upstream_branch_ids
        or geometry.downstream_branch_id != contract.downstream_branch_id
        or tuple(value.branch_id for value in upstream)
        != contract.upstream_branch_ids
        or downstream.branch_id != contract.downstream_branch_id
    ):
        raise ValueError("shallow_water_junction_cell_branch_mismatch")
    surface = hydraulic.common_free_surface_elevation_m
    terminals = (*upstream, downstream)
    boundary_states = (
        *tuple(value.state for value in hydraulic.upstream_boundaries),
        hydraulic.downstream_boundary.state,
    )
    azimuths = (
        *contract.upstream_flow_azimuth_degrees,
        contract.downstream_flow_azimuth_degrees,
    )
    roles = (*(("upstream",) * len(upstream)), "downstream")
    face_by_branch = {
        str(value.branch_id): value for value in geometry.branch_faces
    }
    for terminal, boundary, azimuth, role in zip(
        terminals, boundary_states, azimuths, roles, strict=True
    ):
        face = face_by_branch[terminal.branch_id]
        if (
            terminal.section.side_slope_horizontal_per_vertical != 0.0
            or abs(terminal.section.bottom_width_m - face.length_m)
            > _STATE_TOLERANCE
        ):
            raise ValueError(
                "shallow_water_junction_cell_rectangular_opening_required"
            )
        if abs(terminal.bed_elevation_m - geometry.bed_elevation_m) > (
            _STATE_TOLERANCE
        ):
            raise ValueError("shallow_water_junction_cell_flat_bed_required")
        depth = boundary.area_m2 / face.length_m
        if (
            depth <= 0.0
            or abs(terminal.bed_elevation_m + depth - surface)
            > _STATE_TOLERANCE
            or boundary.discharge_m3s < -_STATE_TOLERANCE
        ):
            raise ValueError(
                "shallow_water_junction_cell_boundary_state_not_supported"
            )
        expected_normal = (
            (azimuth + 180.0) % 360.0 if role == "upstream" else azimuth
        )
        if (
            _azimuth_difference(
                face.outward_normal_azimuth_degrees, expected_normal
            )
            > 1e-8
            or face.branch_role != role
        ):
            raise ValueError(
                "shallow_water_junction_cell_face_orientation_mismatch"
            )


def _exterior_states(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    junction: ConservativeVectorJunctionSolution,
) -> tuple[_ExteriorState, ...]:
    hydraulic = junction.hydraulic_solution
    contract = junction.contract
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


def _opening_hll_flux(
    face: JunctionCellBoundaryFace,
    *,
    cell_depth: float,
    cell_velocity_east_mps: float,
    cell_velocity_north_mps: float,
    exterior: _ExteriorState,
) -> JunctionCellOpeningFlux:
    normal_east, normal_north = face.outward_unit_normal_east_north
    tangent_east, tangent_north = face.unit_tangent_east_north
    cell_normal = (
        cell_velocity_east_mps * normal_east
        + cell_velocity_north_mps * normal_north
    )
    cell_tangential = (
        cell_velocity_east_mps * tangent_east
        + cell_velocity_north_mps * tangent_north
    )
    exterior_normal = (
        exterior.velocity_east_mps * normal_east
        + exterior.velocity_north_mps * normal_north
    )
    exterior_tangential = (
        exterior.velocity_east_mps * tangent_east
        + exterior.velocity_north_mps * tangent_north
    )
    values, minimum_speed, maximum_speed, regime = _hll_rotated_flux(
        cell_depth,
        cell_normal,
        cell_tangential,
        exterior.depth_m,
        exterior_normal,
        exterior_tangential,
    )
    length = face.length_m
    normal_momentum = values[1] * length
    tangential_momentum = values[2] * length
    return JunctionCellOpeningFlux(
        face_id=face.face_id,
        branch_id=exterior.branch_id,
        branch_role=exterior.branch_role,
        minimum_signal_speed_mps=minimum_speed,
        maximum_signal_speed_mps=maximum_speed,
        wave_regime=regime,
        outward_mass_flux_m3s=values[0] * length,
        outward_normal_momentum_flux_m4s2=normal_momentum,
        outward_tangential_momentum_flux_m4s2=tangential_momentum,
        outward_momentum_flux_east_m4s2=(
            normal_momentum * normal_east
            + tangential_momentum * tangent_east
        ),
        outward_momentum_flux_north_m4s2=(
            normal_momentum * normal_north
            + tangential_momentum * tangent_north
        ),
        cell_depth_m=cell_depth,
        exterior_depth_m=exterior.depth_m,
        cell_normal_velocity_mps=cell_normal,
        exterior_normal_velocity_mps=exterior_normal,
    )


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
    minimum_speed = min(
        left_normal_velocity - left_celerity,
        right_normal_velocity - right_celerity,
    )
    maximum_speed = max(
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
    left_flux = _rotated_physical_flux(
        left_depth, left_normal_velocity, left_tangential_velocity
    )
    right_flux = _rotated_physical_flux(
        right_depth, right_normal_velocity, right_tangential_velocity
    )
    if minimum_speed >= 0.0:
        return left_flux, minimum_speed, maximum_speed, "outward_upwind"
    if maximum_speed <= 0.0:
        return right_flux, minimum_speed, maximum_speed, "inward_upwind"
    denominator = maximum_speed - minimum_speed
    flux = tuple(
        (
            maximum_speed * left_value
            - minimum_speed * right_value
            + minimum_speed
            * maximum_speed
            * (right_state_value - left_state_value)
        )
        / denominator
        for left_value, right_value, left_state_value, right_state_value in zip(
            left_flux,
            right_flux,
            left_state,
            right_state,
            strict=True,
        )
    )
    return flux, minimum_speed, maximum_speed, "hll_mixed"


def _rotated_physical_flux(
    depth: float,
    normal_velocity: float,
    tangential_velocity: float,
) -> tuple[float, float, float]:
    normal_discharge = depth * normal_velocity
    return (
        normal_discharge,
        normal_discharge * normal_velocity
        + 0.5 * STANDARD_GRAVITY_MPS2 * depth**2,
        normal_discharge * tangential_velocity,
    )


def _stable_timestep(
    state: ShallowWaterJunctionCellState,
    geometry: ShallowWaterJunctionCellGeometry,
    opening_fluxes: tuple[JunctionCellOpeningFlux, ...],
    wall_fluxes: tuple[JunctionCellWallPressureFlux, ...],
    maximum_speeds: tuple[float, ...],
    courant_number: float,
) -> float:
    faces = (*geometry.branch_faces, *geometry.wall_faces)
    if len(wall_fluxes) != len(geometry.wall_faces):
        raise RuntimeError("shallow_water_junction_cell_wall_flux_mismatch")
    face_spectral_sum = sum(
        face.length_m * speed
        for face, speed in zip(
            faces, maximum_speeds, strict=True
        )
    )
    if face_spectral_sum <= 0.0:
        raise RuntimeError("shallow_water_junction_cell_timestep_undefined")
    wave_limit = (
        courant_number * geometry.plan_area_m2 / face_spectral_sum
    )
    net_outward = sum(
        value.outward_mass_flux_m3s for value in opening_fluxes
    )
    if net_outward > 0.0:
        drain_limit = courant_number * state.volume_m3 / net_outward
        return min(wave_limit, drain_limit)
    return wave_limit


def _boundary_closure_vector(
    faces: tuple[JunctionCellBoundaryFace, ...],
) -> tuple[float, float]:
    return (
        sum(
            value.length_m * value.outward_unit_normal_east_north[0]
            for value in faces
        ),
        sum(
            value.length_m * value.outward_unit_normal_east_north[1]
            for value in faces
        ),
    )


def _courant_number(value: float) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0.0 < result <= 1.0:
        raise ValueError("shallow_water_junction_cell_courant_invalid")
    return result


def _azimuth_difference(left: float, right: float) -> float:
    return abs((right - left + 180.0) % 360.0 - 180.0)
