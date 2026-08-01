"""Auditable force decomposition for HEC-RAS-style steady junction hypotheses.

This module is diagnostic only.  Its variants expose one changed force
assumption at a time; none is a calibrated or admitted production operator.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .dynamic_wave_flux import STANDARD_GRAVITY_MPS2
from .hec_ras_reference import (
    HecRasCrossSection,
    HecRasGeometry,
    HecRasPlan,
    HecRasSteadyFlow,
    ReachKey,
)
from .irregular_section import ConveyanceMomentumDistribution


HEC_RAS_FORCE_DIAGNOSTIC_SCHEMA = (
    "gwm.geospatial_kernel.hec_ras_force_diagnostic.v1"
)
HEC_RAS_FORCE_VARIANT_SOLUTION_SCHEMA = (
    "gwm.geospatial_kernel.hec_ras_force_variant_solution.v1"
)
_FLOW_TOLERANCE_M3S = 1e-9
_ROOT_SCAN_INTERVALS = 4096


@dataclass(frozen=True)
class HecRasForceVariant:
    variant_id: str
    changed_assumption: str
    evidence_basis: str
    pressure_projection: str = "cosine"
    control_volume_upstream_area_projection: str = "cosine"
    friction_downstream_allocation: str = "whole_section"
    bed_slope_interpretation: str = "invert_tangent"
    pressure_term_interpretation: str = "exact_centroid"
    matches_documented_equations: bool = False

    def __post_init__(self) -> None:
        if (
            not self.variant_id
            or not self.changed_assumption
            or not self.evidence_basis
            or self.pressure_projection not in {"cosine", "unprojected"}
            or self.control_volume_upstream_area_projection
            not in {"cosine", "unprojected"}
            or self.friction_downstream_allocation
            not in {"whole_section", "flow_weighted_branch_share"}
            or self.bed_slope_interpretation
            not in {"invert_tangent", "invert_sine", "friction_slope"}
            or self.pressure_term_interpretation
            not in {"exact_centroid", "rectangular_half_max_depth"}
        ):
            raise ValueError("hec_ras_force_variant_contract_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "variant_id": self.variant_id,
            "changed_assumption": self.changed_assumption,
            "evidence_basis": self.evidence_basis,
            "pressure_projection": self.pressure_projection,
            "control_volume_upstream_area_projection": (
                self.control_volume_upstream_area_projection
            ),
            "friction_downstream_allocation": (
                self.friction_downstream_allocation
            ),
            "bed_slope_interpretation": self.bed_slope_interpretation,
            "pressure_term_interpretation": (
                self.pressure_term_interpretation
            ),
            "matches_documented_equations": self.matches_documented_equations,
            "calibrated_to_example10": False,
            "operator_admitted": False,
        }


DOCUMENTED_FORCE_VARIANT = HecRasForceVariant(
    variant_id="documented_full_specific_force_projection",
    changed_assumption="none; Stage 11 documented reference",
    evidence_basis=(
        "USACE equations 4-3 and 4-5 through 4-8: exact specific force, "
        "cosine projection, average-conveyance friction, flow-weighted "
        "downstream area, and small-slope bed weight"
    ),
    matches_documented_equations=True,
)

PRESSURE_UNPROJECTED_VARIANT = HecRasForceVariant(
    variant_id="unprojected_hydrostatic_pressure",
    changed_assumption=(
        "leave hydrostatic pressure unprojected while projecting convective momentum"
    ),
    evidence_basis=(
        "pre-specified alternative vector treatment of bank pressure; conflicts "
        "with the literal SF*cos(theta) in USACE equation 4-5"
    ),
    pressure_projection="unprojected",
)

CONTROL_VOLUME_AREA_UNPROJECTED_VARIANT = HecRasForceVariant(
    variant_id="unprojected_upstream_control_volume_area",
    changed_assumption=(
        "do not cosine-project the upstream half of friction and weight area"
    ),
    evidence_basis=(
        "pre-specified control-volume area-placement alternative; conflicts "
        "with the upstream A*cos(theta) terms in USACE equations 4-6 and 4-8"
    ),
    control_volume_upstream_area_projection="unprojected",
)

EXACT_BED_SINE_VARIANT = HecRasForceVariant(
    variant_id="exact_bed_sine",
    changed_assumption="replace tan(slope angle) by its exact sine",
    evidence_basis=(
        "USACE momentum derivation states sin(angle) is approximated by tangent "
        "for natural-river small slopes"
    ),
    bed_slope_interpretation="invert_sine",
)

BRANCH_ALLOCATED_FRICTION_VARIANT = HecRasForceVariant(
    variant_id="flow_weighted_downstream_friction_share",
    changed_assumption=(
        "allocate downstream conveyance and discharge to each virtual branch "
        "before evaluating representative friction slope"
    ),
    evidence_basis=(
        "pre-specified branch-control-volume interpretation of the documented "
        "flow-weighted downstream area; not stated by USACE equation 4-6"
    ),
    friction_downstream_allocation="flow_weighted_branch_share",
)

FRICTION_SLOPE_WEIGHT_VARIANT = HecRasForceVariant(
    variant_id="friction_slope_as_water_weight",
    changed_assumption="use representative friction slope for the water-weight term",
    evidence_basis=(
        "literal reading of the published second water-weight equation 4-9; "
        "the page repeats the first branch label and contradicts equation 4-8, "
        "so this is treated as a documentation-error diagnostic"
    ),
    bed_slope_interpretation="friction_slope",
)

RECTANGULAR_PRESSURE_VARIANT = HecRasForceVariant(
    variant_id="rectangular_half_max_depth_pressure",
    changed_assumption=(
        "replace exact irregular-section centroid pressure by A*maximum_depth/2"
    ),
    evidence_basis=(
        "standard rectangular-channel approximation specified before evaluation; "
        "USACE equation 4-3 instead requires total area times centroid depth"
    ),
    pressure_term_interpretation="rectangular_half_max_depth",
)

HEC_RAS_FORCE_VARIANTS = (
    DOCUMENTED_FORCE_VARIANT,
    PRESSURE_UNPROJECTED_VARIANT,
    CONTROL_VOLUME_AREA_UNPROJECTED_VARIANT,
    EXACT_BED_SINE_VARIANT,
    BRANCH_ALLOCATED_FRICTION_VARIANT,
    FRICTION_SLOPE_WEIGHT_VARIANT,
    RECTANGULAR_PRESSURE_VARIANT,
)


@dataclass(frozen=True)
class HecRasSectionForceBreakdown:
    reach_key: ReachKey
    river_station: str
    water_surface_elevation_m: float
    discharge_m3s: float
    flow_area_m2: float
    conveyance_m3s: float
    momentum_coefficient_beta: float
    froude_number: float
    hydrostatic_pressure_term_m3: float
    convective_momentum_term_m3: float
    specific_force_m3: float

    def as_dict(self) -> dict[str, object]:
        return {
            "reach_key": list(self.reach_key),
            "river_station": self.river_station,
            "water_surface_elevation_m": self.water_surface_elevation_m,
            "discharge_m3s": self.discharge_m3s,
            "flow_area_m2": self.flow_area_m2,
            "conveyance_m3s": self.conveyance_m3s,
            "momentum_coefficient_beta": self.momentum_coefficient_beta,
            "froude_number": self.froude_number,
            "hydrostatic_pressure_term_m3": self.hydrostatic_pressure_term_m3,
            "convective_momentum_term_m3": self.convective_momentum_term_m3,
            "specific_force_m3": self.specific_force_m3,
        }


@dataclass(frozen=True)
class HecRasBranchForceBreakdown:
    section_force: HecRasSectionForceBreakdown
    deflection_degrees: float
    projection_cosine: float
    projected_hydrostatic_pressure_term_m3: float
    projected_convective_momentum_term_m3: float
    projected_specific_force_m3: float
    section_spacing_m: float
    downstream_area_fraction: float
    upstream_control_volume_area_m2: float
    downstream_allocated_area_m2: float
    half_length_area_volume_m3: float
    representative_friction_slope: float
    invert_tangent_slope: float
    applied_bed_slope: float
    friction_force_m3: float
    water_weight_force_m3: float
    contribution_m3: float

    def as_dict(self) -> dict[str, object]:
        return {
            "section_force": self.section_force.as_dict(),
            "deflection_degrees": self.deflection_degrees,
            "projection_cosine": self.projection_cosine,
            "projected_hydrostatic_pressure_term_m3": (
                self.projected_hydrostatic_pressure_term_m3
            ),
            "projected_convective_momentum_term_m3": (
                self.projected_convective_momentum_term_m3
            ),
            "projected_specific_force_m3": self.projected_specific_force_m3,
            "section_spacing_m": self.section_spacing_m,
            "downstream_area_fraction": self.downstream_area_fraction,
            "upstream_control_volume_area_m2": (
                self.upstream_control_volume_area_m2
            ),
            "downstream_allocated_area_m2": self.downstream_allocated_area_m2,
            "half_length_area_volume_m3": self.half_length_area_volume_m3,
            "representative_friction_slope": self.representative_friction_slope,
            "invert_tangent_slope": self.invert_tangent_slope,
            "applied_bed_slope": self.applied_bed_slope,
            "friction_force_m3": self.friction_force_m3,
            "water_weight_force_m3": self.water_weight_force_m3,
            "net_friction_and_weight_m3": (
                -self.friction_force_m3 + self.water_weight_force_m3
            ),
            "contribution_m3": self.contribution_m3,
        }


@dataclass(frozen=True)
class HecRasForceDiagnosticBalance:
    variant: HecRasForceVariant
    common_upstream_water_surface_elevation_m: float
    downstream_water_surface_elevation_m: float
    downstream_force: HecRasSectionForceBreakdown
    branches: tuple[HecRasBranchForceBreakdown, ...]
    residual_m3: float

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HEC_RAS_FORCE_DIAGNOSTIC_SCHEMA,
            "variant": self.variant.as_dict(),
            "common_upstream_water_surface_elevation_m": (
                self.common_upstream_water_surface_elevation_m
            ),
            "downstream_water_surface_elevation_m": (
                self.downstream_water_surface_elevation_m
            ),
            "downstream_force": self.downstream_force.as_dict(),
            "branches": [value.as_dict() for value in self.branches],
            "upstream_contribution_sum_m3": sum(
                value.contribution_m3 for value in self.branches
            ),
            "residual_m3": self.residual_m3,
            "equation": (
                "SF_down - sum(projected_pressure + projected_convective "
                "- friction + bed_weight)"
            ),
            "diagnostic_only": True,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class HecRasForceVariantSolution:
    variant: HecRasForceVariant
    balance: HecRasForceDiagnosticBalance
    root_bracket_m: tuple[float, float]
    reference_upstream_water_surface_elevation_m: float | None = None

    @property
    def reference_stage_error_m(self) -> float | None:
        if self.reference_upstream_water_surface_elevation_m is None:
            return None
        return (
            self.balance.common_upstream_water_surface_elevation_m
            - self.reference_upstream_water_surface_elevation_m
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": HEC_RAS_FORCE_VARIANT_SOLUTION_SCHEMA,
            "variant": self.variant.as_dict(),
            "balance": self.balance.as_dict(),
            "root_bracket_m": list(self.root_bracket_m),
            "reference_upstream_water_surface_elevation_m": (
                self.reference_upstream_water_surface_elevation_m
            ),
            "reference_stage_error_m": self.reference_stage_error_m,
            "calibrated_to_reference_stage": False,
            "diagnostic_only": True,
            "operator_admitted": False,
        }


def evaluate_hec_ras_force_variant(
    geometry: HecRasGeometry,
    flow: HecRasSteadyFlow,
    plan: HecRasPlan,
    variant: HecRasForceVariant,
    *,
    common_upstream_water_surface_elevation_m: float,
    downstream_water_surface_elevation_m: float,
) -> HecRasForceDiagnosticBalance:
    _validate_inputs(geometry, flow, plan, variant)
    upstream_sections, downstream_section = geometry.junction_terminal_sections()
    upstream_discharges = tuple(
        flow.discharge_for_reach(value.reach_key) for value in upstream_sections
    )
    downstream_discharge = flow.discharge_for_reach(downstream_section.reach_key)
    downstream_distribution = downstream_section.distribution(
        downstream_water_surface_elevation_m, downstream_discharge
    )
    downstream_force = _section_force(
        downstream_section, downstream_distribution, variant
    )
    branches: list[HecRasBranchForceBreakdown] = []
    for section, discharge, length, angle in zip(
        upstream_sections,
        upstream_discharges,
        geometry.junction.reach_lengths_m,
        geometry.junction.deflection_degrees,
        strict=True,
    ):
        distribution = section.distribution(
            common_upstream_water_surface_elevation_m, discharge
        )
        section_force = _section_force(section, distribution, variant)
        cosine = math.cos(math.radians(angle))
        pressure_factor = (
            cosine if variant.pressure_projection == "cosine" else 1.0
        )
        projected_pressure = (
            section_force.hydrostatic_pressure_term_m3 * pressure_factor
        )
        projected_convective = (
            section_force.convective_momentum_term_m3 * cosine
        )
        flow_fraction = discharge / downstream_discharge
        upstream_area_factor = (
            cosine
            if variant.control_volume_upstream_area_projection == "cosine"
            else 1.0
        )
        upstream_control_area = distribution.total_area_m2 * upstream_area_factor
        downstream_allocated_area = (
            downstream_distribution.total_area_m2 * flow_fraction
        )
        half_length_area_volume = 0.5 * length * (
            upstream_control_area + downstream_allocated_area
        )
        if variant.friction_downstream_allocation == "whole_section":
            friction_downstream_discharge = downstream_discharge
            friction_downstream_conveyance = (
                downstream_distribution.total_conveyance_m3s
            )
        else:
            friction_downstream_discharge = downstream_discharge * flow_fraction
            friction_downstream_conveyance = (
                downstream_distribution.total_conveyance_m3s * flow_fraction
            )
        representative_friction_slope = (
            (discharge + friction_downstream_discharge)
            / (
                distribution.total_conveyance_m3s
                + friction_downstream_conveyance
            )
        ) ** 2
        invert_tangent_slope = (
            section.invert_elevation_m - downstream_section.invert_elevation_m
        ) / length
        if invert_tangent_slope < -1e-12:
            raise ValueError("hec_ras_force_adverse_junction_slope_not_supported")
        invert_tangent_slope = max(0.0, invert_tangent_slope)
        if variant.bed_slope_interpretation == "invert_tangent":
            applied_bed_slope = invert_tangent_slope
        elif variant.bed_slope_interpretation == "invert_sine":
            applied_bed_slope = invert_tangent_slope / math.sqrt(
                1.0 + invert_tangent_slope**2
            )
        else:
            applied_bed_slope = representative_friction_slope
        friction_force = representative_friction_slope * half_length_area_volume
        water_weight_force = applied_bed_slope * half_length_area_volume
        projected_specific_force = projected_pressure + projected_convective
        contribution = (
            projected_specific_force - friction_force + water_weight_force
        )
        branches.append(
            HecRasBranchForceBreakdown(
                section_force=section_force,
                deflection_degrees=angle,
                projection_cosine=cosine,
                projected_hydrostatic_pressure_term_m3=projected_pressure,
                projected_convective_momentum_term_m3=projected_convective,
                projected_specific_force_m3=projected_specific_force,
                section_spacing_m=length,
                downstream_area_fraction=flow_fraction,
                upstream_control_volume_area_m2=upstream_control_area,
                downstream_allocated_area_m2=downstream_allocated_area,
                half_length_area_volume_m3=half_length_area_volume,
                representative_friction_slope=representative_friction_slope,
                invert_tangent_slope=invert_tangent_slope,
                applied_bed_slope=applied_bed_slope,
                friction_force_m3=friction_force,
                water_weight_force_m3=water_weight_force,
                contribution_m3=contribution,
            )
        )
    residual = downstream_force.specific_force_m3 - sum(
        value.contribution_m3 for value in branches
    )
    return HecRasForceDiagnosticBalance(
        variant=variant,
        common_upstream_water_surface_elevation_m=float(
            common_upstream_water_surface_elevation_m
        ),
        downstream_water_surface_elevation_m=float(
            downstream_water_surface_elevation_m
        ),
        downstream_force=downstream_force,
        branches=tuple(branches),
        residual_m3=residual,
    )


def solve_hec_ras_force_variant(
    geometry: HecRasGeometry,
    flow: HecRasSteadyFlow,
    plan: HecRasPlan,
    variant: HecRasForceVariant,
    *,
    downstream_water_surface_elevation_m: float,
    reference_upstream_water_surface_elevation_m: float | None = None,
    momentum_tolerance_m3: float = 1e-11,
) -> HecRasForceVariantSolution:
    tolerance = float(momentum_tolerance_m3)
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("hec_ras_force_solver_tolerance_invalid")
    _validate_inputs(geometry, flow, plan, variant)
    upstream_sections, _ = geometry.junction_terminal_sections()
    lower = max(value.section.minimum_elevation_m for value in upstream_sections)
    upper = min(
        value.section.maximum_closed_water_surface_elevation_m
        for value in upstream_sections
    )
    span = upper - lower
    if span <= 0.0:
        raise ValueError("hec_ras_force_root_domain_invalid")
    previous: tuple[float, HecRasForceDiagnosticBalance] | None = None
    bracket: tuple[float, float, HecRasForceDiagnosticBalance] | None = None
    for index in range(_ROOT_SCAN_INTERVALS + 1):
        elevation = lower + span * max(index, 1e-9) / _ROOT_SCAN_INTERVALS
        try:
            balance = evaluate_hec_ras_force_variant(
                geometry,
                flow,
                plan,
                variant,
                common_upstream_water_surface_elevation_m=elevation,
                downstream_water_surface_elevation_m=(
                    downstream_water_surface_elevation_m
                ),
            )
        except ValueError:
            previous = None
            continue
        if abs(balance.residual_m3) <= tolerance:
            return HecRasForceVariantSolution(
                variant,
                balance,
                (elevation, elevation),
                reference_upstream_water_surface_elevation_m,
            )
        if previous is not None and previous[1].residual_m3 * balance.residual_m3 < 0.0:
            bracket = previous[0], elevation, previous[1]
            break
        previous = elevation, balance
    if bracket is None:
        raise ValueError("hec_ras_force_no_momentum_root")
    bracket_lower, bracket_upper, lower_balance = bracket
    original_bracket = bracket_lower, bracket_upper
    lower_residual = lower_balance.residual_m3
    balance = lower_balance
    for _ in range(120):
        elevation = 0.5 * (bracket_lower + bracket_upper)
        balance = evaluate_hec_ras_force_variant(
            geometry,
            flow,
            plan,
            variant,
            common_upstream_water_surface_elevation_m=elevation,
            downstream_water_surface_elevation_m=downstream_water_surface_elevation_m,
        )
        if abs(balance.residual_m3) <= tolerance:
            break
        if lower_residual * balance.residual_m3 <= 0.0:
            bracket_upper = elevation
        else:
            bracket_lower = elevation
            lower_residual = balance.residual_m3
    if abs(balance.residual_m3) > tolerance:
        raise ValueError("hec_ras_force_root_tolerance_not_met")
    return HecRasForceVariantSolution(
        variant,
        balance,
        original_bracket,
        reference_upstream_water_surface_elevation_m,
    )


def _section_force(
    section: HecRasCrossSection,
    distribution: ConveyanceMomentumDistribution,
    variant: HecRasForceVariant,
) -> HecRasSectionForceBreakdown:
    wet = section.section.wet_properties_at_elevation(
        distribution.water_surface_elevation_m
    )
    if wet.top_width_m <= 0.0 or distribution.total_area_m2 <= 0.0:
        raise ValueError("hec_ras_force_wet_section_invalid")
    velocity = distribution.total_discharge_m3s / distribution.total_area_m2
    celerity = math.sqrt(
        STANDARD_GRAVITY_MPS2 * distribution.total_area_m2 / wet.top_width_m
    )
    froude = velocity / celerity
    if froude >= 1.0:
        raise ValueError("hec_ras_force_state_not_subcritical")
    if variant.pressure_term_interpretation == "exact_centroid":
        pressure = wet.hydrostatic_pressure_integral_m3
    else:
        maximum_depth = (
            distribution.water_surface_elevation_m - section.invert_elevation_m
        )
        pressure = 0.5 * distribution.total_area_m2 * maximum_depth
    convective = (
        distribution.momentum_coefficient_beta
        * distribution.total_discharge_m3s**2
        / (STANDARD_GRAVITY_MPS2 * distribution.total_area_m2)
    )
    return HecRasSectionForceBreakdown(
        reach_key=section.reach_key,
        river_station=section.river_station,
        water_surface_elevation_m=distribution.water_surface_elevation_m,
        discharge_m3s=distribution.total_discharge_m3s,
        flow_area_m2=distribution.total_area_m2,
        conveyance_m3s=distribution.total_conveyance_m3s,
        momentum_coefficient_beta=distribution.momentum_coefficient_beta,
        froude_number=froude,
        hydrostatic_pressure_term_m3=pressure,
        convective_momentum_term_m3=convective,
        specific_force_m3=pressure + convective,
    )


def _validate_inputs(
    geometry: HecRasGeometry,
    flow: HecRasSteadyFlow,
    plan: HecRasPlan,
    variant: HecRasForceVariant,
) -> None:
    if (
        not isinstance(geometry, HecRasGeometry)
        or not isinstance(flow, HecRasSteadyFlow)
        or not isinstance(plan, HecRasPlan)
        or not isinstance(variant, HecRasForceVariant)
        or not plan.subcritical_flow
        or plan.short_identifier != "Momentum"
        or plan.friction_slope_method != 1
    ):
        raise ValueError("hec_ras_force_inputs_not_supported")
    upstream_sections, downstream_section = geometry.junction_terminal_sections()
    upstream_discharge = sum(
        flow.discharge_for_reach(value.reach_key) for value in upstream_sections
    )
    downstream_discharge = flow.discharge_for_reach(downstream_section.reach_key)
    if abs(upstream_discharge - downstream_discharge) > _FLOW_TOLERANCE_M3S:
        raise ValueError("hec_ras_force_mass_balance_invalid")
