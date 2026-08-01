"""Conservative subcritical junction contracts for dynamic-wave reaches."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .dynamic_wave_boundaries import (
    CharacteristicDynamicWaveBoundary,
    ResolvedCharacteristicDynamicWaveBoundary,
    resolve_characteristic_dynamic_wave_boundary,
)
from .dynamic_wave_coupled import FixedDynamicWaveBoundary
from .dynamic_wave_flux import (
    DynamicWaveCellState,
    PrismaticDynamicWaveState,
    TrapezoidalChannelSection,
    dynamic_wave_physical_flux,
)
from .dynamic_wave_sources import (
    LateralInflowSourceStep,
    ManningSlopeFrictionStep,
    apply_lateral_inflow_source,
)
from .dynamic_wave_variable_geometry import (
    VariableGeometryHydrostaticOpenStep,
    advance_variable_geometry_hydrostatic_open,
    apply_variable_geometry_manning_friction_only_source,
    maximum_variable_geometry_open_stable_timestep_seconds,
)


SUBCRITICAL_CONFLUENCE_SCHEMA = (
    "gwm.geospatial_kernel.subcritical_dynamic_wave_confluence.v1"
)
SUBCRITICAL_CONFLUENCE_NETWORK_STEP_SCHEMA = (
    "gwm.geospatial_kernel.subcritical_confluence_network_step.v1"
)


@dataclass(frozen=True)
class DynamicWaveJunctionTerminal:
    branch_id: str
    interior_state: DynamicWaveCellState
    section: TrapezoidalChannelSection
    bed_elevation_m: float

    def __post_init__(self) -> None:
        bed = float(self.bed_elevation_m)
        if not self.branch_id.strip() or not math.isfinite(bed):
            raise ValueError("dynamic_wave_junction_terminal_invalid")
        object.__setattr__(self, "bed_elevation_m", bed)


@dataclass(frozen=True)
class SubcriticalConfluenceSolution:
    common_free_surface_elevation_m: float
    upstream_branch_ids: tuple[str, ...]
    upstream_boundaries: tuple[
        ResolvedCharacteristicDynamicWaveBoundary, ...
    ]
    downstream_branch_id: str
    downstream_boundary: ResolvedCharacteristicDynamicWaveBoundary
    total_upstream_discharge_m3s: float
    downstream_discharge_m3s: float
    junction_mass_balance_residual_m3s: float
    maximum_absolute_outgoing_invariant_residual_mps: float
    root_bracket_lower_m: float
    root_bracket_upper_m: float
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SUBCRITICAL_CONFLUENCE_SCHEMA,
            "common_free_surface_elevation_m": (
                self.common_free_surface_elevation_m
            ),
            "upstream_branch_ids": list(self.upstream_branch_ids),
            "upstream_boundaries": [
                value.as_dict() for value in self.upstream_boundaries
            ],
            "downstream_branch_id": self.downstream_branch_id,
            "downstream_boundary": self.downstream_boundary.as_dict(),
            "total_upstream_discharge_m3s": (
                self.total_upstream_discharge_m3s
            ),
            "downstream_discharge_m3s": self.downstream_discharge_m3s,
            "junction_mass_balance_residual_m3s": (
                self.junction_mass_balance_residual_m3s
            ),
            "maximum_absolute_outgoing_invariant_residual_mps": (
                self.maximum_absolute_outgoing_invariant_residual_mps
            ),
            "junction_storage_m3": 0.0,
            "closure_conditions": [
                "common_free_surface_elevation",
                "sum_upstream_discharge_equals_downstream_discharge",
                "one_outgoing_characteristic_invariant_per_branch",
            ],
            "momentum_or_energy_junction_closure": None,
            "subcritical_only": True,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class DynamicWaveNetworkReach:
    reach_id: str
    state: PrismaticDynamicWaveState
    bed_elevation_m: tuple[float, ...]
    sections: tuple[TrapezoidalChannelSection, ...]
    cell_length_m: float
    manning_n: tuple[float, ...]
    lateral_inflow_m2s: tuple[float, ...]

    def __post_init__(self) -> None:
        length = float(self.cell_length_m)
        bed = np.asarray(self.bed_elevation_m, dtype=float)
        roughness = np.asarray(self.manning_n, dtype=float)
        lateral = np.asarray(self.lateral_inflow_m2s, dtype=float)
        if (
            not self.reach_id.strip()
            or not math.isfinite(length)
            or length <= 0.0
            or len(self.sections) != self.state.cell_count
            or bed.shape != (self.state.cell_count,)
            or roughness.shape != bed.shape
            or lateral.shape != bed.shape
            or not np.isfinite(bed).all()
            or not np.isfinite(roughness).all()
            or not np.isfinite(lateral).all()
            or (roughness <= 0.0).any()
            or (lateral < 0.0).any()
        ):
            raise ValueError("dynamic_wave_network_reach_invalid")
        object.__setattr__(self, "cell_length_m", length)
        object.__setattr__(
            self, "bed_elevation_m", tuple(float(value) for value in bed)
        )
        object.__setattr__(
            self, "manning_n", tuple(float(value) for value in roughness)
        )
        object.__setattr__(
            self,
            "lateral_inflow_m2s",
            tuple(float(value) for value in lateral),
        )


@dataclass(frozen=True)
class SubcriticalConfluenceNetworkStep:
    upstream_states: tuple[PrismaticDynamicWaveState, ...]
    downstream_state: PrismaticDynamicWaveState
    junction: SubcriticalConfluenceSolution
    timestep_seconds: float
    maximum_courant_number: float
    volume_before_m3: float
    lateral_volume_change_m3: float
    external_boundary_volume_change_m3: float
    junction_mass_balance_residual_volume_m3: float
    volume_after_m3: float
    network_volume_balance_error_m3: float
    maximum_absolute_reach_volume_ledger_error_m3: float
    maximum_absolute_reach_momentum_ledger_error_m4s: float
    minimum_area_m2: float
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SUBCRITICAL_CONFLUENCE_NETWORK_STEP_SCHEMA,
            "upstream_states": [
                {
                    "area_m2": list(state.area_m2),
                    "discharge_m3s": list(state.discharge_m3s),
                }
                for state in self.upstream_states
            ],
            "downstream_state": {
                "area_m2": list(self.downstream_state.area_m2),
                "discharge_m3s": list(self.downstream_state.discharge_m3s),
            },
            "junction": self.junction.as_dict(),
            "timestep_seconds": self.timestep_seconds,
            "maximum_courant_number": self.maximum_courant_number,
            "volume_before_m3": self.volume_before_m3,
            "lateral_volume_change_m3": self.lateral_volume_change_m3,
            "external_boundary_volume_change_m3": (
                self.external_boundary_volume_change_m3
            ),
            "junction_mass_balance_residual_volume_m3": (
                self.junction_mass_balance_residual_volume_m3
            ),
            "volume_after_m3": self.volume_after_m3,
            "network_volume_balance_error_m3": (
                self.network_volume_balance_error_m3
            ),
            "maximum_absolute_reach_volume_ledger_error_m3": (
                self.maximum_absolute_reach_volume_ledger_error_m3
            ),
            "maximum_absolute_reach_momentum_ledger_error_m4s": (
                self.maximum_absolute_reach_momentum_ledger_error_m4s
            ),
            "minimum_area_m2": self.minimum_area_m2,
            "finite_state": True,
            "nonnegative_area": self.minimum_area_m2 >= 0.0,
            "junction_momentum_conservation_claimed": False,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class _PreparedReach:
    reach: DynamicWaveNetworkReach
    volume_before_m3: float
    momentum_before_m4s: float
    lateral_first: LateralInflowSourceStep
    momentum_after_lateral_first_m4s: float
    friction_first: ManningSlopeFrictionStep
    momentum_after_friction_first_m4s: float


@dataclass(frozen=True)
class _FinishedReach:
    state: PrismaticDynamicWaveState
    lateral_volume_change_m3: float
    volume_ledger_error_m3: float
    momentum_ledger_error_m4s: float
    hydrostatic: VariableGeometryHydrostaticOpenStep


def solve_subcritical_dynamic_wave_confluence(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    *,
    mass_balance_tolerance_m3s: float = 1e-12,
) -> SubcriticalConfluenceSolution:
    tolerance = float(mass_balance_tolerance_m3s)
    if (
        len(upstream) < 1
        or not math.isfinite(tolerance)
        or tolerance <= 0.0
    ):
        raise ValueError("dynamic_wave_confluence_contract_invalid")
    branch_ids = tuple(value.branch_id for value in upstream) + (
        downstream.branch_id,
    )
    if len(branch_ids) != len(set(branch_ids)):
        raise ValueError("dynamic_wave_confluence_branch_ids_not_unique")
    terminals = (*upstream, downstream)
    interior_surfaces = tuple(
        value.bed_elevation_m
        + value.section.depth_m(value.interior_state.area_m2)
        for value in terminals
    )
    maximum_bed = max(value.bed_elevation_m for value in terminals)
    reference_surface = float(np.median(interior_surfaces))
    reference_depth = max(1e-3, reference_surface - maximum_bed)
    depths = np.geomspace(
        max(1e-6, reference_depth * 1e-4),
        max(100.0, reference_depth * 1e4),
        601,
    )
    surfaces = sorted(
        set(float(maximum_bed + value) for value in depths)
        | set(float(value) for value in interior_surfaces if value > maximum_bed)
    )
    valid: list[
        tuple[
            float,
            float,
            tuple[ResolvedCharacteristicDynamicWaveBoundary, ...],
            ResolvedCharacteristicDynamicWaveBoundary,
        ]
    ] = []
    for surface in surfaces:
        try:
            upstream_states, downstream_state = _resolve_at_surface(
                upstream, downstream, surface
            )
        except ValueError:
            continue
        residual = sum(
            value.state.discharge_m3s for value in upstream_states
        ) - downstream_state.state.discharge_m3s
        valid.append(
            (surface, residual, upstream_states, downstream_state)
        )
        if abs(residual) <= tolerance:
            return _solution(
                upstream,
                downstream,
                surface,
                upstream_states,
                downstream_state,
                residual,
                surface,
                surface,
            )
    brackets = [
        (left, right)
        for left, right in zip(valid, valid[1:])
        if left[1] * right[1] < 0.0
    ]
    if not brackets:
        raise ValueError("dynamic_wave_confluence_no_subcritical_root")
    lower_entry, upper_entry = min(
        brackets,
        key=lambda pair: abs(
            0.5 * (pair[0][0] + pair[1][0]) - reference_surface
        ),
    )
    bracket_lower = lower_entry[0]
    bracket_upper = upper_entry[0]
    lower = bracket_lower
    upper = bracket_upper
    lower_value = lower_entry[1]
    resolved_upstream = lower_entry[2]
    resolved_downstream = lower_entry[3]
    residual = lower_value
    surface = lower
    for _ in range(100):
        surface = 0.5 * (lower + upper)
        resolved_upstream, resolved_downstream = _resolve_at_surface(
            upstream, downstream, surface
        )
        residual = sum(
            value.state.discharge_m3s for value in resolved_upstream
        ) - resolved_downstream.state.discharge_m3s
        if abs(residual) <= tolerance:
            break
        if lower_value * residual <= 0.0:
            upper = surface
        else:
            lower = surface
            lower_value = residual
    if abs(residual) > tolerance:
        raise ValueError("dynamic_wave_confluence_root_tolerance_not_met")
    return _solution(
        upstream,
        downstream,
        surface,
        resolved_upstream,
        resolved_downstream,
        residual,
        bracket_lower,
        bracket_upper,
    )


def maximum_subcritical_confluence_stable_timestep_seconds(
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    *,
    upstream_left_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_right_boundary: FixedDynamicWaveBoundary,
    courant_number: float,
    lateral_momentum_convention: str = "zero_longitudinal_momentum",
) -> float:
    _validate_network_inputs(
        upstream_reaches,
        downstream_reach,
        upstream_left_boundaries,
    )
    junction = solve_subcritical_dynamic_wave_confluence(
        tuple(_upstream_terminal(value) for value in upstream_reaches),
        _downstream_terminal(downstream_reach),
    )
    candidate = _minimum_network_hydrostatic_timestep(
        upstream_reaches,
        downstream_reach,
        upstream_states=tuple(value.state for value in upstream_reaches),
        downstream_state=downstream_reach.state,
        upstream_left_boundaries=upstream_left_boundaries,
        downstream_right_boundary=downstream_right_boundary,
        junction=junction,
        courant_number=courant_number,
    )
    for _ in range(12):
        half_timestep = 0.5 * candidate
        prepared_upstream = tuple(
            _prepare_reach(
                value, half_timestep, lateral_momentum_convention
            )
            for value in upstream_reaches
        )
        prepared_downstream = _prepare_reach(
            downstream_reach,
            half_timestep,
            lateral_momentum_convention,
        )
        prepared_junction = solve_subcritical_dynamic_wave_confluence(
            tuple(
                _upstream_terminal(
                    value.reach, state=value.friction_first.state
                )
                for value in prepared_upstream
            ),
            _downstream_terminal(
                prepared_downstream.reach,
                state=prepared_downstream.friction_first.state,
            ),
        )
        allowed = _minimum_network_hydrostatic_timestep(
            upstream_reaches,
            downstream_reach,
            upstream_states=tuple(
                value.friction_first.state for value in prepared_upstream
            ),
            downstream_state=prepared_downstream.friction_first.state,
            upstream_left_boundaries=upstream_left_boundaries,
            downstream_right_boundary=downstream_right_boundary,
            junction=prepared_junction,
            courant_number=courant_number,
        )
        if candidate <= allowed:
            return candidate
        candidate = allowed * (1.0 - 1e-12)
    raise RuntimeError("dynamic_wave_confluence_cfl_iteration_not_converged")


def advance_subcritical_confluence_network_open(
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    *,
    upstream_left_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_right_boundary: FixedDynamicWaveBoundary,
    lateral_momentum_convention: str,
    timestep_seconds: float,
    maximum_courant_number: float,
) -> SubcriticalConfluenceNetworkStep:
    _validate_network_inputs(
        upstream_reaches,
        downstream_reach,
        upstream_left_boundaries,
    )
    timestep = float(timestep_seconds)
    limit = float(maximum_courant_number)
    if (
        not math.isfinite(timestep)
        or timestep <= 0.0
        or not math.isfinite(limit)
        or not 0.0 < limit <= 1.0
    ):
        raise ValueError("dynamic_wave_confluence_step_contract_invalid")
    half_timestep = 0.5 * timestep
    prepared_upstream = tuple(
        _prepare_reach(value, half_timestep, lateral_momentum_convention)
        for value in upstream_reaches
    )
    prepared_downstream = _prepare_reach(
        downstream_reach, half_timestep, lateral_momentum_convention
    )
    junction = solve_subcritical_dynamic_wave_confluence(
        tuple(
            _upstream_terminal(value.reach, state=value.friction_first.state)
            for value in prepared_upstream
        ),
        _downstream_terminal(
            prepared_downstream.reach,
            state=prepared_downstream.friction_first.state,
        ),
    )
    upstream_finished = []
    for prepared, external, node in zip(
        prepared_upstream,
        upstream_left_boundaries,
        junction.upstream_boundaries,
        strict=True,
    ):
        reach = prepared.reach
        node_flux = dynamic_wave_physical_flux(
            node.state, reach.sections[-1]
        )
        hydrostatic = advance_variable_geometry_hydrostatic_open(
            prepared.friction_first.state,
            reach.bed_elevation_m,
            reach.sections,
            left_boundary_state=external.state,
            right_boundary_state=node.state,
            left_boundary_bed_elevation_m=external.bed_elevation_m,
            right_boundary_bed_elevation_m=reach.bed_elevation_m[-1],
            left_boundary_section=reach.sections[0],
            right_boundary_section=reach.sections[-1],
            cell_length_m=reach.cell_length_m,
            timestep_seconds=timestep,
            maximum_courant_number=limit,
            right_boundary_cell_flux_override=node_flux,
        )
        upstream_finished.append(
            _finish_reach(
                prepared,
                hydrostatic,
                half_timestep,
                lateral_momentum_convention,
            )
        )
    downstream_node_flux = dynamic_wave_physical_flux(
        junction.downstream_boundary.state,
        downstream_reach.sections[0],
    )
    downstream_hydrostatic = advance_variable_geometry_hydrostatic_open(
        prepared_downstream.friction_first.state,
        downstream_reach.bed_elevation_m,
        downstream_reach.sections,
        left_boundary_state=junction.downstream_boundary.state,
        right_boundary_state=downstream_right_boundary.state,
        left_boundary_bed_elevation_m=downstream_reach.bed_elevation_m[0],
        right_boundary_bed_elevation_m=(
            downstream_right_boundary.bed_elevation_m
        ),
        left_boundary_section=downstream_reach.sections[0],
        right_boundary_section=downstream_reach.sections[-1],
        cell_length_m=downstream_reach.cell_length_m,
        timestep_seconds=timestep,
        maximum_courant_number=limit,
        left_boundary_cell_flux_override=downstream_node_flux,
    )
    downstream_finished = _finish_reach(
        prepared_downstream,
        downstream_hydrostatic,
        half_timestep,
        lateral_momentum_convention,
    )
    all_prepared = (*prepared_upstream, prepared_downstream)
    all_finished = (*upstream_finished, downstream_finished)
    volume_before = sum(value.volume_before_m3 for value in all_prepared)
    lateral_volume = sum(
        value.lateral_volume_change_m3 for value in all_finished
    )
    external_volume = timestep * (
        sum(
            value.hydrostatic.left_boundary_area_flux_m3s
            for value in upstream_finished
        )
        - downstream_finished.hydrostatic.right_boundary_area_flux_m3s
    )
    junction_residual_volume = (
        timestep * junction.junction_mass_balance_residual_m3s
    )
    volume_after = sum(
        _volume(value.state, prepared.reach.cell_length_m)
        for value, prepared in zip(
            all_finished, all_prepared, strict=True
        )
    )
    return SubcriticalConfluenceNetworkStep(
        upstream_states=tuple(value.state for value in upstream_finished),
        downstream_state=downstream_finished.state,
        junction=junction,
        timestep_seconds=timestep,
        maximum_courant_number=max(
            value.hydrostatic.maximum_courant_number
            for value in all_finished
        ),
        volume_before_m3=volume_before,
        lateral_volume_change_m3=lateral_volume,
        external_boundary_volume_change_m3=external_volume,
        junction_mass_balance_residual_volume_m3=junction_residual_volume,
        volume_after_m3=volume_after,
        network_volume_balance_error_m3=(
            volume_after
            - volume_before
            - lateral_volume
            - external_volume
            + junction_residual_volume
        ),
        maximum_absolute_reach_volume_ledger_error_m3=max(
            abs(value.volume_ledger_error_m3) for value in all_finished
        ),
        maximum_absolute_reach_momentum_ledger_error_m4s=max(
            abs(value.momentum_ledger_error_m4s) for value in all_finished
        ),
        minimum_area_m2=min(
            min(value.state.area_m2) for value in all_finished
        ),
    )


def _prepare_reach(
    reach: DynamicWaveNetworkReach,
    half_timestep: float,
    momentum_convention: str,
) -> _PreparedReach:
    volume_before = _volume(reach.state, reach.cell_length_m)
    momentum_before = _momentum(reach.state, reach.cell_length_m)
    lateral_first = apply_lateral_inflow_source(
        reach.state,
        lateral_inflow_m2s=reach.lateral_inflow_m2s,
        timestep_seconds=half_timestep,
        cell_length_m=reach.cell_length_m,
        momentum_convention=momentum_convention,
    )
    momentum_after_lateral = _momentum(
        lateral_first.state, reach.cell_length_m
    )
    friction_first = apply_variable_geometry_manning_friction_only_source(
        lateral_first.state,
        reach.sections,
        manning_n=reach.manning_n,
        timestep_seconds=half_timestep,
        cell_length_m=reach.cell_length_m,
    )
    return _PreparedReach(
        reach=reach,
        volume_before_m3=volume_before,
        momentum_before_m4s=momentum_before,
        lateral_first=lateral_first,
        momentum_after_lateral_first_m4s=momentum_after_lateral,
        friction_first=friction_first,
        momentum_after_friction_first_m4s=_momentum(
            friction_first.state, reach.cell_length_m
        ),
    )


def _finish_reach(
    prepared: _PreparedReach,
    hydrostatic: VariableGeometryHydrostaticOpenStep,
    half_timestep: float,
    momentum_convention: str,
) -> _FinishedReach:
    reach = prepared.reach
    momentum_after_hydrostatic = _momentum(
        hydrostatic.state, reach.cell_length_m
    )
    friction_second = apply_variable_geometry_manning_friction_only_source(
        hydrostatic.state,
        reach.sections,
        manning_n=reach.manning_n,
        timestep_seconds=half_timestep,
        cell_length_m=reach.cell_length_m,
    )
    momentum_after_friction = _momentum(
        friction_second.state, reach.cell_length_m
    )
    lateral_second = apply_lateral_inflow_source(
        friction_second.state,
        lateral_inflow_m2s=reach.lateral_inflow_m2s,
        timestep_seconds=half_timestep,
        cell_length_m=reach.cell_length_m,
        momentum_convention=momentum_convention,
    )
    state = lateral_second.state
    momentum_after = _momentum(state, reach.cell_length_m)
    lateral_volume = (
        prepared.lateral_first.prescribed_lateral_volume_m3
        + lateral_second.prescribed_lateral_volume_m3
    )
    lateral_momentum = (
        prepared.momentum_after_lateral_first_m4s
        - prepared.momentum_before_m4s
        + momentum_after
        - momentum_after_friction
    )
    friction_momentum = (
        prepared.momentum_after_friction_first_m4s
        - prepared.momentum_after_lateral_first_m4s
        + momentum_after_friction
        - momentum_after_hydrostatic
    )
    hydrostatic_momentum = (
        momentum_after_hydrostatic
        - prepared.momentum_after_friction_first_m4s
    )
    return _FinishedReach(
        state=state,
        lateral_volume_change_m3=lateral_volume,
        volume_ledger_error_m3=(
            _volume(state, reach.cell_length_m)
            - prepared.volume_before_m3
            - lateral_volume
            - hydrostatic.prescribed_boundary_volume_change_m3
        ),
        momentum_ledger_error_m4s=(
            momentum_after
            - prepared.momentum_before_m4s
            - lateral_momentum
            - friction_momentum
            - hydrostatic_momentum
        ),
        hydrostatic=hydrostatic,
    )


def _resolve_at_surface(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    surface_elevation_m: float,
) -> tuple[
    tuple[ResolvedCharacteristicDynamicWaveBoundary, ...],
    ResolvedCharacteristicDynamicWaveBoundary,
]:
    upstream_states = tuple(
        resolve_characteristic_dynamic_wave_boundary(
            CharacteristicDynamicWaveBoundary(
                side="right",
                prescribed_quantity="free_surface_elevation_m",
                prescribed_value=surface_elevation_m,
                bed_elevation_m=value.bed_elevation_m,
            ),
            value.interior_state,
            value.section,
        )
        for value in upstream
    )
    downstream_state = resolve_characteristic_dynamic_wave_boundary(
        CharacteristicDynamicWaveBoundary(
            side="left",
            prescribed_quantity="free_surface_elevation_m",
            prescribed_value=surface_elevation_m,
            bed_elevation_m=downstream.bed_elevation_m,
        ),
        downstream.interior_state,
        downstream.section,
    )
    return upstream_states, downstream_state


def _solution(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    surface: float,
    upstream_states: tuple[
        ResolvedCharacteristicDynamicWaveBoundary, ...
    ],
    downstream_state: ResolvedCharacteristicDynamicWaveBoundary,
    residual: float,
    bracket_lower: float,
    bracket_upper: float,
) -> SubcriticalConfluenceSolution:
    return SubcriticalConfluenceSolution(
        common_free_surface_elevation_m=surface,
        upstream_branch_ids=tuple(value.branch_id for value in upstream),
        upstream_boundaries=upstream_states,
        downstream_branch_id=downstream.branch_id,
        downstream_boundary=downstream_state,
        total_upstream_discharge_m3s=sum(
            value.state.discharge_m3s for value in upstream_states
        ),
        downstream_discharge_m3s=(
            downstream_state.state.discharge_m3s
        ),
        junction_mass_balance_residual_m3s=residual,
        maximum_absolute_outgoing_invariant_residual_mps=max(
            abs(value.outgoing_invariant_residual_mps)
            for value in (*upstream_states, downstream_state)
        ),
        root_bracket_lower_m=bracket_lower,
        root_bracket_upper_m=bracket_upper,
    )


def _validate_network_inputs(
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    upstream_left_boundaries: tuple[FixedDynamicWaveBoundary, ...],
) -> None:
    if (
        len(upstream_reaches) < 2
        or len(upstream_left_boundaries) != len(upstream_reaches)
    ):
        raise ValueError("dynamic_wave_confluence_network_contract_invalid")
    reach_ids = tuple(value.reach_id for value in upstream_reaches) + (
        downstream_reach.reach_id,
    )
    if len(reach_ids) != len(set(reach_ids)):
        raise ValueError("dynamic_wave_confluence_network_reach_ids_not_unique")


def _minimum_network_hydrostatic_timestep(
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    *,
    upstream_states: tuple[PrismaticDynamicWaveState, ...],
    downstream_state: PrismaticDynamicWaveState,
    upstream_left_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_right_boundary: FixedDynamicWaveBoundary,
    junction: SubcriticalConfluenceSolution,
    courant_number: float,
) -> float:
    timesteps = []
    for reach, state, external, node in zip(
        upstream_reaches,
        upstream_states,
        upstream_left_boundaries,
        junction.upstream_boundaries,
        strict=True,
    ):
        timestep = maximum_variable_geometry_open_stable_timestep_seconds(
            state,
            reach.sections,
            left_boundary_state=external.state,
            right_boundary_state=node.state,
            left_boundary_section=reach.sections[0],
            right_boundary_section=reach.sections[-1],
            cell_length_m=reach.cell_length_m,
            courant_number=courant_number,
        )
        if timestep is not None:
            timesteps.append(timestep)
    downstream_timestep = (
        maximum_variable_geometry_open_stable_timestep_seconds(
            downstream_state,
            downstream_reach.sections,
            left_boundary_state=junction.downstream_boundary.state,
            right_boundary_state=downstream_right_boundary.state,
            left_boundary_section=downstream_reach.sections[0],
            right_boundary_section=downstream_reach.sections[-1],
            cell_length_m=downstream_reach.cell_length_m,
            courant_number=courant_number,
        )
    )
    if downstream_timestep is not None:
        timesteps.append(downstream_timestep)
    if not timesteps:
        raise RuntimeError("dynamic_wave_confluence_timestep_undefined")
    return min(timesteps)


def _upstream_terminal(
    reach: DynamicWaveNetworkReach,
    *,
    state: PrismaticDynamicWaveState | None = None,
) -> DynamicWaveJunctionTerminal:
    current = reach.state if state is None else state
    return DynamicWaveJunctionTerminal(
        branch_id=reach.reach_id,
        interior_state=DynamicWaveCellState(
            current.area_m2[-1], current.discharge_m3s[-1]
        ),
        section=reach.sections[-1],
        bed_elevation_m=reach.bed_elevation_m[-1],
    )


def _downstream_terminal(
    reach: DynamicWaveNetworkReach,
    *,
    state: PrismaticDynamicWaveState | None = None,
) -> DynamicWaveJunctionTerminal:
    current = reach.state if state is None else state
    return DynamicWaveJunctionTerminal(
        branch_id=reach.reach_id,
        interior_state=DynamicWaveCellState(
            current.area_m2[0], current.discharge_m3s[0]
        ),
        section=reach.sections[0],
        bed_elevation_m=reach.bed_elevation_m[0],
    )


def _volume(state: PrismaticDynamicWaveState, cell_length_m: float) -> float:
    return float(sum(state.area_m2) * cell_length_m)


def _momentum(state: PrismaticDynamicWaveState, cell_length_m: float) -> float:
    return float(sum(state.discharge_m3s) * cell_length_m)
