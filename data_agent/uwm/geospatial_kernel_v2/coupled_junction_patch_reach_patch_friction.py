"""Spatially supported 2D patch friction around the Stage 19 split step."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .conservative_vector_junction import ConservativeVectorJunctionContract
from .coupled_junction_patch_reach_sources import (
    SourceSplitCoupledJunctionPatchReachStep,
    advance_source_split_coupled_junction_patch_reaches,
    maximum_source_split_coupled_junction_patch_timestep_seconds,
)
from .dynamic_wave_coupled import FixedDynamicWaveBoundary
from .dynamic_wave_flux import STANDARD_GRAVITY_MPS2, PrismaticDynamicWaveState
from .dynamic_wave_junction import DynamicWaveNetworkReach
from .shallow_water_junction_patch import (
    JunctionPatchCellState,
    ShallowWaterJunctionPatchGeometry,
    ShallowWaterJunctionPatchState,
)


JUNCTION_PATCH_MANNING_FIELD_SCHEMA = (
    "gwm.geospatial_kernel.junction_patch_manning_field.v1"
)
JUNCTION_PATCH_MANNING_STEP_SCHEMA = (
    "gwm.geospatial_kernel.junction_patch_manning_step.v1"
)
PATCH_FRICTION_SOURCE_SPLIT_STEP_SCHEMA = (
    "gwm.geospatial_kernel.patch_friction_source_split_step.v1"
)
_SUPPORT_TOLERANCE_M2 = 1e-9
_CFL_ITERATION_COUNT = 12


@dataclass(frozen=True)
class JunctionPatchCellManningRoughness:
    cell_id: str
    manning_n: float
    support_area_m2: float
    provenance_id: str

    def __post_init__(self) -> None:
        roughness = float(self.manning_n)
        area = float(self.support_area_m2)
        if (
            not isinstance(self.cell_id, str)
            or not self.cell_id.strip()
            or not math.isfinite(roughness)
            or roughness <= 0.0
            or not math.isfinite(area)
            or area <= 0.0
            or not isinstance(self.provenance_id, str)
            or not self.provenance_id.strip()
        ):
            raise ValueError("junction_patch_cell_manning_roughness_invalid")
        object.__setattr__(self, "manning_n", roughness)
        object.__setattr__(self, "support_area_m2", area)

    def as_dict(self) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "manning_n": self.manning_n,
            "support_area_m2": self.support_area_m2,
            "provenance_id": self.provenance_id,
        }


@dataclass(frozen=True)
class JunctionPatchManningRoughnessField:
    junction_id: str
    geometry_provenance_id: str
    cells: tuple[JunctionPatchCellManningRoughness, ...]
    provenance_id: str

    def __post_init__(self) -> None:
        cells = tuple(self.cells)
        if (
            not isinstance(self.junction_id, str)
            or not self.junction_id.strip()
            or not isinstance(self.geometry_provenance_id, str)
            or not self.geometry_provenance_id.strip()
            or len(cells) < 2
            or any(
                not isinstance(value, JunctionPatchCellManningRoughness)
                for value in cells
            )
            or len({value.cell_id for value in cells}) != len(cells)
            or not isinstance(self.provenance_id, str)
            or not self.provenance_id.strip()
        ):
            raise ValueError("junction_patch_manning_roughness_field_invalid")
        object.__setattr__(self, "cells", cells)

    @property
    def cell_by_id(self) -> dict[str, JunctionPatchCellManningRoughness]:
        return {value.cell_id: value for value in self.cells}

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": JUNCTION_PATCH_MANNING_FIELD_SCHEMA,
            "junction_id": self.junction_id,
            "geometry_provenance_id": self.geometry_provenance_id,
            "cells": [value.as_dict() for value in self.cells],
            "provenance_id": self.provenance_id,
            "spatial_support": "exact_junction_patch_cell_polygon",
            "roughness_is_calibrated": False,
        }


@dataclass(frozen=True)
class JunctionPatchCellManningTrace:
    cell_id: str
    manning_n: float
    support_area_m2: float
    depth_m: float
    speed_before_mps: float
    damping_rate_per_s: float
    damping_factor: float
    momentum_before_east_m4s: float
    momentum_before_north_m4s: float
    momentum_after_east_m4s: float
    momentum_after_north_m4s: float
    friction_impulse_east_m4s: float
    friction_impulse_north_m4s: float
    kinetic_energy_before_m5s2: float
    kinetic_energy_after_m5s2: float

    @property
    def kinetic_energy_dissipation_m5s2(self) -> float:
        return (
            self.kinetic_energy_before_m5s2
            - self.kinetic_energy_after_m5s2
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "cell_id": self.cell_id,
            "manning_n": self.manning_n,
            "support_area_m2": self.support_area_m2,
            "depth_m": self.depth_m,
            "speed_before_mps": self.speed_before_mps,
            "damping_rate_per_s": self.damping_rate_per_s,
            "damping_factor": self.damping_factor,
            "momentum_before_east_north_m4s": [
                self.momentum_before_east_m4s,
                self.momentum_before_north_m4s,
            ],
            "momentum_after_east_north_m4s": [
                self.momentum_after_east_m4s,
                self.momentum_after_north_m4s,
            ],
            "friction_impulse_east_north_m4s": [
                self.friction_impulse_east_m4s,
                self.friction_impulse_north_m4s,
            ],
            "kinetic_energy_before_m5s2": (
                self.kinetic_energy_before_m5s2
            ),
            "kinetic_energy_after_m5s2": self.kinetic_energy_after_m5s2,
            "kinetic_energy_dissipation_m5s2": (
                self.kinetic_energy_dissipation_m5s2
            ),
        }


@dataclass(frozen=True)
class JunctionPatchManningFrictionStep:
    geometry: ShallowWaterJunctionPatchGeometry
    roughness_field: JunctionPatchManningRoughnessField
    state_before: ShallowWaterJunctionPatchState
    state_after: ShallowWaterJunctionPatchState
    cell_traces: tuple[JunctionPatchCellManningTrace, ...]
    timestep_seconds: float
    total_volume_before_m3: float
    total_volume_after_m3: float
    volume_ledger_error_m3: float
    momentum_before_east_m4s: float
    momentum_before_north_m4s: float
    friction_impulse_east_m4s: float
    friction_impulse_north_m4s: float
    momentum_after_east_m4s: float
    momentum_after_north_m4s: float
    momentum_ledger_error_east_m4s: float
    momentum_ledger_error_north_m4s: float
    kinetic_energy_before_m5s2: float
    kinetic_energy_after_m5s2: float
    kinetic_energy_dissipation_m5s2: float
    diagnostic_only: bool = True

    @property
    def momentum_ledger_error_magnitude_m4s(self) -> float:
        return math.hypot(
            self.momentum_ledger_error_east_m4s,
            self.momentum_ledger_error_north_m4s,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": JUNCTION_PATCH_MANNING_STEP_SCHEMA,
            "geometry": self.geometry.as_dict(),
            "roughness_field": self.roughness_field.as_dict(),
            "state_before": self.state_before.as_dict(self.geometry),
            "state_after": self.state_after.as_dict(self.geometry),
            "cell_traces": [value.as_dict() for value in self.cell_traces],
            "timestep_seconds": self.timestep_seconds,
            "mass_ledger": {
                "volume_before_m3": self.total_volume_before_m3,
                "volume_after_m3": self.total_volume_after_m3,
                "error_m3": self.volume_ledger_error_m3,
            },
            "momentum_ledger": {
                "momentum_before_east_north_m4s": [
                    self.momentum_before_east_m4s,
                    self.momentum_before_north_m4s,
                ],
                "friction_impulse_east_north_m4s": [
                    self.friction_impulse_east_m4s,
                    self.friction_impulse_north_m4s,
                ],
                "momentum_after_east_north_m4s": [
                    self.momentum_after_east_m4s,
                    self.momentum_after_north_m4s,
                ],
                "error_east_north_m4s": [
                    self.momentum_ledger_error_east_m4s,
                    self.momentum_ledger_error_north_m4s,
                ],
                "error_magnitude_m4s": (
                    self.momentum_ledger_error_magnitude_m4s
                ),
            },
            "kinetic_energy_integral": {
                "before_m5s2": self.kinetic_energy_before_m5s2,
                "after_m5s2": self.kinetic_energy_after_m5s2,
                "dissipation_m5s2": self.kinetic_energy_dissipation_m5s2,
            },
            "manning_hydraulic_radius_rule": "local_depth_wide_cell",
            "semi_implicit_vector_drag": True,
            "flow_direction_preserved": True,
            "rotation_invariant": True,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class PatchFrictionSourceSplitStep:
    patch_state_after: ShallowWaterJunctionPatchState
    upstream_states: tuple[PrismaticDynamicWaveState, ...]
    downstream_state: PrismaticDynamicWaveState
    patch_friction_first: JunctionPatchManningFrictionStep
    reach_source_split_step: SourceSplitCoupledJunctionPatchReachStep
    patch_friction_second: JunctionPatchManningFrictionStep
    timestep_seconds: float
    maximum_stable_timestep_seconds: float
    maximum_courant_number: float
    lateral_momentum_convention: str
    total_volume_before_m3: float
    lateral_volume_change_m3: float
    external_boundary_volume_change_m3: float
    total_volume_after_m3: float
    total_volume_ledger_error_m3: float
    geographic_momentum_before_east_m4s: float
    geographic_momentum_before_north_m4s: float
    lateral_momentum_change_east_m4s: float
    lateral_momentum_change_north_m4s: float
    reach_friction_momentum_change_east_m4s: float
    reach_friction_momentum_change_north_m4s: float
    patch_friction_momentum_change_east_m4s: float
    patch_friction_momentum_change_north_m4s: float
    external_boundary_momentum_impulse_east_m4s: float
    external_boundary_momentum_impulse_north_m4s: float
    patch_solid_wall_fluid_impulse_east_m4s: float
    patch_solid_wall_fluid_impulse_north_m4s: float
    transition_wall_fluid_impulse_east_m4s: float
    transition_wall_fluid_impulse_north_m4s: float
    geographic_momentum_after_east_m4s: float
    geographic_momentum_after_north_m4s: float
    geographic_momentum_ledger_error_east_m4s: float
    geographic_momentum_ledger_error_north_m4s: float
    patch_kinetic_energy_dissipation_m5s2: float
    minimum_reach_area_m2: float
    minimum_patch_cell_volume_m3: float
    diagnostic_only: bool = True

    @property
    def geographic_momentum_ledger_error_magnitude_m4s(self) -> float:
        return math.hypot(
            self.geographic_momentum_ledger_error_east_m4s,
            self.geographic_momentum_ledger_error_north_m4s,
        )

    @property
    def patch_friction_momentum_change_magnitude_m4s(self) -> float:
        return math.hypot(
            self.patch_friction_momentum_change_east_m4s,
            self.patch_friction_momentum_change_north_m4s,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PATCH_FRICTION_SOURCE_SPLIT_STEP_SCHEMA,
            "patch_state_after": self.patch_state_after.as_dict(
                self.patch_friction_first.geometry
            ),
            "upstream_states": [
                _state_dict(value) for value in self.upstream_states
            ],
            "downstream_state": _state_dict(self.downstream_state),
            "patch_friction_first": self.patch_friction_first.as_dict(),
            "reach_source_split_step": self.reach_source_split_step.as_dict(),
            "patch_friction_second": self.patch_friction_second.as_dict(),
            "timestep_seconds": self.timestep_seconds,
            "maximum_stable_timestep_seconds": (
                self.maximum_stable_timestep_seconds
            ),
            "maximum_courant_number": self.maximum_courant_number,
            "lateral_momentum_convention": self.lateral_momentum_convention,
            "mass_ledger": {
                "total_volume_before_m3": self.total_volume_before_m3,
                "lateral_volume_change_m3": self.lateral_volume_change_m3,
                "external_boundary_volume_change_m3": (
                    self.external_boundary_volume_change_m3
                ),
                "total_volume_after_m3": self.total_volume_after_m3,
                "error_m3": self.total_volume_ledger_error_m3,
            },
            "geographic_momentum_ledger": {
                "momentum_before_east_north_m4s": [
                    self.geographic_momentum_before_east_m4s,
                    self.geographic_momentum_before_north_m4s,
                ],
                "lateral_change_east_north_m4s": [
                    self.lateral_momentum_change_east_m4s,
                    self.lateral_momentum_change_north_m4s,
                ],
                "reach_friction_change_east_north_m4s": [
                    self.reach_friction_momentum_change_east_m4s,
                    self.reach_friction_momentum_change_north_m4s,
                ],
                "patch_friction_change_east_north_m4s": [
                    self.patch_friction_momentum_change_east_m4s,
                    self.patch_friction_momentum_change_north_m4s,
                ],
                "external_boundary_impulse_east_north_m4s": [
                    self.external_boundary_momentum_impulse_east_m4s,
                    self.external_boundary_momentum_impulse_north_m4s,
                ],
                "patch_solid_wall_fluid_impulse_east_north_m4s": [
                    self.patch_solid_wall_fluid_impulse_east_m4s,
                    self.patch_solid_wall_fluid_impulse_north_m4s,
                ],
                "transition_wall_fluid_impulse_east_north_m4s": [
                    self.transition_wall_fluid_impulse_east_m4s,
                    self.transition_wall_fluid_impulse_north_m4s,
                ],
                "momentum_after_east_north_m4s": [
                    self.geographic_momentum_after_east_m4s,
                    self.geographic_momentum_after_north_m4s,
                ],
                "error_east_north_m4s": [
                    self.geographic_momentum_ledger_error_east_m4s,
                    self.geographic_momentum_ledger_error_north_m4s,
                ],
                "error_magnitude_m4s": (
                    self.geographic_momentum_ledger_error_magnitude_m4s
                ),
            },
            "patch_kinetic_energy_dissipation_m5s2": (
                self.patch_kinetic_energy_dissipation_m5s2
            ),
            "minimum_reach_area_m2": self.minimum_reach_area_m2,
            "minimum_patch_cell_volume_m3": self.minimum_patch_cell_volume_m3,
            "source_split_order": (
                "patch_friction_half,(lateral_half+reach_friction_half),"
                "stage18_patch_reach_conservative_core_full,"
                "(reach_friction_half+lateral_half),patch_friction_half"
            ),
            "patch_and_reach_sources_act_on_disjoint_state_partitions": True,
            "spatially_supported_patch_roughness": True,
            "stage19_reach_source_split_preserved": True,
            "stage18_transition_reaction_preserved": True,
            "persistent_transverse_momentum_reservoir": False,
            "public_validation_completed": False,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


def apply_junction_patch_manning_friction(
    state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    roughness_field: JunctionPatchManningRoughnessField,
    *,
    timestep_seconds: float,
) -> JunctionPatchManningFrictionStep:
    timestep = float(timestep_seconds)
    if not math.isfinite(timestep) or timestep <= 0.0:
        raise ValueError("junction_patch_manning_timestep_invalid")
    _validate_roughness_binding(state, geometry, roughness_field)
    areas = geometry.cell_areas_m2
    roughness = roughness_field.cell_by_id
    after_cells = []
    traces = []
    for before in state.cells:
        support = roughness[before.cell_id]
        depth = before.depth_m(areas[before.cell_id])
        speed = math.hypot(
            before.velocity_east_mps, before.velocity_north_mps
        )
        damping_rate = (
            STANDARD_GRAVITY_MPS2
            * support.manning_n**2
            * speed
            / depth ** (4.0 / 3.0)
        )
        damping_factor = 1.0 / (1.0 + timestep * damping_rate)
        after = JunctionPatchCellState(
            before.cell_id,
            before.volume_m3,
            before.momentum_east_m4s * damping_factor,
            before.momentum_north_m4s * damping_factor,
        )
        before_energy = _cell_kinetic_energy(before)
        after_energy = _cell_kinetic_energy(after)
        after_cells.append(after)
        traces.append(
            JunctionPatchCellManningTrace(
                cell_id=before.cell_id,
                manning_n=support.manning_n,
                support_area_m2=support.support_area_m2,
                depth_m=depth,
                speed_before_mps=speed,
                damping_rate_per_s=damping_rate,
                damping_factor=damping_factor,
                momentum_before_east_m4s=before.momentum_east_m4s,
                momentum_before_north_m4s=before.momentum_north_m4s,
                momentum_after_east_m4s=after.momentum_east_m4s,
                momentum_after_north_m4s=after.momentum_north_m4s,
                friction_impulse_east_m4s=(
                    after.momentum_east_m4s - before.momentum_east_m4s
                ),
                friction_impulse_north_m4s=(
                    after.momentum_north_m4s - before.momentum_north_m4s
                ),
                kinetic_energy_before_m5s2=before_energy,
                kinetic_energy_after_m5s2=after_energy,
            )
        )
    state_after = ShallowWaterJunctionPatchState(tuple(after_cells))
    east_impulse = sum(value.friction_impulse_east_m4s for value in traces)
    north_impulse = sum(value.friction_impulse_north_m4s for value in traces)
    energy_before = sum(
        value.kinetic_energy_before_m5s2 for value in traces
    )
    energy_after = sum(
        value.kinetic_energy_after_m5s2 for value in traces
    )
    return JunctionPatchManningFrictionStep(
        geometry=geometry,
        roughness_field=roughness_field,
        state_before=state,
        state_after=state_after,
        cell_traces=tuple(traces),
        timestep_seconds=timestep,
        total_volume_before_m3=state.total_volume_m3,
        total_volume_after_m3=state_after.total_volume_m3,
        volume_ledger_error_m3=(
            state_after.total_volume_m3 - state.total_volume_m3
        ),
        momentum_before_east_m4s=state.total_momentum_east_m4s,
        momentum_before_north_m4s=state.total_momentum_north_m4s,
        friction_impulse_east_m4s=east_impulse,
        friction_impulse_north_m4s=north_impulse,
        momentum_after_east_m4s=state_after.total_momentum_east_m4s,
        momentum_after_north_m4s=state_after.total_momentum_north_m4s,
        momentum_ledger_error_east_m4s=(
            state_after.total_momentum_east_m4s
            - state.total_momentum_east_m4s
            - east_impulse
        ),
        momentum_ledger_error_north_m4s=(
            state_after.total_momentum_north_m4s
            - state.total_momentum_north_m4s
            - north_impulse
        ),
        kinetic_energy_before_m5s2=energy_before,
        kinetic_energy_after_m5s2=energy_after,
        kinetic_energy_dissipation_m5s2=energy_before - energy_after,
    )


def maximum_patch_friction_source_split_timestep_seconds(
    patch_state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    roughness_field: JunctionPatchManningRoughnessField,
    contract: ConservativeVectorJunctionContract,
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    *,
    upstream_external_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_external_boundary: FixedDynamicWaveBoundary,
    lateral_momentum_convention: str,
    courant_number: float,
) -> float:
    _validate_roughness_binding(patch_state, geometry, roughness_field)
    common = {
        "upstream_external_boundaries": upstream_external_boundaries,
        "downstream_external_boundary": downstream_external_boundary,
        "lateral_momentum_convention": lateral_momentum_convention,
        "courant_number": courant_number,
    }
    candidate = maximum_source_split_coupled_junction_patch_timestep_seconds(
        patch_state,
        geometry,
        contract,
        upstream_reaches,
        downstream_reach,
        **common,
    )
    for _ in range(_CFL_ITERATION_COUNT):
        friction = apply_junction_patch_manning_friction(
            patch_state,
            geometry,
            roughness_field,
            timestep_seconds=0.5 * candidate,
        )
        allowed = maximum_source_split_coupled_junction_patch_timestep_seconds(
            friction.state_after,
            geometry,
            contract,
            upstream_reaches,
            downstream_reach,
            **common,
        )
        if candidate <= allowed:
            return candidate
        candidate = allowed * (1.0 - 1e-12)
    raise RuntimeError("patch_friction_source_split_cfl_not_converged")


def advance_patch_friction_source_split(
    patch_state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    roughness_field: JunctionPatchManningRoughnessField,
    contract: ConservativeVectorJunctionContract,
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    *,
    upstream_external_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_external_boundary: FixedDynamicWaveBoundary,
    lateral_momentum_convention: str,
    timestep_seconds: float,
    maximum_courant_number: float,
) -> PatchFrictionSourceSplitStep:
    timestep = float(timestep_seconds)
    if not math.isfinite(timestep) or timestep <= 0.0:
        raise ValueError("patch_friction_source_split_timestep_invalid")
    stable = maximum_patch_friction_source_split_timestep_seconds(
        patch_state,
        geometry,
        roughness_field,
        contract,
        upstream_reaches,
        downstream_reach,
        upstream_external_boundaries=upstream_external_boundaries,
        downstream_external_boundary=downstream_external_boundary,
        lateral_momentum_convention=lateral_momentum_convention,
        courant_number=maximum_courant_number,
    )
    if timestep > stable * (1.0 + 1e-12):
        raise ValueError("patch_friction_source_split_cfl_exceeded")
    half_timestep = 0.5 * timestep
    patch_first = apply_junction_patch_manning_friction(
        patch_state,
        geometry,
        roughness_field,
        timestep_seconds=half_timestep,
    )
    reach_sources = advance_source_split_coupled_junction_patch_reaches(
        patch_first.state_after,
        geometry,
        contract,
        upstream_reaches,
        downstream_reach,
        upstream_external_boundaries=upstream_external_boundaries,
        downstream_external_boundary=downstream_external_boundary,
        lateral_momentum_convention=lateral_momentum_convention,
        timestep_seconds=timestep,
        maximum_courant_number=maximum_courant_number,
    )
    patch_core_after = (
        reach_sources.conservative_core_step.junction_patch_step.state_after
    )
    patch_second = apply_junction_patch_manning_friction(
        patch_core_after,
        geometry,
        roughness_field,
        timestep_seconds=half_timestep,
    )
    reaches_before = (*upstream_reaches, downstream_reach)
    reaches_after = (
        *reach_sources.upstream_states,
        reach_sources.downstream_state,
    )
    tangents = _branch_tangents(contract)
    lengths = tuple(value.cell_length_m for value in reaches_before)
    momentum_before = _geographic_momentum(
        tuple(value.state for value in reaches_before),
        lengths,
        tangents,
        patch_state,
    )
    momentum_after = _geographic_momentum(
        reaches_after,
        lengths,
        tangents,
        patch_second.state_after,
    )
    patch_friction = (
        patch_first.friction_impulse_east_m4s
        + patch_second.friction_impulse_east_m4s,
        patch_first.friction_impulse_north_m4s
        + patch_second.friction_impulse_north_m4s,
    )
    expected = (
        reach_sources.lateral_momentum_change_east_m4s
        + reach_sources.friction_momentum_change_east_m4s
        + patch_friction[0]
        + reach_sources.external_boundary_momentum_impulse_east_m4s
        + reach_sources.patch_solid_wall_fluid_impulse_east_m4s
        + reach_sources.transition_wall_fluid_impulse_east_m4s,
        reach_sources.lateral_momentum_change_north_m4s
        + reach_sources.friction_momentum_change_north_m4s
        + patch_friction[1]
        + reach_sources.external_boundary_momentum_impulse_north_m4s
        + reach_sources.patch_solid_wall_fluid_impulse_north_m4s
        + reach_sources.transition_wall_fluid_impulse_north_m4s,
    )
    volume_before = patch_state.total_volume_m3 + sum(
        _state_volume(reach.state, reach.cell_length_m)
        for reach in reaches_before
    )
    volume_after = patch_second.state_after.total_volume_m3 + sum(
        _state_volume(state, length)
        for state, length in zip(reaches_after, lengths, strict=True)
    )
    return PatchFrictionSourceSplitStep(
        patch_state_after=patch_second.state_after,
        upstream_states=reach_sources.upstream_states,
        downstream_state=reach_sources.downstream_state,
        patch_friction_first=patch_first,
        reach_source_split_step=reach_sources,
        patch_friction_second=patch_second,
        timestep_seconds=timestep,
        maximum_stable_timestep_seconds=stable,
        maximum_courant_number=float(maximum_courant_number),
        lateral_momentum_convention=lateral_momentum_convention,
        total_volume_before_m3=volume_before,
        lateral_volume_change_m3=reach_sources.lateral_volume_change_m3,
        external_boundary_volume_change_m3=(
            reach_sources.external_boundary_volume_change_m3
        ),
        total_volume_after_m3=volume_after,
        total_volume_ledger_error_m3=(
            volume_after
            - volume_before
            - reach_sources.lateral_volume_change_m3
            - reach_sources.external_boundary_volume_change_m3
        ),
        geographic_momentum_before_east_m4s=momentum_before[0],
        geographic_momentum_before_north_m4s=momentum_before[1],
        lateral_momentum_change_east_m4s=(
            reach_sources.lateral_momentum_change_east_m4s
        ),
        lateral_momentum_change_north_m4s=(
            reach_sources.lateral_momentum_change_north_m4s
        ),
        reach_friction_momentum_change_east_m4s=(
            reach_sources.friction_momentum_change_east_m4s
        ),
        reach_friction_momentum_change_north_m4s=(
            reach_sources.friction_momentum_change_north_m4s
        ),
        patch_friction_momentum_change_east_m4s=patch_friction[0],
        patch_friction_momentum_change_north_m4s=patch_friction[1],
        external_boundary_momentum_impulse_east_m4s=(
            reach_sources.external_boundary_momentum_impulse_east_m4s
        ),
        external_boundary_momentum_impulse_north_m4s=(
            reach_sources.external_boundary_momentum_impulse_north_m4s
        ),
        patch_solid_wall_fluid_impulse_east_m4s=(
            reach_sources.patch_solid_wall_fluid_impulse_east_m4s
        ),
        patch_solid_wall_fluid_impulse_north_m4s=(
            reach_sources.patch_solid_wall_fluid_impulse_north_m4s
        ),
        transition_wall_fluid_impulse_east_m4s=(
            reach_sources.transition_wall_fluid_impulse_east_m4s
        ),
        transition_wall_fluid_impulse_north_m4s=(
            reach_sources.transition_wall_fluid_impulse_north_m4s
        ),
        geographic_momentum_after_east_m4s=momentum_after[0],
        geographic_momentum_after_north_m4s=momentum_after[1],
        geographic_momentum_ledger_error_east_m4s=(
            momentum_after[0] - momentum_before[0] - expected[0]
        ),
        geographic_momentum_ledger_error_north_m4s=(
            momentum_after[1] - momentum_before[1] - expected[1]
        ),
        patch_kinetic_energy_dissipation_m5s2=(
            patch_first.kinetic_energy_dissipation_m5s2
            + patch_second.kinetic_energy_dissipation_m5s2
        ),
        minimum_reach_area_m2=reach_sources.minimum_reach_area_m2,
        minimum_patch_cell_volume_m3=min(
            value.volume_m3 for value in patch_second.state_after.cells
        ),
    )


def _validate_roughness_binding(
    state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    roughness_field: JunctionPatchManningRoughnessField,
) -> None:
    if not isinstance(state, ShallowWaterJunctionPatchState):
        raise TypeError("shallow_water_junction_patch_state_required")
    if not isinstance(geometry, ShallowWaterJunctionPatchGeometry):
        raise TypeError("shallow_water_junction_patch_geometry_required")
    if not isinstance(roughness_field, JunctionPatchManningRoughnessField):
        raise TypeError("junction_patch_manning_roughness_field_required")
    geometry_ids = tuple(value.cell_id for value in geometry.cells)
    field_ids = tuple(value.cell_id for value in roughness_field.cells)
    state_ids = tuple(value.cell_id for value in state.cells)
    if (
        roughness_field.junction_id != geometry.junction_id
        or roughness_field.geometry_provenance_id != geometry.provenance_id
        or field_ids != geometry_ids
        or state_ids != geometry_ids
    ):
        raise ValueError("junction_patch_manning_spatial_binding_mismatch")
    areas = geometry.cell_areas_m2
    if any(
        abs(value.support_area_m2 - areas[value.cell_id])
        > max(_SUPPORT_TOLERANCE_M2, areas[value.cell_id] * 1e-10)
        for value in roughness_field.cells
    ):
        raise ValueError("junction_patch_manning_support_area_mismatch")


def _cell_kinetic_energy(cell: JunctionPatchCellState) -> float:
    return 0.5 * (
        cell.momentum_east_m4s**2 + cell.momentum_north_m4s**2
    ) / cell.volume_m3


def _branch_tangents(
    contract: ConservativeVectorJunctionContract,
) -> tuple[tuple[float, float], ...]:
    azimuths = (
        *contract.upstream_flow_azimuth_degrees,
        contract.downstream_flow_azimuth_degrees,
    )
    return tuple(
        (math.sin(math.radians(value)), math.cos(math.radians(value)))
        for value in azimuths
    )


def _geographic_momentum(
    states: tuple[PrismaticDynamicWaveState, ...],
    lengths: tuple[float, ...],
    tangents: tuple[tuple[float, float], ...],
    patch_state: ShallowWaterJunctionPatchState,
) -> tuple[float, float]:
    east = patch_state.total_momentum_east_m4s
    north = patch_state.total_momentum_north_m4s
    for state, length, tangent in zip(states, lengths, tangents, strict=True):
        longitudinal = sum(state.discharge_m3s) * length
        east += longitudinal * tangent[0]
        north += longitudinal * tangent[1]
    return east, north


def _state_volume(
    state: PrismaticDynamicWaveState, cell_length_m: float
) -> float:
    return sum(state.area_m2) * cell_length_m


def _state_dict(state: PrismaticDynamicWaveState) -> dict[str, object]:
    return {
        "area_m2": list(state.area_m2),
        "discharge_m3s": list(state.discharge_m3s),
    }
