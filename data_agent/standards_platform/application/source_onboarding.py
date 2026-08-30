"""Deterministic full-dataset onboarding evidence for real vector sources."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from data_agent.platform_contracts import (
    Artifact,
    ArtifactRole,
    Resource,
    ResourceVersion,
    canonical_json_fingerprint,
)
from data_agent.platform_gateway import PlatformGateway

from .acceptance import bundle_identity, dataset_members, sha256_file

PROTOCOL_SCHEMA = "gis-data-agent.vector-source-onboarding.v1"
REPORT_SCHEMA = "gis-data-agent.vector-source-onboarding-report.v1"
PUBLIC_SUMMARY_SCHEMA = "gis-data-agent.vector-source-onboarding-summary.v1"


def evaluate_vector_source_onboarding(
    *,
    protocol: Mapping[str, Any],
    dataset_root: Path,
) -> dict[str, Any]:
    """Scan every feature and return aggregate-only onboarding evidence."""
    _validate_protocol(protocol)
    root = dataset_root.resolve(strict=True)
    relative_path = Path(str(protocol["source"]["relative_path"]))
    if relative_path.is_absolute():
        raise ValueError("source relative_path must not be absolute")
    source_path = (root / relative_path).resolve(strict=True)
    if not source_path.is_relative_to(root):
        raise ValueError("source path escapes dataset root")

    import geopandas as gpd
    import numpy as np
    import pandas as pd

    frame = gpd.read_file(source_path)
    identity = bundle_identity(source_path)
    member_suffixes = {
        _member_suffix(member.name, source_path.stem)
        for member in dataset_members(source_path)
    }
    required_suffixes = {
        str(value).casefold() for value in protocol["source"]["required_members"]
    }
    missing_members = sorted(required_suffixes - member_suffixes)
    expected_bundle_sha256 = str(protocol["source"]["bundle_sha256"])
    field_names = [str(column) for column in frame.columns if column != frame.geometry.name]
    field_set = set(field_names)

    checks: list[dict[str, Any]] = []
    _add_check(
        checks,
        check_id="bundle_members_complete",
        category="source_quality",
        status="passed" if not missing_members else "failed",
        severity="critical",
        metrics={
            "required_members": sorted(required_suffixes),
            "observed_members": sorted(member_suffixes),
            "missing_members": missing_members,
        },
    )
    _add_check(
        checks,
        check_id="bundle_identity_matches",
        category="source_quality",
        status=(
            "passed"
            if identity["bundle_sha256"] == expected_bundle_sha256
            else "failed"
        ),
        severity="critical",
        metrics={"identity_match": identity["bundle_sha256"] == expected_bundle_sha256},
    )
    _add_check(
        checks,
        check_id="full_dataset_readable",
        category="source_quality",
        status="passed" if len(frame) > 0 else "failed",
        severity="critical",
        metrics={"records_scanned": len(frame)},
    )

    observed_crs = frame.crs.to_string() if frame.crs else None
    expected_crs = str(protocol["quality_rules"]["expected_crs"])
    _add_check(
        checks,
        check_id="crs_truth_matches",
        category="source_quality",
        status="passed" if observed_crs == expected_crs else "failed",
        severity="critical",
        metrics={"expected_crs": expected_crs, "observed_crs": observed_crs},
    )

    geometry = frame.geometry
    null_geometry = int(geometry.isna().sum())
    empty_geometry = int(geometry.is_empty.sum())
    invalid_geometry = int((~geometry.is_valid & ~geometry.isna()).sum())
    geometry_types = {
        str(name): int(count)
        for name, count in geometry.geom_type.value_counts(dropna=False).items()
    }
    allowed_geometry_types = set(protocol["quality_rules"]["allowed_geometry_types"])
    unexpected_geometry_types = sorted(set(geometry_types) - allowed_geometry_types)
    geometry_failed = bool(
        null_geometry
        or empty_geometry
        or invalid_geometry
        or unexpected_geometry_types
    )
    _add_check(
        checks,
        check_id="geometries_valid",
        category="source_quality",
        status="failed" if geometry_failed else "passed",
        severity="critical",
        metrics={
            "geometry_types": geometry_types,
            "null_count": null_geometry,
            "empty_count": empty_geometry,
            "invalid_count": invalid_geometry,
            "unexpected_types": unexpected_geometry_types,
        },
    )

    required_source_fields = [
        str(value) for value in protocol["quality_rules"]["required_source_fields"]
    ]
    missing_source_fields = sorted(set(required_source_fields) - field_set)
    _add_check(
        checks,
        check_id="required_source_fields_present",
        category="source_quality",
        status="passed" if not missing_source_fields else "failed",
        severity="critical",
        metrics={
            "required_count": len(required_source_fields),
            "observed_count": len(field_names),
            "missing_fields": missing_source_fields,
        },
    )

    incomplete_fields = []
    for field in required_source_fields:
        if field not in frame:
            continue
        series = frame[field]
        null_count = int(series.isna().sum())
        blank_count = (
            int(series.fillna("").astype(str).str.strip().eq("").sum())
            if pd.api.types.is_string_dtype(series.dtype)
            or pd.api.types.is_object_dtype(series.dtype)
            else 0
        )
        if null_count or blank_count:
            incomplete_fields.append(
                {"field": field, "null_count": null_count, "blank_count": blank_count}
            )
    _add_check(
        checks,
        check_id="required_source_values_complete",
        category="source_quality",
        status="passed" if not incomplete_fields else "failed",
        severity="critical",
        metrics={"incomplete_fields": incomplete_fields},
    )

    primary_key = str(protocol["quality_rules"]["primary_key"])
    if primary_key in frame:
        primary_series = frame[primary_key]
        primary_nulls = int(primary_series.isna().sum())
        primary_blanks = int(
            primary_series.fillna("").astype(str).str.strip().eq("").sum()
        )
        duplicate_rows = int(primary_series.duplicated(keep=False).sum())
        distinct_values = int(primary_series.nunique(dropna=True))
    else:
        primary_nulls = len(frame)
        primary_blanks = len(frame)
        duplicate_rows = 0
        distinct_values = 0
    primary_key_failed = bool(
        primary_key not in frame
        or primary_nulls
        or primary_blanks
        or duplicate_rows
    )
    _add_check(
        checks,
        check_id="primary_key_unique",
        category="source_quality",
        status="failed" if primary_key_failed else "passed",
        severity="critical",
        metrics={
            "field": primary_key,
            "distinct_values": distinct_values,
            "null_count": primary_nulls,
            "blank_count": primary_blanks,
            "duplicate_rows": duplicate_rows,
        },
    )

    numeric_findings = []
    for rule in protocol["quality_rules"]["numeric_constraints"]:
        field = str(rule["field"])
        if field not in frame:
            numeric_findings.append(
                {"field": field, "invalid_count": len(frame), "violating_count": 0}
            )
            continue
        values = pd.to_numeric(frame[field], errors="coerce")
        invalid_count = int(values.isna().sum())
        if "min_exclusive" in rule:
            violating = values <= float(rule["min_exclusive"])
        else:
            violating = values < float(rule["min_inclusive"])
        numeric_findings.append(
            {
                "field": field,
                "invalid_count": invalid_count,
                "violating_count": int(violating.fillna(False).sum()),
                "minimum": _finite_round(values.min()),
                "maximum": _finite_round(values.max()),
                "sum": _finite_round(values.sum()),
            }
        )
    numeric_failed = any(
        finding["invalid_count"] or finding["violating_count"]
        for finding in numeric_findings
    )
    _add_check(
        checks,
        check_id="numeric_constraints_satisfied",
        category="source_quality",
        status="failed" if numeric_failed else "passed",
        severity="high",
        metrics={"fields": numeric_findings},
    )

    area_rule = protocol["quality_rules"]["area_consistency"]
    declared_area_field = str(area_rule["declared_area_field"])
    tolerance = float(area_rule["max_relative_error"])
    area_metrics: dict[str, Any]
    area_status = "blocked"
    if (
        frame.crs is not None
        and frame.crs.is_projected
        and declared_area_field in frame
        and len(frame) > 0
    ):
        declared_area = pd.to_numeric(frame[declared_area_field], errors="coerce")
        comparable = declared_area.notna() & (declared_area > 0) & geometry.notna()
        geometric_area = geometry.area
        relative_error = (
            (geometric_area[comparable] - declared_area[comparable]).abs()
            / declared_area[comparable].abs()
        )
        finite_relative_error = relative_error[np.isfinite(relative_error)]
        outside_tolerance = finite_relative_error > tolerance
        area_metrics = {
            "declared_area_field": declared_area_field,
            "max_relative_error": tolerance,
            "records_compared": int(len(finite_relative_error)),
            "records_excluded": int(len(frame) - len(finite_relative_error)),
            "outside_tolerance_count": int(outside_tolerance.sum()),
            "mean_relative_error": _finite_round(finite_relative_error.mean()),
            "maximum_relative_error": _finite_round(finite_relative_error.max()),
            "geometry_area_sum": _finite_round(geometric_area.sum()),
            "declared_area_sum": _finite_round(declared_area.sum()),
        }
        area_status = "failed" if outside_tolerance.any() else "passed"
    else:
        area_metrics = {
            "declared_area_field": declared_area_field,
            "max_relative_error": tolerance,
            "records_compared": 0,
            "blocked_reason": "projected_crs_and_declared_area_required",
        }
    _add_check(
        checks,
        check_id="declared_area_consistent",
        category="source_quality",
        status=area_status,
        severity="high",
        metrics=area_metrics,
    )

    target_mapping = {
        str(target): str(source)
        for target, source in protocol["standardization"]["source_to_target"].items()
    }
    required_target_fields = [
        str(value) for value in protocol["standardization"]["required_target_fields"]
    ]
    missing_target_fields = sorted(
        target
        for target in required_target_fields
        if target not in target_mapping or target_mapping[target] not in field_set
    )
    pending_derivations = sorted(
        target
        for target in missing_target_fields
        if target in protocol["standardization"].get("derivations", {})
    )
    _add_check(
        checks,
        check_id="standard_required_fields_covered",
        category="standardization",
        status="passed" if not missing_target_fields else "blocked",
        severity="critical",
        metrics={
            "required_count": len(required_target_fields),
            "covered_count": len(required_target_fields) - len(missing_target_fields),
            "missing_target_fields": missing_target_fields,
            "pending_derived_fields": pending_derivations,
        },
    )

    source_checks = [check for check in checks if check["category"] == "source_quality"]
    source_quality_verdict = _verdict(source_checks)
    standardization_status = (
        "ready" if not missing_target_fields else "blocked"
    )
    blockers = _promotion_blockers(
        protocol=protocol,
        source_quality_verdict=source_quality_verdict,
        checks=checks,
        missing_target_fields=missing_target_fields,
    )
    control_plane = _control_plane_targets(protocol, identity["bundle_sha256"])
    report = {
        "schema": REPORT_SCHEMA,
        "protocol_id": protocol["protocol_id"],
        "evaluation_policy": {
            "mode": "full_dataset_read_only",
            "records_scanned": len(frame),
            "full_dataset_validated": True,
            "samples_persisted": False,
            "source_values_persisted": False,
            "authoritative_quality_result": False,
            "data_product_version_created": False,
        },
        "source": {
            "archive_sha256": protocol["source"]["archive_sha256"],
            "relative_path": relative_path.as_posix(),
            "bundle": identity,
            "bundle_identity_match": identity["bundle_sha256"] == expected_bundle_sha256,
            "profile": {
                "driver": "ESRI Shapefile",
                "feature_count": len(frame),
                "crs": observed_crs,
                "geometry_types": geometry_types,
                "bounds": [_finite_round(value) for value in frame.total_bounds],
                "fields": field_names,
            },
        },
        "quality": {
            "rule_version": protocol["quality_rules"]["rule_version"],
            "source_quality_verdict": source_quality_verdict,
            "checks": checks,
            "summary": _check_summary(checks),
        },
        "standardization": {
            "target_table": protocol["standardization"]["target_table"],
            "status": standardization_status,
            "required_target_fields": required_target_fields,
            "missing_target_fields": missing_target_fields,
            "pending_derived_fields": pending_derivations,
        },
        "governance": dict(protocol["governance"]),
        "runtime": dict(protocol["runtime"]),
        "control_plane": control_plane,
        "promotion": {
            "ready": False,
            "max_stage": "source_version_registered",
            "blockers": blockers,
        },
        "evaluated_at": protocol["onboarding_at"],
    }
    report["evidence_sha256"] = canonical_json_fingerprint(report)
    return report


def register_source_onboarding_evidence(
    *,
    report: Mapping[str, Any],
    evidence_path: Path,
    gateway: PlatformGateway | None = None,
) -> dict[str, Any]:
    """Register source identity and non-authoritative evidence, but no Run result."""
    _validate_report(report)
    evidence = evidence_path.resolve(strict=True)
    target = report["control_plane"]
    source = report["source"]
    governance = report["governance"]
    quality = report["quality"]
    tenant_id = str(target["tenant_id"])
    resource = Resource(
        tenant_id=tenant_id,
        resource_urn=target["resource_urn"],
        resource_kind="dataset",
        authority_system="source-archive",
        authority_locator=(
            f"sha256:{source['archive_sha256']}/{source['relative_path']}"
        ),
        owner_ref=str(governance["platform_owner"]),
        governance_ref={
            "classification": governance["classification"],
            "policy_ref": target["governance_policy_ref"],
        },
        technical_refs=(
            {
                "kind": "shapefile_bundle",
                "bundle_sha256": source["bundle"]["bundle_sha256"],
                "feature_count": source["profile"]["feature_count"],
            },
            {
                "kind": "spatial_profile",
                "crs": source["profile"]["crs"],
                "geometry_types": source["profile"]["geometry_types"],
            },
        ),
    )
    created_at = datetime.fromisoformat(str(report["evaluated_at"]).replace("Z", "+00:00"))
    version = ResourceVersion(
        tenant_id=tenant_id,
        resource_urn=target["resource_urn"],
        resource_version_id=UUID(str(target["resource_version_id"])),
        version_key=str(target["version_key"]),
        content_sha256=source["bundle"]["bundle_sha256"],
        authority_version_ref={
            "archive_sha256": source["archive_sha256"],
            "relative_path": source["relative_path"],
            "bundle_sha256": source["bundle"]["bundle_sha256"],
        },
        created_by="workload:source-onboarding",
        created_at=created_at,
    )
    artifact = Artifact(
        tenant_id=tenant_id,
        artifact_id=UUID(str(target["evidence_artifact_id"])),
        artifact_key=str(target["evidence_artifact_key"]),
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri=evidence.as_uri(),
        media_type="application/json",
        content_sha256=sha256_file(evidence),
        size_bytes=evidence.stat().st_size,
        resource_version_id=version.resource_version_id,
        manifest={
            "schema": REPORT_SCHEMA,
            "evidence_sha256": report["evidence_sha256"],
            "rule_version": quality["rule_version"],
            "source_quality_verdict": quality["source_quality_verdict"],
            "authoritative_quality_result": False,
        },
        created_by="workload:source-onboarding",
        created_at=created_at,
    )
    platform_gateway = gateway or PlatformGateway()
    resource_result = platform_gateway.register_resource(resource)
    version_result = platform_gateway.register_resource_version(version)
    artifact_result = platform_gateway.record_artifact(artifact)
    return {
        "schema": "gis-data-agent.vector-source-onboarding-registration.v1",
        "tenant_id": tenant_id,
        "resource_urn": resource.resource_urn,
        "resource_version_id": str(version.resource_version_id),
        "evidence_artifact_id": str(artifact.artifact_id),
        "resource_created": resource_result.created,
        "resource_version_created": version_result.created,
        "evidence_artifact_created": artifact_result.created,
        "quality_result_recorded": False,
        "platform_run_created": False,
        "data_product_version_created": False,
    }


def source_onboarding_public_summary(
    report: Mapping[str, Any],
    *,
    source_registered: bool = False,
    evidence_registered: bool = False,
) -> dict[str, Any]:
    """Return aggregate operational status without paths, hashes, IDs or values."""
    _validate_report(report)
    checks = {check["id"]: check for check in report["quality"]["checks"]}
    primary_key = checks["primary_key_unique"]["metrics"]
    area = checks["declared_area_consistent"]["metrics"]
    numeric = checks["numeric_constraints_satisfied"]["metrics"]
    numeric_violations = {
        item["field"]: item["violating_count"]
        for item in numeric["fields"]
        if item["invalid_count"] or item["violating_count"]
    }
    return {
        "schema": PUBLIC_SUMMARY_SCHEMA,
        "protocol_id": report["protocol_id"],
        "source": {
            "label": "重庆璧山 JQDLTB 原始图斑",
            "feature_count": report["source"]["profile"]["feature_count"],
            "crs": report["source"]["profile"]["crs"],
            "full_dataset_scanned": report["evaluation_policy"]["full_dataset_validated"],
        },
        "control_plane": {
            "source_registered": source_registered,
            "evidence_registered": evidence_registered,
            "quality_result_recorded": False,
            "data_product_version_created": False,
        },
        "quality": {
            "verdict": report["quality"]["source_quality_verdict"],
            "summary": report["quality"]["summary"],
            "findings": {
                "primary_key_field": primary_key["field"],
                "primary_key_duplicate_rows": primary_key["duplicate_rows"],
                "numeric_violations": numeric_violations,
                "area_outside_tolerance": area.get("outside_tolerance_count", 0),
                "invalid_geometries": checks["geometries_valid"]["metrics"][
                    "invalid_count"
                ],
            },
        },
        "standardization": {
            "status": report["standardization"]["status"],
            "missing_target_fields": list(
                report["standardization"]["missing_target_fields"]
            ),
            "pending_derived_fields": list(
                report["standardization"]["pending_derived_fields"]
            ),
        },
        "promotion": {
            "ready": False,
            "blockers": list(report["promotion"]["blockers"]),
        },
    }


def _validate_protocol(protocol: Mapping[str, Any]) -> None:
    if protocol.get("schema") != PROTOCOL_SCHEMA:
        raise ValueError("unsupported source onboarding protocol schema")
    for key in (
        "protocol_id",
        "onboarding_at",
        "source",
        "resource",
        "quality_rules",
        "standardization",
        "governance",
        "runtime",
    ):
        if key not in protocol:
            raise ValueError(f"source onboarding protocol requires {key}")
    datetime.fromisoformat(str(protocol["onboarding_at"]).replace("Z", "+00:00"))
    expected_hash = str(protocol["source"].get("bundle_sha256") or "")
    if len(expected_hash) != 64:
        raise ValueError("source bundle_sha256 must be sealed")


def _validate_report(report: Mapping[str, Any]) -> None:
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError("unsupported source onboarding report schema")
    expected = dict(report)
    observed = expected.pop("evidence_sha256", None)
    if observed != canonical_json_fingerprint(expected):
        raise ValueError("source onboarding report evidence hash does not match")
    if report.get("evaluation_policy", {}).get("authoritative_quality_result") is not False:
        raise ValueError("onboarding evidence must not claim an authoritative QualityResult")
    if report.get("promotion", {}).get("ready") is not False:
        raise ValueError("source onboarding evidence cannot claim promotion readiness")


def _control_plane_targets(
    protocol: Mapping[str, Any], bundle_sha256: str
) -> dict[str, Any]:
    tenant_id = str(protocol["resource"]["tenant_id"])
    resource_urn = str(protocol["resource"]["resource_urn"])
    version_id = uuid5(NAMESPACE_URL, f"{resource_urn}@sha256:{bundle_sha256}")
    rule_version = str(protocol["quality_rules"]["rule_version"])
    artifact_id = uuid5(version_id, f"evidence:{rule_version}")
    return {
        "tenant_id": tenant_id,
        "resource_urn": resource_urn,
        "resource_version_id": str(version_id),
        "version_key": f"sha256-{bundle_sha256[:12]}",
        "evidence_artifact_id": str(artifact_id),
        "evidence_artifact_key": f"cq-jqdltb-quality-{bundle_sha256[:12]}",
        "governance_policy_ref": protocol["resource"]["governance_policy_ref"],
    }


def _promotion_blockers(
    *,
    protocol: Mapping[str, Any],
    source_quality_verdict: str,
    checks: list[dict[str, Any]],
    missing_target_fields: list[str],
) -> list[str]:
    blockers: list[str] = []
    governance = protocol["governance"]
    if str(governance.get("business_steward", "")).startswith("pending"):
        blockers.append("business_steward")
    if str(governance.get("license_status", "")).startswith("pending"):
        blockers.append("license_status")
    if source_quality_verdict != "passed":
        blockers.append("source_quality_not_passed")
    failed_ids = {check["id"] for check in checks if check["status"] == "failed"}
    if "primary_key_unique" in failed_ids:
        blockers.append("source_primary_key_not_unique")
    if "numeric_constraints_satisfied" in failed_ids:
        blockers.append("source_numeric_constraints_failed")
    if "declared_area_consistent" in failed_ids:
        blockers.append("source_area_consistency_failed")
    if missing_target_fields:
        blockers.append("standardization_derived_fields_missing")
    if not protocol["runtime"].get("dolphinscheduler_configured"):
        blockers.append("dolphinscheduler_runtime_not_configured")
    blockers.extend(
        [
            "authoritative_quality_result_not_recorded",
            "data_product_version_not_created",
        ]
    )
    return list(dict.fromkeys(blockers))


def _member_suffix(name: str, stem: str) -> str:
    if not name.casefold().startswith(stem.casefold()):
        return Path(name).suffix.casefold()
    return name[len(stem):].casefold()


def _finite_round(value: Any) -> float | None:
    import math

    number = float(value)
    return round(number, 8) if math.isfinite(number) else None


def _add_check(
    checks: list[dict[str, Any]],
    *,
    check_id: str,
    category: str,
    status: str,
    severity: str,
    metrics: dict[str, Any],
) -> None:
    checks.append(
        {
            "id": check_id,
            "category": category,
            "status": status,
            "severity": severity,
            "metrics": metrics,
        }
    )


def _verdict(checks: list[dict[str, Any]]) -> str:
    if any(check["status"] == "failed" for check in checks):
        return "failed"
    if any(check["status"] == "blocked" for check in checks):
        return "blocked"
    return "passed"


def _check_summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        status: sum(check["status"] == status for check in checks)
        for status in ("passed", "failed", "blocked", "not_applicable")
    }
