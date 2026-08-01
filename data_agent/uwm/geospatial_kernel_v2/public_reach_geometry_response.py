"""Propagate public reach geometry hypotheses through dynamic-wave diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .dynamic_wave_flux import (
    STANDARD_GRAVITY_MPS2,
    DynamicWaveCellState,
    TrapezoidalChannelSection,
    dynamic_wave_characteristic_speeds_mps,
    dynamic_wave_physical_flux,
    hll_dynamic_wave_flux,
)
from .public_reach_geometry_stability import (
    PublicReachGeometryStabilityAudit,
    compile_public_reach_geometry_stability_audit,
)


PUBLIC_REACH_GEOMETRY_RESPONSE_SCHEMA = (
    "gwm.geospatial_kernel.public_reach_geometry_response.v1"
)
FLUX_IDENTITY_TOLERANCE = 1e-10
GEOMETRY_RESPONSE_MATERIALITY = 0.05


@dataclass(frozen=True)
class GeometryStateDiagnostic:
    geometry_id: str
    depth_m: float
    top_width_m: float
    gravity_wave_celerity_mps: float
    hydrostatic_pressure_integral_m3: float
    hydrostatic_momentum_flux_m4s2: float
    convective_momentum_flux_m4s2: float
    physical_area_flux_m3s: float
    physical_momentum_flux_m4s2: float
    hll_area_flux_m3s: float
    hll_momentum_flux_m4s2: float
    minimum_signal_speed_mps: float
    maximum_signal_speed_mps: float
    froude_number: float
    hll_wave_regime: str

    def __post_init__(self) -> None:
        scalars = (
            self.depth_m,
            self.top_width_m,
            self.gravity_wave_celerity_mps,
            self.hydrostatic_pressure_integral_m3,
            self.hydrostatic_momentum_flux_m4s2,
            self.convective_momentum_flux_m4s2,
            self.physical_area_flux_m3s,
            self.physical_momentum_flux_m4s2,
            self.hll_area_flux_m3s,
            self.hll_momentum_flux_m4s2,
            self.minimum_signal_speed_mps,
            self.maximum_signal_speed_mps,
            self.froude_number,
        )
        if (
            not self.geometry_id
            or any(not math.isfinite(value) for value in scalars)
            or self.depth_m <= 0.0
            or self.top_width_m <= 0.0
            or self.gravity_wave_celerity_mps <= 0.0
            or self.hydrostatic_pressure_integral_m3 <= 0.0
            or self.minimum_signal_speed_mps >= self.maximum_signal_speed_mps
            or self.hll_wave_regime != "subcritical_or_transcritical"
        ):
            raise ValueError("public_reach_geometry_state_diagnostic_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "geometry_id": self.geometry_id,
            "depth_m": self.depth_m,
            "top_width_m": self.top_width_m,
            "gravity_wave_celerity_mps": self.gravity_wave_celerity_mps,
            "hydrostatic_pressure_integral_m3": (
                self.hydrostatic_pressure_integral_m3
            ),
            "hydrostatic_momentum_flux_m4s2": (
                self.hydrostatic_momentum_flux_m4s2
            ),
            "convective_momentum_flux_m4s2": (
                self.convective_momentum_flux_m4s2
            ),
            "physical_flux": {
                "area_flux_m3s": self.physical_area_flux_m3s,
                "momentum_flux_m4s2": self.physical_momentum_flux_m4s2,
            },
            "identical_state_hll_flux": {
                "area_flux_m3s": self.hll_area_flux_m3s,
                "momentum_flux_m4s2": self.hll_momentum_flux_m4s2,
                "minimum_signal_speed_mps": self.minimum_signal_speed_mps,
                "maximum_signal_speed_mps": self.maximum_signal_speed_mps,
                "wave_regime": self.hll_wave_regime,
            },
            "froude_number": self.froude_number,
        }


@dataclass(frozen=True)
class ObservedStateGeometryResponse:
    measurement_id: str
    time: str
    observed_gage_height_m: float
    observed_state: DynamicWaveCellState
    state_conditioned_rectangle: GeometryStateDiagnostic
    bridge_trapezoid_candidate: GeometryStateDiagnostic
    bridge_candidate_implied_gage_height_m: float
    bridge_candidate_stage_error_m: float

    def __post_init__(self) -> None:
        baseline = self.state_conditioned_rectangle
        candidate = self.bridge_trapezoid_candidate
        if (
            not self.measurement_id
            or baseline.geometry_id != "state_conditioned_observed_rectangle"
            or candidate.geometry_id != "stage24_bridge_trapezoid_candidate"
            or abs(
                baseline.physical_area_flux_m3s
                - self.observed_state.discharge_m3s
            )
            > FLUX_IDENTITY_TOLERANCE
            or abs(
                candidate.physical_area_flux_m3s
                - self.observed_state.discharge_m3s
            )
            > FLUX_IDENTITY_TOLERANCE
            or abs(baseline.hll_area_flux_m3s - self.observed_state.discharge_m3s)
            > FLUX_IDENTITY_TOLERANCE
            or abs(candidate.hll_area_flux_m3s - self.observed_state.discharge_m3s)
            > FLUX_IDENTITY_TOLERANCE
            or abs(
                baseline.hll_momentum_flux_m4s2
                - baseline.physical_momentum_flux_m4s2
            )
            > FLUX_IDENTITY_TOLERANCE
            or abs(
                candidate.hll_momentum_flux_m4s2
                - candidate.physical_momentum_flux_m4s2
            )
            > FLUX_IDENTITY_TOLERANCE
            or baseline.convective_momentum_flux_m4s2
            != candidate.convective_momentum_flux_m4s2
        ):
            raise ValueError("public_reach_observed_geometry_response_invalid")

    def relative_change(self, field: str) -> float:
        baseline = float(getattr(self.state_conditioned_rectangle, field))
        candidate = float(getattr(self.bridge_trapezoid_candidate, field))
        if baseline == 0.0:
            raise ValueError("public_reach_geometry_response_zero_baseline")
        return candidate / baseline - 1.0

    def as_dict(self) -> dict[str, object]:
        relative_fields = {
            "depth": "depth_m",
            "top_width": "top_width_m",
            "gravity_wave_celerity": "gravity_wave_celerity_mps",
            "hydrostatic_pressure_integral": (
                "hydrostatic_pressure_integral_m3"
            ),
            "physical_momentum_flux": "physical_momentum_flux_m4s2",
            "froude_number": "froude_number",
        }
        return {
            "measurement_id": self.measurement_id,
            "time": self.time,
            "observed_gage_height_m": self.observed_gage_height_m,
            "observed_state": {
                "area_m2": self.observed_state.area_m2,
                "discharge_m3s": self.observed_state.discharge_m3s,
                "mean_velocity_mps": self.observed_state.mean_velocity_mps,
            },
            "state_conditioned_rectangle": (
                self.state_conditioned_rectangle.as_dict()
            ),
            "bridge_trapezoid_candidate": (
                self.bridge_trapezoid_candidate.as_dict()
            ),
            "bridge_candidate_implied_gage_height_m": (
                self.bridge_candidate_implied_gage_height_m
            ),
            "bridge_candidate_stage_error_m": self.bridge_candidate_stage_error_m,
            "candidate_relative_change_from_rectangle": {
                name: self.relative_change(field)
                for name, field in relative_fields.items()
            },
        }


@dataclass(frozen=True)
class PublicReachGeometryResponseAudit:
    source: PublicReachGeometryStabilityAudit
    responses: tuple[ObservedStateGeometryResponse, ...]

    def __post_init__(self) -> None:
        temporal_ids = self.source.cohort_measurement_ids["temporal_holdout"]
        if (
            len(self.responses) != 20
            or tuple(value.measurement_id for value in self.responses)
            != temporal_ids
            or len({value.measurement_id for value in self.responses}) != 20
        ):
            raise ValueError("public_reach_geometry_response_audit_invalid")

    def require_runtime_geometry_rollout(self) -> None:
        raise ValueError("public_reach_geometry_response_is_state_diagnostic_only")

    def require_reach_wide_geometry_transfer(self) -> None:
        raise ValueError("public_reach_geometry_response_not_reach_wide_transfer")

    def require_confluence_patch_geometry(self) -> None:
        raise ValueError("public_reach_geometry_response_not_confluence_geometry")

    def as_dict(self) -> dict[str, object]:
        relative_fields = {
            "depth": "depth_m",
            "top_width": "top_width_m",
            "gravity_wave_celerity": "gravity_wave_celerity_mps",
            "hydrostatic_pressure_integral": (
                "hydrostatic_pressure_integral_m3"
            ),
            "physical_momentum_flux": "physical_momentum_flux_m4s2",
            "froude_number": "froude_number",
        }
        response_distributions = {
            name: _distribution(
                [value.relative_change(field) for value in self.responses]
            )
            for name, field in relative_fields.items()
        }
        response_distributions["bridge_candidate_stage_error_m"] = _distribution(
            [value.bridge_candidate_stage_error_m for value in self.responses]
        )
        maximum_area_flux_error = max(
            abs(
                diagnostic.hll_area_flux_m3s
                - response.observed_state.discharge_m3s
            )
            for response in self.responses
            for diagnostic in (
                response.state_conditioned_rectangle,
                response.bridge_trapezoid_candidate,
            )
        )
        maximum_hll_physical_momentum_error = max(
            abs(
                diagnostic.hll_momentum_flux_m4s2
                - diagnostic.physical_momentum_flux_m4s2
            )
            for response in self.responses
            for diagnostic in (
                response.state_conditioned_rectangle,
                response.bridge_trapezoid_candidate,
            )
        )
        return {
            "schema": PUBLIC_REACH_GEOMETRY_RESPONSE_SCHEMA,
            "source_geometry_schema": (
                self.source.as_dict()["schema"]
            ),
            "monitoring_location_id": self.source.source.monitoring_location_id,
            "reach_id": self.source.source.reach_id,
            "evaluation_cohort": "stage24_temporal_holdout_bridge_adcp",
            "measurement_count": len(self.responses),
            "geometry_hypotheses": [
                "state_conditioned_observed_rectangle",
                "stage24_bridge_trapezoid_candidate",
            ],
            "comparison_contract": {
                "same_observed_area_and_discharge_for_both_geometries": True,
                "same_mean_velocity_and_convective_momentum_for_both": True,
                "identical_state_hll_interface": True,
                "temporal_records_treated_as_adjacent_spatial_cells": False,
                "difference_origin": (
                    "section_depth_top_width_and_hydrostatic_pressure_only"
                ),
            },
            "response_distributions": response_distributions,
            "maximum_hll_area_flux_identity_error_m3s": maximum_area_flux_error,
            "maximum_hll_physical_momentum_identity_error_m4s2": (
                maximum_hll_physical_momentum_error
            ),
            "materiality_threshold": GEOMETRY_RESPONSE_MATERIALITY,
            "hydrostatic_geometry_response_is_material": (
                response_distributions["hydrostatic_pressure_integral"][
                    "minimum"
                ]
                > GEOMETRY_RESPONSE_MATERIALITY
            ),
            "responses": [value.as_dict() for value in self.responses],
            "decision": {
                "geometry_contract_changes_hydrodynamic_response": True,
                "mass_flux_changes_when_state_is_fixed": False,
                "convective_momentum_changes_when_state_is_fixed": False,
                "hydrostatic_momentum_changes_when_state_is_fixed": True,
                "stage24_bridge_geometry_admitted_for_runtime": False,
                "reach_wide_geometry_transfer_admitted": False,
                "confluence_patch_geometry_admitted": False,
                "operator_admitted": False,
            },
            "claim_boundary": {
                "observed_state_geometry_response_quantified": True,
                "dynamic_time_advance_performed": False,
                "spatial_neighbor_state_observed": False,
                "identical_state_hll_used_as_physical_flux_diagnostic": True,
                "runtime_geometry_admitted": False,
                "operator_admitted": False,
            },
        }


def compile_public_reach_geometry_response_audit(
    source: PublicReachGeometryStabilityAudit | None = None,
) -> PublicReachGeometryResponseAudit:
    if source is None:
        source = compile_public_reach_geometry_stability_audit()
    by_id = {
        value.measurement_id: value for value in source.source.measurements
    }
    responses = []
    for measurement_id in source.cohort_measurement_ids["temporal_holdout"]:
        measurement = by_id[measurement_id]
        candidate_depth = source.candidate.section.depth_m(
            measurement.flow_area_m2
        )
        implied_stage = source.candidate.zero_area_gage_height_m + candidate_depth
        responses.append(
            ObservedStateGeometryResponse(
                measurement_id=measurement.measurement_id,
                time=measurement.time,
                observed_gage_height_m=measurement.gage_height_m,
                observed_state=measurement.dynamic_wave_state,
                state_conditioned_rectangle=_diagnose(
                    "state_conditioned_observed_rectangle",
                    measurement.dynamic_wave_state,
                    measurement.equivalent_section,
                ),
                bridge_trapezoid_candidate=_diagnose(
                    "stage24_bridge_trapezoid_candidate",
                    measurement.dynamic_wave_state,
                    source.candidate.section,
                ),
                bridge_candidate_implied_gage_height_m=implied_stage,
                bridge_candidate_stage_error_m=(
                    implied_stage - measurement.gage_height_m
                ),
            )
        )
    return PublicReachGeometryResponseAudit(source, tuple(responses))


def _diagnose(
    geometry_id: str,
    state: DynamicWaveCellState,
    section: TrapezoidalChannelSection,
) -> GeometryStateDiagnostic:
    depth = section.depth_m(state.area_m2)
    top_width = section.top_width_m(state.area_m2)
    celerity = section.gravity_wave_celerity_mps(state.area_m2)
    pressure_integral = section.hydrostatic_pressure_integral_m3(state.area_m2)
    physical = dynamic_wave_physical_flux(state, section)
    hll = hll_dynamic_wave_flux(state, state, section)
    minimum_speed, maximum_speed = dynamic_wave_characteristic_speeds_mps(
        state, section
    )
    convective = state.discharge_m3s**2 / state.area_m2
    return GeometryStateDiagnostic(
        geometry_id=geometry_id,
        depth_m=depth,
        top_width_m=top_width,
        gravity_wave_celerity_mps=celerity,
        hydrostatic_pressure_integral_m3=pressure_integral,
        hydrostatic_momentum_flux_m4s2=(STANDARD_GRAVITY_MPS2 * pressure_integral),
        convective_momentum_flux_m4s2=convective,
        physical_area_flux_m3s=physical.area_flux_m3s,
        physical_momentum_flux_m4s2=physical.momentum_flux_m4s2,
        hll_area_flux_m3s=hll.flux.area_flux_m3s,
        hll_momentum_flux_m4s2=hll.flux.momentum_flux_m4s2,
        minimum_signal_speed_mps=minimum_speed,
        maximum_signal_speed_mps=maximum_speed,
        froude_number=state.mean_velocity_mps / celerity,
        hll_wave_regime=hll.wave_regime,
    )


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "minimum": ordered[0],
        "p05": _quantile(ordered, 0.05),
        "median": _quantile(ordered, 0.5),
        "p95": _quantile(ordered, 0.95),
        "maximum": ordered[-1],
        "maximum_absolute": max(abs(value) for value in ordered),
    }


def _quantile(ordered: list[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])
