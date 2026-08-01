"""Source splitting around the Stage 18 patch/reach conservative core."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math

from .conservative_vector_junction import ConservativeVectorJunctionContract
from .coupled_junction_patch_reach import (
    CoupledJunctionPatchReachStep,
    advance_coupled_junction_patch_reaches,
    maximum_coupled_junction_patch_reach_timestep_seconds,
)
from .dynamic_wave_coupled import FixedDynamicWaveBoundary
from .dynamic_wave_flux import PrismaticDynamicWaveState
from .dynamic_wave_junction import DynamicWaveNetworkReach
from .dynamic_wave_sources import (
    LateralInflowSourceStep,
    ManningSlopeFrictionStep,
    apply_lateral_inflow_source,
)
from .dynamic_wave_variable_geometry import (
    apply_variable_geometry_manning_friction_only_source,
)
from .shallow_water_junction_patch import (
    ShallowWaterJunctionPatchGeometry,
    ShallowWaterJunctionPatchState,
)


SOURCE_SPLIT_COUPLED_JUNCTION_PATCH_REACH_STEP_SCHEMA = (
    "gwm.geospatial_kernel.source_split_coupled_junction_patch_reach_step.v1"
)
_LATERAL_MOMENTUM_CONVENTIONS = frozenset(
    ("zero_longitudinal_momentum", "matched_local_velocity")
)
_CFL_ITERATION_COUNT = 12


@dataclass(frozen=True)
class SourceSplitPatchReachTrace:
    branch_id: str
    state_before: PrismaticDynamicWaveState
    lateral_first: LateralInflowSourceStep
    friction_first: ManningSlopeFrictionStep
    core_state: PrismaticDynamicWaveState
    friction_second: ManningSlopeFrictionStep
    lateral_second: LateralInflowSourceStep
    state_after: PrismaticDynamicWaveState
    lateral_volume_change_m3: float
    lateral_longitudinal_momentum_change_m4s: float
    friction_longitudinal_momentum_change_m4s: float

    def as_dict(self) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "state_before": _state_dict(self.state_before),
            "lateral_first": self.lateral_first.as_dict(),
            "friction_first": self.friction_first.as_dict(),
            "core_state": _state_dict(self.core_state),
            "friction_second": self.friction_second.as_dict(),
            "lateral_second": self.lateral_second.as_dict(),
            "state_after": _state_dict(self.state_after),
            "lateral_volume_change_m3": self.lateral_volume_change_m3,
            "lateral_longitudinal_momentum_change_m4s": (
                self.lateral_longitudinal_momentum_change_m4s
            ),
            "friction_longitudinal_momentum_change_m4s": (
                self.friction_longitudinal_momentum_change_m4s
            ),
            "source_order": [
                "lateral_half",
                "manning_friction_half",
                "stage18_patch_reach_conservative_core_full",
                "manning_friction_half",
                "lateral_half",
            ],
        }


@dataclass(frozen=True)
class SourceSplitCoupledJunctionPatchReachStep:
    upstream_states: tuple[PrismaticDynamicWaveState, ...]
    downstream_state: PrismaticDynamicWaveState
    upstream_source_traces: tuple[SourceSplitPatchReachTrace, ...]
    downstream_source_trace: SourceSplitPatchReachTrace
    conservative_core_step: CoupledJunctionPatchReachStep
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
    friction_momentum_change_east_m4s: float
    friction_momentum_change_north_m4s: float
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
    def lateral_momentum_change_magnitude_m4s(self) -> float:
        return math.hypot(
            self.lateral_momentum_change_east_m4s,
            self.lateral_momentum_change_north_m4s,
        )

    @property
    def friction_momentum_change_magnitude_m4s(self) -> float:
        return math.hypot(
            self.friction_momentum_change_east_m4s,
            self.friction_momentum_change_north_m4s,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SOURCE_SPLIT_COUPLED_JUNCTION_PATCH_REACH_STEP_SCHEMA,
            "upstream_states": [
                _state_dict(value) for value in self.upstream_states
            ],
            "downstream_state": _state_dict(self.downstream_state),
            "upstream_source_traces": [
                value.as_dict() for value in self.upstream_source_traces
            ],
            "downstream_source_trace": self.downstream_source_trace.as_dict(),
            "conservative_core_step": self.conservative_core_step.as_dict(),
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
                "friction_change_east_north_m4s": [
                    self.friction_momentum_change_east_m4s,
                    self.friction_momentum_change_north_m4s,
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
            "minimum_reach_area_m2": self.minimum_reach_area_m2,
            "minimum_patch_cell_volume_m3": (
                self.conservative_core_step
                .junction_patch_step.minimum_cell_volume_m3
            ),
            "source_split_order": (
                "lateral_half,manning_friction_half,"
                "stage18_patch_reach_conservative_core_full,"
                "manning_friction_half,lateral_half"
            ),
            "stage18_opening_exchange_preserved": True,
            "lateral_mass_source_explicit": True,
            "lateral_momentum_semantics_explicit": True,
            "reach_manning_friction_dissipation_explicit": True,
            "patch_bed_friction_implemented": False,
            "persistent_transverse_momentum_reservoir": False,
            "transition_reaction_preserved": True,
            "public_validation_completed": False,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class _PreparedReach:
    reach: DynamicWaveNetworkReach
    lateral_first: LateralInflowSourceStep
    friction_first: ManningSlopeFrictionStep


def maximum_source_split_coupled_junction_patch_timestep_seconds(
    patch_state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    contract: ConservativeVectorJunctionContract,
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    *,
    upstream_external_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_external_boundary: FixedDynamicWaveBoundary,
    lateral_momentum_convention: str,
    courant_number: float,
) -> float:
    convention = _momentum_convention(lateral_momentum_convention)
    source_free_upstream = tuple(
        _source_free_reach(value, value.state) for value in upstream_reaches
    )
    source_free_downstream = _source_free_reach(
        downstream_reach, downstream_reach.state
    )
    common = {
        "upstream_external_boundaries": upstream_external_boundaries,
        "downstream_external_boundary": downstream_external_boundary,
        "courant_number": courant_number,
    }
    candidate = maximum_coupled_junction_patch_reach_timestep_seconds(
        patch_state,
        geometry,
        contract,
        source_free_upstream,
        source_free_downstream,
        **common,
    )
    for _ in range(_CFL_ITERATION_COUNT):
        half_timestep = 0.5 * candidate
        prepared_upstream = tuple(
            _prepare_reach(value, half_timestep, convention)
            for value in upstream_reaches
        )
        prepared_downstream = _prepare_reach(
            downstream_reach, half_timestep, convention
        )
        allowed = maximum_coupled_junction_patch_reach_timestep_seconds(
            patch_state,
            geometry,
            contract,
            tuple(
                _source_free_reach(value.reach, value.friction_first.state)
                for value in prepared_upstream
            ),
            _source_free_reach(
                prepared_downstream.reach,
                prepared_downstream.friction_first.state,
            ),
            **common,
        )
        if candidate <= allowed:
            return candidate
        candidate = allowed * (1.0 - 1e-12)
    raise RuntimeError(
        "source_split_coupled_junction_patch_cfl_not_converged"
    )


def advance_source_split_coupled_junction_patch_reaches(
    patch_state: ShallowWaterJunctionPatchState,
    geometry: ShallowWaterJunctionPatchGeometry,
    contract: ConservativeVectorJunctionContract,
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    *,
    upstream_external_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_external_boundary: FixedDynamicWaveBoundary,
    lateral_momentum_convention: str,
    timestep_seconds: float,
    maximum_courant_number: float,
) -> SourceSplitCoupledJunctionPatchReachStep:
    timestep = float(timestep_seconds)
    convention = _momentum_convention(lateral_momentum_convention)
    if not math.isfinite(timestep) or timestep <= 0.0:
        raise ValueError(
            "source_split_coupled_junction_patch_timestep_invalid"
        )
    stable = maximum_source_split_coupled_junction_patch_timestep_seconds(
        patch_state,
        geometry,
        contract,
        upstream_reaches,
        downstream_reach,
        upstream_external_boundaries=upstream_external_boundaries,
        downstream_external_boundary=downstream_external_boundary,
        lateral_momentum_convention=convention,
        courant_number=maximum_courant_number,
    )
    if timestep > stable * (1.0 + 1e-12):
        raise ValueError("source_split_coupled_junction_patch_cfl_exceeded")
    half_timestep = 0.5 * timestep
    prepared_upstream = tuple(
        _prepare_reach(value, half_timestep, convention)
        for value in upstream_reaches
    )
    prepared_downstream = _prepare_reach(
        downstream_reach, half_timestep, convention
    )
    core_upstream = tuple(
        _source_free_reach(value.reach, value.friction_first.state)
        for value in prepared_upstream
    )
    core_downstream = _source_free_reach(
        prepared_downstream.reach,
        prepared_downstream.friction_first.state,
    )
    core = advance_coupled_junction_patch_reaches(
        patch_state,
        geometry,
        contract,
        core_upstream,
        core_downstream,
        upstream_external_boundaries=upstream_external_boundaries,
        downstream_external_boundary=downstream_external_boundary,
        timestep_seconds=timestep,
        maximum_courant_number=maximum_courant_number,
    )
    upstream_traces = tuple(
        _finish_reach(prepared, state, half_timestep, convention)
        for prepared, state in zip(
            prepared_upstream, core.upstream_states, strict=True
        )
    )
    downstream_trace = _finish_reach(
        prepared_downstream,
        core.downstream_state,
        half_timestep,
        convention,
    )
    traces = (*upstream_traces, downstream_trace)
    reaches_before = (*upstream_reaches, downstream_reach)
    states_before = tuple(value.state for value in reaches_before)
    states_after = tuple(value.state_after for value in traces)
    tangents = _branch_tangents(contract)
    lengths = tuple(value.cell_length_m for value in reaches_before)
    total_volume_before = patch_state.total_volume_m3 + sum(
        _state_volume(state, length)
        for state, length in zip(states_before, lengths, strict=True)
    )
    total_volume_after = (
        core.junction_patch_step.state_after.total_volume_m3
        + sum(
            _state_volume(state, length)
            for state, length in zip(states_after, lengths, strict=True)
        )
    )
    lateral_volume = sum(
        value.lateral_volume_change_m3 for value in traces
    )
    momentum_before = _geographic_momentum(
        states_before,
        lengths,
        tangents,
        patch_state,
    )
    momentum_after = _geographic_momentum(
        states_after,
        lengths,
        tangents,
        core.junction_patch_step.state_after,
    )
    lateral_momentum = _vectorize_longitudinal_changes(
        tuple(
            value.lateral_longitudinal_momentum_change_m4s
            for value in traces
        ),
        tangents,
    )
    friction_momentum = _vectorize_longitudinal_changes(
        tuple(
            value.friction_longitudinal_momentum_change_m4s
            for value in traces
        ),
        tangents,
    )
    expected_momentum_change = (
        lateral_momentum[0]
        + friction_momentum[0]
        + core.external_boundary_momentum_impulse_east_m4s
        + core.patch_solid_wall_fluid_impulse_east_m4s
        + core.transition_wall_fluid_impulse_east_m4s,
        lateral_momentum[1]
        + friction_momentum[1]
        + core.external_boundary_momentum_impulse_north_m4s
        + core.patch_solid_wall_fluid_impulse_north_m4s
        + core.transition_wall_fluid_impulse_north_m4s,
    )
    momentum_error = (
        momentum_after[0]
        - momentum_before[0]
        - expected_momentum_change[0],
        momentum_after[1]
        - momentum_before[1]
        - expected_momentum_change[1],
    )
    return SourceSplitCoupledJunctionPatchReachStep(
        upstream_states=tuple(value.state_after for value in upstream_traces),
        downstream_state=downstream_trace.state_after,
        upstream_source_traces=upstream_traces,
        downstream_source_trace=downstream_trace,
        conservative_core_step=core,
        timestep_seconds=timestep,
        maximum_stable_timestep_seconds=stable,
        maximum_courant_number=float(maximum_courant_number),
        lateral_momentum_convention=convention,
        total_volume_before_m3=total_volume_before,
        lateral_volume_change_m3=lateral_volume,
        external_boundary_volume_change_m3=(
            core.external_boundary_volume_change_m3
        ),
        total_volume_after_m3=total_volume_after,
        total_volume_ledger_error_m3=(
            total_volume_after
            - total_volume_before
            - lateral_volume
            - core.external_boundary_volume_change_m3
        ),
        geographic_momentum_before_east_m4s=momentum_before[0],
        geographic_momentum_before_north_m4s=momentum_before[1],
        lateral_momentum_change_east_m4s=lateral_momentum[0],
        lateral_momentum_change_north_m4s=lateral_momentum[1],
        friction_momentum_change_east_m4s=friction_momentum[0],
        friction_momentum_change_north_m4s=friction_momentum[1],
        external_boundary_momentum_impulse_east_m4s=(
            core.external_boundary_momentum_impulse_east_m4s
        ),
        external_boundary_momentum_impulse_north_m4s=(
            core.external_boundary_momentum_impulse_north_m4s
        ),
        patch_solid_wall_fluid_impulse_east_m4s=(
            core.patch_solid_wall_fluid_impulse_east_m4s
        ),
        patch_solid_wall_fluid_impulse_north_m4s=(
            core.patch_solid_wall_fluid_impulse_north_m4s
        ),
        transition_wall_fluid_impulse_east_m4s=(
            core.transition_wall_fluid_impulse_east_m4s
        ),
        transition_wall_fluid_impulse_north_m4s=(
            core.transition_wall_fluid_impulse_north_m4s
        ),
        geographic_momentum_after_east_m4s=momentum_after[0],
        geographic_momentum_after_north_m4s=momentum_after[1],
        geographic_momentum_ledger_error_east_m4s=momentum_error[0],
        geographic_momentum_ledger_error_north_m4s=momentum_error[1],
        minimum_reach_area_m2=min(
            min(value.area_m2) for value in states_after
        ),
    )


def _prepare_reach(
    reach: DynamicWaveNetworkReach,
    half_timestep: float,
    momentum_convention: str,
) -> _PreparedReach:
    lateral = apply_lateral_inflow_source(
        reach.state,
        lateral_inflow_m2s=reach.lateral_inflow_m2s,
        timestep_seconds=half_timestep,
        cell_length_m=reach.cell_length_m,
        momentum_convention=momentum_convention,
    )
    friction = apply_variable_geometry_manning_friction_only_source(
        lateral.state,
        reach.sections,
        manning_n=reach.manning_n,
        timestep_seconds=half_timestep,
        cell_length_m=reach.cell_length_m,
    )
    return _PreparedReach(reach, lateral, friction)


def _finish_reach(
    prepared: _PreparedReach,
    core_state: PrismaticDynamicWaveState,
    half_timestep: float,
    momentum_convention: str,
) -> SourceSplitPatchReachTrace:
    reach = prepared.reach
    friction = apply_variable_geometry_manning_friction_only_source(
        core_state,
        reach.sections,
        manning_n=reach.manning_n,
        timestep_seconds=half_timestep,
        cell_length_m=reach.cell_length_m,
    )
    lateral = apply_lateral_inflow_source(
        friction.state,
        lateral_inflow_m2s=reach.lateral_inflow_m2s,
        timestep_seconds=half_timestep,
        cell_length_m=reach.cell_length_m,
        momentum_convention=momentum_convention,
    )
    length = reach.cell_length_m
    momentum_before = _state_momentum(reach.state, length)
    momentum_after_lateral_first = _state_momentum(
        prepared.lateral_first.state, length
    )
    momentum_after_friction_first = _state_momentum(
        prepared.friction_first.state, length
    )
    momentum_after_core = _state_momentum(core_state, length)
    momentum_after_friction_second = _state_momentum(
        friction.state, length
    )
    momentum_after = _state_momentum(lateral.state, length)
    return SourceSplitPatchReachTrace(
        branch_id=reach.reach_id,
        state_before=reach.state,
        lateral_first=prepared.lateral_first,
        friction_first=prepared.friction_first,
        core_state=core_state,
        friction_second=friction,
        lateral_second=lateral,
        state_after=lateral.state,
        lateral_volume_change_m3=(
            prepared.lateral_first.prescribed_lateral_volume_m3
            + lateral.prescribed_lateral_volume_m3
        ),
        lateral_longitudinal_momentum_change_m4s=(
            momentum_after_lateral_first
            - momentum_before
            + momentum_after
            - momentum_after_friction_second
        ),
        friction_longitudinal_momentum_change_m4s=(
            momentum_after_friction_first
            - momentum_after_lateral_first
            + momentum_after_friction_second
            - momentum_after_core
        ),
    )


def _source_free_reach(
    reach: DynamicWaveNetworkReach,
    state: PrismaticDynamicWaveState,
) -> DynamicWaveNetworkReach:
    return replace(
        reach,
        state=state,
        lateral_inflow_m2s=(0.0,) * state.cell_count,
    )


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
        longitudinal = _state_momentum(state, length)
        east += longitudinal * tangent[0]
        north += longitudinal * tangent[1]
    return east, north


def _vectorize_longitudinal_changes(
    changes: tuple[float, ...],
    tangents: tuple[tuple[float, float], ...],
) -> tuple[float, float]:
    return (
        sum(
            value * tangent[0]
            for value, tangent in zip(changes, tangents, strict=True)
        ),
        sum(
            value * tangent[1]
            for value, tangent in zip(changes, tangents, strict=True)
        ),
    )


def _state_volume(
    state: PrismaticDynamicWaveState, cell_length_m: float
) -> float:
    return sum(state.area_m2) * cell_length_m


def _state_momentum(
    state: PrismaticDynamicWaveState, cell_length_m: float
) -> float:
    return sum(state.discharge_m3s) * cell_length_m


def _state_dict(state: PrismaticDynamicWaveState) -> dict[str, object]:
    return {
        "area_m2": list(state.area_m2),
        "discharge_m3s": list(state.discharge_m3s),
    }


def _momentum_convention(value: str) -> str:
    if value not in _LATERAL_MOMENTUM_CONVENTIONS:
        raise ValueError(
            "source_split_coupled_junction_patch_lateral_momentum_invalid"
        )
    return value
