"""Fail-closed impact and exposure contract for Abu Dhabi urban flooding.

The diagnostic contract proves metric semantics with synthetic, non-overlapping
overlay units. It cannot grant admission to customer data, hydraulic results,
cross-source identity, GWM training, or production impact claims.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

FLOOD_IMPACT_WINDOW_SCHEMA = "gwm.abu_dhabi_flood.impact_assessment_window.v1"
FLOOD_IMPACT_POLICY_SCHEMA = "gwm.abu_dhabi_flood.impact_assessment_policy.v1"
FLOOD_IMPACT_RECEIPT_SCHEMA = "gwm.abu_dhabi_flood.impact_assessment_receipt.v1"

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_OVERLAY_METHODS = frozenset({"synthetic_partition_fixture"})
_RECEIPT_STATUS = "validated_synthetic_impact_contract_not_admitted"
_EXECUTION_BOUNDARY: dict[str, object] = {
    "actual_hydraulic_solver_result_consumed": False,
    "customer_liveability_rows_consumed": False,
    "cross_database_join_executed": False,
    "contract_only_synthetic_aggregation": True,
}
_CLAIM_BOUNDARY: dict[str, object] = {
    "diagnostic_only": True,
    "synthetic_fixture_only": True,
    "hydraulic_result_admitted": False,
    "common_geography_approved": False,
    "aggregate_impact_overlay_admitted": False,
    "per_asset_identity_admitted": False,
    "traditional_model_admitted": False,
    "gwm_training_admitted": False,
    "production_admitted": False,
    "city_scale_prediction_claim_allowed": False,
}


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"flood_impact_{field}_invalid")
    return value


def _finite_nonnegative(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"flood_impact_{field}_invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"flood_impact_{field}_invalid")
    return result


def _nonnegative_integer(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"flood_impact_{field}_invalid")
    return value


@dataclass(frozen=True)
class InundationImpactUnit:
    """Hydraulic result summarized for one non-overlapping overlay unit."""

    overlay_unit_id: str
    maximum_depth_m: float
    inundation_duration_seconds: float
    inundated_area_m2: float
    provenance_id: str

    def __post_init__(self) -> None:
        _identifier(self.overlay_unit_id, "overlay_unit_id")
        _identifier(self.provenance_id, "inundation_provenance_id")
        _finite_nonnegative(self.maximum_depth_m, "maximum_depth_m")
        _finite_nonnegative(
            self.inundation_duration_seconds, "inundation_duration_seconds"
        )
        _finite_nonnegative(self.inundated_area_m2, "inundated_area_m2")

    def as_dict(self) -> dict[str, object]:
        return {
            "overlay_unit_id": self.overlay_unit_id,
            "maximum_depth_m": float(self.maximum_depth_m),
            "inundation_duration_seconds": float(
                self.inundation_duration_seconds
            ),
            "inundated_area_m2": float(self.inundated_area_m2),
            "provenance_id": self.provenance_id,
        }


@dataclass(frozen=True)
class ExposureImpactUnit:
    """Exposure totals bound to exactly one non-overlapping overlay unit."""

    overlay_unit_id: str
    population_count: float
    critical_facility_count: int
    road_length_m: float
    plot_count: int
    provenance_id: str

    def __post_init__(self) -> None:
        _identifier(self.overlay_unit_id, "overlay_unit_id")
        _identifier(self.provenance_id, "exposure_provenance_id")
        _finite_nonnegative(self.population_count, "population_count")
        _nonnegative_integer(
            self.critical_facility_count, "critical_facility_count"
        )
        _finite_nonnegative(self.road_length_m, "road_length_m")
        _nonnegative_integer(self.plot_count, "plot_count")

    def as_dict(self) -> dict[str, object]:
        return {
            "overlay_unit_id": self.overlay_unit_id,
            "population_count": float(self.population_count),
            "critical_facility_count": self.critical_facility_count,
            "road_length_m": float(self.road_length_m),
            "plot_count": self.plot_count,
            "provenance_id": self.provenance_id,
        }


@dataclass(frozen=True)
class FloodImpactAssessmentPolicy:
    """Thresholds defining affected and severe impact aggregates."""

    minimum_affected_depth_m: float = 0.10
    severe_depth_m: float = 0.50
    minimum_affected_duration_seconds: float = 60.0

    def __post_init__(self) -> None:
        minimum = _finite_nonnegative(
            self.minimum_affected_depth_m, "minimum_affected_depth_m"
        )
        severe = _finite_nonnegative(self.severe_depth_m, "severe_depth_m")
        _finite_nonnegative(
            self.minimum_affected_duration_seconds,
            "minimum_affected_duration_seconds",
        )
        if severe < minimum:
            raise ValueError("flood_impact_severe_depth_below_affected_depth")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": FLOOD_IMPACT_POLICY_SCHEMA,
            "minimum_affected_depth_m": float(self.minimum_affected_depth_m),
            "severe_depth_m": float(self.severe_depth_m),
            "minimum_affected_duration_seconds": float(
                self.minimum_affected_duration_seconds
            ),
        }


@dataclass(frozen=True)
class FloodImpactAssessmentWindow:
    """One immutable synthetic window for impact-contract diagnostics."""

    run_id: str
    window_start_seconds: float
    window_end_seconds: float
    crs: str
    overlay_method: str
    hydraulic_result_reference_id: str
    exposure_snapshot_reference_id: str
    inundation_units: tuple[InundationImpactUnit, ...]
    exposure_units: tuple[ExposureImpactUnit, ...]
    evidence_class: str = "synthetic_fixture"
    diagnostic_only: bool = True
    hydraulic_result_admitted: bool = False
    common_geography_approved: bool = False
    aggregate_impact_overlay_admitted: bool = False
    production_admitted: bool = False

    def __post_init__(self) -> None:
        _identifier(self.run_id, "run_id")
        _identifier(
            self.hydraulic_result_reference_id,
            "hydraulic_result_reference_id",
        )
        _identifier(
            self.exposure_snapshot_reference_id,
            "exposure_snapshot_reference_id",
        )
        start = _finite_nonnegative(
            self.window_start_seconds, "window_start_seconds"
        )
        end = _finite_nonnegative(self.window_end_seconds, "window_end_seconds")
        if end <= start:
            raise ValueError("flood_impact_window_invalid")
        if self.crs != "EPSG:32640":
            raise ValueError("flood_impact_crs_must_be_epsg32640")
        if self.overlay_method not in _OVERLAY_METHODS:
            raise ValueError("flood_impact_direct_or_unapproved_overlay_forbidden")
        if self.evidence_class != "synthetic_fixture":
            raise ValueError("flood_impact_real_data_not_admitted")
        if (
            self.diagnostic_only is not True
            or self.hydraulic_result_admitted is not False
            or self.common_geography_approved is not False
            or self.aggregate_impact_overlay_admitted is not False
            or self.production_admitted is not False
        ):
            raise ValueError("flood_impact_contract_cannot_grant_admission")
        if not self.inundation_units or not self.exposure_units:
            raise ValueError("flood_impact_units_required")
        inundation_ids = tuple(item.overlay_unit_id for item in self.inundation_units)
        exposure_ids = tuple(item.overlay_unit_id for item in self.exposure_units)
        if len(set(inundation_ids)) != len(inundation_ids):
            raise ValueError("flood_impact_inundation_unit_ids_must_be_unique")
        if len(set(exposure_ids)) != len(exposure_ids):
            raise ValueError("flood_impact_exposure_unit_ids_must_be_unique")
        if set(inundation_ids) != set(exposure_ids):
            raise ValueError("flood_impact_overlay_unit_sets_must_match")
        window_duration = end - start
        if any(
            item.inundation_duration_seconds > window_duration
            for item in self.inundation_units
        ):
            raise ValueError("flood_impact_duration_exceeds_window")

    def claim_boundary(self) -> dict[str, object]:
        return dict(_CLAIM_BOUNDARY)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": FLOOD_IMPACT_WINDOW_SCHEMA,
            "run_id": self.run_id,
            "window_start_seconds": float(self.window_start_seconds),
            "window_end_seconds": float(self.window_end_seconds),
            "crs": self.crs,
            "overlay_method": self.overlay_method,
            "hydraulic_result_reference_id": self.hydraulic_result_reference_id,
            "exposure_snapshot_reference_id": self.exposure_snapshot_reference_id,
            "inundation_units": [item.as_dict() for item in self.inundation_units],
            "exposure_units": [item.as_dict() for item in self.exposure_units],
            "input_governance": {
                "evidence_class": self.evidence_class,
                "diagnostic_only": True,
                "contains_customer_rows": False,
            },
            "claim_boundary": self.claim_boundary(),
        }


def evaluate_flood_impact(
    window: FloodImpactAssessmentWindow,
    policy: FloodImpactAssessmentPolicy,
) -> dict[str, object]:
    """Calculate deterministic aggregate impact metrics for matching units."""

    if not isinstance(window, FloodImpactAssessmentWindow):
        raise ValueError("flood_impact_window_required")
    if not isinstance(policy, FloodImpactAssessmentPolicy):
        raise ValueError("flood_impact_policy_required")
    exposure_by_id = {item.overlay_unit_id: item for item in window.exposure_units}
    affected = [
        item
        for item in window.inundation_units
        if item.maximum_depth_m >= policy.minimum_affected_depth_m
        and item.inundation_duration_seconds
        >= policy.minimum_affected_duration_seconds
    ]
    severe = [
        item for item in affected if item.maximum_depth_m >= policy.severe_depth_m
    ]

    def exposure_total(items: list[InundationImpactUnit], field: str) -> float:
        return float(
            sum(
                getattr(exposure_by_id[item.overlay_unit_id], field)
                for item in items
            )
        )

    metrics = {
        "overlay_unit_count": len(window.inundation_units),
        "affected_overlay_unit_count": len(affected),
        "severe_overlay_unit_count": len(severe),
        "affected_inundated_area_m2": float(
            sum(item.inundated_area_m2 for item in affected)
        ),
        "severe_inundated_area_m2": float(
            sum(item.inundated_area_m2 for item in severe)
        ),
        "affected_population_count": exposure_total(affected, "population_count"),
        "severe_population_count": exposure_total(severe, "population_count"),
        "affected_critical_facility_count": int(
            exposure_total(affected, "critical_facility_count")
        ),
        "severe_critical_facility_count": int(
            exposure_total(severe, "critical_facility_count")
        ),
        "affected_road_length_m": exposure_total(affected, "road_length_m"),
        "severe_road_length_m": exposure_total(severe, "road_length_m"),
        "affected_plot_count": int(exposure_total(affected, "plot_count")),
        "severe_plot_count": int(exposure_total(severe, "plot_count")),
        "maximum_depth_m": float(
            max(item.maximum_depth_m for item in window.inundation_units)
        ),
        "maximum_inundation_duration_seconds": float(
            max(item.inundation_duration_seconds for item in window.inundation_units)
        ),
    }
    checks = [
        _check(
            "overlay_unit_sets_match_exactly",
            {item.overlay_unit_id for item in window.inundation_units}
            == {item.overlay_unit_id for item in window.exposure_units},
            len(window.inundation_units),
            len(window.exposure_units),
        ),
        _check(
            "overlay_units_are_non_overlapping_by_contract",
            window.overlay_method == "synthetic_partition_fixture",
            window.overlay_method,
            "synthetic_partition_fixture",
        ),
        _check(
            "customer_data_and_hydraulic_results_not_admitted",
            window.claim_boundary()["aggregate_impact_overlay_admitted"] is False
            and window.claim_boundary()["hydraulic_result_admitted"] is False,
            window.claim_boundary(),
            "all admission flags false",
        ),
    ]
    failed_checks = [str(item["check_id"]) for item in checks if not item["passed"]]
    return {
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "metrics": metrics,
        "admission_effect": "none_diagnostic_metric_contract_only",
    }


def build_flood_impact_receipt(
    window: FloodImpactAssessmentWindow,
    policy: FloodImpactAssessmentPolicy,
) -> dict[str, object]:
    """Build a self-hashed synthetic receipt for the impact metric contract."""

    quality = evaluate_flood_impact(window, policy)
    if quality["passed"] is not True:
        raise ValueError("flood_impact_quality_gate_failed")
    receipt: dict[str, object] = {
        "schema": FLOOD_IMPACT_RECEIPT_SCHEMA,
        "status": _RECEIPT_STATUS,
        "assessment_window": window.as_dict(),
        "policy": policy.as_dict(),
        "quality_gates": quality,
        "execution": dict(_EXECUTION_BOUNDARY),
        "admission": window.claim_boundary(),
    }
    receipt["receipt_sha256"] = _sha256_json(receipt)
    return receipt


def verify_flood_impact_receipt(receipt: dict[str, object]) -> None:
    """Reject a modified receipt or one that weakens the diagnostic boundary."""

    if not isinstance(receipt, dict):
        raise ValueError("flood_impact_receipt_required")
    receipt_sha256 = receipt.get("receipt_sha256")
    if (
        not isinstance(receipt_sha256, str)
        or _SHA256_PATTERN.fullmatch(receipt_sha256) is None
    ):
        raise ValueError("flood_impact_receipt_sha256_invalid")
    unhashed = dict(receipt)
    unhashed.pop("receipt_sha256")
    try:
        computed_sha256 = _sha256_json(unhashed)
    except (TypeError, ValueError) as exc:
        raise ValueError("flood_impact_receipt_not_canonical_json") from exc
    if receipt_sha256 != computed_sha256:
        raise ValueError("flood_impact_receipt_sha256_mismatch")
    if receipt.get("schema") != FLOOD_IMPACT_RECEIPT_SCHEMA:
        raise ValueError("flood_impact_receipt_schema_invalid")
    if receipt.get("status") != _RECEIPT_STATUS:
        raise ValueError("flood_impact_receipt_status_invalid")
    if receipt.get("execution") != _EXECUTION_BOUNDARY:
        raise ValueError("flood_impact_receipt_execution_boundary_invalid")
    if receipt.get("admission") != _CLAIM_BOUNDARY:
        raise ValueError("flood_impact_receipt_admission_boundary_invalid")
    assessment_window = receipt.get("assessment_window")
    if not isinstance(assessment_window, dict):
        raise ValueError("flood_impact_receipt_window_invalid")
    if assessment_window.get("claim_boundary") != _CLAIM_BOUNDARY:
        raise ValueError("flood_impact_receipt_window_claim_boundary_invalid")
    quality_gates = receipt.get("quality_gates")
    if not isinstance(quality_gates, dict) or quality_gates.get("passed") is not True:
        raise ValueError("flood_impact_receipt_quality_gate_invalid")


def _check(
    check_id: str, passed: bool, observed: object, threshold_or_required: object
) -> dict[str, object]:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "observed": observed,
        "threshold_or_required": threshold_or_required,
    }


def _sha256_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
