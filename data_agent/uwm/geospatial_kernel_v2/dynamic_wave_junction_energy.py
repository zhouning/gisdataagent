"""Subcritical junction closure with explicit branch energy losses."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import math

import numpy as np

from .dynamic_wave_boundaries import (
    CharacteristicDynamicWaveBoundary,
    ResolvedCharacteristicDynamicWaveBoundary,
    dynamic_wave_characteristic_potential_mps,
    resolve_characteristic_dynamic_wave_boundary,
)
from .dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    dynamic_wave_characteristic_speeds_mps,
)
from .dynamic_wave_junction import DynamicWaveJunctionTerminal


SUBCRITICAL_ENERGY_JUNCTION_SCHEMA = (
    "gwm.geospatial_kernel.subcritical_dynamic_wave_energy_junction.v1"
)
_AREA_LOG_OFFSETS = np.linspace(-4.0, 4.0, 201)
_INTERIOR_AREA_INDEX = len(_AREA_LOG_OFFSETS) // 2
_FLOW_DIRECTION_TOLERANCE_M3S = 1e-12


@dataclass(frozen=True)
class DynamicWaveJunctionEnergyLoss:
    upstream_branch_ids: tuple[str, ...]
    upstream_loss_coefficients: tuple[float, ...]
    downstream_loss_coefficient: float

    def __post_init__(self) -> None:
        branch_ids = tuple(self.upstream_branch_ids)
        coefficients = tuple(
            float(value) for value in self.upstream_loss_coefficients
        )
        downstream = float(self.downstream_loss_coefficient)
        if (
            not branch_ids
            or len(branch_ids) != len(coefficients)
            or len(branch_ids) != len(set(branch_ids))
            or any(
                not isinstance(value, str) or not value.strip()
                for value in branch_ids
            )
            or any(not math.isfinite(value) or value < 0.0 for value in coefficients)
            or not math.isfinite(downstream)
            or downstream < 0.0
        ):
            raise ValueError("dynamic_wave_junction_energy_loss_invalid")
        object.__setattr__(self, "upstream_branch_ids", branch_ids)
        object.__setattr__(self, "upstream_loss_coefficients", coefficients)
        object.__setattr__(self, "downstream_loss_coefficient", downstream)

    def upstream_coefficient(self, branch_id: str) -> float:
        try:
            return self.upstream_loss_coefficients[
                self.upstream_branch_ids.index(branch_id)
            ]
        except ValueError as exc:
            raise KeyError(branch_id) from exc

    def as_dict(self) -> dict[str, object]:
        return {
            "upstream_loss_coefficients": dict(
                zip(
                    self.upstream_branch_ids,
                    self.upstream_loss_coefficients,
                    strict=True,
                )
            ),
            "downstream_loss_coefficient": self.downstream_loss_coefficient,
            "coefficient_units": "dimensionless_velocity_head_multiplier",
        }


@dataclass(frozen=True)
class SubcriticalEnergyJunctionSolution:
    node_reference_total_head_m: float
    upstream_branch_ids: tuple[str, ...]
    upstream_boundaries: tuple[
        ResolvedCharacteristicDynamicWaveBoundary, ...
    ]
    downstream_branch_id: str
    downstream_boundary: ResolvedCharacteristicDynamicWaveBoundary
    energy_loss: DynamicWaveJunctionEnergyLoss
    upstream_boundary_total_heads_m: tuple[float, ...]
    downstream_boundary_total_head_m: float
    maximum_absolute_energy_equation_residual_m: float
    total_upstream_discharge_m3s: float
    downstream_discharge_m3s: float
    junction_mass_balance_residual_m3s: float
    maximum_absolute_outgoing_invariant_residual_mps: float
    root_bracket_lower_m: float
    root_bracket_upper_m: float
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SUBCRITICAL_ENERGY_JUNCTION_SCHEMA,
            "node_reference_total_head_m": self.node_reference_total_head_m,
            "upstream_branch_ids": list(self.upstream_branch_ids),
            "upstream_boundaries": [
                value.as_dict() for value in self.upstream_boundaries
            ],
            "downstream_branch_id": self.downstream_branch_id,
            "downstream_boundary": self.downstream_boundary.as_dict(),
            "energy_loss": self.energy_loss.as_dict(),
            "upstream_boundary_total_heads_m": list(
                self.upstream_boundary_total_heads_m
            ),
            "downstream_boundary_total_head_m": (
                self.downstream_boundary_total_head_m
            ),
            "maximum_absolute_energy_equation_residual_m": (
                self.maximum_absolute_energy_equation_residual_m
            ),
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
            "root_bracket_lower_m": self.root_bracket_lower_m,
            "root_bracket_upper_m": self.root_bracket_upper_m,
            "junction_storage_m3": 0.0,
            "closure_conditions": [
                "sum_upstream_discharge_equals_downstream_discharge",
                "one_outgoing_characteristic_invariant_per_branch",
                "branch_total_head_difference_equals_local_loss",
            ],
            "momentum_junction_closure": None,
            "downstream_oriented_flow_tolerance_m3s": (
                _FLOW_DIRECTION_TOLERANCE_M3S
            ),
            "subcritical_only": True,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class _EnergyBranch:
    terminal: DynamicWaveJunctionTerminal
    side: str
    loss_coefficient: float
    areas_m2: tuple[float, ...]
    node_heads_m: tuple[float, ...]

    @property
    def minimum_node_head_m(self) -> float:
        return self.node_heads_m[0]

    @property
    def maximum_node_head_m(self) -> float:
        return self.node_heads_m[-1]

    @property
    def interior_node_head_m(self) -> float:
        return _equivalent_node_head_m(
            self.terminal.interior_state,
            self.terminal,
            self.side,
            self.loss_coefficient,
        )

    def resolve(
        self, node_head_m: float
    ) -> ResolvedCharacteristicDynamicWaveBoundary:
        target = float(node_head_m)
        range_tolerance = 2e-13 * max(1.0, abs(target))
        root_tolerance = 2e-15 * max(1.0, abs(target))
        if target < self.minimum_node_head_m - range_tolerance or target > (
            self.maximum_node_head_m + range_tolerance
        ):
            raise ValueError("dynamic_wave_energy_branch_head_outside_range")
        target = min(
            self.maximum_node_head_m,
            max(self.minimum_node_head_m, target),
        )
        index = bisect_left(self.node_heads_m, target)
        if index == 0:
            area = self.areas_m2[0]
        elif index == len(self.node_heads_m):
            area = self.areas_m2[-1]
        elif abs(self.node_heads_m[index] - target) <= root_tolerance:
            area = self.areas_m2[index]
        else:
            lower = self.areas_m2[index - 1]
            upper = self.areas_m2[index]
            for _ in range(100):
                middle = 0.5 * (lower + upper)
                state = _state_at_area(self, middle)
                value = _equivalent_node_head_m(
                    state,
                    self.terminal,
                    self.side,
                    self.loss_coefficient,
                )
                if abs(value - target) <= root_tolerance:
                    lower = middle
                    upper = middle
                    break
                if value < target:
                    lower = middle
                else:
                    upper = middle
            area = 0.5 * (lower + upper)
        return resolve_characteristic_dynamic_wave_boundary(
            CharacteristicDynamicWaveBoundary(
                side=self.side,
                prescribed_quantity="area_m2",
                prescribed_value=area,
                bed_elevation_m=self.terminal.bed_elevation_m,
            ),
            self.terminal.interior_state,
            self.terminal.section,
        )


def solve_subcritical_dynamic_wave_energy_junction(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    energy_loss: DynamicWaveJunctionEnergyLoss,
    *,
    mass_balance_tolerance_m3s: float = 1e-12,
) -> SubcriticalEnergyJunctionSolution:
    tolerance = float(mass_balance_tolerance_m3s)
    branch_ids = tuple(value.branch_id for value in upstream)
    if (
        not upstream
        or branch_ids != energy_loss.upstream_branch_ids
        or downstream.branch_id in branch_ids
        or len(branch_ids) != len(set(branch_ids))
        or not math.isfinite(tolerance)
        or tolerance <= 0.0
    ):
        raise ValueError("dynamic_wave_energy_junction_contract_invalid")
    upstream_branches = tuple(
        _build_energy_branch(
            terminal,
            side="right",
            loss_coefficient=coefficient,
        )
        for terminal, coefficient in zip(
            upstream,
            energy_loss.upstream_loss_coefficients,
            strict=True,
        )
    )
    downstream_branch = _build_energy_branch(
        downstream,
        side="left",
        loss_coefficient=energy_loss.downstream_loss_coefficient,
    )
    branches = (*upstream_branches, downstream_branch)
    lower = max(value.minimum_node_head_m for value in branches)
    upper = min(value.maximum_node_head_m for value in branches)
    head_tolerance = 2e-13 * max(1.0, abs(lower), abs(upper))
    if lower > upper + head_tolerance:
        raise ValueError("dynamic_wave_energy_junction_no_common_head_range")
    if lower > upper:
        lower = upper = 0.5 * (lower + upper)

    candidates = sorted(
        set(
            (lower, upper)
            + tuple(
                value.interior_node_head_m
                for value in branches
                if lower <= value.interior_node_head_m <= upper
            )
        )
    )
    resolved = [_resolve_node(branches, value) for value in candidates]
    for node_head, entry in zip(candidates, resolved, strict=True):
        if abs(entry[0]) <= tolerance:
            return _solution(
                node_head,
                upstream_branches,
                downstream_branch,
                energy_loss,
                entry,
                lower,
                upper,
            )
    bracket = next(
        (
            (left_head, right_head, left_entry, right_entry)
            for left_head, right_head, left_entry, right_entry in zip(
                candidates,
                candidates[1:],
                resolved,
                resolved[1:],
            )
            if left_entry[0] * right_entry[0] < 0.0
        ),
        None,
    )
    if bracket is None:
        raise ValueError("dynamic_wave_energy_junction_no_mass_root")
    bracket_lower, bracket_upper, lower_entry, _ = bracket
    lower_value = lower_entry[0]
    node_head = bracket_lower
    entry = lower_entry
    for _ in range(100):
        node_head = 0.5 * (bracket_lower + bracket_upper)
        entry = _resolve_node(branches, node_head)
        if abs(entry[0]) <= tolerance:
            break
        if lower_value * entry[0] <= 0.0:
            bracket_upper = node_head
        else:
            bracket_lower = node_head
            lower_value = entry[0]
    if abs(entry[0]) > tolerance:
        raise ValueError("dynamic_wave_energy_junction_root_tolerance_not_met")
    return _solution(
        node_head,
        upstream_branches,
        downstream_branch,
        energy_loss,
        entry,
        lower,
        upper,
    )


def _build_energy_branch(
    terminal: DynamicWaveJunctionTerminal,
    *,
    side: str,
    loss_coefficient: float,
) -> _EnergyBranch:
    interior = terminal.interior_state
    speeds = dynamic_wave_characteristic_speeds_mps(interior, terminal.section)
    if (
        interior.area_m2 <= 0.0
        or interior.discharge_m3s < -_FLOW_DIRECTION_TOLERANCE_M3S
        or not speeds[0] < 0.0 < speeds[1]
    ):
        raise ValueError("dynamic_wave_energy_junction_terminal_not_supported")
    areas = interior.area_m2 * np.power(10.0, _AREA_LOG_OFFSETS)
    areas[_INTERIOR_AREA_INDEX] = interior.area_m2
    prototype = _EnergyBranch(terminal, side, loss_coefficient, (), ())
    valid = []
    for area in areas:
        state = _state_at_area(prototype, float(area))
        branch_speeds = dynamic_wave_characteristic_speeds_mps(
            state, terminal.section
        )
        valid.append(
            state.discharge_m3s >= -_FLOW_DIRECTION_TOLERANCE_M3S
            and branch_speeds[0] < 0.0 < branch_speeds[1]
        )
    if not valid[_INTERIOR_AREA_INDEX]:
        raise ValueError("dynamic_wave_energy_junction_terminal_not_supported")
    first = _INTERIOR_AREA_INDEX
    last = _INTERIOR_AREA_INDEX
    while first > 0 and valid[first - 1]:
        first -= 1
    while last < len(valid) - 1 and valid[last + 1]:
        last += 1
    branch_areas = [float(value) for value in areas[first : last + 1]]
    zero_discharge_area = _zero_discharge_area_m2(prototype)
    if side == "right" and zero_discharge_area > branch_areas[-1]:
        branch_areas.append(zero_discharge_area)
    elif side == "left" and zero_discharge_area < branch_areas[0]:
        branch_areas.insert(0, zero_discharge_area)
    branch_areas_tuple = tuple(branch_areas)
    node_heads = tuple(
        _equivalent_node_head_m(
            _state_at_area(prototype, area),
            terminal,
            side,
            loss_coefficient,
        )
        for area in branch_areas_tuple
    )
    if len(node_heads) < 2 or any(
        right <= left for left, right in zip(node_heads, node_heads[1:])
    ):
        raise ValueError("dynamic_wave_energy_junction_branch_not_monotone")
    return _EnergyBranch(
        terminal=terminal,
        side=side,
        loss_coefficient=loss_coefficient,
        areas_m2=branch_areas_tuple,
        node_heads_m=node_heads,
    )


def _state_at_area(branch: _EnergyBranch, area_m2: float) -> DynamicWaveCellState:
    terminal = branch.terminal
    potential = dynamic_wave_characteristic_potential_mps(
        area_m2, terminal.section
    )
    interior = terminal.interior_state
    interior_potential = dynamic_wave_characteristic_potential_mps(
        interior.area_m2, terminal.section
    )
    invariant = (
        interior.mean_velocity_mps - interior_potential
        if branch.side == "left"
        else interior.mean_velocity_mps + interior_potential
    )
    velocity = (
        invariant + potential
        if branch.side == "left"
        else invariant - potential
    )
    return DynamicWaveCellState(area_m2, area_m2 * velocity)


def _zero_discharge_area_m2(branch: _EnergyBranch) -> float:
    terminal = branch.terminal
    interior = terminal.interior_state
    if interior.discharge_m3s <= _FLOW_DIRECTION_TOLERANCE_M3S:
        return interior.area_m2
    interior_potential = dynamic_wave_characteristic_potential_mps(
        interior.area_m2, terminal.section
    )
    invariant = (
        interior.mean_velocity_mps - interior_potential
        if branch.side == "left"
        else interior.mean_velocity_mps + interior_potential
    )
    target_potential = -invariant if branch.side == "left" else invariant
    if target_potential <= 0.0:
        raise ValueError("dynamic_wave_energy_junction_zero_flow_root_missing")
    if branch.side == "right":
        lower = interior.area_m2
        upper = 1.1 * lower
        while dynamic_wave_characteristic_potential_mps(
            upper, terminal.section
        ) < target_potential:
            upper *= 2.0
    else:
        upper = interior.area_m2
        lower = upper / 1.1
        while dynamic_wave_characteristic_potential_mps(
            lower, terminal.section
        ) > target_potential:
            lower *= 0.5
    for _ in range(100):
        middle = 0.5 * (lower + upper)
        if middle == lower or middle == upper:
            break
        potential = dynamic_wave_characteristic_potential_mps(
            middle, terminal.section
        )
        if potential < target_potential:
            lower = middle
        else:
            upper = middle
    return 0.5 * (lower + upper)


def _equivalent_node_head_m(
    state: DynamicWaveCellState,
    terminal: DynamicWaveJunctionTerminal,
    side: str,
    loss_coefficient: float,
) -> float:
    surface = terminal.bed_elevation_m + terminal.section.depth_m(state.area_m2)
    velocity_head = state.mean_velocity_mps**2 / (2.0 * STANDARD_GRAVITY_MPS2)
    total_head = surface + velocity_head
    return (
        total_head - loss_coefficient * velocity_head
        if side == "right"
        else total_head + loss_coefficient * velocity_head
    )


def _resolve_node(
    branches: tuple[_EnergyBranch, ...],
    node_head_m: float,
) -> tuple[
    float,
    tuple[ResolvedCharacteristicDynamicWaveBoundary, ...],
    ResolvedCharacteristicDynamicWaveBoundary,
]:
    boundaries = tuple(value.resolve(node_head_m) for value in branches)
    upstream = boundaries[:-1]
    downstream = boundaries[-1]
    residual = sum(value.state.discharge_m3s for value in upstream) - (
        downstream.state.discharge_m3s
    )
    return residual, upstream, downstream


def _solution(
    node_head_m: float,
    upstream_branches: tuple[_EnergyBranch, ...],
    downstream_branch: _EnergyBranch,
    energy_loss: DynamicWaveJunctionEnergyLoss,
    resolved: tuple[
        float,
        tuple[ResolvedCharacteristicDynamicWaveBoundary, ...],
        ResolvedCharacteristicDynamicWaveBoundary,
    ],
    bracket_lower_m: float,
    bracket_upper_m: float,
) -> SubcriticalEnergyJunctionSolution:
    residual, upstream, downstream = resolved
    upstream_total_heads = tuple(
        _total_head_m(value.state, branch.terminal)
        for value, branch in zip(upstream, upstream_branches, strict=True)
    )
    downstream_total_head = _total_head_m(
        downstream.state, downstream_branch.terminal
    )
    energy_residuals = tuple(
        head
        - node_head_m
        - coefficient
        * value.state.mean_velocity_mps**2
        / (2.0 * STANDARD_GRAVITY_MPS2)
        for head, coefficient, value in zip(
            upstream_total_heads,
            energy_loss.upstream_loss_coefficients,
            upstream,
            strict=True,
        )
    ) + (
        node_head_m
        - downstream_total_head
        - energy_loss.downstream_loss_coefficient
        * downstream.state.mean_velocity_mps**2
        / (2.0 * STANDARD_GRAVITY_MPS2),
    )
    return SubcriticalEnergyJunctionSolution(
        node_reference_total_head_m=node_head_m,
        upstream_branch_ids=tuple(
            value.terminal.branch_id for value in upstream_branches
        ),
        upstream_boundaries=upstream,
        downstream_branch_id=downstream_branch.terminal.branch_id,
        downstream_boundary=downstream,
        energy_loss=energy_loss,
        upstream_boundary_total_heads_m=upstream_total_heads,
        downstream_boundary_total_head_m=downstream_total_head,
        maximum_absolute_energy_equation_residual_m=max(
            abs(value) for value in energy_residuals
        ),
        total_upstream_discharge_m3s=sum(
            value.state.discharge_m3s for value in upstream
        ),
        downstream_discharge_m3s=downstream.state.discharge_m3s,
        junction_mass_balance_residual_m3s=residual,
        maximum_absolute_outgoing_invariant_residual_mps=max(
            abs(value.outgoing_invariant_residual_mps)
            for value in (*upstream, downstream)
        ),
        root_bracket_lower_m=bracket_lower_m,
        root_bracket_upper_m=bracket_upper_m,
    )


def _total_head_m(
    state: DynamicWaveCellState,
    terminal: DynamicWaveJunctionTerminal,
) -> float:
    return (
        terminal.bed_elevation_m
        + terminal.section.depth_m(state.area_m2)
        + state.mean_velocity_mps**2 / (2.0 * STANDARD_GRAVITY_MPS2)
    )
