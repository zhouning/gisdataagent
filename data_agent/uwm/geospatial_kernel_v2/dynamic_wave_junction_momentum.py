"""Direction-aware projected-momentum closure for subcritical confluences."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .dynamic_wave_boundaries import (
    CharacteristicDynamicWaveBoundary,
    ResolvedCharacteristicDynamicWaveBoundary,
    resolve_characteristic_dynamic_wave_boundary,
)
from .dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    TrapezoidalChannelSection,
    dynamic_wave_characteristic_speeds_mps,
)
from .dynamic_wave_junction import DynamicWaveJunctionTerminal


SUBCRITICAL_PROJECTED_MOMENTUM_JUNCTION_SCHEMA = (
    "gwm.geospatial_kernel.subcritical_projected_momentum_junction.v1"
)
PROJECTED_MOMENTUM_JUNCTION_CONTRACT_SCHEMA = (
    "gwm.geospatial_kernel.projected_momentum_junction_contract.v1"
)
PROJECTED_MOMENTUM_ROOT_SCAN_SCHEMA = (
    "gwm.geospatial_kernel.projected_momentum_root_scan.v1"
)
_FLOW_DIRECTION_TOLERANCE_M3S = 1e-12
_MAXIMUM_COMBINING_DEFLECTION_DEGREES = 90.0
_ELEVATION_LOG_OFFSETS = np.linspace(-6.0, 6.0, 4801)


@dataclass(frozen=True)
class ProjectedMomentumJunctionContract:
    """Hydraulic and geographic inputs to a downstream-axis momentum balance."""

    upstream_branch_ids: tuple[str, ...]
    downstream_branch_id: str
    upstream_deflection_degrees: tuple[float, ...]
    section_spacing_m: tuple[float, ...]
    upstream_manning_n: tuple[float, ...]
    downstream_manning_n: float
    upstream_bed_slopes: tuple[float, ...]
    downstream_bed_slope: float
    upstream_momentum_coefficients: tuple[float, ...]
    downstream_momentum_coefficient: float
    provenance_id: str

    def __post_init__(self) -> None:
        branch_ids = tuple(self.upstream_branch_ids)
        angles = tuple(float(value) for value in self.upstream_deflection_degrees)
        spacing = tuple(float(value) for value in self.section_spacing_m)
        upstream_n = tuple(float(value) for value in self.upstream_manning_n)
        downstream_n = float(self.downstream_manning_n)
        upstream_slopes = tuple(float(value) for value in self.upstream_bed_slopes)
        downstream_slope = float(self.downstream_bed_slope)
        upstream_beta = tuple(
            float(value) for value in self.upstream_momentum_coefficients
        )
        downstream_beta = float(self.downstream_momentum_coefficient)
        branch_count = len(branch_ids)
        if any(
            math.isfinite(value)
            and value > _MAXIMUM_COMBINING_DEFLECTION_DEGREES
            for value in angles
        ):
            raise ValueError("projected_momentum_junction_angle_not_supported")
        if (
            branch_count < 2
            or len(branch_ids) != len(set(branch_ids))
            or any(
                not isinstance(value, str) or not value.strip()
                for value in branch_ids
            )
            or not isinstance(self.downstream_branch_id, str)
            or not self.downstream_branch_id.strip()
            or self.downstream_branch_id in branch_ids
            or any(
                len(values) != branch_count
                for values in (
                    angles,
                    spacing,
                    upstream_n,
                    upstream_slopes,
                    upstream_beta,
                )
            )
            or any(
                not math.isfinite(value)
                or not 0.0 <= value <= _MAXIMUM_COMBINING_DEFLECTION_DEGREES
                for value in angles
            )
            or any(not math.isfinite(value) or value < 0.0 for value in spacing)
            or any(not math.isfinite(value) or value <= 0.0 for value in upstream_n)
            or not math.isfinite(downstream_n)
            or downstream_n <= 0.0
            or any(
                not math.isfinite(value) or value < 0.0
                for value in upstream_slopes
            )
            or not math.isfinite(downstream_slope)
            or downstream_slope < 0.0
            or any(
                not math.isfinite(value) or value <= 0.0
                for value in upstream_beta
            )
            or not math.isfinite(downstream_beta)
            or downstream_beta <= 0.0
            or not isinstance(self.provenance_id, str)
            or not self.provenance_id.strip()
        ):
            raise ValueError("projected_momentum_junction_contract_invalid")
        object.__setattr__(self, "upstream_branch_ids", branch_ids)
        object.__setattr__(self, "upstream_deflection_degrees", angles)
        object.__setattr__(self, "section_spacing_m", spacing)
        object.__setattr__(self, "upstream_manning_n", upstream_n)
        object.__setattr__(self, "downstream_manning_n", downstream_n)
        object.__setattr__(self, "upstream_bed_slopes", upstream_slopes)
        object.__setattr__(self, "downstream_bed_slope", downstream_slope)
        object.__setattr__(self, "upstream_momentum_coefficients", upstream_beta)
        object.__setattr__(self, "downstream_momentum_coefficient", downstream_beta)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PROJECTED_MOMENTUM_JUNCTION_CONTRACT_SCHEMA,
            "upstream_branch_ids": list(self.upstream_branch_ids),
            "downstream_branch_id": self.downstream_branch_id,
            "upstream_deflection_degrees": dict(
                zip(
                    self.upstream_branch_ids,
                    self.upstream_deflection_degrees,
                    strict=True,
                )
            ),
            "section_spacing_m": dict(
                zip(self.upstream_branch_ids, self.section_spacing_m, strict=True)
            ),
            "upstream_manning_n": dict(
                zip(self.upstream_branch_ids, self.upstream_manning_n, strict=True)
            ),
            "downstream_manning_n": self.downstream_manning_n,
            "upstream_bed_slopes": dict(
                zip(self.upstream_branch_ids, self.upstream_bed_slopes, strict=True)
            ),
            "downstream_bed_slope": self.downstream_bed_slope,
            "upstream_momentum_coefficients": dict(
                zip(
                    self.upstream_branch_ids,
                    self.upstream_momentum_coefficients,
                    strict=True,
                )
            ),
            "downstream_momentum_coefficient": (
                self.downstream_momentum_coefficient
            ),
            "provenance_id": self.provenance_id,
            "projection_axis": "downstream_flow_direction",
            "closure_dimension": "one_dimensional_projected_momentum",
            "friction_slope_averaging": "arithmetic_endpoint_Manning",
            "downstream_area_partition": "upstream_discharge_fraction",
            "momentum_coefficient_beta_required": True,
            "subcritical_combining_only": True,
            "vector_momentum_closure": False,
        }


@dataclass(frozen=True)
class ProjectedMomentumBalance:
    upstream_specific_forces_m3: tuple[float, ...]
    upstream_projected_specific_forces_m3: tuple[float, ...]
    downstream_specific_force_m3: float
    downstream_area_fractions: tuple[float, ...]
    friction_forces_m3: tuple[float, ...]
    water_weight_forces_m3: tuple[float, ...]
    upstream_branch_contributions_m3: tuple[float, ...]
    upstream_contribution_sum_m3: float
    residual_m3: float

    def as_dict(
        self, upstream_branch_ids: tuple[str, ...]
    ) -> dict[str, object]:
        def by_branch(values: tuple[float, ...]) -> dict[str, float]:
            return dict(zip(upstream_branch_ids, values, strict=True))

        return {
            "upstream_specific_forces_m3": by_branch(
                self.upstream_specific_forces_m3
            ),
            "upstream_projected_specific_forces_m3": by_branch(
                self.upstream_projected_specific_forces_m3
            ),
            "downstream_specific_force_m3": self.downstream_specific_force_m3,
            "downstream_area_fractions": by_branch(
                self.downstream_area_fractions
            ),
            "friction_forces_m3": by_branch(self.friction_forces_m3),
            "water_weight_forces_m3": by_branch(self.water_weight_forces_m3),
            "upstream_branch_contributions_m3": by_branch(
                self.upstream_branch_contributions_m3
            ),
            "upstream_contribution_sum_m3": self.upstream_contribution_sum_m3,
            "residual_m3": self.residual_m3,
            "equation": (
                "SF_down=sum(SF_up*cos(theta)-F_friction+W_bed_slope)"
            ),
        }


@dataclass(frozen=True)
class ProjectedMomentumRootScan:
    candidate_count: int
    admissible_candidate_count: int
    minimum_admissible_elevation_m: float | None
    maximum_admissible_elevation_m: float | None
    minimum_residual_m3: float | None
    maximum_residual_m3: float | None
    closest_elevation_m: float | None
    closest_absolute_residual_m3: float | None
    sign_change_brackets_m: tuple[tuple[float, float], ...]

    @property
    def root_bracket_found(self) -> bool:
        return bool(self.sign_change_brackets_m)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PROJECTED_MOMENTUM_ROOT_SCAN_SCHEMA,
            "candidate_count": self.candidate_count,
            "admissible_candidate_count": self.admissible_candidate_count,
            "minimum_admissible_elevation_m": (
                self.minimum_admissible_elevation_m
            ),
            "maximum_admissible_elevation_m": (
                self.maximum_admissible_elevation_m
            ),
            "minimum_residual_m3": self.minimum_residual_m3,
            "maximum_residual_m3": self.maximum_residual_m3,
            "closest_elevation_m": self.closest_elevation_m,
            "closest_absolute_residual_m3": (
                self.closest_absolute_residual_m3
            ),
            "sign_change_brackets_m": [
                list(value) for value in self.sign_change_brackets_m
            ],
            "root_bracket_found": self.root_bracket_found,
            "elevation_sampling": "logarithmic_depth_10^-6_to_10^6",
            "inadmissible_candidates_break_continuity": True,
        }


@dataclass(frozen=True)
class SubcriticalProjectedMomentumJunctionSolution:
    common_upstream_free_surface_elevation_m: float
    upstream_branch_ids: tuple[str, ...]
    upstream_boundaries: tuple[
        ResolvedCharacteristicDynamicWaveBoundary, ...
    ]
    downstream_branch_id: str
    downstream_boundary: ResolvedCharacteristicDynamicWaveBoundary
    contract: ProjectedMomentumJunctionContract
    momentum_balance: ProjectedMomentumBalance
    total_upstream_discharge_m3s: float
    downstream_discharge_m3s: float
    junction_mass_balance_residual_m3s: float
    maximum_absolute_outgoing_invariant_residual_mps: float
    root_bracket_lower_m: float
    root_bracket_upper_m: float
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SUBCRITICAL_PROJECTED_MOMENTUM_JUNCTION_SCHEMA,
            "common_upstream_free_surface_elevation_m": (
                self.common_upstream_free_surface_elevation_m
            ),
            "upstream_branch_ids": list(self.upstream_branch_ids),
            "upstream_boundaries": [
                value.as_dict() for value in self.upstream_boundaries
            ],
            "downstream_branch_id": self.downstream_branch_id,
            "downstream_boundary": self.downstream_boundary.as_dict(),
            "contract": self.contract.as_dict(),
            "momentum_balance": self.momentum_balance.as_dict(
                self.upstream_branch_ids
            ),
            "total_upstream_discharge_m3s": self.total_upstream_discharge_m3s,
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
                "common_upstream_free_surface_elevation",
                "sum_upstream_discharge_equals_downstream_discharge",
                "one_outgoing_characteristic_invariant_per_branch",
                "downstream_axis_projected_momentum_balance",
            ],
            "subcritical_only": True,
            "combining_flow_only": True,
            "vector_momentum_closure": False,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


def dynamic_wave_specific_force_m3(
    state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
    momentum_coefficient: float,
) -> float:
    """Return beta*Q^2/(g*A) + integral(depth below surface) dA."""

    beta = float(momentum_coefficient)
    if (
        state.area_m2 <= 0.0
        or not math.isfinite(beta)
        or beta <= 0.0
    ):
        raise ValueError("dynamic_wave_specific_force_contract_invalid")
    return (
        beta * state.discharge_m3s**2
        / (STANDARD_GRAVITY_MPS2 * state.area_m2)
        + section.hydrostatic_pressure_integral_m3(state.area_m2)
    )


def manning_friction_slope(
    state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
    manning_n: float,
) -> float:
    """Return the nonnegative Manning friction-slope magnitude."""

    roughness = float(manning_n)
    if (
        state.area_m2 <= 0.0
        or not math.isfinite(roughness)
        or roughness <= 0.0
    ):
        raise ValueError("dynamic_wave_manning_friction_slope_contract_invalid")
    depth = section.depth_m(state.area_m2)
    wetted_perimeter = section.bottom_width_m + 2.0 * depth * math.sqrt(
        1.0 + section.side_slope_horizontal_per_vertical**2
    )
    hydraulic_radius = state.area_m2 / wetted_perimeter
    velocity = state.discharge_m3s / state.area_m2
    return roughness**2 * velocity**2 / hydraulic_radius ** (4.0 / 3.0)


def evaluate_projected_momentum_balance(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    upstream_states: tuple[DynamicWaveCellState, ...],
    downstream_state: DynamicWaveCellState,
    contract: ProjectedMomentumJunctionContract,
    *,
    mass_balance_tolerance_m3s: float = 1e-10,
) -> ProjectedMomentumBalance:
    """Evaluate the HEC-style one-dimensional junction momentum equation."""

    tolerance = float(mass_balance_tolerance_m3s)
    _validate_attachment(upstream, downstream, contract)
    if (
        len(upstream_states) != len(upstream)
        or not math.isfinite(tolerance)
        or tolerance <= 0.0
        or any(value.area_m2 <= 0.0 for value in upstream_states)
        or downstream_state.area_m2 <= 0.0
        or any(
            value.discharge_m3s < -_FLOW_DIRECTION_TOLERANCE_M3S
            for value in upstream_states
        )
        or downstream_state.discharge_m3s <= _FLOW_DIRECTION_TOLERANCE_M3S
    ):
        raise ValueError("projected_momentum_junction_state_not_supported")
    total_upstream = sum(value.discharge_m3s for value in upstream_states)
    if abs(total_upstream - downstream_state.discharge_m3s) > tolerance:
        raise ValueError("projected_momentum_junction_mass_balance_required")
    states = (*upstream_states, downstream_state)
    sections = tuple(value.section for value in upstream) + (downstream.section,)
    if any(
        not (speeds[0] < 0.0 < speeds[1])
        for speeds in (
            dynamic_wave_characteristic_speeds_mps(state, section)
            for state, section in zip(states, sections, strict=True)
        )
    ):
        raise ValueError("projected_momentum_junction_state_not_subcritical")

    downstream_force = dynamic_wave_specific_force_m3(
        downstream_state,
        downstream.section,
        contract.downstream_momentum_coefficient,
    )
    downstream_sf = manning_friction_slope(
        downstream_state,
        downstream.section,
        contract.downstream_manning_n,
    )
    fractions = tuple(
        max(0.0, value.discharge_m3s) / downstream_state.discharge_m3s
        for value in upstream_states
    )
    upstream_forces = tuple(
        dynamic_wave_specific_force_m3(state, terminal.section, beta)
        for state, terminal, beta in zip(
            upstream_states,
            upstream,
            contract.upstream_momentum_coefficients,
            strict=True,
        )
    )
    cosines = tuple(
        math.cos(math.radians(value))
        for value in contract.upstream_deflection_degrees
    )
    projected_forces = tuple(
        force * cosine
        for force, cosine in zip(upstream_forces, cosines, strict=True)
    )
    friction_forces = []
    water_weight_forces = []
    for state, terminal, cosine, fraction, length, roughness, slope in zip(
        upstream_states,
        upstream,
        cosines,
        fractions,
        contract.section_spacing_m,
        contract.upstream_manning_n,
        contract.upstream_bed_slopes,
        strict=True,
    ):
        upstream_sf = manning_friction_slope(
            state, terminal.section, roughness
        )
        projected_control_area = (
            state.area_m2 * cosine + downstream_state.area_m2 * fraction
        )
        friction_forces.append(
            0.5 * (upstream_sf + downstream_sf)
            * 0.5 * length
            * projected_control_area
        )
        water_weight_forces.append(
            0.5 * (slope + contract.downstream_bed_slope)
            * 0.5 * length
            * projected_control_area
        )
    friction = tuple(friction_forces)
    weight = tuple(water_weight_forces)
    contributions = tuple(
        force - friction_force + weight_force
        for force, friction_force, weight_force in zip(
            projected_forces, friction, weight, strict=True
        )
    )
    contribution_sum = sum(contributions)
    return ProjectedMomentumBalance(
        upstream_specific_forces_m3=upstream_forces,
        upstream_projected_specific_forces_m3=projected_forces,
        downstream_specific_force_m3=downstream_force,
        downstream_area_fractions=fractions,
        friction_forces_m3=friction,
        water_weight_forces_m3=weight,
        upstream_branch_contributions_m3=contributions,
        upstream_contribution_sum_m3=contribution_sum,
        residual_m3=downstream_force - contribution_sum,
    )


def solve_subcritical_projected_momentum_junction(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    contract: ProjectedMomentumJunctionContract,
    *,
    momentum_tolerance_m3: float = 1e-10,
    mass_balance_tolerance_m3s: float = 1e-10,
) -> SubcriticalProjectedMomentumJunctionSolution:
    """Solve common upstream stage and downstream-axis momentum simultaneously."""

    momentum_tolerance = float(momentum_tolerance_m3)
    mass_tolerance = float(mass_balance_tolerance_m3s)
    _validate_attachment(upstream, downstream, contract)
    if (
        not math.isfinite(momentum_tolerance)
        or momentum_tolerance <= 0.0
        or not math.isfinite(mass_tolerance)
        or mass_tolerance <= 0.0
    ):
        raise ValueError("projected_momentum_junction_solver_contract_invalid")
    _validate_interior_states(upstream, downstream)
    candidates = _candidate_upstream_elevations(upstream, downstream)
    evaluated: list[
        tuple[
            tuple[ResolvedCharacteristicDynamicWaveBoundary, ...],
            ResolvedCharacteristicDynamicWaveBoundary,
            ProjectedMomentumBalance,
        ]
        | None
    ] = []
    for elevation in candidates:
        try:
            entry = _resolve_at_elevation(
                elevation,
                upstream,
                downstream,
                contract,
                mass_tolerance,
            )
        except ValueError:
            entry = None
        evaluated.append(entry)
        if (
            entry is not None
            and abs(entry[2].residual_m3) <= momentum_tolerance
        ):
            return _solution(
                elevation,
                upstream,
                downstream,
                contract,
                entry,
                elevation,
                elevation,
            )

    bracket = None
    previous = None
    for elevation, entry in zip(candidates, evaluated, strict=True):
        if entry is None:
            previous = None
            continue
        if (
            previous is not None
            and previous[1][2].residual_m3 * entry[2].residual_m3 < 0.0
        ):
            bracket = (previous[0], elevation, previous[1], entry)
            break
        previous = (elevation, entry)
    if bracket is None:
        raise ValueError("projected_momentum_junction_no_momentum_root")

    lower, upper, lower_entry, _ = bracket
    original_lower = lower
    original_upper = upper
    lower_residual = lower_entry[2].residual_m3
    entry = lower_entry
    elevation = lower
    for _ in range(120):
        elevation = 0.5 * (lower + upper)
        entry = _resolve_at_elevation(
            elevation,
            upstream,
            downstream,
            contract,
            mass_tolerance,
        )
        residual = entry[2].residual_m3
        if abs(residual) <= momentum_tolerance:
            break
        if lower_residual * residual <= 0.0:
            upper = elevation
        else:
            lower = elevation
            lower_residual = residual
    if abs(entry[2].residual_m3) > momentum_tolerance:
        raise ValueError("projected_momentum_junction_root_tolerance_not_met")
    return _solution(
        elevation,
        upstream,
        downstream,
        contract,
        entry,
        original_lower,
        original_upper,
    )


def scan_subcritical_projected_momentum_roots(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    contract: ProjectedMomentumJunctionContract,
    *,
    mass_balance_tolerance_m3s: float = 1e-10,
) -> ProjectedMomentumRootScan:
    """Report the admissible residual envelope used to bracket a root."""

    tolerance = float(mass_balance_tolerance_m3s)
    _validate_attachment(upstream, downstream, contract)
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("projected_momentum_junction_solver_contract_invalid")
    _validate_interior_states(upstream, downstream)
    candidates = _candidate_upstream_elevations(upstream, downstream)
    admissible: list[tuple[float, float]] = []
    brackets: list[tuple[float, float]] = []
    previous: tuple[float, float] | None = None
    for elevation in candidates:
        try:
            entry = _resolve_at_elevation(
                elevation,
                upstream,
                downstream,
                contract,
                tolerance,
            )
        except ValueError:
            previous = None
            continue
        residual = entry[2].residual_m3
        admissible.append((elevation, residual))
        if previous is not None and previous[1] * residual < 0.0:
            brackets.append((previous[0], elevation))
        previous = (elevation, residual)
    if not admissible:
        return ProjectedMomentumRootScan(
            candidate_count=len(candidates),
            admissible_candidate_count=0,
            minimum_admissible_elevation_m=None,
            maximum_admissible_elevation_m=None,
            minimum_residual_m3=None,
            maximum_residual_m3=None,
            closest_elevation_m=None,
            closest_absolute_residual_m3=None,
            sign_change_brackets_m=(),
        )
    closest_elevation, closest_residual = min(
        admissible, key=lambda value: abs(value[1])
    )
    return ProjectedMomentumRootScan(
        candidate_count=len(candidates),
        admissible_candidate_count=len(admissible),
        minimum_admissible_elevation_m=admissible[0][0],
        maximum_admissible_elevation_m=admissible[-1][0],
        minimum_residual_m3=min(value[1] for value in admissible),
        maximum_residual_m3=max(value[1] for value in admissible),
        closest_elevation_m=closest_elevation,
        closest_absolute_residual_m3=abs(closest_residual),
        sign_change_brackets_m=tuple(brackets),
    )


def _validate_attachment(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    contract: ProjectedMomentumJunctionContract,
) -> None:
    if (
        not isinstance(contract, ProjectedMomentumJunctionContract)
        or tuple(value.branch_id for value in upstream)
        != contract.upstream_branch_ids
        or downstream.branch_id != contract.downstream_branch_id
    ):
        raise ValueError("projected_momentum_junction_attachment_invalid")


def _validate_interior_states(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
) -> None:
    terminals = (*upstream, downstream)
    if any(
        value.interior_state.area_m2 <= 0.0
        or value.interior_state.discharge_m3s < -_FLOW_DIRECTION_TOLERANCE_M3S
        or not (
            speeds[0] < 0.0 < speeds[1]
        )
        for value in terminals
        for speeds in (
            dynamic_wave_characteristic_speeds_mps(
                value.interior_state, value.section
            ),
        )
    ):
        raise ValueError("projected_momentum_junction_terminal_not_supported")


def _candidate_upstream_elevations(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
) -> tuple[float, ...]:
    terminals = (*upstream, downstream)
    base = max(value.bed_elevation_m for value in upstream)
    interior_elevations = tuple(
        value.bed_elevation_m
        + value.section.depth_m(value.interior_state.area_m2)
        for value in upstream
    )
    characteristic_depths = tuple(
        value.section.depth_m(value.interior_state.area_m2)
        for value in terminals
    )
    scale = max(
        1.0,
        *characteristic_depths,
        *(abs(value - base) for value in interior_elevations),
    )
    candidates = {
        base + scale * float(10.0**offset)
        for offset in _ELEVATION_LOG_OFFSETS
    }
    candidates.update(
        value for value in interior_elevations if value > base
    )
    return tuple(sorted(candidates))


def _resolve_at_elevation(
    elevation: float,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    contract: ProjectedMomentumJunctionContract,
    mass_tolerance: float,
) -> tuple[
    tuple[ResolvedCharacteristicDynamicWaveBoundary, ...],
    ResolvedCharacteristicDynamicWaveBoundary,
    ProjectedMomentumBalance,
]:
    upstream_boundaries = tuple(
        resolve_characteristic_dynamic_wave_boundary(
            CharacteristicDynamicWaveBoundary(
                side="right",
                prescribed_quantity="free_surface_elevation_m",
                prescribed_value=elevation,
                bed_elevation_m=terminal.bed_elevation_m,
            ),
            terminal.interior_state,
            terminal.section,
        )
        for terminal in upstream
    )
    total_discharge = sum(
        value.state.discharge_m3s for value in upstream_boundaries
    )
    if total_discharge <= _FLOW_DIRECTION_TOLERANCE_M3S:
        raise ValueError("projected_momentum_junction_state_not_supported")
    downstream_boundary = resolve_characteristic_dynamic_wave_boundary(
        CharacteristicDynamicWaveBoundary(
            side="left",
            prescribed_quantity="discharge_m3s",
            prescribed_value=total_discharge,
            bed_elevation_m=downstream.bed_elevation_m,
        ),
        downstream.interior_state,
        downstream.section,
    )
    balance = evaluate_projected_momentum_balance(
        upstream,
        downstream,
        tuple(value.state for value in upstream_boundaries),
        downstream_boundary.state,
        contract,
        mass_balance_tolerance_m3s=mass_tolerance,
    )
    return upstream_boundaries, downstream_boundary, balance


def _solution(
    elevation: float,
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    contract: ProjectedMomentumJunctionContract,
    entry: tuple[
        tuple[ResolvedCharacteristicDynamicWaveBoundary, ...],
        ResolvedCharacteristicDynamicWaveBoundary,
        ProjectedMomentumBalance,
    ],
    bracket_lower: float,
    bracket_upper: float,
) -> SubcriticalProjectedMomentumJunctionSolution:
    upstream_boundaries, downstream_boundary, balance = entry
    total_upstream = sum(
        value.state.discharge_m3s for value in upstream_boundaries
    )
    downstream_discharge = downstream_boundary.state.discharge_m3s
    return SubcriticalProjectedMomentumJunctionSolution(
        common_upstream_free_surface_elevation_m=elevation,
        upstream_branch_ids=contract.upstream_branch_ids,
        upstream_boundaries=upstream_boundaries,
        downstream_branch_id=contract.downstream_branch_id,
        downstream_boundary=downstream_boundary,
        contract=contract,
        momentum_balance=balance,
        total_upstream_discharge_m3s=total_upstream,
        downstream_discharge_m3s=downstream_discharge,
        junction_mass_balance_residual_m3s=(
            total_upstream - downstream_discharge
        ),
        maximum_absolute_outgoing_invariant_residual_mps=max(
            abs(value.outgoing_invariant_residual_mps)
            for value in (*upstream_boundaries, downstream_boundary)
        ),
        root_bracket_lower_m=bracket_lower,
        root_bracket_upper_m=bracket_upper,
    )
