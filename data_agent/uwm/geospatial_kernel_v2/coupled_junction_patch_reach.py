"""Synchronous coupling of a multi-cell 2D junction patch to 1D reaches."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .conservative_vector_junction import (
    ConservativeVectorJunctionContract,
    ConservativeVectorJunctionSolution,
    solve_conservative_vector_junction,
)
from .dynamic_wave_coupled import FixedDynamicWaveBoundary
from .dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    DynamicWaveFlux,
    PrismaticDynamicWaveState,
)
from .dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
    DynamicWaveNetworkReach,
)
from .dynamic_wave_variable_geometry import (
    VariableGeometryHydrostaticOpenStep,
    advance_variable_geometry_hydrostatic_open,
    maximum_variable_geometry_open_stable_timestep_seconds,
    variable_geometry_hydrostatic_hll_flux,
)
from .shallow_water_junction_patch import (
    JunctionPatchFaceFlux,
    ShallowWaterJunctionPatchGeometry,
    ShallowWaterJunctionPatchState,
    ShallowWaterJunctionPatchStep,
    advance_shallow_water_junction_patch,
    maximum_shallow_water_junction_patch_timestep_seconds,
)


COUPLED_JUNCTION_PATCH_REACH_STEP_SCHEMA = (
    "gwm.geospatial_kernel.coupled_junction_patch_reach_step.v1"
)
_GEOMETRY_TOLERANCE = 1e-10


@dataclass(frozen=True)
class JunctionPatchReachOpeningExchange:
    """One synchronous 2D/1D exchange and its dimensional closure."""

    branch_id: str
    branch_role: str
    outward_mass_flux_m3s: float
    outward_momentum_flux_east_m4s2: float
    outward_momentum_flux_north_m4s2: float
    longitudinal_momentum_flux_m4s2: float
    transverse_momentum_flux_east_m4s2: float
    transverse_momentum_flux_north_m4s2: float
    branch_volume_impulse_m3: float
    patch_volume_impulse_m3: float
    branch_longitudinal_impulse_east_m4s: float
    branch_longitudinal_impulse_north_m4s: float
    patch_momentum_impulse_east_m4s: float
    patch_momentum_impulse_north_m4s: float
    transition_wall_fluid_impulse_east_m4s: float
    transition_wall_fluid_impulse_north_m4s: float
    transition_wall_structure_reaction_east_m4s: float
    transition_wall_structure_reaction_north_m4s: float
    mass_cancellation_error_m3: float
    momentum_closure_error_east_m4s: float
    momentum_closure_error_north_m4s: float

    @property
    def transverse_momentum_flux_magnitude_m4s2(self) -> float:
        return math.hypot(
            self.transverse_momentum_flux_east_m4s2,
            self.transverse_momentum_flux_north_m4s2,
        )

    @property
    def momentum_closure_error_magnitude_m4s(self) -> float:
        return math.hypot(
            self.momentum_closure_error_east_m4s,
            self.momentum_closure_error_north_m4s,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "branch_role": self.branch_role,
            "outward_mass_flux_m3s": self.outward_mass_flux_m3s,
            "outward_momentum_flux_east_north_m4s2": [
                self.outward_momentum_flux_east_m4s2,
                self.outward_momentum_flux_north_m4s2,
            ],
            "longitudinal_momentum_flux_m4s2": (
                self.longitudinal_momentum_flux_m4s2
            ),
            "transverse_momentum_flux_east_north_m4s2": [
                self.transverse_momentum_flux_east_m4s2,
                self.transverse_momentum_flux_north_m4s2,
            ],
            "transverse_momentum_flux_magnitude_m4s2": (
                self.transverse_momentum_flux_magnitude_m4s2
            ),
            "branch_volume_impulse_m3": self.branch_volume_impulse_m3,
            "patch_volume_impulse_m3": self.patch_volume_impulse_m3,
            "branch_longitudinal_impulse_east_north_m4s": [
                self.branch_longitudinal_impulse_east_m4s,
                self.branch_longitudinal_impulse_north_m4s,
            ],
            "patch_momentum_impulse_east_north_m4s": [
                self.patch_momentum_impulse_east_m4s,
                self.patch_momentum_impulse_north_m4s,
            ],
            "transition_wall_fluid_impulse_east_north_m4s": [
                self.transition_wall_fluid_impulse_east_m4s,
                self.transition_wall_fluid_impulse_north_m4s,
            ],
            "transition_wall_structure_reaction_east_north_m4s": [
                self.transition_wall_structure_reaction_east_m4s,
                self.transition_wall_structure_reaction_north_m4s,
            ],
            "mass_cancellation_error_m3": self.mass_cancellation_error_m3,
            "momentum_closure_error_east_north_m4s": [
                self.momentum_closure_error_east_m4s,
                self.momentum_closure_error_north_m4s,
            ],
            "momentum_closure_error_magnitude_m4s": (
                self.momentum_closure_error_magnitude_m4s
            ),
            "transverse_closure": "instantaneous_transition_wall_reaction",
        }


@dataclass(frozen=True)
class CoupledJunctionPatchReachStep:
    upstream_states: tuple[PrismaticDynamicWaveState, ...]
    downstream_state: PrismaticDynamicWaveState
    junction_solution: ConservativeVectorJunctionSolution
    junction_patch_step: ShallowWaterJunctionPatchStep
    upstream_reach_steps: tuple[VariableGeometryHydrostaticOpenStep, ...]
    downstream_reach_step: VariableGeometryHydrostaticOpenStep
    opening_exchanges: tuple[JunctionPatchReachOpeningExchange, ...]
    timestep_seconds: float
    maximum_stable_timestep_seconds: float
    maximum_courant_number: float
    total_volume_before_m3: float
    external_boundary_volume_change_m3: float
    total_volume_after_m3: float
    total_volume_ledger_error_m3: float
    geographic_momentum_before_east_m4s: float
    geographic_momentum_before_north_m4s: float
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
    minimum_reach_area_m2: float
    diagnostic_only: bool = True

    @property
    def geographic_momentum_ledger_error_magnitude_m4s(self) -> float:
        return math.hypot(
            self.geographic_momentum_ledger_error_east_m4s,
            self.geographic_momentum_ledger_error_north_m4s,
        )

    @property
    def maximum_opening_mass_cancellation_error_m3(self) -> float:
        return max(
            abs(value.mass_cancellation_error_m3)
            for value in self.opening_exchanges
        )

    @property
    def maximum_opening_momentum_closure_error_m4s(self) -> float:
        return max(
            value.momentum_closure_error_magnitude_m4s
            for value in self.opening_exchanges
        )

    @property
    def transition_wall_fluid_impulse_magnitude_m4s(self) -> float:
        return math.hypot(
            self.transition_wall_fluid_impulse_east_m4s,
            self.transition_wall_fluid_impulse_north_m4s,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": COUPLED_JUNCTION_PATCH_REACH_STEP_SCHEMA,
            "upstream_states": [
                _dynamic_state_dict(value) for value in self.upstream_states
            ],
            "downstream_state": _dynamic_state_dict(self.downstream_state),
            "junction_solution": self.junction_solution.as_dict(),
            "junction_patch_step": self.junction_patch_step.as_dict(),
            "upstream_reach_steps": [
                value.as_dict() for value in self.upstream_reach_steps
            ],
            "downstream_reach_step": self.downstream_reach_step.as_dict(),
            "opening_exchanges": [
                value.as_dict() for value in self.opening_exchanges
            ],
            "timestep_seconds": self.timestep_seconds,
            "maximum_stable_timestep_seconds": (
                self.maximum_stable_timestep_seconds
            ),
            "maximum_courant_number": self.maximum_courant_number,
            "mass_ledger": {
                "total_volume_before_m3": self.total_volume_before_m3,
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
            "maximum_opening_mass_cancellation_error_m3": (
                self.maximum_opening_mass_cancellation_error_m3
            ),
            "maximum_opening_momentum_closure_error_m4s": (
                self.maximum_opening_momentum_closure_error_m4s
            ),
            "minimum_reach_area_m2": self.minimum_reach_area_m2,
            "minimum_patch_cell_volume_m3": (
                self.junction_patch_step.minimum_cell_volume_m3
            ),
            "synchronous_patch_reach_exchange": True,
            "complete_vector_opening_flux_audited": True,
            "one_dimensional_longitudinal_projection": True,
            "transverse_closure": "instantaneous_transition_wall_reaction",
            "persistent_transverse_momentum_reservoir": False,
            "transition_reaction_feedback_to_flux": False,
            "friction_and_lateral_source_splitting": False,
            "flat_bed_uniform_rectangular_reaches_only": True,
            "public_validation_completed": False,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class _CouplingContext:
    upstream_terminals: tuple[DynamicWaveJunctionTerminal, ...]
    downstream_terminal: DynamicWaveJunctionTerminal
    junction: ConservativeVectorJunctionSolution


def maximum_coupled_junction_patch_reach_timestep_seconds(
    patch_state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    contract: ConservativeVectorJunctionContract,
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    *,
    upstream_external_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_external_boundary: FixedDynamicWaveBoundary,
    courant_number: float,
) -> float:
    limit = _courant_number(courant_number)
    context = _prepare_context(
        patch_state,
        geometry,
        contract,
        upstream_reaches,
        downstream_reach,
        upstream_external_boundaries,
        downstream_external_boundary,
    )
    stable = [
        maximum_shallow_water_junction_patch_timestep_seconds(
            patch_state,
            geometry,
            context.upstream_terminals,
            context.downstream_terminal,
            context.junction,
            courant_number=limit,
        )
    ]
    hydraulic = context.junction.hydraulic_solution
    for reach, external, boundary in zip(
        upstream_reaches,
        upstream_external_boundaries,
        hydraulic.upstream_boundaries,
        strict=True,
    ):
        value = maximum_variable_geometry_open_stable_timestep_seconds(
            reach.state,
            reach.sections,
            left_boundary_state=external.state,
            right_boundary_state=boundary.state,
            left_boundary_section=reach.sections[0],
            right_boundary_section=reach.sections[-1],
            cell_length_m=reach.cell_length_m,
            courant_number=limit,
        )
        if value is not None:
            stable.append(value)
        stable.append(
            _opening_reach_stable_timestep_seconds(
                patch_state, geometry, contract, reach, boundary.state, limit
            )
        )
    value = maximum_variable_geometry_open_stable_timestep_seconds(
        downstream_reach.state,
        downstream_reach.sections,
        left_boundary_state=hydraulic.downstream_boundary.state,
        right_boundary_state=downstream_external_boundary.state,
        left_boundary_section=downstream_reach.sections[0],
        right_boundary_section=downstream_reach.sections[-1],
        cell_length_m=downstream_reach.cell_length_m,
        courant_number=limit,
    )
    if value is not None:
        stable.append(value)
    stable.append(
        _opening_reach_stable_timestep_seconds(
            patch_state,
            geometry,
            contract,
            downstream_reach,
            hydraulic.downstream_boundary.state,
            limit,
        )
    )
    return min(stable)


def advance_coupled_junction_patch_reaches(
    patch_state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    contract: ConservativeVectorJunctionContract,
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    *,
    upstream_external_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_external_boundary: FixedDynamicWaveBoundary,
    timestep_seconds: float,
    maximum_courant_number: float,
) -> CoupledJunctionPatchReachStep:
    timestep = float(timestep_seconds)
    limit = _courant_number(maximum_courant_number)
    if not math.isfinite(timestep) or timestep <= 0.0:
        raise ValueError("coupled_junction_patch_reach_timestep_invalid")
    context = _prepare_context(
        patch_state,
        geometry,
        contract,
        upstream_reaches,
        downstream_reach,
        upstream_external_boundaries,
        downstream_external_boundary,
    )
    stable = maximum_coupled_junction_patch_reach_timestep_seconds(
        patch_state,
        geometry,
        contract,
        upstream_reaches,
        downstream_reach,
        upstream_external_boundaries=upstream_external_boundaries,
        downstream_external_boundary=downstream_external_boundary,
        courant_number=limit,
    )
    if timestep > stable * (1.0 + 1e-12):
        raise ValueError("coupled_junction_patch_reach_cfl_exceeded")
    patch_step = advance_shallow_water_junction_patch(
        patch_state,
        geometry,
        context.upstream_terminals,
        context.downstream_terminal,
        context.junction,
        timestep_seconds=timestep,
        maximum_courant_number=limit,
    )
    flux_by_branch = {
        str(value.branch_id): value
        for value in patch_step.face_fluxes
        if value.boundary_type == "branch_opening"
    }
    tangent_by_branch = _branch_tangents(contract)

    upstream_steps = []
    external_momentum_east = 0.0
    external_momentum_north = 0.0
    hydraulic = context.junction.hydraulic_solution
    for reach, external, boundary in zip(
        upstream_reaches,
        upstream_external_boundaries,
        hydraulic.upstream_boundaries,
        strict=True,
    ):
        flux = flux_by_branch[reach.reach_id]
        tangent = tangent_by_branch[reach.reach_id]
        projected = _dot_flux_tangent(flux, tangent)
        external_flux = variable_geometry_hydrostatic_hll_flux(
            external.state,
            DynamicWaveCellState(
                reach.state.area_m2[0], reach.state.discharge_m3s[0]
            ),
            left_bed_elevation_m=external.bed_elevation_m,
            right_bed_elevation_m=reach.bed_elevation_m[0],
            left_section=reach.sections[0],
            right_section=reach.sections[0],
        ).right_cell_flux
        external_momentum_east += (
            timestep * external_flux.momentum_flux_m4s2 * tangent[0]
        )
        external_momentum_north += (
            timestep * external_flux.momentum_flux_m4s2 * tangent[1]
        )
        upstream_steps.append(
            advance_variable_geometry_hydrostatic_open(
                reach.state,
                reach.bed_elevation_m,
                reach.sections,
                left_boundary_state=external.state,
                right_boundary_state=boundary.state,
                left_boundary_bed_elevation_m=external.bed_elevation_m,
                right_boundary_bed_elevation_m=reach.bed_elevation_m[-1],
                left_boundary_section=reach.sections[0],
                right_boundary_section=reach.sections[-1],
                cell_length_m=reach.cell_length_m,
                timestep_seconds=timestep,
                maximum_courant_number=limit,
                right_boundary_cell_flux_override=DynamicWaveFlux(
                    -flux.outward_mass_flux_m3s,
                    -projected,
                ),
            )
        )

    downstream_flux = flux_by_branch[downstream_reach.reach_id]
    downstream_tangent = tangent_by_branch[downstream_reach.reach_id]
    downstream_projected = _dot_flux_tangent(
        downstream_flux, downstream_tangent
    )
    external_right_flux = variable_geometry_hydrostatic_hll_flux(
        DynamicWaveCellState(
            downstream_reach.state.area_m2[-1],
            downstream_reach.state.discharge_m3s[-1],
        ),
        downstream_external_boundary.state,
        left_bed_elevation_m=downstream_reach.bed_elevation_m[-1],
        right_bed_elevation_m=downstream_external_boundary.bed_elevation_m,
        left_section=downstream_reach.sections[-1],
        right_section=downstream_reach.sections[-1],
    ).left_cell_flux
    external_momentum_east -= (
        timestep * external_right_flux.momentum_flux_m4s2
        * downstream_tangent[0]
    )
    external_momentum_north -= (
        timestep * external_right_flux.momentum_flux_m4s2
        * downstream_tangent[1]
    )
    downstream_step = advance_variable_geometry_hydrostatic_open(
        downstream_reach.state,
        downstream_reach.bed_elevation_m,
        downstream_reach.sections,
        left_boundary_state=hydraulic.downstream_boundary.state,
        right_boundary_state=downstream_external_boundary.state,
        left_boundary_bed_elevation_m=downstream_reach.bed_elevation_m[0],
        right_boundary_bed_elevation_m=(
            downstream_external_boundary.bed_elevation_m
        ),
        left_boundary_section=downstream_reach.sections[0],
        right_boundary_section=downstream_reach.sections[-1],
        cell_length_m=downstream_reach.cell_length_m,
        timestep_seconds=timestep,
        maximum_courant_number=limit,
        left_boundary_cell_flux_override=DynamicWaveFlux(
            downstream_flux.outward_mass_flux_m3s,
            downstream_projected,
        ),
    )

    branch_ids = (*contract.upstream_branch_ids, contract.downstream_branch_id)
    exchanges = tuple(
        _opening_exchange(
            flux_by_branch[branch_id],
            tangent_by_branch[branch_id],
            timestep,
        )
        for branch_id in branch_ids
    )
    reaches_before = (*upstream_reaches, downstream_reach)
    reaches_after = (
        *tuple(value.state for value in upstream_steps),
        downstream_step.state,
    )
    tangents = tuple(
        tangent_by_branch[value.reach_id] for value in reaches_before
    )
    volume_before = patch_state.total_volume_m3 + sum(
        _reach_volume(value) for value in reaches_before
    )
    volume_after = patch_step.state_after.total_volume_m3 + sum(
        _state_volume(state, reach.cell_length_m)
        for state, reach in zip(reaches_after, reaches_before, strict=True)
    )
    external_volume = timestep * (
        sum(value.left_boundary_area_flux_m3s for value in upstream_steps)
        - downstream_step.right_boundary_area_flux_m3s
    )
    momentum_before = _geographic_momentum(
        tuple(value.state for value in reaches_before),
        tuple(value.cell_length_m for value in reaches_before),
        tangents,
        patch_state,
    )
    momentum_after = _geographic_momentum(
        reaches_after,
        tuple(value.cell_length_m for value in reaches_before),
        tangents,
        patch_step.state_after,
    )
    patch_wall_impulse = (
        -timestep * patch_step.wall_pressure_flux_east_m4s2,
        -timestep * patch_step.wall_pressure_flux_north_m4s2,
    )
    transition_impulse = (
        sum(value.transition_wall_fluid_impulse_east_m4s for value in exchanges),
        sum(value.transition_wall_fluid_impulse_north_m4s for value in exchanges),
    )
    momentum_error = (
        momentum_after[0]
        - momentum_before[0]
        - external_momentum_east
        - patch_wall_impulse[0]
        - transition_impulse[0],
        momentum_after[1]
        - momentum_before[1]
        - external_momentum_north
        - patch_wall_impulse[1]
        - transition_impulse[1],
    )
    return CoupledJunctionPatchReachStep(
        upstream_states=tuple(value.state for value in upstream_steps),
        downstream_state=downstream_step.state,
        junction_solution=context.junction,
        junction_patch_step=patch_step,
        upstream_reach_steps=tuple(upstream_steps),
        downstream_reach_step=downstream_step,
        opening_exchanges=exchanges,
        timestep_seconds=timestep,
        maximum_stable_timestep_seconds=stable,
        maximum_courant_number=limit,
        total_volume_before_m3=volume_before,
        external_boundary_volume_change_m3=external_volume,
        total_volume_after_m3=volume_after,
        total_volume_ledger_error_m3=(
            volume_after - volume_before - external_volume
        ),
        geographic_momentum_before_east_m4s=momentum_before[0],
        geographic_momentum_before_north_m4s=momentum_before[1],
        external_boundary_momentum_impulse_east_m4s=external_momentum_east,
        external_boundary_momentum_impulse_north_m4s=external_momentum_north,
        patch_solid_wall_fluid_impulse_east_m4s=patch_wall_impulse[0],
        patch_solid_wall_fluid_impulse_north_m4s=patch_wall_impulse[1],
        transition_wall_fluid_impulse_east_m4s=transition_impulse[0],
        transition_wall_fluid_impulse_north_m4s=transition_impulse[1],
        geographic_momentum_after_east_m4s=momentum_after[0],
        geographic_momentum_after_north_m4s=momentum_after[1],
        geographic_momentum_ledger_error_east_m4s=momentum_error[0],
        geographic_momentum_ledger_error_north_m4s=momentum_error[1],
        minimum_reach_area_m2=min(
            min(value.area_m2) for value in reaches_after
        ),
    )


def _prepare_context(
    patch_state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    contract: ConservativeVectorJunctionContract,
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    upstream_external_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_external_boundary: FixedDynamicWaveBoundary,
) -> _CouplingContext:
    if not isinstance(patch_state, ShallowWaterJunctionPatchState):
        raise TypeError("shallow_water_junction_patch_state_required")
    if not isinstance(geometry, ShallowWaterJunctionPatchGeometry):
        raise TypeError("shallow_water_junction_patch_geometry_required")
    if not isinstance(contract, ConservativeVectorJunctionContract):
        raise TypeError("conservative_vector_junction_contract_required")
    upstream = tuple(upstream_reaches)
    external = tuple(upstream_external_boundaries)
    if any(
        not isinstance(value, DynamicWaveNetworkReach)
        for value in (*upstream, downstream_reach)
    ):
        raise TypeError("dynamic_wave_network_reach_required")
    branch_ids = (*contract.upstream_branch_ids, contract.downstream_branch_id)
    if (
        geometry.junction_id != contract.junction_id
        or geometry.upstream_branch_ids != contract.upstream_branch_ids
        or geometry.downstream_branch_id != contract.downstream_branch_id
        or tuple(value.reach_id for value in upstream)
        != contract.upstream_branch_ids
        or downstream_reach.reach_id != contract.downstream_branch_id
        or len(external) != len(upstream)
        or any(
            not isinstance(value, FixedDynamicWaveBoundary)
            for value in (*external, downstream_external_boundary)
        )
        or tuple(value.cell_id for value in patch_state.cells)
        != tuple(value.cell_id for value in geometry.cells)
        or len(branch_ids) != len(set(branch_ids))
    ):
        raise ValueError("coupled_junction_patch_reach_branch_binding_mismatch")
    face_by_branch = {
        str(value.branch_id): value for value in geometry.branch_faces
    }
    for reach in (*upstream, downstream_reach):
        length = geometry.face_measure(face_by_branch[reach.reach_id])[0]
        if (
            any(
                section.side_slope_horizontal_per_vertical != 0.0
                or abs(section.bottom_width_m - length) > _GEOMETRY_TOLERANCE
                for section in reach.sections
            )
            or any(
                abs(value - geometry.bed_elevation_m) > _GEOMETRY_TOLERANCE
                for value in reach.bed_elevation_m
            )
            or any(value != 0.0 for value in reach.lateral_inflow_m2s)
        ):
            raise ValueError(
                "coupled_junction_patch_reach_"
                "uniform_rectangular_flat_contract_required"
            )
    if any(
        abs(value.bed_elevation_m - geometry.bed_elevation_m)
        > _GEOMETRY_TOLERANCE
        or value.state.area_m2 <= 0.0
        for value in (*external, downstream_external_boundary)
    ):
        raise ValueError(
            "coupled_junction_patch_reach_external_boundary_not_supported"
        )
    upstream_terminals = tuple(
        DynamicWaveJunctionTerminal(
            reach.reach_id,
            DynamicWaveCellState(
                reach.state.area_m2[-1], reach.state.discharge_m3s[-1]
            ),
            reach.sections[-1],
            reach.bed_elevation_m[-1],
        )
        for reach in upstream
    )
    downstream_terminal = DynamicWaveJunctionTerminal(
        downstream_reach.reach_id,
        DynamicWaveCellState(
            downstream_reach.state.area_m2[0],
            downstream_reach.state.discharge_m3s[0],
        ),
        downstream_reach.sections[0],
        downstream_reach.bed_elevation_m[0],
    )
    junction = solve_conservative_vector_junction(
        upstream_terminals, downstream_terminal, contract
    )
    return _CouplingContext(
        upstream_terminals, downstream_terminal, junction
    )


def _opening_exchange(
    flux: JunctionPatchFaceFlux,
    tangent: tuple[float, float],
    timestep: float,
) -> JunctionPatchReachOpeningExchange:
    if flux.branch_id is None or flux.branch_role is None:
        raise ValueError("junction_patch_reach_opening_flux_required")
    projected = _dot_flux_tangent(flux, tangent)
    transverse = (
        flux.outward_momentum_flux_east_m4s2 - projected * tangent[0],
        flux.outward_momentum_flux_north_m4s2 - projected * tangent[1],
    )
    branch_impulse = (
        timestep * projected * tangent[0],
        timestep * projected * tangent[1],
    )
    patch_impulse = (
        -timestep * flux.outward_momentum_flux_east_m4s2,
        -timestep * flux.outward_momentum_flux_north_m4s2,
    )
    transition_fluid = (
        -timestep * transverse[0],
        -timestep * transverse[1],
    )
    closure = (
        patch_impulse[0] + branch_impulse[0] - transition_fluid[0],
        patch_impulse[1] + branch_impulse[1] - transition_fluid[1],
    )
    return JunctionPatchReachOpeningExchange(
        branch_id=flux.branch_id,
        branch_role=flux.branch_role,
        outward_mass_flux_m3s=flux.outward_mass_flux_m3s,
        outward_momentum_flux_east_m4s2=(
            flux.outward_momentum_flux_east_m4s2
        ),
        outward_momentum_flux_north_m4s2=(
            flux.outward_momentum_flux_north_m4s2
        ),
        longitudinal_momentum_flux_m4s2=projected,
        transverse_momentum_flux_east_m4s2=transverse[0],
        transverse_momentum_flux_north_m4s2=transverse[1],
        branch_volume_impulse_m3=timestep * flux.outward_mass_flux_m3s,
        patch_volume_impulse_m3=-timestep * flux.outward_mass_flux_m3s,
        branch_longitudinal_impulse_east_m4s=branch_impulse[0],
        branch_longitudinal_impulse_north_m4s=branch_impulse[1],
        patch_momentum_impulse_east_m4s=patch_impulse[0],
        patch_momentum_impulse_north_m4s=patch_impulse[1],
        transition_wall_fluid_impulse_east_m4s=transition_fluid[0],
        transition_wall_fluid_impulse_north_m4s=transition_fluid[1],
        transition_wall_structure_reaction_east_m4s=-transition_fluid[0],
        transition_wall_structure_reaction_north_m4s=-transition_fluid[1],
        mass_cancellation_error_m3=0.0,
        momentum_closure_error_east_m4s=closure[0],
        momentum_closure_error_north_m4s=closure[1],
    )


def _opening_reach_stable_timestep_seconds(
    patch_state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    contract: ConservativeVectorJunctionContract,
    reach: DynamicWaveNetworkReach,
    boundary_state: DynamicWaveCellState,
    courant_number: float,
) -> float:
    face = next(
        value for value in geometry.branch_faces
        if value.branch_id == reach.reach_id
    )
    length, normal, _ = geometry.face_measure(face)
    tangent = _branch_tangents(contract)[reach.reach_id]
    cell = patch_state.cell_by_id[face.left_cell_id]
    cell_depth = cell.depth_m(geometry.cell_areas_m2[cell.cell_id])
    cell_normal_velocity = (
        cell.velocity_east_mps * normal[0]
        + cell.velocity_north_mps * normal[1]
    )
    exterior_velocity = boundary_state.discharge_m3s / boundary_state.area_m2
    exterior_normal_velocity = exterior_velocity * (
        tangent[0] * normal[0] + tangent[1] * normal[1]
    )
    maximum_speed = max(
        abs(cell_normal_velocity)
        + math.sqrt(STANDARD_GRAVITY_MPS2 * cell_depth),
        abs(exterior_normal_velocity)
        + math.sqrt(
            STANDARD_GRAVITY_MPS2 * boundary_state.area_m2 / length
        ),
    )
    return courant_number * reach.cell_length_m / maximum_speed


def _branch_tangents(
    contract: ConservativeVectorJunctionContract,
) -> dict[str, tuple[float, float]]:
    branch_ids = (*contract.upstream_branch_ids, contract.downstream_branch_id)
    azimuths = (
        *contract.upstream_flow_azimuth_degrees,
        contract.downstream_flow_azimuth_degrees,
    )
    return {
        branch_id: _tangent(azimuth)
        for branch_id, azimuth in zip(branch_ids, azimuths, strict=True)
    }


def _tangent(azimuth_degrees: float) -> tuple[float, float]:
    angle = math.radians(azimuth_degrees)
    return math.sin(angle), math.cos(angle)


def _dot_flux_tangent(
    flux: JunctionPatchFaceFlux,
    tangent: tuple[float, float],
) -> float:
    return (
        flux.outward_momentum_flux_east_m4s2 * tangent[0]
        + flux.outward_momentum_flux_north_m4s2 * tangent[1]
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


def _reach_volume(reach: DynamicWaveNetworkReach) -> float:
    return _state_volume(reach.state, reach.cell_length_m)


def _state_volume(
    state: PrismaticDynamicWaveState, cell_length_m: float
) -> float:
    return sum(state.area_m2) * cell_length_m


def _dynamic_state_dict(
    state: PrismaticDynamicWaveState,
) -> dict[str, object]:
    return {
        "area_m2": list(state.area_m2),
        "discharge_m3s": list(state.discharge_m3s),
    }


def _courant_number(value: float) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0.0 < result <= 1.0:
        raise ValueError("coupled_junction_patch_reach_cfl_invalid")
    return result
