"""Deterministic, non-row-level quality report for the Chongqing customer bundle.

The report binds the customer artifact hashes and natural-resource ontology
baseline, then exposes only aggregate quality evidence. It is a technical
precheck and does not represent customer approval or a production decision.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from shapely.errors import GEOSException
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .chongqing_entity_link_baseline import (
    CUSTOMER_BUNDLE_DIR,
    ONTOLOGY_PACKAGE_DIR,
    ONTOLOGY_PACKAGE_ID,
    ONTOLOGY_PACKAGE_SHA256,
    ChongqingBaselineError,
    build_chongqing_entity_link_baseline,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint

QUALITY_REPORT_SCHEMA_ID = "gda.chongqing-customer-data-quality-report.v1"


class ChongqingCustomerDataQualityError(RuntimeError):
    """The customer bundle cannot produce a trustworthy quality report."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChongqingCustomerDataQualityValueCount(_FrozenModel):
    value: NonEmptyText
    count: int = Field(ge=1)


class ChongqingCustomerDataQualityFieldProfile(_FrozenModel):
    field_name: NonEmptyText
    record_count: int = Field(ge=0)
    present_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    distinct_value_count: int = Field(ge=0)
    value_set_sha256: Sha256
    value_counts_sha256: Sha256
    value_counts: tuple[ChongqingCustomerDataQualityValueCount, ...] = ()


class ChongqingCustomerDataQualityGeometryCount(_FrozenModel):
    geometry_type: NonEmptyText
    count: int = Field(ge=1)


class ChongqingCustomerDataQualityArtifactProfile(_FrozenModel):
    artifact_name: NonEmptyText
    artifact_sha256: Sha256
    feature_count: int = Field(ge=0)
    crs_state: Literal["rfc7946_default_wgs84"]
    geometry_type_counts: tuple[ChongqingCustomerDataQualityGeometryCount, ...]
    empty_geometry_count: int = Field(ge=0)
    invalid_geometry_count: int = Field(ge=0)
    non_area_geometry_count: int = Field(ge=0)
    bounds: tuple[float, float, float, float] | None = None
    required_fields: tuple[NonEmptyText, ...] = Field(min_length=1)
    field_profiles: tuple[ChongqingCustomerDataQualityFieldProfile, ...] = Field(min_length=1)
    primary_key_fields: tuple[NonEmptyText, ...] = Field(min_length=1)
    primary_key_missing_count: int = Field(ge=0)
    primary_key_distinct_count: int = Field(ge=0)
    primary_key_duplicate_group_count: int = Field(ge=0)
    primary_key_duplicate_row_count: int = Field(ge=0)
    primary_key_duplicate_policy: Literal["allowed_identity_aggregation", "must_be_unique"]
    identity_count: int = Field(ge=0)
    profile_sha256: Sha256

    @model_validator(mode="after")
    def validate_passed_profile(self) -> ChongqingCustomerDataQualityArtifactProfile:
        field_names = tuple(profile.field_name for profile in self.field_profiles)
        if field_names != self.required_fields or len(set(field_names)) != len(field_names):
            raise ValueError("field profiles do not exactly cover the required fields")
        for profile in self.field_profiles:
            if profile.record_count != self.feature_count:
                raise ValueError("field profile record count does not match artifact")
            if profile.present_count + profile.missing_count != profile.record_count:
                raise ValueError("field profile coverage counts are inconsistent")
            if profile.missing_count:
                raise ValueError("a required customer field is missing or empty")
        if sum(item.count for item in self.geometry_type_counts) != self.feature_count:
            raise ValueError("geometry type counts do not cover every feature")
        if self.empty_geometry_count or self.invalid_geometry_count:
            raise ValueError("customer artifact contains empty or invalid geometry")
        if self.non_area_geometry_count:
            raise ValueError("customer artifact contains non-area geometry")
        if self.bounds is None:
            raise ValueError("customer artifact lacks area geometry bounds")
        min_x, min_y, max_x, max_y = self.bounds
        if not (-180 <= min_x <= max_x <= 180 and -90 <= min_y <= max_y <= 90):
            raise ValueError("RFC 7946 coordinates fall outside WGS84 longitude/latitude")
        if self.primary_key_missing_count:
            raise ValueError("customer artifact primary key is missing")
        if self.identity_count != self.primary_key_distinct_count:
            raise ValueError("identity count does not match distinct primary keys")
        if self.primary_key_duplicate_policy == "must_be_unique":
            if self.primary_key_duplicate_group_count or self.primary_key_duplicate_row_count:
                raise ValueError("customer artifact primary key must be unique")
            if self.primary_key_distinct_count != self.feature_count:
                raise ValueError("unique primary key does not cover every feature")
        expected = _fingerprint(self.model_dump(mode="json", exclude={"profile_sha256"}))
        if self.profile_sha256 != expected:
            raise ValueError("artifact quality profile fingerprint mismatch")
        return self


