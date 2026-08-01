"""Native mass coupling with an explicit two-dimensional junction reaction."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .dynamic_wave_coupled import FixedDynamicWaveBoundary
from .dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    TrapezoidalChannelSection,
)
from .dynamic_wave_junction import (
    DynamicWaveJunctionTerminal,
    DynamicWaveNetworkReach,
    SubcriticalConfluenceSolution,
    SubcriticalConfluenceNetworkStep,
    advance_subcritical_confluence_network_open,
    solve_subcritical_dynamic_wave_confluence,
)
from .dynamic_wave_junction_geometry import GeographicJunctionGeometry


CONSERVATIVE_VECTOR_JUNCTION_CONTRACT_SCHEMA = (
    "gwm.geospatial_kernel.conservative_vector_junction_contract.v1"
)
CONSERVATIVE_VECTOR_JUNCTION_SCHEMA = (
    "gwm.geospatial_kernel.conservative_vector_junction.v1"
)
CONSERVATIVE_VECTOR_NETWORK_STEP_SCHEMA = (
    "gwm.geospatial_kernel.conservative_vector_junction_network_step.v1"
)
_FLOW_DIRECTION_TOLERANCE_M3S = 1e-12


@dataclass(frozen=True)
class ConservativeVectorJunctionContract:
    """Branch directions for a zero-storage, multi-in/one-out junction."""

    junction_id: str
    upstream_branch_ids: tuple[str, ...]
    downstream_branch_id: str
    upstream_flow_azimuth_degrees: tuple[float, ...]
    downstream_flow_azimuth_degrees: float
    provenance_id: str

    def __post_init__(self) -> None:
        branch_ids = tuple(self.upstream_branch_ids)
        azimuths = tuple(
            float(value) for value in self.upstream_flow_azimuth_degrees
        )
        downstream_azimuth = float(self.downstream_flow_azimuth_degrees)
        if (
            not isinstance(self.junction_id, str)
            or not self.junction_id.strip()
            or len(branch_ids) < 2
            or len(branch_ids) != len(set(branch_ids))
            or any(
                not isinstance(value, str) or not value.strip()
                for value in branch_ids
            )
            or not isinstance(self.downstream_branch_id, str)
            or not self.downstream_branch_id.strip()
            or self.downstream_branch_id in branch_ids
            or len(azimuths) != len(branch_ids)
            or any(
                not math.isfinite(value) or not 0.0 <= value < 360.0
                for value in azimuths
            )
            or not math.isfinite(downstream_azimuth)
            or not 0.0 <= downstream_azimuth < 360.0
            or not isinstance(self.provenance_id, str)
            or not self.provenance_id.strip()
        ):
            raise ValueError("conservative_vector_junction_contract_invalid")
        object.__setattr__(self, "upstream_branch_ids", branch_ids)
        object.__setattr__(self, "upstream_flow_azimuth_degrees", azimuths)
        object.__setattr__(
            self,
            "downstream_flow_azimuth_degrees",
            downstream_azimuth,
        )

    @classmethod
    def from_geographic_geometry(
        cls,
        geometry: GeographicJunctionGeometry,
    ) -> ConservativeVectorJunctionContract:
        if not isinstance(geometry, GeographicJunctionGeometry):
            raise TypeError("geographic_junction_geometry_required")
        if not geometry.geometry_admitted:
            raise ValueError(
                "conservative_vector_junction_geometry_not_admitted"
            )
        return cls(
            junction_id=geometry.junction_id,
            upstream_branch_ids=geometry.upstream_branch_ids,
            downstream_branch_id=geometry.downstream_branch_id,
            upstream_flow_azimuth_degrees=tuple(
                value.flow_azimuth_degrees
                for value in geometry.upstream_branches
            ),
            downstream_flow_azimuth_degrees=(
                geometry.downstream_branch.flow_azimuth_degrees
            ),
            provenance_id=(
                "geographic_junction_geometry:" + geometry.junction_id
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONSERVATIVE_VECTOR_JUNCTION_CONTRACT_SCHEMA,
            "junction_id": self.junction_id,
            "upstream_branch_ids": list(self.upstream_branch_ids),
            "downstream_branch_id": self.downstream_branch_id,
            "upstream_flow_azimuth_degrees": dict(
                zip(
                    self.upstream_branch_ids,
                    self.upstream_flow_azimuth_degrees,
                    strict=True,
                )
            ),
            "downstream_flow_azimuth_degrees": (
                self.downstream_flow_azimuth_degrees
            ),
            "azimuth_reference": "degrees_clockwise_from_true_north",
            "coordinate_components": ["east", "north"],
            "provenance_id": self.provenance_id,
            "zero_junction_storage": True,
            "saint_venant_momentum_coefficient_beta": 1.0,
            "implicit_zero_reaction_assumed": False,
        }


@dataclass(frozen=True)
class ConservativeVectorBranchFlux:
    """One cross-section contribution to the junction momentum ledger."""

    branch_id: str
    role: str
    flow_azimuth_degrees: float
    tangent_east: float
    tangent_north: float
    outward_normal_sign: float
    area_m2: float
    discharge_m3s: float
    convective_flux_m4s2: float
    hydrostatic_flux_m4s2: float
    total_flux_m4s2: float
    outward_convective_flux_east_m4s2: float
    outward_convective_flux_north_m4s2: float
    outward_hydrostatic_flux_east_m4s2: float
    outward_hydrostatic_flux_north_m4s2: float
    outward_total_flux_east_m4s2: float
    outward_total_flux_north_m4s2: float

    def as_dict(self) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "role": self.role,
            "flow_azimuth_degrees": self.flow_azimuth_degrees,
            "unit_tangent_east_north": [
                self.tangent_east,
                self.tangent_north,
            ],
            "outward_normal_sign": self.outward_normal_sign,
            "state": {
                "area_m2": self.area_m2,
                "discharge_m3s": self.discharge_m3s,
            },
            "scalar_flux": {
                "convective_m4s2": self.convective_flux_m4s2,
                "hydrostatic_m4s2": self.hydrostatic_flux_m4s2,
                "total_m4s2": self.total_flux_m4s2,
            },
            "outward_vector_flux_east_north": {
                "convective_m4s2": [
                    self.outward_convective_flux_east_m4s2,
                    self.outward_convective_flux_north_m4s2,
                ],
                "hydrostatic_m4s2": [
                    self.outward_hydrostatic_flux_east_m4s2,
                    self.outward_hydrostatic_flux_north_m4s2,
                ],
                "total_m4s2": [
                    self.outward_total_flux_east_m4s2,
                    self.outward_total_flux_north_m4s2,
                ],
            },
        }


@dataclass(frozen=True)
class ConservativeVectorJunctionSolution:
    """Hydraulic coupling plus the reaction required by its vector fluxes."""

    contract: ConservativeVectorJunctionContract
    hydraulic_solution: SubcriticalConfluenceSolution
    upstream_fluxes: tuple[ConservativeVectorBranchFlux, ...]
    downstream_flux: ConservativeVectorBranchFlux
    net_outward_mass_flux_m3s: float
    boundary_convective_flux_east_m4s2: float
    boundary_convective_flux_north_m4s2: float
    boundary_hydrostatic_flux_east_m4s2: float
    boundary_hydrostatic_flux_north_m4s2: float
    boundary_total_flux_east_m4s2: float
    boundary_total_flux_north_m4s2: float
    junction_on_fluid_reaction_east_m4s2: float
    junction_on_fluid_reaction_north_m4s2: float
    momentum_ledger_residual_east_m4s2: float
    momentum_ledger_residual_north_m4s2: float
    diagnostic_only: bool = True

    @property
    def junction_reaction_magnitude_m4s2(self) -> float:
        return math.hypot(
            self.junction_on_fluid_reaction_east_m4s2,
            self.junction_on_fluid_reaction_north_m4s2,
        )

    @property
    def momentum_ledger_residual_magnitude_m4s2(self) -> float:
        return math.hypot(
            self.momentum_ledger_residual_east_m4s2,
            self.momentum_ledger_residual_north_m4s2,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONSERVATIVE_VECTOR_JUNCTION_SCHEMA,
            "contract": self.contract.as_dict(),
            "hydraulic_solution": self.hydraulic_solution.as_dict(),
            "branch_fluxes": [
                value.as_dict()
                for value in (*self.upstream_fluxes, self.downstream_flux)
            ],
            "mass_ledger": {
                "storage_rate_m3s": 0.0,
                "net_outward_mass_flux_m3s": self.net_outward_mass_flux_m3s,
                "residual_m3s": self.net_outward_mass_flux_m3s,
            },
            "momentum_ledger": {
                "boundary_convective_flux_east_north_m4s2": [
                    self.boundary_convective_flux_east_m4s2,
                    self.boundary_convective_flux_north_m4s2,
                ],
                "boundary_hydrostatic_flux_east_north_m4s2": [
                    self.boundary_hydrostatic_flux_east_m4s2,
                    self.boundary_hydrostatic_flux_north_m4s2,
                ],
                "boundary_total_flux_east_north_m4s2": [
                    self.boundary_total_flux_east_m4s2,
                    self.boundary_total_flux_north_m4s2,
                ],
                "junction_on_fluid_reaction_east_north_m4s2": [
                    self.junction_on_fluid_reaction_east_m4s2,
                    self.junction_on_fluid_reaction_north_m4s2,
                ],
                "reaction_magnitude_m4s2": (
                    self.junction_reaction_magnitude_m4s2
                ),
                "balance_equation": (
                    "boundary_generalized_flux-junction_on_fluid_reaction=0"
                ),
                "residual_east_north_m4s2": [
                    self.momentum_ledger_residual_east_m4s2,
                    self.momentum_ledger_residual_north_m4s2,
                ],
                "residual_magnitude_m4s2": (
                    self.momentum_ledger_residual_magnitude_m4s2
                ),
            },
            "closure_conditions": [
                "common_free_surface_elevation",
                "zero_storage_mass_conservation",
                "one_outgoing_characteristic_invariant_per_branch",
                "explicit_two_dimensional_junction_reaction",
            ],
            "reaction_is_inferred_not_observed": True,
            "multidimensional_junction_state_solved": False,
            "zero_reaction_assumed": False,
            "vector_momentum_ledger_closed_with_explicit_reaction": True,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class ConservativeVectorJunctionNetworkStep:
    """One synchronous 1D network step with its node-level vector ledger."""

    hydraulic_step: SubcriticalConfluenceNetworkStep
    vector_junction: ConservativeVectorJunctionSolution
    diagnostic_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CONSERVATIVE_VECTOR_NETWORK_STEP_SCHEMA,
            "hydraulic_step": self.hydraulic_step.as_dict(),
            "vector_junction": self.vector_junction.as_dict(),
            "network_volume_balance_error_m3": (
                self.hydraulic_step.network_volume_balance_error_m3
            ),
            "junction_mass_balance_residual_m3s": (
                self.vector_junction.net_outward_mass_flux_m3s
            ),
            "junction_vector_momentum_residual_m4s2": (
                self.vector_junction.momentum_ledger_residual_magnitude_m4s2
            ),
            "junction_reaction_retained_as_node_state": True,
            "junction_reaction_applied_as_one_dimensional_branch_source": False,
            "diagnostic_only": self.diagnostic_only,
            "operator_admitted": False,
        }


def solve_conservative_vector_junction(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    contract: ConservativeVectorJunctionContract,
    *,
    mass_balance_tolerance_m3s: float = 1e-12,
) -> ConservativeVectorJunctionSolution:
    """Solve native hydraulic coupling and expose its exact vector reaction.

    Flow azimuths point with the water motion. At the junction control volume,
    upstream cross sections have outward sign -1 and the downstream cross
    section has outward sign +1. The returned reaction is the source exerted
    by the unresolved junction walls and bed on the water. It is retained in
    the balance rather than silently assumed to vanish.
    """

    if not isinstance(contract, ConservativeVectorJunctionContract):
        raise TypeError("conservative_vector_junction_contract_required")
    terminals = tuple(upstream)
    if (
        tuple(value.branch_id for value in terminals)
        != contract.upstream_branch_ids
        or downstream.branch_id != contract.downstream_branch_id
    ):
        raise ValueError("conservative_vector_junction_branch_mismatch")
    hydraulic = solve_subcritical_dynamic_wave_confluence(
        terminals,
        downstream,
        mass_balance_tolerance_m3s=mass_balance_tolerance_m3s,
    )
    return evaluate_conservative_vector_junction_balance(
        terminals,
        downstream,
        contract,
        hydraulic,
    )


def evaluate_conservative_vector_junction_balance(
    upstream: tuple[DynamicWaveJunctionTerminal, ...],
    downstream: DynamicWaveJunctionTerminal,
    contract: ConservativeVectorJunctionContract,
    hydraulic: SubcriticalConfluenceSolution,
) -> ConservativeVectorJunctionSolution:
    """Project an already resolved scalar junction into its vector ledger."""

    if not isinstance(contract, ConservativeVectorJunctionContract):
        raise TypeError("conservative_vector_junction_contract_required")
    if not isinstance(hydraulic, SubcriticalConfluenceSolution):
        raise TypeError("subcritical_confluence_solution_required")
    terminals = tuple(upstream)
    if (
        tuple(value.branch_id for value in terminals)
        != contract.upstream_branch_ids
        or downstream.branch_id != contract.downstream_branch_id
        or hydraulic.upstream_branch_ids != contract.upstream_branch_ids
        or hydraulic.downstream_branch_id != contract.downstream_branch_id
    ):
        raise ValueError("conservative_vector_junction_branch_mismatch")
    upstream_fluxes = tuple(
        _branch_flux(
            terminal.branch_id,
            "upstream",
            boundary.state,
            terminal.section,
            azimuth,
            outward_normal_sign=-1.0,
        )
        for terminal, boundary, azimuth in zip(
            terminals,
            hydraulic.upstream_boundaries,
            contract.upstream_flow_azimuth_degrees,
            strict=True,
        )
    )
    downstream_flux = _branch_flux(
        downstream.branch_id,
        "downstream",
        hydraulic.downstream_boundary.state,
        downstream.section,
        contract.downstream_flow_azimuth_degrees,
        outward_normal_sign=1.0,
    )
    branch_fluxes = (*upstream_fluxes, downstream_flux)
    if any(
        value.discharge_m3s < -_FLOW_DIRECTION_TOLERANCE_M3S
        for value in branch_fluxes
    ):
        raise ValueError(
            "conservative_vector_junction_flow_direction_not_supported"
        )
    boundary_convective_east = sum(
        value.outward_convective_flux_east_m4s2
        for value in branch_fluxes
    )
    boundary_convective_north = sum(
        value.outward_convective_flux_north_m4s2
        for value in branch_fluxes
    )
    boundary_hydrostatic_east = sum(
        value.outward_hydrostatic_flux_east_m4s2
        for value in branch_fluxes
    )
    boundary_hydrostatic_north = sum(
        value.outward_hydrostatic_flux_north_m4s2
        for value in branch_fluxes
    )
    boundary_total_east = (
        boundary_convective_east + boundary_hydrostatic_east
    )
    boundary_total_north = (
        boundary_convective_north + boundary_hydrostatic_north
    )
    reaction_east = boundary_total_east
    reaction_north = boundary_total_north
    return ConservativeVectorJunctionSolution(
        contract=contract,
        hydraulic_solution=hydraulic,
        upstream_fluxes=upstream_fluxes,
        downstream_flux=downstream_flux,
        net_outward_mass_flux_m3s=(
            hydraulic.downstream_discharge_m3s
            - hydraulic.total_upstream_discharge_m3s
        ),
        boundary_convective_flux_east_m4s2=boundary_convective_east,
        boundary_convective_flux_north_m4s2=boundary_convective_north,
        boundary_hydrostatic_flux_east_m4s2=boundary_hydrostatic_east,
        boundary_hydrostatic_flux_north_m4s2=boundary_hydrostatic_north,
        boundary_total_flux_east_m4s2=boundary_total_east,
        boundary_total_flux_north_m4s2=boundary_total_north,
        junction_on_fluid_reaction_east_m4s2=reaction_east,
        junction_on_fluid_reaction_north_m4s2=reaction_north,
        momentum_ledger_residual_east_m4s2=(
            boundary_total_east - reaction_east
        ),
        momentum_ledger_residual_north_m4s2=(
            boundary_total_north - reaction_north
        ),
    )


def advance_conservative_vector_confluence_network_open(
    upstream_reaches: tuple[DynamicWaveNetworkReach, ...],
    downstream_reach: DynamicWaveNetworkReach,
    contract: ConservativeVectorJunctionContract,
    *,
    upstream_left_boundaries: tuple[FixedDynamicWaveBoundary, ...],
    downstream_right_boundary: FixedDynamicWaveBoundary,
    lateral_momentum_convention: str,
    timestep_seconds: float,
    maximum_courant_number: float,
) -> ConservativeVectorJunctionNetworkStep:
    """Advance the existing 1D FV network and retain the node reaction."""

    if not isinstance(contract, ConservativeVectorJunctionContract):
        raise TypeError("conservative_vector_junction_contract_required")
    if (
        tuple(value.reach_id for value in upstream_reaches)
        != contract.upstream_branch_ids
        or downstream_reach.reach_id != contract.downstream_branch_id
    ):
        raise ValueError("conservative_vector_junction_branch_mismatch")
    hydraulic_step = advance_subcritical_confluence_network_open(
        upstream_reaches,
        downstream_reach,
        upstream_left_boundaries=upstream_left_boundaries,
        downstream_right_boundary=downstream_right_boundary,
        lateral_momentum_convention=lateral_momentum_convention,
        timestep_seconds=timestep_seconds,
        maximum_courant_number=maximum_courant_number,
    )
    upstream_terminals = tuple(
        DynamicWaveJunctionTerminal(
            branch_id=reach.reach_id,
            interior_state=DynamicWaveCellState(
                reach.state.area_m2[-1], reach.state.discharge_m3s[-1]
            ),
            section=reach.sections[-1],
            bed_elevation_m=reach.bed_elevation_m[-1],
        )
        for reach in upstream_reaches
    )
    downstream_terminal = DynamicWaveJunctionTerminal(
        branch_id=downstream_reach.reach_id,
        interior_state=DynamicWaveCellState(
            downstream_reach.state.area_m2[0],
            downstream_reach.state.discharge_m3s[0],
        ),
        section=downstream_reach.sections[0],
        bed_elevation_m=downstream_reach.bed_elevation_m[0],
    )
    vector_junction = evaluate_conservative_vector_junction_balance(
        upstream_terminals,
        downstream_terminal,
        contract,
        hydraulic_step.junction,
    )
    return ConservativeVectorJunctionNetworkStep(
        hydraulic_step=hydraulic_step,
        vector_junction=vector_junction,
    )


def _branch_flux(
    branch_id: str,
    role: str,
    state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
    azimuth_degrees: float,
    *,
    outward_normal_sign: float,
) -> ConservativeVectorBranchFlux:
    radians = math.radians(azimuth_degrees)
    tangent_east = math.sin(radians)
    tangent_north = math.cos(radians)
    convective = (
        0.0
        if state.area_m2 == 0.0
        else state.discharge_m3s**2 / state.area_m2
    )
    hydrostatic = (
        STANDARD_GRAVITY_MPS2
        * section.hydrostatic_pressure_integral_m3(state.area_m2)
    )
    total = convective + hydrostatic
    signed_east = outward_normal_sign * tangent_east
    signed_north = outward_normal_sign * tangent_north
    return ConservativeVectorBranchFlux(
        branch_id=branch_id,
        role=role,
        flow_azimuth_degrees=azimuth_degrees,
        tangent_east=tangent_east,
        tangent_north=tangent_north,
        outward_normal_sign=outward_normal_sign,
        area_m2=state.area_m2,
        discharge_m3s=state.discharge_m3s,
        convective_flux_m4s2=convective,
        hydrostatic_flux_m4s2=hydrostatic,
        total_flux_m4s2=total,
        outward_convective_flux_east_m4s2=signed_east * convective,
        outward_convective_flux_north_m4s2=signed_north * convective,
        outward_hydrostatic_flux_east_m4s2=signed_east * hydrostatic,
        outward_hydrostatic_flux_north_m4s2=signed_north * hydrostatic,
        outward_total_flux_east_m4s2=signed_east * total,
        outward_total_flux_north_m4s2=signed_north * total,
    )
