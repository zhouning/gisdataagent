"""Fail-closed K0 data delivery and acceptance contract for Abu Dhabi flooding.

This contract turns the current readiness blockers into a customer handoff
checklist. It records what must be supplied and how it will be accepted, but it
cannot open K0 or admit any hydraulic, GWM, impact, or operational claim.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

K0_DATA_REQUEST_SCHEMA = "gwm.abu_dhabi_flood.k0_data_request.v1"
K0_DATA_REQUEST_RECEIPT_SCHEMA = "gwm.abu_dhabi_flood.k0_data_request_receipt.v1"

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_STATUSES = frozenset(
    {"missing_customer_authoritative", "candidate_only", "partial_candidate_only", "admitted"}
)
_RECEIPT_STATUS = "k0_data_request_contract_blocked_not_admitted"
_EXECUTION_BOUNDARY: dict[str, object] = {
    "customer_rows_consumed": False,
    "database_connection_executed": False,
    "credentials_recorded": False,
    "k0_gate_opened": False,
    "contract_only_checklist": True,
}
_CLAIM_BOUNDARY: dict[str, object] = {
    "diagnostic_only": True,
    "k0_opened": False,
    "traditional_model_admitted": False,
    "gwm_training_admitted": False,
    "hybrid_planner_admitted": False,
    "aggregate_impact_overlay_admitted": False,
    "per_asset_identity_admitted": False,
    "production_admitted": False,
    "city_scale_prediction_claim_allowed": False,
}


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"k0_data_request_{field}_invalid")
    return value


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"k0_data_request_{field}_invalid")
    return value.strip()


@dataclass(frozen=True)
class K0DataRequestItem:
    """One customer-owned artifact and its minimum K0 acceptance evidence."""

    request_id: str
    priority: int
    domain: str
    required_artifact: str
    minimum_acceptance: str
    current_status: str
    customer_owner_role: str
    current_evidence: str
    evidence_reference: str = "none"

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValueError("k0_data_request_priority_invalid")
        if self.priority not in {1, 2, 3}:
            raise ValueError("k0_data_request_priority_invalid")
        for field in (
            "domain",
            "required_artifact",
            "minimum_acceptance",
            "customer_owner_role",
            "current_evidence",
        ):
            _text(getattr(self, field), field)
        if self.current_status not in _STATUSES:
            raise ValueError("k0_data_request_current_status_invalid")
        if self.evidence_reference != "none":
            _identifier(self.evidence_reference, "evidence_reference")

    def as_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "priority": self.priority,
            "domain": self.domain,
            "required_artifact": self.required_artifact,
            "minimum_acceptance": self.minimum_acceptance,
            "current_status": self.current_status,
            "customer_owner_role": self.customer_owner_role,
            "current_evidence": self.current_evidence,
            "evidence_reference": self.evidence_reference,
        }


@dataclass(frozen=True)
class K0DataRequestPackage:
    """A deterministic, non-admitting checklist for closing the K0 evidence gap."""

    package_id: str
    dataset_scope: str
    target_crs: str
    source_readiness_reference: str
    requests: tuple[K0DataRequestItem, ...]
    diagnostic_only: bool = True
    k0_opened: bool = False
    traditional_model_admitted: bool = False
    gwm_training_admitted: bool = False
    hybrid_planner_admitted: bool = False
    production_admitted: bool = False

    def __post_init__(self) -> None:
        _identifier(self.package_id, "package_id")
        _text(self.dataset_scope, "dataset_scope")
        _identifier(self.source_readiness_reference, "source_readiness_reference")
        if self.target_crs != "EPSG:32640":
            raise ValueError("k0_data_request_crs_must_be_epsg32640")
        if self.diagnostic_only is not True or any(
            flag is not False
            for flag in (
                self.k0_opened,
                self.traditional_model_admitted,
                self.gwm_training_admitted,
                self.hybrid_planner_admitted,
                self.production_admitted,
            )
        ):
            raise ValueError("k0_data_request_contract_cannot_grant_admission")
        if not self.requests:
            raise ValueError("k0_data_request_items_required")
        request_ids = tuple(item.request_id for item in self.requests)
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("k0_data_request_ids_must_be_unique")

    def claim_boundary(self) -> dict[str, object]:
        return dict(_CLAIM_BOUNDARY)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": K0_DATA_REQUEST_SCHEMA,
            "package_id": self.package_id,
            "dataset_scope": self.dataset_scope,
            "target_crs": self.target_crs,
            "source_readiness_reference": self.source_readiness_reference,
            "requests": [item.as_dict() for item in self.requests],
            "input_governance": {
                "diagnostic_only": True,
                "customer_rows_consumed": False,
                "credentials_recorded": False,
            },
            "claim_boundary": self.claim_boundary(),
        }


def evaluate_k0_data_request(package: K0DataRequestPackage) -> dict[str, object]:
    """Evaluate checklist completeness without changing any admission state."""

    if not isinstance(package, K0DataRequestPackage):
        raise ValueError("k0_data_request_package_required")
    missing = [
        item.request_id
        for item in package.requests
        if item.current_status != "admitted"
    ]
    checks = [
        _check(
            "all_required_customer_artifacts_admitted",
            not missing,
            missing,
            [],
        ),
        _check(
            "target_crs_is_epsg32640",
            package.target_crs == "EPSG:32640",
            package.target_crs,
            "EPSG:32640",
        ),
        _check(
            "k0_and_model_admission_flags_remain_closed",
            package.claim_boundary() == _CLAIM_BOUNDARY,
            package.claim_boundary(),
            _CLAIM_BOUNDARY,
        ),
    ]
    failed_checks = [str(item["check_id"]) for item in checks if not item["passed"]]
    return {
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "missing_request_ids": missing,
        "admission_effect": "none_customer_data_request_only",
    }


def build_k0_data_request_receipt(
    package: K0DataRequestPackage,
) -> dict[str, object]:
    """Build a self-hashed blocked checklist receipt."""

    quality = evaluate_k0_data_request(package)
    receipt: dict[str, object] = {
        "schema": K0_DATA_REQUEST_RECEIPT_SCHEMA,
        "status": _RECEIPT_STATUS,
        "data_request": package.as_dict(),
        "quality_gates": quality,
        "execution": dict(_EXECUTION_BOUNDARY),
        "admission": package.claim_boundary(),
    }
    receipt["receipt_sha256"] = _sha256_json(receipt)
    return receipt


def verify_k0_data_request_receipt(receipt: dict[str, object]) -> None:
    """Reject a modified checklist or a receipt that claims K0 admission."""

    if not isinstance(receipt, dict):
        raise ValueError("k0_data_request_receipt_required")
    receipt_sha256 = receipt.get("receipt_sha256")
    if (
        not isinstance(receipt_sha256, str)
        or _SHA256_PATTERN.fullmatch(receipt_sha256) is None
    ):
        raise ValueError("k0_data_request_receipt_sha256_invalid")
    unhashed = dict(receipt)
    unhashed.pop("receipt_sha256")
    if receipt_sha256 != _sha256_json(unhashed):
        raise ValueError("k0_data_request_receipt_sha256_mismatch")
    if receipt.get("schema") != K0_DATA_REQUEST_RECEIPT_SCHEMA:
        raise ValueError("k0_data_request_receipt_schema_invalid")
    if receipt.get("status") != _RECEIPT_STATUS:
        raise ValueError("k0_data_request_receipt_status_invalid")
    if receipt.get("execution") != _EXECUTION_BOUNDARY:
        raise ValueError("k0_data_request_receipt_execution_boundary_invalid")
    if receipt.get("admission") != _CLAIM_BOUNDARY:
        raise ValueError("k0_data_request_receipt_admission_boundary_invalid")
    data_request = receipt.get("data_request")
    if not isinstance(data_request, dict):
        raise ValueError("k0_data_request_receipt_payload_invalid")
    if data_request.get("claim_boundary") != _CLAIM_BOUNDARY:
        raise ValueError("k0_data_request_receipt_payload_boundary_invalid")


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


def default_k0_data_request_package() -> K0DataRequestPackage:
    """Return the current customer handoff checklist without source data."""

    return K0DataRequestPackage(
        package_id="abu-dhabi-k0-data-request-v1",
        dataset_scope="abu-dhabi-urban-stormwater-world-model",
        target_crs="EPSG:32640",
        source_readiness_reference="fixture:hybrid-readiness-v1",
        requests=(
            K0DataRequestItem(
                "engineering-surface-vertical-datum",
                1,
                "terrain",
                "authoritative_engineering_dem_and_vertical_control",
                (
                    "Provide DEM/LiDAR or survey surface, vertical datum, control points, "
                    "accuracy, epoch and reuse authority."
                ),
                "candidate_only",
                "DMT or municipal GIS engineering owner",
                (
                    "SRTM/Copernicus and SmartMakani contours are public candidates; vertical "
                    "datum and hydrological conditioning are unverified."
                ),
                "audit:surface-candidate-v1",
            ),
            K0DataRequestItem(
                "drainage-network-topology-units",
                1,
                "drainage_network",
                "authoritative_pipes_nodes_facilities_crosswalk_and_units",
                (
                    "Provide asset version, IDs, pipe units/sections/inverts, "
                    "node-facility-catchment relations, direction, outfalls, pumps and "
                    "change history."
                ),
                "partial_candidate_only",
                "Drainage asset and operations owner",
                (
                    "PostgreSQL and Makani candidates exist, but units, vertical datum, "
                    "topology and authoritative relationships are unresolved."
                ),
                "audit:makani-postgres-v1",
            ),
            K0DataRequestItem(
                "event-rainfall-forcing",
                1,
                "rainfall",
                "target_and_independent_event_rain_gauge_or_radar_series",
                (
                    "Provide quality-controlled station/radar forcing with timestamps, "
                    "timezone, units, spatial coverage, missingness and event IDs."
                ),
                "missing_customer_authoritative",
                "NCM or customer meteorology owner",
                (
                    "Open-Meteo and NASA POWER/MERRA2 are public forcing candidates only "
                    "and are not calibration-admitted."
                ),
                "audit:weather-candidates-v1",
            ),
            K0DataRequestItem(
                "coastal-boundary-time-series",
                1,
                "coastal_boundary",
                "event_tide_surge_and_outfall_boundary_series",
                (
                    "Provide tide/surge observations or official hindcast at applicable "
                    "outfalls with datum, timezone, station mapping and event IDs."
                ),
                "missing_customer_authoritative",
                "Coastal or hydrology operations owner",
                (
                    "SmartMakani bathymetry is static terrain support and does not provide "
                    "event tide or surge time series."
                ),
                "audit:coastal-boundary-gap-v1",
            ),
            K0DataRequestItem(
                "pump-gate-operation-history",
                1,
                "operations",
                "pump_gate_storage_and_outfall_operation_logs",
                (
                    "Provide event-aligned pump curves, commands, states, gate openings, "
                    "storage levels, measured discharge and failure states."
                ),
                "missing_customer_authoritative",
                "Drainage operations/SCADA owner",
                (
                    "Only static pump and outfall candidates are present; no event operation "
                    "log is admitted."
                ),
                "audit:operation-gap-v1",
            ),
            K0DataRequestItem(
                "timed-inundation-observations",
                1,
                "inundation_observation",
                "event_depth_extent_duration_and_road_impact_panel",
                (
                    "Provide timestamped depth, extent, peak, recession, location uncertainty, "
                    "road closure/traffic impact and independent holdout event labels."
                ),
                "missing_customer_authoritative",
                "Emergency response and transport operations owner",
                (
                    "Rain incident/MIMS layers provide location proxies but no validated "
                    "depth/duration panel for the target event."
                ),
                "audit:inundation-observation-gap-v1",
            ),
            K0DataRequestItem(
                "common-geography-overlay-rule",
                2,
                "spatial_overlay",
                "approved_common_boundary_or_deterministic_overlay_specification",
                (
                    "Approve common spatial unit, overlay tolerance, CRS, version alignment, "
                    "aggregation grain and per-asset identity policy."
                ),
                "missing_customer_authoritative",
                "GIS data governance owner",
                (
                    "Direct district-code overlap is zero and plot-ID overlap is only a "
                    "crosswalk candidate; no overlay rule is approved."
                ),
                "audit:cross-source-geography-v1",
            ),
            K0DataRequestItem(
                "liveability-exposure-semantics",
                2,
                "exposure_and_impact",
                "approved_liveability_snapshot_semantics_and_output_policy",
                (
                    "Confirm snapshot version, reference date, facility classes, "
                    "population/road/plot definitions, privacy constraints and output "
                    "granularity."
                ),
                "candidate_only",
                "Liveability business data owner",
                (
                    "The current database is an impact/exposure candidate; dictionary "
                    "semantics and current counts are different snapshots."
                ),
                "audit:liveability-postgres-v1",
            ),
        ),
    )
