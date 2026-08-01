"""Synchronous dynamic-wave scheduling over a dendritic reach DAG."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

from .dynamic_wave_coupled import FixedDynamicWaveBoundary
from .dynamic_wave_flux import (
    DynamicWaveCellState,
    DynamicWaveFlux,
    PrismaticDynamicWaveState,
    dynamic_wave_physical_flux,
)
from .dynamic_wave_junction import (
    DynamicWaveNetworkReach,
    SubcriticalConfluenceSolution,
    _FinishedReach,
    _PreparedReach,
    _downstream_terminal,
    _finish_reach,
    _prepare_reach,
    _upstream_terminal,
    solve_subcritical_dynamic_wave_confluence,
)
from .dynamic_wave_junction_energy import (
    DynamicWaveJunctionEnergyLoss,
    SubcriticalEnergyJunctionSolution,
    solve_subcritical_dynamic_wave_energy_junction,
)
from .dynamic_wave_variable_geometry import (
    advance_variable_geometry_hydrostatic_open,
    maximum_variable_geometry_open_stable_timestep_seconds,
)


DENDRITIC_DYNAMIC_WAVE_NETWORK_STEP_SCHEMA = (
    "gwm.geospatial_kernel.dendritic_dynamic_wave_network_step.v1"
)
DynamicWaveJunctionSolution = (
    SubcriticalConfluenceSolution | SubcriticalEnergyJunctionSolution
)


@dataclass(frozen=True)
class DynamicWaveDendriticTopology:
    """A connected, acyclic reach graph with one outlet and no bifurcation."""

    reach_ids: tuple[str, ...]
    downstream_reach_ids: tuple[str | None, ...]

    def __post_init__(self) -> None:
        reach_ids = tuple(self.reach_ids)
        downstream_ids = tuple(self.downstream_reach_ids)
        if (
            not reach_ids
            or len(reach_ids) != len(downstream_ids)
            or any(
                not isinstance(value, str) or not value.strip()
                for value in reach_ids
            )
            or len(reach_ids) != len(set(reach_ids))
            or sum(value is None for value in downstream_ids) != 1
            or any(
                value is not None
                and (not isinstance(value, str) or value not in reach_ids)
                for value in downstream_ids
            )
        ):
            raise ValueError("dynamic_wave_dendritic_topology_invalid")
        downstream_by_id = dict(zip(reach_ids, downstream_ids, strict=True))
        if any(
            downstream_by_id[reach_id] == reach_id for reach_id in reach_ids
        ):
            raise ValueError("dynamic_wave_dendritic_topology_cycle")
        for origin in reach_ids:
            visited: set[str] = set()
            current: str | None = origin
            while current is not None:
                if current in visited:
                    raise ValueError("dynamic_wave_dendritic_topology_cycle")
                visited.add(current)
                current = downstream_by_id[current]
        object.__setattr__(self, "reach_ids", reach_ids)
        object.__setattr__(self, "downstream_reach_ids", downstream_ids)

    @property
    def outlet_reach_id(self) -> str:
        return self.reach_ids[self.downstream_reach_ids.index(None)]

    @property
    def source_reach_ids(self) -> tuple[str, ...]:
        non_sources = {
            value for value in self.downstream_reach_ids if value is not None
        }
        return tuple(value for value in self.reach_ids if value not in non_sources)

    @property
    def junction_reach_ids(self) -> tuple[str, ...]:
        targets = {
            value for value in self.downstream_reach_ids if value is not None
        }
        return tuple(value for value in self.reach_ids if value in targets)

    def downstream_reach_id(self, reach_id: str) -> str | None:
        try:
            index = self.reach_ids.index(reach_id)
        except ValueError as exc:
            raise KeyError(reach_id) from exc
        return self.downstream_reach_ids[index]

    def upstream_reach_ids(self, reach_id: str) -> tuple[str, ...]:
        if reach_id not in self.reach_ids:
            raise KeyError(reach_id)
        return tuple(
            candidate
            for candidate, downstream in zip(
                self.reach_ids, self.downstream_reach_ids, strict=True
            )
            if downstream == reach_id
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "reach_ids": list(self.reach_ids),
            "downstream_reach_ids": list(self.downstream_reach_ids),
            "source_reach_ids": list(self.source_reach_ids),
            "junction_reach_ids": list(self.junction_reach_ids),
            "outlet_reach_id": self.outlet_reach_id,
            "single_outlet": True,
            "acyclic": True,
            "bifurcation_supported": False,
        }


@dataclass(frozen=True)
class DendriticDynamicWaveNetworkStep:
    topology: DynamicWaveDendriticTopology
    states: tuple[PrismaticDynamicWaveState, ...]
    junctions: tuple[DynamicWaveJunctionSolution, ...]
    timestep_seconds: float
    maximum_courant_number: float
    volume_before_m3: float
    lateral_volume_change_m3: float
    source_boundary_inflow_volume_m3: float
    outlet_boundary_outflow_volume_m3: float
    junction_mass_balance_residual_volume_m3: float
    volume_after_m3: float
    network_volume_balance_error_m3: float
    maximum_absolute_node_mass_balance_residual_m3s: float
    maximum_absolute_outgoing_invariant_residual_mps: float
    maximum_absolute_reach_volume_ledger_error_m3: float
    maximum_absolute_reach_momentum_ledger_error_m4s: float
    minimum_area_m2: float
    diagnostic_only: bool = True

    def state_for_reach(self, reach_id: str) -> PrismaticDynamicWaveState:
        try:
            return self.states[self.topology.reach_ids.index(reach_id)]
        except ValueError as exc:
            raise KeyError(reach_id) from exc

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": DENDRITIC_DYNAMIC_WAVE_NETWORK_STEP_SCHEMA,
            "topology": self.topology.as_dict(),
            "reach_states": {
                reach_id: {
                    "area_m2": list(state.area_m2),
                    "discharge_m3s": list(state.discharge_m3s),
                }
                for reach_id, state in zip(
                    self.topology.reach_ids, self.states, strict=True
                )
            },
            "junctions": [value.as_dict() for value in self.junctions],
            "timestep_seconds": self.timestep_seconds,
            "maximum_courant_number": self.maximum_courant_number,
            "volume_before_m3": self.volume_before_m3,
            "lateral_volume_change_m3": self.lateral_volume_change_m3,
            "source_boundary_inflow_volume_m3": (
                self.source_boundary_inflow_volume_m3
            ),
            "outlet_boundary_outflow_volume_m3": (
                self.outlet_boundary_outflow_volume_m3
            ),
            "junction_mass_balance_residual_volume_m3": (
                self.junction_mass_balance_residual_volume_m3
            ),
            "volume_after_m3": self.volume_after_m3,
            "network_volume_balance_error_m3": (
                self.network_volume_balance_error_m3
            ),
            "maximum_absolute_node_mass_balance_residual_m3s": (
                self.maximum_absolute_node_mass_balance_residual_m3s
            ),
            "maximum_absolute_outgoing_invariant_residual_mps": (
                self.maximum_absolute_outgoing_invariant_residual_mps
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
class _BoundaryBindings:
    left_states: Mapping[str, DynamicWaveCellState]
    right_states: Mapping[str, DynamicWaveCellState]
    left_flux_overrides: Mapping[str, DynamicWaveFlux]
    right_flux_overrides: Mapping[str, DynamicWaveFlux]


def maximum_dendritic_dynamic_wave_stable_timestep_seconds(
    topology: DynamicWaveDendriticTopology,
    reaches: tuple[DynamicWaveNetworkReach, ...],
    *,
    source_left_boundaries: Mapping[str, FixedDynamicWaveBoundary],
    outlet_right_boundary: FixedDynamicWaveBoundary,
    courant_number: float,
    lateral_momentum_convention: str = "zero_longitudinal_momentum",
    junction_energy_losses: (
        Mapping[str, DynamicWaveJunctionEnergyLoss] | None
    ) = None,
) -> float:
    reach_by_id, source_boundaries = _validate_network_inputs(
        topology,
        reaches,
        source_left_boundaries,
        outlet_right_boundary,
    )
    energy_loss_by_id = _validate_junction_energy_losses(
        topology, junction_energy_losses
    )
    junction_by_id = _solve_junctions(
        topology, reach_by_id, energy_loss_by_id
    )
    candidate = _minimum_network_hydrostatic_timestep(
        topology,
        reach_by_id,
        source_boundaries,
        outlet_right_boundary,
        junction_by_id,
        courant_number,
    )
    for _ in range(12):
        half_timestep = 0.5 * candidate
        prepared = {
            reach_id: _prepare_reach(
                reach_by_id[reach_id],
                half_timestep,
                lateral_momentum_convention,
            )
            for reach_id in topology.reach_ids
        }
        prepared_reaches = {
            reach_id: _reach_with_state(
                reach_by_id[reach_id], prepared[reach_id].friction_first.state
            )
            for reach_id in topology.reach_ids
        }
        prepared_junctions = _solve_junctions(
            topology, prepared_reaches, energy_loss_by_id
        )
        allowed = _minimum_network_hydrostatic_timestep(
            topology,
            prepared_reaches,
            source_boundaries,
            outlet_right_boundary,
            prepared_junctions,
            courant_number,
        )
        if candidate <= allowed:
            return candidate
        candidate = allowed * (1.0 - 1e-12)
    raise RuntimeError("dynamic_wave_dendritic_cfl_iteration_not_converged")


def advance_dendritic_dynamic_wave_network_open(
    topology: DynamicWaveDendriticTopology,
    reaches: tuple[DynamicWaveNetworkReach, ...],
    *,
    source_left_boundaries: Mapping[str, FixedDynamicWaveBoundary],
    outlet_right_boundary: FixedDynamicWaveBoundary,
    timestep_seconds: float,
    maximum_courant_number: float,
    lateral_momentum_convention: str,
    junction_energy_losses: (
        Mapping[str, DynamicWaveJunctionEnergyLoss] | None
    ) = None,
) -> DendriticDynamicWaveNetworkStep:
    reach_by_id, source_boundaries = _validate_network_inputs(
        topology,
        reaches,
        source_left_boundaries,
        outlet_right_boundary,
    )
    energy_loss_by_id = _validate_junction_energy_losses(
        topology, junction_energy_losses
    )
    timestep = float(timestep_seconds)
    limit = float(maximum_courant_number)
    if (
        not math.isfinite(timestep)
        or timestep <= 0.0
        or not math.isfinite(limit)
        or not 0.0 < limit <= 1.0
    ):
        raise ValueError("dynamic_wave_dendritic_step_contract_invalid")
    half_timestep = 0.5 * timestep
    prepared: dict[str, _PreparedReach] = {
        reach_id: _prepare_reach(
            reach_by_id[reach_id],
            half_timestep,
            lateral_momentum_convention,
        )
        for reach_id in topology.reach_ids
    }
    prepared_reaches = {
        reach_id: _reach_with_state(
            reach_by_id[reach_id], prepared[reach_id].friction_first.state
        )
        for reach_id in topology.reach_ids
    }
    junction_by_id = _solve_junctions(
        topology, prepared_reaches, energy_loss_by_id
    )
    bindings = _boundary_bindings(
        topology,
        prepared_reaches,
        source_boundaries,
        outlet_right_boundary,
        junction_by_id,
    )
    finished: dict[str, _FinishedReach] = {}
    for reach_id in topology.reach_ids:
        reach = reach_by_id[reach_id]
        left_external = source_boundaries.get(reach_id)
        right_external = (
            outlet_right_boundary
            if reach_id == topology.outlet_reach_id
            else None
        )
        hydrostatic = advance_variable_geometry_hydrostatic_open(
            prepared[reach_id].friction_first.state,
            reach.bed_elevation_m,
            reach.sections,
            left_boundary_state=bindings.left_states[reach_id],
            right_boundary_state=bindings.right_states[reach_id],
            left_boundary_bed_elevation_m=(
                left_external.bed_elevation_m
                if left_external is not None
                else reach.bed_elevation_m[0]
            ),
            right_boundary_bed_elevation_m=(
                right_external.bed_elevation_m
                if right_external is not None
                else reach.bed_elevation_m[-1]
            ),
            left_boundary_section=reach.sections[0],
            right_boundary_section=reach.sections[-1],
            cell_length_m=reach.cell_length_m,
            timestep_seconds=timestep,
            maximum_courant_number=limit,
            left_boundary_cell_flux_override=(
                bindings.left_flux_overrides.get(reach_id)
            ),
            right_boundary_cell_flux_override=(
                bindings.right_flux_overrides.get(reach_id)
            ),
        )
        finished[reach_id] = _finish_reach(
            prepared[reach_id],
            hydrostatic,
            half_timestep,
            lateral_momentum_convention,
        )
    ordered_finished = tuple(finished[value] for value in topology.reach_ids)
    volume_before = sum(
        prepared[value].volume_before_m3 for value in topology.reach_ids
    )
    lateral_volume = sum(
        value.lateral_volume_change_m3 for value in ordered_finished
    )
    source_inflow = timestep * sum(
        finished[value].hydrostatic.left_boundary_area_flux_m3s
        for value in topology.source_reach_ids
    )
    outlet_outflow = (
        timestep
        * finished[
            topology.outlet_reach_id
        ].hydrostatic.right_boundary_area_flux_m3s
    )
    junction_residual_volume = timestep * sum(
        value.junction_mass_balance_residual_m3s
        for value in junction_by_id.values()
    )
    volume_after = sum(
        _volume(finished[reach_id].state, reach_by_id[reach_id].cell_length_m)
        for reach_id in topology.reach_ids
    )
    junctions = tuple(
        junction_by_id[value] for value in topology.junction_reach_ids
    )
    return DendriticDynamicWaveNetworkStep(
        topology=topology,
        states=tuple(value.state for value in ordered_finished),
        junctions=junctions,
        timestep_seconds=timestep,
        maximum_courant_number=max(
            value.hydrostatic.maximum_courant_number
            for value in ordered_finished
        ),
        volume_before_m3=volume_before,
        lateral_volume_change_m3=lateral_volume,
        source_boundary_inflow_volume_m3=source_inflow,
        outlet_boundary_outflow_volume_m3=outlet_outflow,
        junction_mass_balance_residual_volume_m3=(
            junction_residual_volume
        ),
        volume_after_m3=volume_after,
        network_volume_balance_error_m3=(
            volume_after
            - volume_before
            - lateral_volume
            - source_inflow
            + outlet_outflow
            + junction_residual_volume
        ),
        maximum_absolute_node_mass_balance_residual_m3s=max(
            (
                abs(value.junction_mass_balance_residual_m3s)
                for value in junctions
            ),
            default=0.0,
        ),
        maximum_absolute_outgoing_invariant_residual_mps=max(
            (
                value.maximum_absolute_outgoing_invariant_residual_mps
                for value in junctions
            ),
            default=0.0,
        ),
        maximum_absolute_reach_volume_ledger_error_m3=max(
            abs(value.volume_ledger_error_m3) for value in ordered_finished
        ),
        maximum_absolute_reach_momentum_ledger_error_m4s=max(
            abs(value.momentum_ledger_error_m4s)
            for value in ordered_finished
        ),
        minimum_area_m2=min(
            min(value.state.area_m2) for value in ordered_finished
        ),
    )


def _validate_network_inputs(
    topology: DynamicWaveDendriticTopology,
    reaches: tuple[DynamicWaveNetworkReach, ...],
    source_left_boundaries: Mapping[str, FixedDynamicWaveBoundary],
    outlet_right_boundary: FixedDynamicWaveBoundary,
) -> tuple[
    dict[str, DynamicWaveNetworkReach], dict[str, FixedDynamicWaveBoundary]
]:
    reach_by_id = {value.reach_id: value for value in reaches}
    source_boundaries = dict(source_left_boundaries)
    if (
        len(reach_by_id) != len(reaches)
        or set(reach_by_id) != set(topology.reach_ids)
        or set(source_boundaries) != set(topology.source_reach_ids)
        or not isinstance(outlet_right_boundary, FixedDynamicWaveBoundary)
        or any(
            not isinstance(value, FixedDynamicWaveBoundary)
            for value in source_boundaries.values()
        )
    ):
        raise ValueError("dynamic_wave_dendritic_network_contract_invalid")
    return reach_by_id, source_boundaries


def _solve_junctions(
    topology: DynamicWaveDendriticTopology,
    reach_by_id: Mapping[str, DynamicWaveNetworkReach],
    energy_loss_by_id: Mapping[str, DynamicWaveJunctionEnergyLoss] | None,
) -> dict[str, DynamicWaveJunctionSolution]:
    return {
        downstream_id: _solve_junction(
            topology,
            reach_by_id,
            downstream_id,
            None
            if energy_loss_by_id is None
            else energy_loss_by_id[downstream_id],
        )
        for downstream_id in topology.junction_reach_ids
    }


def _solve_junction(
    topology: DynamicWaveDendriticTopology,
    reach_by_id: Mapping[str, DynamicWaveNetworkReach],
    downstream_id: str,
    energy_loss: DynamicWaveJunctionEnergyLoss | None,
) -> DynamicWaveJunctionSolution:
    upstream = tuple(
        _upstream_terminal(reach_by_id[value])
        for value in topology.upstream_reach_ids(downstream_id)
    )
    downstream = _downstream_terminal(reach_by_id[downstream_id])
    if energy_loss is None:
        return solve_subcritical_dynamic_wave_confluence(upstream, downstream)
    return solve_subcritical_dynamic_wave_energy_junction(
        upstream, downstream, energy_loss
    )


def _validate_junction_energy_losses(
    topology: DynamicWaveDendriticTopology,
    junction_energy_losses: (
        Mapping[str, DynamicWaveJunctionEnergyLoss] | None
    ),
) -> dict[str, DynamicWaveJunctionEnergyLoss] | None:
    if junction_energy_losses is None:
        return None
    loss_by_id = dict(junction_energy_losses)
    if (
        set(loss_by_id) != set(topology.junction_reach_ids)
        or any(
            not isinstance(value, DynamicWaveJunctionEnergyLoss)
            for value in loss_by_id.values()
        )
        or any(
            loss_by_id[junction_id].upstream_branch_ids
            != topology.upstream_reach_ids(junction_id)
            for junction_id in topology.junction_reach_ids
        )
    ):
        raise ValueError("dynamic_wave_dendritic_energy_loss_contract_invalid")
    return loss_by_id


def _boundary_bindings(
    topology: DynamicWaveDendriticTopology,
    reach_by_id: Mapping[str, DynamicWaveNetworkReach],
    source_boundaries: Mapping[str, FixedDynamicWaveBoundary],
    outlet_right_boundary: FixedDynamicWaveBoundary,
    junction_by_id: Mapping[str, DynamicWaveJunctionSolution],
) -> _BoundaryBindings:
    left_states: dict[str, DynamicWaveCellState] = {}
    right_states: dict[str, DynamicWaveCellState] = {}
    left_fluxes: dict[str, DynamicWaveFlux] = {}
    right_fluxes: dict[str, DynamicWaveFlux] = {}
    upstream_boundary_by_id = {
        branch_id: boundary
        for junction in junction_by_id.values()
        for branch_id, boundary in zip(
            junction.upstream_branch_ids,
            junction.upstream_boundaries,
            strict=True,
        )
    }
    for reach_id in topology.reach_ids:
        reach = reach_by_id[reach_id]
        if reach_id in source_boundaries:
            left_states[reach_id] = source_boundaries[reach_id].state
        else:
            boundary = junction_by_id[reach_id].downstream_boundary.state
            left_states[reach_id] = boundary
            left_fluxes[reach_id] = dynamic_wave_physical_flux(
                boundary, reach.sections[0]
            )
        downstream_id = topology.downstream_reach_id(reach_id)
        if downstream_id is None:
            right_states[reach_id] = outlet_right_boundary.state
        else:
            boundary = upstream_boundary_by_id[reach_id].state
            right_states[reach_id] = boundary
            right_fluxes[reach_id] = dynamic_wave_physical_flux(
                boundary, reach.sections[-1]
            )
    return _BoundaryBindings(
        left_states=left_states,
        right_states=right_states,
        left_flux_overrides=left_fluxes,
        right_flux_overrides=right_fluxes,
    )


def _minimum_network_hydrostatic_timestep(
    topology: DynamicWaveDendriticTopology,
    reach_by_id: Mapping[str, DynamicWaveNetworkReach],
    source_boundaries: Mapping[str, FixedDynamicWaveBoundary],
    outlet_right_boundary: FixedDynamicWaveBoundary,
    junction_by_id: Mapping[str, DynamicWaveJunctionSolution],
    courant_number: float,
) -> float:
    bindings = _boundary_bindings(
        topology,
        reach_by_id,
        source_boundaries,
        outlet_right_boundary,
        junction_by_id,
    )
    timesteps = []
    for reach_id in topology.reach_ids:
        reach = reach_by_id[reach_id]
        timestep = maximum_variable_geometry_open_stable_timestep_seconds(
            reach.state,
            reach.sections,
            left_boundary_state=bindings.left_states[reach_id],
            right_boundary_state=bindings.right_states[reach_id],
            left_boundary_section=reach.sections[0],
            right_boundary_section=reach.sections[-1],
            cell_length_m=reach.cell_length_m,
            courant_number=courant_number,
        )
        if timestep is not None:
            timesteps.append(timestep)
    if not timesteps:
        raise RuntimeError("dynamic_wave_dendritic_timestep_undefined")
    return min(timesteps)


def _reach_with_state(
    reach: DynamicWaveNetworkReach,
    state: PrismaticDynamicWaveState,
) -> DynamicWaveNetworkReach:
    return DynamicWaveNetworkReach(
        reach_id=reach.reach_id,
        state=state,
        bed_elevation_m=reach.bed_elevation_m,
        sections=reach.sections,
        cell_length_m=reach.cell_length_m,
        manning_n=reach.manning_n,
        lateral_inflow_m2s=reach.lateral_inflow_m2s,
    )


def _volume(state: PrismaticDynamicWaveState, cell_length_m: float) -> float:
    return float(sum(state.area_m2) * cell_length_m)
