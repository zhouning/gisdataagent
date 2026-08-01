"""Audit whether public reach observations support a stable cross section."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from statistics import median

from .dynamic_wave_flux import TrapezoidalChannelSection
from .public_reach_hydraulic_measurements import (
    ObservedReachHydraulicState,
    PublicReachHydraulicMeasurements,
    compile_public_reach_hydraulic_measurements,
)


PUBLIC_REACH_GEOMETRY_STABILITY_SCHEMA = (
    "gwm.geospatial_kernel.public_reach_geometry_stability.v1"
)
TEMPORAL_HOLDOUT_START = "2023-01-01T00:00:00+00:00"
PRIMARY_MAXIMUM_DISTANCE_M = 30.0
METHOD_HOLDOUT_MINIMUM_DISTANCE_M = 30.0
AREA_FIT_SCALE_M2 = 100.0
WIDTH_FIT_SCALE_M = 50.0
MEDIAN_ABSOLUTE_PERCENTAGE_ERROR_LIMIT = 0.10
P90_ABSOLUTE_PERCENTAGE_ERROR_LIMIT = 0.15


@dataclass(frozen=True)
class TrapezoidalStageGeometryCandidate:
    reference_gage_height_m: float
    area_at_reference_m2: float
    top_width_at_reference_m: float
    side_slope_horizontal_per_vertical: float
    zero_area_gage_height_m: float
    section: TrapezoidalChannelSection
    training_stage_range_m: tuple[float, float]
    training_measurement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (
            self.reference_gage_height_m,
            self.area_at_reference_m2,
            self.top_width_at_reference_m,
            self.side_slope_horizontal_per_vertical,
            self.zero_area_gage_height_m,
        )
        if (
            any(not math.isfinite(value) for value in values)
            or self.area_at_reference_m2 <= 0.0
            or self.top_width_at_reference_m <= 0.0
            or self.side_slope_horizontal_per_vertical <= 0.0
            or self.zero_area_gage_height_m
            >= self.training_stage_range_m[0]
            or len(self.training_measurement_ids) != 55
        ):
            raise ValueError("public_reach_geometry_candidate_invalid")
        predicted_area, predicted_width = self.predict(
            self.reference_gage_height_m
        )
        if (
            abs(predicted_area - self.area_at_reference_m2) > 1e-9
            or abs(predicted_width - self.top_width_at_reference_m) > 1e-9
        ):
            raise ValueError("public_reach_geometry_candidate_binding_invalid")

    def depth_m(self, gage_height_m: float) -> float:
        stage = float(gage_height_m)
        if not math.isfinite(stage) or stage < self.zero_area_gage_height_m:
            raise ValueError("public_reach_geometry_stage_outside_physical_domain")
        return stage - self.zero_area_gage_height_m

    def predict(self, gage_height_m: float) -> tuple[float, float]:
        depth = self.depth_m(gage_height_m)
        area = self.section.area_m2(depth)
        return area, self.section.top_width_m(area)

    def derivative_width_m(self, gage_height_m: float) -> float:
        depth = self.depth_m(gage_height_m)
        return self.section.bottom_width_m + 2.0 * (
            self.section.side_slope_horizontal_per_vertical * depth
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "model": "gage_datum_referenced_trapezoidal_stage_geometry",
            "reference_gage_height_m": self.reference_gage_height_m,
            "area_at_reference_m2": self.area_at_reference_m2,
            "top_width_at_reference_m": self.top_width_at_reference_m,
            "side_slope_horizontal_per_vertical": (
                self.side_slope_horizontal_per_vertical
            ),
            "zero_area_gage_height_m": self.zero_area_gage_height_m,
            "section": {
                "bottom_width_m": self.section.bottom_width_m,
                "side_slope_horizontal_per_vertical": (
                    self.section.side_slope_horizontal_per_vertical
                ),
            },
            "training_stage_range_m": list(self.training_stage_range_m),
            "training_measurement_count": len(self.training_measurement_ids),
            "training_measurement_ids": list(self.training_measurement_ids),
            "structural_identity": "dA_dH_equals_top_width",
            "structural_identity_maximum_error_m": 0.0,
            "gage_height_used_as_depth": False,
            "diagnostic_candidate_only": True,
        }


@dataclass(frozen=True)
class AreaStageDerivativeModel:
    reference_gage_height_m: float
    area_intercept_m2: float
    area_linear_m: float
    area_quadratic: float

    def area_m2(self, gage_height_m: float) -> float:
        offset = float(gage_height_m) - self.reference_gage_height_m
        return (
            self.area_intercept_m2
            + self.area_linear_m * offset
            + self.area_quadratic * offset**2
        )

    def derivative_width_m(self, gage_height_m: float) -> float:
        offset = float(gage_height_m) - self.reference_gage_height_m
        return self.area_linear_m + 2.0 * self.area_quadratic * offset

    def as_dict(self) -> dict[str, object]:
        return {
            "model": "independent_area_only_quadratic",
            "reference_gage_height_m": self.reference_gage_height_m,
            "area_intercept_m2": self.area_intercept_m2,
            "area_linear_m": self.area_linear_m,
            "area_quadratic": self.area_quadratic,
            "observed_width_used_during_fit": False,
            "purpose": "independent_dA_dH_against_observed_width_audit",
        }


@dataclass(frozen=True)
class GeometryCohortEvaluation:
    cohort_id: str
    measurement_count: int
    time_range: tuple[str, str]
    stage_range_m: tuple[float, float]
    area_mae_m2: float
    width_mae_m: float
    area_median_absolute_percentage_error: float
    area_p90_absolute_percentage_error: float
    width_median_absolute_percentage_error: float
    width_p90_absolute_percentage_error: float
    derivative_width_median_absolute_percentage_error: float
    derivative_width_p90_absolute_percentage_error: float
    area_mean_signed_error_m2: float
    width_mean_signed_error_m: float
    accuracy_passed: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "cohort_id": self.cohort_id,
            "measurement_count": self.measurement_count,
            "time_range": list(self.time_range),
            "stage_range_m": list(self.stage_range_m),
            "area_mae_m2": self.area_mae_m2,
            "width_mae_m": self.width_mae_m,
            "area_median_absolute_percentage_error": (
                self.area_median_absolute_percentage_error
            ),
            "area_p90_absolute_percentage_error": (
                self.area_p90_absolute_percentage_error
            ),
            "width_median_absolute_percentage_error": (
                self.width_median_absolute_percentage_error
            ),
            "width_p90_absolute_percentage_error": (
                self.width_p90_absolute_percentage_error
            ),
            "derivative_width_median_absolute_percentage_error": (
                self.derivative_width_median_absolute_percentage_error
            ),
            "derivative_width_p90_absolute_percentage_error": (
                self.derivative_width_p90_absolute_percentage_error
            ),
            "area_mean_signed_error_m2": self.area_mean_signed_error_m2,
            "width_mean_signed_error_m": self.width_mean_signed_error_m,
            "thresholds": {
                "median_absolute_percentage_error": (
                    MEDIAN_ABSOLUTE_PERCENTAGE_ERROR_LIMIT
                ),
                "p90_absolute_percentage_error": (
                    P90_ABSOLUTE_PERCENTAGE_ERROR_LIMIT
                ),
            },
            "accuracy_passed": self.accuracy_passed,
        }


@dataclass(frozen=True)
class PublicReachGeometryStabilityAudit:
    source: PublicReachHydraulicMeasurements
    candidate: TrapezoidalStageGeometryCandidate
    independent_area_model: AreaStageDerivativeModel
    development: GeometryCohortEvaluation
    temporal_holdout: GeometryCohortEvaluation
    method_spatial_holdout: GeometryCohortEvaluation
    cohort_measurement_ids: dict[str, tuple[str, ...]]
    method_holdout_outside_stage_support_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        partition_ids = tuple(
            measurement_id
            for values in self.cohort_measurement_ids.values()
            for measurement_id in values
        )
        source_ids = tuple(value.measurement_id for value in self.source.measurements)
        if (
            len(partition_ids) != 110
            or len(set(partition_ids)) != 110
            or set(partition_ids) != set(source_ids)
            or not self.development.accuracy_passed
            or not self.temporal_holdout.accuracy_passed
            or self.method_spatial_holdout.accuracy_passed
        ):
            raise ValueError("public_reach_geometry_stability_audit_invalid")

    def require_reach_wide_fixed_geometry(self) -> None:
        raise ValueError("public_reach_geometry_method_spatial_holdout_failed")

    def require_runtime_hydraulic_geometry(self) -> None:
        raise ValueError("public_reach_geometry_candidate_diagnostic_only")

    def require_confluence_patch_bathymetry(self) -> None:
        raise ValueError(
            "public_reach_geometry_candidate_not_confluence_patch_bathymetry"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": PUBLIC_REACH_GEOMETRY_STABILITY_SCHEMA,
            "source_provenance_id": self.source.provenance_id,
            "monitoring_location_id": self.source.monitoring_location_id,
            "reach_id": self.source.reach_id,
            "temporal_holdout_start": TEMPORAL_HOLDOUT_START,
            "selection_contract": {
                "development_and_temporal": {
                    "measurement_type": "BridgeDownstreamSide",
                    "channel_measurement_type": "adcp",
                    "channel_location_direction": "Downstream",
                    "maximum_channel_location_distance_m": (
                        PRIMARY_MAXIMUM_DISTANCE_M
                    ),
                    "gage_height_approval_status": "Approved",
                    "simultaneous_component_channels_excluded": True,
                },
                "method_spatial_holdout": {
                    "measurement_type": "Wading",
                    "channel_measurement_type": "point_velocity",
                    "channel_location_direction": "Downstream",
                    "minimum_channel_location_distance_m_exclusive": (
                        METHOD_HOLDOUT_MINIMUM_DISTANCE_M
                    ),
                    "gage_height_approval_status": "Approved",
                    "evaluated_only_inside_development_stage_support": True,
                },
            },
            "fit_contract": {
                "joint_equations": [
                    "A(H)=A_ref+W_ref*x+z*x^2",
                    "W(H)=W_ref+2*z*x",
                ],
                "x": "gage_height_m-reference_gage_height_m",
                "area_residual_scale_m2": AREA_FIT_SCALE_M2,
                "width_residual_scale_m": WIDTH_FIT_SCALE_M,
                "ordinary_least_squares": True,
                "robust_or_posthoc_outlier_removal": False,
            },
            "candidate": self.candidate.as_dict(),
            "independent_area_derivative_audit": (
                self.independent_area_model.as_dict()
            ),
            "evaluations": {
                "development": self.development.as_dict(),
                "temporal_holdout": self.temporal_holdout.as_dict(),
                "method_spatial_holdout_inside_stage_support": (
                    self.method_spatial_holdout.as_dict()
                ),
            },
            "cohort_counts": {
                name: len(values)
                for name, values in self.cohort_measurement_ids.items()
            },
            "cohort_measurement_ids": {
                name: list(values)
                for name, values in self.cohort_measurement_ids.items()
            },
            "method_holdout_outside_stage_support_count": len(
                self.method_holdout_outside_stage_support_ids
            ),
            "method_holdout_outside_stage_support_ids": list(
                self.method_holdout_outside_stage_support_ids
            ),
            "decision": {
                "bridge_location_candidate_temporally_supported": True,
                "method_spatial_transfer_supported": False,
                "reach_wide_fixed_geometry_admitted": False,
                "runtime_hydraulic_geometry_admitted": False,
                "confluence_patch_bathymetry_admitted": False,
                "operator_admitted": False,
            },
            "claim_boundary": {
                "observed_geometry_stability_audited": True,
                "gage_height_treated_as_bed_referenced_depth": False,
                "zero_area_stage_is_surveyed_bed_elevation": False,
                "bridge_candidate_is_surveyed_cross_section": False,
                "reach_wide_fixed_geometry_admitted": False,
                "confluence_bathymetry_completed": False,
                "operator_admitted": False,
            },
        }


def compile_public_reach_geometry_stability_audit(
    source: PublicReachHydraulicMeasurements | None = None,
) -> PublicReachGeometryStabilityAudit:
    if source is None:
        source = compile_public_reach_hydraulic_measurements()
    key_counts = Counter(
        (value.field_visit_id, value.time, value.measurement_number)
        for value in source.measurements
    )
    cohorts: dict[str, list[ObservedReachHydraulicState]] = {
        "development": [],
        "temporal_holdout": [],
        "method_spatial_holdout": [],
        "provisional_primary": [],
        "simultaneous_component_channels": [],
        "other_retained": [],
    }
    for value in source.measurements:
        key = (value.field_visit_id, value.time, value.measurement_number)
        if key_counts[key] > 1:
            cohort = "simultaneous_component_channels"
        elif _matches_primary_location(value):
            if value.gage_height_approval_status != "Approved":
                cohort = "provisional_primary"
            elif value.time < TEMPORAL_HOLDOUT_START:
                cohort = "development"
            else:
                cohort = "temporal_holdout"
        elif _matches_method_spatial_holdout(value):
            cohort = "method_spatial_holdout"
        else:
            cohort = "other_retained"
        cohorts[cohort].append(value)

    development = tuple(cohorts["development"])
    temporal = tuple(cohorts["temporal_holdout"])
    method_spatial = tuple(cohorts["method_spatial_holdout"])
    candidate = _fit_joint_trapezoidal_candidate(development)
    independent_area_model = _fit_independent_area_model(development)
    stage_minimum, stage_maximum = candidate.training_stage_range_m
    method_inside = tuple(
        value
        for value in method_spatial
        if stage_minimum <= value.gage_height_m <= stage_maximum
    )
    method_outside = tuple(
        value.measurement_id
        for value in method_spatial
        if value not in method_inside
    )
    return PublicReachGeometryStabilityAudit(
        source=source,
        candidate=candidate,
        independent_area_model=independent_area_model,
        development=_evaluate(
            "development", development, candidate, independent_area_model
        ),
        temporal_holdout=_evaluate(
            "temporal_holdout", temporal, candidate, independent_area_model
        ),
        method_spatial_holdout=_evaluate(
            "method_spatial_holdout_inside_stage_support",
            method_inside,
            candidate,
            independent_area_model,
        ),
        cohort_measurement_ids={
            name: tuple(value.measurement_id for value in values)
            for name, values in cohorts.items()
        },
        method_holdout_outside_stage_support_ids=method_outside,
    )


def _matches_primary_location(value: ObservedReachHydraulicState) -> bool:
    return (
        value.measurement_type == "BridgeDownstreamSide"
        and value.channel_measurement_type == "adcp"
        and value.channel_location_direction == "Downstream"
        and value.channel_location_distance_m is not None
        and value.channel_location_distance_m <= PRIMARY_MAXIMUM_DISTANCE_M
    )


def _matches_method_spatial_holdout(
    value: ObservedReachHydraulicState,
) -> bool:
    return (
        value.measurement_type == "Wading"
        and value.channel_measurement_type == "point_velocity"
        and value.channel_location_direction == "Downstream"
        and value.channel_location_distance_m is not None
        and value.channel_location_distance_m
        > METHOD_HOLDOUT_MINIMUM_DISTANCE_M
        and value.gage_height_approval_status == "Approved"
    )


def _fit_joint_trapezoidal_candidate(
    values: tuple[ObservedReachHydraulicState, ...],
) -> TrapezoidalStageGeometryCandidate:
    if len(values) != 55:
        raise ValueError("public_reach_geometry_development_cohort_invalid")
    reference = median(value.gage_height_m for value in values)
    rows: list[tuple[tuple[float, float, float], float]] = []
    for value in values:
        offset = value.gage_height_m - reference
        rows.append(
            (
                (
                    1.0 / AREA_FIT_SCALE_M2,
                    offset / AREA_FIT_SCALE_M2,
                    offset**2 / AREA_FIT_SCALE_M2,
                ),
                value.flow_area_m2 / AREA_FIT_SCALE_M2,
            )
        )
        rows.append(
            (
                (
                    0.0,
                    1.0 / WIDTH_FIT_SCALE_M,
                    2.0 * offset / WIDTH_FIT_SCALE_M,
                ),
                value.top_width_m / WIDTH_FIT_SCALE_M,
            )
        )
    area_ref, width_ref, side_slope = _least_squares_3(rows)
    discriminant = width_ref**2 - 4.0 * side_slope * area_ref
    if side_slope <= 0.0 or discriminant <= 0.0:
        raise ValueError("public_reach_geometry_physical_root_missing")
    bottom_width = math.sqrt(discriminant)
    root_offset = (-width_ref + bottom_width) / (2.0 * side_slope)
    stage_zero = reference + root_offset
    return TrapezoidalStageGeometryCandidate(
        reference_gage_height_m=reference,
        area_at_reference_m2=area_ref,
        top_width_at_reference_m=width_ref,
        side_slope_horizontal_per_vertical=side_slope,
        zero_area_gage_height_m=stage_zero,
        section=TrapezoidalChannelSection(bottom_width, side_slope),
        training_stage_range_m=(
            min(value.gage_height_m for value in values),
            max(value.gage_height_m for value in values),
        ),
        training_measurement_ids=tuple(value.measurement_id for value in values),
    )


def _fit_independent_area_model(
    values: tuple[ObservedReachHydraulicState, ...],
) -> AreaStageDerivativeModel:
    reference = median(value.gage_height_m for value in values)
    rows = []
    for value in values:
        offset = value.gage_height_m - reference
        rows.append(((1.0, offset, offset**2), value.flow_area_m2))
    intercept, linear, quadratic = _least_squares_3(rows)
    return AreaStageDerivativeModel(reference, intercept, linear, quadratic)


def _evaluate(
    cohort_id: str,
    values: tuple[ObservedReachHydraulicState, ...],
    candidate: TrapezoidalStageGeometryCandidate,
    independent_area_model: AreaStageDerivativeModel,
) -> GeometryCohortEvaluation:
    if not values:
        raise ValueError("public_reach_geometry_evaluation_cohort_empty")
    area_errors = []
    width_errors = []
    area_percentage_errors = []
    width_percentage_errors = []
    derivative_percentage_errors = []
    for value in values:
        predicted_area, predicted_width = candidate.predict(value.gage_height_m)
        area_error = predicted_area - value.flow_area_m2
        width_error = predicted_width - value.top_width_m
        derivative_error = (
            independent_area_model.derivative_width_m(value.gage_height_m)
            - value.top_width_m
        )
        area_errors.append(area_error)
        width_errors.append(width_error)
        area_percentage_errors.append(abs(area_error) / value.flow_area_m2)
        width_percentage_errors.append(abs(width_error) / value.top_width_m)
        derivative_percentage_errors.append(
            abs(derivative_error) / value.top_width_m
        )
    metrics = {
        "area_median": median(area_percentage_errors),
        "area_p90": _quantile(area_percentage_errors, 0.9),
        "width_median": median(width_percentage_errors),
        "width_p90": _quantile(width_percentage_errors, 0.9),
        "derivative_median": median(derivative_percentage_errors),
        "derivative_p90": _quantile(derivative_percentage_errors, 0.9),
    }
    passed = (
        metrics["area_median"]
        <= MEDIAN_ABSOLUTE_PERCENTAGE_ERROR_LIMIT
        and metrics["area_p90"] <= P90_ABSOLUTE_PERCENTAGE_ERROR_LIMIT
        and metrics["width_median"]
        <= MEDIAN_ABSOLUTE_PERCENTAGE_ERROR_LIMIT
        and metrics["width_p90"] <= P90_ABSOLUTE_PERCENTAGE_ERROR_LIMIT
        and metrics["derivative_median"]
        <= MEDIAN_ABSOLUTE_PERCENTAGE_ERROR_LIMIT
        and metrics["derivative_p90"]
        <= P90_ABSOLUTE_PERCENTAGE_ERROR_LIMIT
    )
    return GeometryCohortEvaluation(
        cohort_id=cohort_id,
        measurement_count=len(values),
        time_range=(values[0].time, values[-1].time),
        stage_range_m=(
            min(value.gage_height_m for value in values),
            max(value.gage_height_m for value in values),
        ),
        area_mae_m2=_mean(abs(value) for value in area_errors),
        width_mae_m=_mean(abs(value) for value in width_errors),
        area_median_absolute_percentage_error=metrics["area_median"],
        area_p90_absolute_percentage_error=metrics["area_p90"],
        width_median_absolute_percentage_error=metrics["width_median"],
        width_p90_absolute_percentage_error=metrics["width_p90"],
        derivative_width_median_absolute_percentage_error=(
            metrics["derivative_median"]
        ),
        derivative_width_p90_absolute_percentage_error=(
            metrics["derivative_p90"]
        ),
        area_mean_signed_error_m2=_mean(area_errors),
        width_mean_signed_error_m=_mean(width_errors),
        accuracy_passed=passed,
    )


def _least_squares_3(
    rows: list[tuple[tuple[float, float, float], float]],
) -> tuple[float, float, float]:
    normal = [[0.0] * 3 for _ in range(3)]
    right = [0.0] * 3
    for coefficients, target in rows:
        for row in range(3):
            right[row] += coefficients[row] * target
            for column in range(3):
                normal[row][column] += coefficients[row] * coefficients[column]
    augmented = [normal[index] + [right[index]] for index in range(3)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= 1e-14:
            raise ValueError("public_reach_geometry_fit_singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                value - factor * pivot_value
                for value, pivot_value in zip(
                    augmented[row], augmented[column], strict=True
                )
            ]
    return tuple(augmented[row][3] for row in range(3))


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _mean(values) -> float:
    items = tuple(values)
    return sum(items) / len(items)