class ChongqingCustomerDataQualityGate(_FrozenModel):
    gate_id: NonEmptyText
    status: Literal["passed", "warning"]
    observed_count: int = Field(ge=0)
    detail: NonEmptyText
    evidence_sha256: Sha256

    @model_validator(mode="after")
    def validate_evidence_hash(self) -> ChongqingCustomerDataQualityGate:
        expected = _fingerprint(self.model_dump(mode="json", exclude={"evidence_sha256"}))
        if self.evidence_sha256 != expected:
            raise ValueError("quality gate evidence fingerprint mismatch")
        return self


class ChongqingCustomerDataQualityIssue(_FrozenModel):
    code: NonEmptyText
    severity: Literal["info", "warning"]
    artifact_name: NonEmptyText
    affected_count: int = Field(ge=0)
    detail: NonEmptyText
    issue_sha256: Sha256

    @model_validator(mode="after")
    def validate_issue_hash(self) -> ChongqingCustomerDataQualityIssue:
        expected = _fingerprint(self.model_dump(mode="json", exclude={"issue_sha256"}))
        if self.issue_sha256 != expected:
            raise ValueError("quality issue fingerprint mismatch")
        return self


class ChongqingCustomerDataQualityReport(_FrozenModel):
    schema_id: Literal["gda.chongqing-customer-data-quality-report.v1"] = QUALITY_REPORT_SCHEMA_ID
    tenant_id: TenantId
    customer_bundle_id: NonEmptyText
    customer_bundle_version: NonEmptyText
    customer_bundle_sha256: Sha256
    ontology_package_id: Literal["natural-resource-one-map:2.3.0:587915868b1221af"]
    ontology_package_sha256: Sha256
    ontology_review_status: Literal["technical_baseline_unreviewed"]
    usage_status: Literal["assisted_precheck_not_for_production_decision"]
    decision_scope: NonEmptyText
    artifact_profiles: tuple[ChongqingCustomerDataQualityArtifactProfile, ...] = Field(
        min_length=2, max_length=2
    )
    quality_gates: tuple[ChongqingCustomerDataQualityGate, ...] = Field(min_length=1)
    issues: tuple[ChongqingCustomerDataQualityIssue, ...] = ()
    parcel_record_count: int = Field(ge=0)
    parcel_identity_count: int = Field(ge=0)
    constraint_feature_count: int = Field(ge=0)
    constraint_identity_count: int = Field(ge=0)
    entity_count: int = Field(ge=0)
    link_identity_count: int = Field(ge=0)
    customer_link_evidence_observation_count: int = Field(ge=0)
    exact_intersection_observation_count: int = Field(ge=0)
    excluded_precision_sliver_count: int = Field(ge=0)
    quality_state: Literal["passed_with_documented_precision_exclusion"]
    authority_write_performed: Literal[False] = False
    customer_approval_present: Literal[False] = False
    report_sha256: Sha256

    @model_validator(mode="after")
    def validate_sealed_report(self) -> ChongqingCustomerDataQualityReport:
        profiles = {profile.artifact_name: profile for profile in self.artifact_profiles}
        expected_names = {
            "heping_changed_parcels.geojson",
            "heping_constraints.geojson",
        }
        if set(profiles) != expected_names:
            raise ValueError("quality report does not contain the two sealed customer artifacts")
        parcels = profiles["heping_changed_parcels.geojson"]
        constraints = profiles["heping_constraints.geojson"]
        if (
            self.parcel_record_count != parcels.feature_count
            or self.parcel_identity_count != parcels.identity_count
            or self.constraint_feature_count != constraints.feature_count
            or self.constraint_identity_count != constraints.identity_count
        ):
            raise ValueError("report counters do not match artifact profiles")
        if self.entity_count != self.parcel_identity_count + self.constraint_identity_count:
            raise ValueError("entity count does not match parcel and constraint identities")
        gate_statuses = {gate.gate_id: gate.status for gate in self.quality_gates}
        if len(gate_statuses) != len(self.quality_gates):
            raise ValueError("quality report contains duplicate gate identifiers")
        expected_gate_statuses = {
            "customer_artifact_hashes": "passed",
            "ontology_binding": "passed",
            "required_field_coverage": "passed",
            "area_geometry_and_rfc7946_crs": "passed",
            "customer_constraint_evidence": "passed",
            "precision_sliver_policy": "warning",
        }
        if gate_statuses != expected_gate_statuses:
            raise ValueError("quality report gates are incomplete or have an invalid status")
        expected_hash = canonical_json_fingerprint(
            {
                "schema": self.schema_id,
                "data": self.model_dump(
                    mode="json",
                    exclude={"schema_id", "report_sha256"},
                ),
            }
        )
        if self.report_sha256 != expected_hash:
            raise ValueError("customer data quality report fingerprint mismatch")
        return self

    @classmethod
    def seal(cls, values: dict[str, Any]) -> ChongqingCustomerDataQualityReport:
        return cls(
            **values,
            report_sha256=canonical_json_fingerprint(
                {"schema": QUALITY_REPORT_SCHEMA_ID, "data": _json_ready(values)}
            ),
        )

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(value: Any) -> str:
    return canonical_json_fingerprint(_json_ready(value))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ChongqingCustomerDataQualityError(
            f"cannot read customer artifact {path.name}"
        ) from exc
    return digest.hexdigest()


def _read_feature_collection(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChongqingCustomerDataQualityError(
            f"cannot parse customer artifact {path.name}"
        ) from exc
    if not isinstance(document, dict) or document.get("type") != "FeatureCollection":
        raise ChongqingCustomerDataQualityError(
            f"customer artifact {path.name} is not a FeatureCollection"
        )
    features = document.get("features")
    if not isinstance(features, list) or any(not isinstance(item, dict) for item in features):
        raise ChongqingCustomerDataQualityError(
            f"customer artifact {path.name} has invalid features"
        )
    if "crs" in document:
        raise ChongqingCustomerDataQualityError(
            f"customer artifact {path.name} has a non-RFC-7946 CRS member"
        )
    for index, feature in enumerate(features):
        if feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
            raise ChongqingCustomerDataQualityError(
                f"customer artifact {path.name} feature {index} is invalid"
            )
    return document, features


def _normalized_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, (dict, list, tuple)):
        if not value:
            return None
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return str(value)


def _field_profile(
    features: list[dict[str, Any]],
    field_name: str,
    *,
    include_counts: bool,
) -> ChongqingCustomerDataQualityFieldProfile:
    values = [
        _normalized_value((feature.get("properties") or {}).get(field_name)) for feature in features
    ]
    present = [value for value in values if value is not None]
    counter = Counter(present)
    counts = (
        tuple(
            ChongqingCustomerDataQualityValueCount(value=value, count=count)
            for value, count in sorted(counter.items())
        )
        if include_counts
        else ()
    )
    return ChongqingCustomerDataQualityFieldProfile(
        field_name=field_name,
        record_count=len(features),
        present_count=len(present),
        missing_count=len(features) - len(present),
        distinct_value_count=len(counter),
        value_set_sha256=_fingerprint(sorted(counter)),
        value_counts_sha256=_fingerprint(sorted(counter.items())),
        value_counts=counts,
    )


def _geometry_quality(
    features: list[dict[str, Any]],
) -> tuple[
    tuple[ChongqingCustomerDataQualityGeometryCount, ...],
    int,
    int,
    int,
    tuple[float, float, float, float] | None,
]:
    geometry_counts: Counter[str] = Counter()
    empty_count = 0
    invalid_count = 0
    non_area_count = 0
    bounds: list[tuple[float, float, float, float]] = []
    for feature in features:
        geometry_document = feature.get("geometry")
        if not isinstance(geometry_document, dict):
            invalid_count += 1
            continue
        geometry_type = _normalized_value(geometry_document.get("type")) or "missing"
        geometry_counts[geometry_type] += 1
        try:
            geometry: BaseGeometry = shape(geometry_document)
        except (GEOSException, TypeError, ValueError):
            invalid_count += 1
            continue
        if geometry.is_empty:
            empty_count += 1
        if not geometry.is_valid:
            invalid_count += 1
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            non_area_count += 1
        elif not geometry.is_empty:
            bounds.append(tuple(float(value) for value in geometry.bounds))
    overall_bounds = None
    if bounds:
        overall_bounds = (
            min(value[0] for value in bounds),
            min(value[1] for value in bounds),
            max(value[2] for value in bounds),
            max(value[3] for value in bounds),
        )
    return (
        tuple(
            ChongqingCustomerDataQualityGeometryCount(geometry_type=name, count=count)
            for name, count in sorted(geometry_counts.items())
        ),
        empty_count,
        invalid_count,
        non_area_count,
        overall_bounds,
    )


def _primary_key_profile(
    features: list[dict[str, Any]],
    fields: tuple[str, ...],
    *,
    policy: Literal["allowed_identity_aggregation", "must_be_unique"],
    identity_count: int,
) -> dict[str, Any]:
    keys: list[tuple[str, ...] | None] = []
    for feature in features:
        properties = feature.get("properties") or {}
        key = tuple(_normalized_value(properties.get(field)) for field in fields)
        keys.append(None if any(value is None for value in key) else key)
    present = [key for key in keys if key is not None]
    counter = Counter(present)
    return {
        "primary_key_fields": fields,
        "primary_key_missing_count": len(keys) - len(present),
        "primary_key_distinct_count": len(counter),
        "primary_key_duplicate_group_count": sum(count > 1 for count in counter.values()),
        "primary_key_duplicate_row_count": sum(
            count - 1 for count in counter.values() if count > 1
        ),
        "primary_key_duplicate_policy": policy,
        "identity_count": identity_count,
    }


def _artifact_profile(
    *,
    path: Path,
    features: list[dict[str, Any]],
    required_fields: tuple[str, ...],
    code_fields: frozenset[str],
    primary_key_fields: tuple[str, ...],
    primary_key_policy: Literal["allowed_identity_aggregation", "must_be_unique"],
    identity_count: int,
) -> ChongqingCustomerDataQualityArtifactProfile:
    geometry = _geometry_quality(features)
    fields = tuple(
        _field_profile(features, name, include_counts=name in code_fields)
        for name in required_fields
    )
    values = _primary_key_profile(
        features,
        primary_key_fields,
        policy=primary_key_policy,
        identity_count=identity_count,
    )
    profile_values = {
        "artifact_name": path.name,
        "artifact_sha256": _file_sha256(path),
        "feature_count": len(features),
        "crs_state": "rfc7946_default_wgs84",
        "geometry_type_counts": geometry[0],
        "empty_geometry_count": geometry[1],
        "invalid_geometry_count": geometry[2],
        "non_area_geometry_count": geometry[3],
        "bounds": geometry[4],
        "required_fields": required_fields,
        "field_profiles": fields,
        **values,
    }
    try:
        return ChongqingCustomerDataQualityArtifactProfile(
            **profile_values,
            profile_sha256=_fingerprint(profile_values),
        )
    except ValidationError as exc:
        raise ChongqingCustomerDataQualityError(
            f"customer artifact {path.name} failed aggregate quality validation"
        ) from exc


def _gate(
    gate_id: str,
    status: Literal["passed", "warning"],
    count: int,
    detail: str,
) -> ChongqingCustomerDataQualityGate:
    values = {
        "gate_id": gate_id,
        "status": status,
        "observed_count": count,
        "detail": detail,
    }
    return ChongqingCustomerDataQualityGate(
        **values,
        evidence_sha256=_fingerprint(values),
    )


def _issue(
    code: str,
    severity: Literal["info", "warning"],
    artifact: str,
    count: int,
    detail: str,
) -> ChongqingCustomerDataQualityIssue:
    values = {
        "code": code,
        "severity": severity,
        "artifact_name": artifact,
        "affected_count": count,
        "detail": detail,
    }
    return ChongqingCustomerDataQualityIssue(
        **values,
        issue_sha256=_fingerprint(values),
    )


def build_chongqing_customer_data_quality_report(
    *,
    tenant_id: str = "chongqing-customer",
    bundle_dir: str | Path = CUSTOMER_BUNDLE_DIR,
    ontology_package_dir: str | Path = ONTOLOGY_PACKAGE_DIR,
) -> ChongqingCustomerDataQualityReport:
    """Build an aggregate quality report bound to the Chongqing technical baseline."""

    try:
        baseline = build_chongqing_entity_link_baseline(
            tenant_id=tenant_id,
            bundle_dir=bundle_dir,
            ontology_package_dir=ontology_package_dir,
        )
    except (ChongqingBaselineError, OSError, TypeError, ValueError) as exc:
        raise ChongqingCustomerDataQualityError(
            "Chongqing customer bundle failed the sealed baseline validation"
        ) from exc
    bundle_path = Path(bundle_dir).resolve()
    parcel_path = bundle_path / "heping_changed_parcels.geojson"
    constraint_path = bundle_path / "heping_constraints.geojson"
    _, parcel_features = _read_feature_collection(parcel_path)
    _, constraint_features = _read_feature_collection(constraint_path)

    parcels = _artifact_profile(
        path=parcel_path,
        features=parcel_features,
        required_fields=(
            "parcel_id",
            "BSM",
            "TBBH",
            "JQDLDM",
            "JQDLMC",
            "GHDLDM",
            "GHDLMC",
            "source_state_id",
            "target_state_id",
            "process_id",
            "area_ha",
            "review_status",
            "evidence",
        ),
        code_fields=frozenset({"JQDLDM", "JQDLMC", "GHDLDM", "GHDLMC", "review_status"}),
        primary_key_fields=("parcel_id",),
        primary_key_policy="allowed_identity_aggregation",
        identity_count=baseline.parcel_identity_count,
    )
    constraints = _artifact_profile(
        path=constraint_path,
        features=constraint_features,
        required_fields=(
            "BSM",
            "GZMC",
            "JSMJ",
            "layer",
            "constraint_type",
            "rule",
            "severity",
            "ontology_class",
        ),
        code_fields=frozenset({"layer", "constraint_type", "severity", "ontology_class"}),
        primary_key_fields=("layer", "BSM"),
        primary_key_policy="must_be_unique",
        identity_count=baseline.constraint_identity_count,
    )
    artifacts = (parcels, constraints)
    gates = (
        _gate(
            "customer_artifact_hashes",
            "passed",
            len(artifacts),
            "both GeoJSON artifact hashes matched the customer manifest",
        ),
        _gate(
            "ontology_binding",
            "passed",
            1,
            f"ontology package is pinned to {ONTOLOGY_PACKAGE_ID}",
        ),
        _gate(
            "required_field_coverage",
            "passed",
            sum(profile.feature_count for profile in artifacts),
            "all required fields are present and non-empty for every feature",
        ),
        _gate(
            "area_geometry_and_rfc7946_crs",
            "passed",
            sum(profile.feature_count for profile in artifacts),
            "all geometries are valid area geometries and CRS follows RFC 7946 default WGS84",
        ),
        _gate(
            "customer_constraint_evidence",
            "passed",
            baseline.exact_intersection_observation_count,
            "customer constraint hits map exactly to positive-area intersections",
        ),
        _gate(
            "precision_sliver_policy",
            "warning",
            baseline.excluded_precision_sliver_count,
            "precision slivers are documented and excluded, not promoted to links",
        ),
    )
    issues = (
        _issue(
            "source_record_identity_aggregation",
            "info",
            parcels.artifact_name,
            parcels.primary_key_duplicate_row_count,
            "duplicate parcel_id records are intentionally aggregated into stable parcel "
            "identities",
        ),
        _issue(
            "excluded_precision_sliver",
            "warning",
            parcels.artifact_name,
            baseline.excluded_precision_sliver_count,
            "positive intersections at or below the sealed precision threshold are excluded",
        ),
    )
    values = {
        "tenant_id": baseline.tenant_id,
        "customer_bundle_id": baseline.customer_bundle_id,
        "customer_bundle_version": baseline.customer_bundle_version,
        "customer_bundle_sha256": _file_sha256(bundle_path / "manifest.json"),
        "ontology_package_id": baseline.ontology_package_id,
        "ontology_package_sha256": ONTOLOGY_PACKAGE_SHA256,
        "ontology_review_status": baseline.ontology_review_status,
        "usage_status": baseline.usage_status,
        "decision_scope": baseline.decision_scope,
        "artifact_profiles": artifacts,
        "quality_gates": gates,
        "issues": issues,
        "parcel_record_count": baseline.parcel_record_count,
        "parcel_identity_count": baseline.parcel_identity_count,
        "constraint_feature_count": baseline.constraint_feature_count,
        "constraint_identity_count": baseline.constraint_identity_count,
        "entity_count": baseline.parcel_identity_count + baseline.constraint_identity_count,
        "link_identity_count": baseline.link_identity_count,
        "customer_link_evidence_observation_count": baseline.link_evidence_observation_count,
        "exact_intersection_observation_count": baseline.exact_intersection_observation_count,
        "excluded_precision_sliver_count": baseline.excluded_precision_sliver_count,
        "quality_state": "passed_with_documented_precision_exclusion",
        "authority_write_performed": False,
        "customer_approval_present": False,
    }
    return ChongqingCustomerDataQualityReport.seal(values)


__all__ = [
    "QUALITY_REPORT_SCHEMA_ID",
    "ChongqingCustomerDataQualityArtifactProfile",
    "ChongqingCustomerDataQualityError",
    "ChongqingCustomerDataQualityFieldProfile",
    "ChongqingCustomerDataQualityGate",
    "ChongqingCustomerDataQualityGeometryCount",
    "ChongqingCustomerDataQualityIssue",
    "ChongqingCustomerDataQualityReport",
    "ChongqingCustomerDataQualityValueCount",
    "build_chongqing_customer_data_quality_report",
]
