"""Build a non-promotable JQDLTB candidate with field-level quarantine.

This path is intentionally separate from :mod:`jqdltb_transformation_executor`.
The approved executor may only run after a complete transformation approval;
this builder is useful before that point for inspecting the physical Raw to ADS
shape.  It preserves the Raw source, omits unresolved semantic targets from
derived candidate layers, and emits a typed quarantine receipt instead of
inventing values for ``SJNF`` or ``MSSM``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .jqdltb_transformation_executor import (
    _as_number,
    _geometry_area,
    _non_blank,
    _read_features,
)
from .platform_contracts import (
    JqdltbSemanticFieldQuarantineArtifact,
    JqdltbSemanticFieldQuarantineEntry,
    canonical_json_bytes,
    canonical_json_fingerprint,
    jqdltb_semantic_field_quarantine_fingerprint,
)
from .standards_platform.application.acceptance import bundle_identity

TARGET_FIELDS = ("SJNF", "MSSM")
CANDIDATE_SCHEMA = "gda.jqdltb_semantic_candidate.v1"
QUARANTINE_SCHEMA = "gda.jqdltb_semantic_field_quarantine.v1"
UNRESOLVED_DECISIONS = {
    "blocked_no_authoritative_derivation",
    "pending_business_evidence",
    "quarantine_until_authority_exists",
}
ACCEPTED_DECISIONS = {"accepted", "approved", "accepted_candidate_available"}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class JqdltbSemanticCandidateConfig(_FrozenModel):
    """Inputs for the local candidate builder; no control-plane writes occur."""

    source_path: Path
    output_root: Path
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    source_resource_version_id: UUID
    source_resource_urn: str
    archive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    standard_version_ref: str = Field(min_length=1, max_length=512)
    standard_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_candidate_audit_path: Path
    canonical_key: Literal["TBBH"] = "TBBH"
    allow_non_shapefile_fixture: bool = False

    @model_validator(mode="after")
    def _valid_paths(self) -> JqdltbSemanticCandidateConfig:
        if not self.source_path.is_absolute() or not self.source_path.exists():
            raise ValueError("JQDLTB candidate source must be an existing absolute path")
        if not self.output_root.is_absolute():
            raise ValueError("JQDLTB candidate output root must be absolute")
        if (
            not self.semantic_candidate_audit_path.is_absolute()
            or not self.semantic_candidate_audit_path.is_file()
        ):
            raise ValueError("JQDLTB semantic candidate audit must be an existing absolute file")
        return self


class JqdltbSemanticCandidateResult(_FrozenModel):
    schema_name: str = Field(default=CANDIDATE_SCHEMA, alias="schema")
    status: Literal["completed_non_promotable_candidate"]
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_resource_version_id: UUID
    output_root: str
    records_read: int = Field(ge=0)
    records_materialized: int = Field(ge=0)
    semantic_fields_quarantined: int = Field(ge=0)
    quality_verdict: Literal["failed"] = "failed"
    promotable: Literal[False] = False
    authority_state_created: Literal[False] = False
    data_product_version_created: Literal[False] = False
    replayed: bool = False


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _read_semantic_audit(path: Path) -> tuple[dict[str, Any], str]:
    audit = _read_json(path)
    observed = audit.get("report_sha256")
    payload = dict(audit)
    payload.pop("report_sha256", None)
    expected = canonical_json_fingerprint(payload)
    if observed != expected:
        raise ValueError("JQDLTB semantic candidate audit fingerprint is invalid")
    return audit, expected


def _verify_source_identity(
    source_path: Path,
    *,
    expected_bundle_sha256: str,
    allow_non_shapefile_fixture: bool,
) -> dict[str, Any]:
    if source_path.suffix.lower() == ".shp":
        before = bundle_identity(source_path.resolve(strict=True))
        after = bundle_identity(source_path.resolve(strict=True))
        if before != after:
            raise ValueError("JQDLTB source bundle changed while candidate was reading it")
        if after["bundle_sha256"] != expected_bundle_sha256:
            raise ValueError("JQDLTB source bundle does not match the frozen identity")
        return {
            "verification": "shapefile_sidecar_bundle_verified",
            "bundle_sha256": after["bundle_sha256"],
            "size_bytes": after["size_bytes"],
            "member_count": len(after["members"]),
        }
    if not allow_non_shapefile_fixture:
        raise ValueError(
            "non-Shapefile candidate input requires explicit fixture allowance"
        )
    content = source_path.read_bytes()
    return {
        "verification": "explicit_non_shapefile_fixture",
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _semantic_targets(
    audit: Mapping[str, Any],
) -> dict[str, tuple[str, ...]]:
    candidates = audit.get("candidates")
    decisions = audit.get("decisions")
    if not isinstance(candidates, Mapping) or not isinstance(decisions, Mapping):
        raise ValueError("JQDLTB semantic candidate audit is missing candidates or decisions")
    result: dict[str, tuple[str, ...]] = {}
    for target in TARGET_FIELDS:
        decision = str(decisions.get(target, ""))
        if decision in ACCEPTED_DECISIONS:
            raise ValueError(
                f"{target} has semantic admission; use the approved transformation executor"
            )
        if decision not in UNRESOLVED_DECISIONS:
            raise ValueError(f"{target} semantic decision is not an explicit quarantine state")
        values = candidates.get(target)
        if not isinstance(values, list):
            raise ValueError(f"JQDLTB semantic candidates are missing for {target}")
        fields = {
            str(item["field"])
            for item in values
            if (
                isinstance(item, Mapping)
                and _non_blank(item.get("field"))
                and str(item.get("field")) != "no_authoritative_candidate"
            )
        }
        result[target] = tuple(sorted(fields))
    return result


def _strip_unresolved_targets(feature: Mapping[str, Any]) -> dict[str, Any]:
    properties = dict(feature.get("properties") or {})
    for target in TARGET_FIELDS:
        properties.pop(target, None)
    return {
        "type": "Feature",
        "id": feature.get("id"),
        "properties": properties,
        "geometry": feature.get("geometry"),
    }


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _quality_summary(features: list[dict[str, Any]], canonical_key: str) -> dict[str, Any]:
    keys = [str((item.get("properties") or {}).get(canonical_key, "")).strip() for item in features]
    key_blank_count = sum(not value for value in keys)
    non_blank = [value for value in keys if value]
    duplicate_count = len(non_blank) - len(set(non_blank))
    nonpositive: dict[str, int] = {}
    for field in ("TBMJ", "TBDLMJ"):
        nonpositive[field] = sum(
            (_as_number((item.get("properties") or {}).get(field)) is None)
            or (_as_number((item.get("properties") or {}).get(field)) or 0) <= 0
            for item in features
        )
    area_deviation_count = 0
    for item in features:
        props = item.get("properties") or {}
        declared = _as_number(props.get("TBMJ"))
        area = _geometry_area(item.get("geometry"))
        if declared is not None and declared > 0 and area is not None:
            area_deviation_count += abs(area - declared) / abs(declared) > 0.01
    return {
        "records_read": len(features),
        "canonical_key": canonical_key,
        "canonical_key_blank_count": key_blank_count,
        "canonical_key_duplicate_count": duplicate_count,
        "nonpositive_area_by_field": nonpositive,
        "area_deviation_outside_tolerance_count": area_deviation_count,
        "source_quality_verdict": "failed"
        if key_blank_count or duplicate_count or any(nonpositive.values())
        else "not_passed_due_to_unresolved_semantics",
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))
    path.chmod(0o640)


def _quarantine_artifact(
    *,
    config: JqdltbSemanticCandidateConfig,
    audit: Mapping[str, Any],
    features: list[dict[str, Any]],
    target_candidates: Mapping[str, tuple[str, ...]],
) -> JqdltbSemanticFieldQuarantineArtifact:
    entries: list[JqdltbSemanticFieldQuarantineEntry] = []
    for index, feature in enumerate(features):
        properties = feature.get("properties") or {}
        raw_key = properties.get(config.canonical_key)
        record_key = str(raw_key).strip() if _non_blank(raw_key) else f"feature-{index}"
        feature_id = feature.get("id")
        source_feature_id = str(feature_id) if _non_blank(feature_id) else f"feature-{index}"
        for target in TARGET_FIELDS:
            entries.append(
                JqdltbSemanticFieldQuarantineEntry(
                    record_key=record_key,
                    source_feature_id=source_feature_id,
                    target_field=target,
                    reason="semantic_derivation_unresolved",
                    policy="quarantine_until_authority_exists",
                    candidate_source_fields=target_candidates[target],
                )
            )
    identity = audit.get("identities")
    if not isinstance(identity, Mapping):
        raise ValueError("JQDLTB semantic audit identities are missing")
    payload = {
        "tenant_id": config.tenant_id,
        "source_resource_version_id": str(config.source_resource_version_id),
        "source_resource_urn": config.source_resource_urn,
        "archive_sha256": config.archive_sha256,
        "bundle_sha256": config.bundle_sha256,
        "standard_version_ref": config.standard_version_ref,
        "standard_fingerprint": config.standard_fingerprint,
        "target_fields": tuple(sorted(TARGET_FIELDS)),
        "records": tuple(item.model_dump(mode="json") for item in entries),
        "records_quarantined": len(entries),
    }
    payload["artifact_sha256"] = jqdltb_semantic_field_quarantine_fingerprint(
        tenant_id=config.tenant_id,
        source_resource_version_id=config.source_resource_version_id,
        source_resource_urn=config.source_resource_urn,
        archive_sha256=config.archive_sha256,
        bundle_sha256=config.bundle_sha256,
        standard_version_ref=config.standard_version_ref,
        standard_fingerprint=config.standard_fingerprint,
        target_fields=tuple(sorted(TARGET_FIELDS)),
        records=tuple(item.model_dump(mode="json") for item in entries),
    )
    return JqdltbSemanticFieldQuarantineArtifact.model_validate(payload)


def build_semantic_candidate(
    config: JqdltbSemanticCandidateConfig,
    *,
    evaluated_at: datetime | None = None,
) -> JqdltbSemanticCandidateResult:
    """Materialize a deterministic candidate without touching platform authority."""

    evaluated_at = evaluated_at or datetime.now(UTC)
    audit, audit_sha256 = _read_semantic_audit(config.semantic_candidate_audit_path)
    identity = audit.get("identities")
    if not isinstance(identity, Mapping):
        raise ValueError("JQDLTB semantic candidate audit identities are missing")
    expected_standard_ref = (
        f"{identity.get('standard_doc_code')}:{identity.get('standard_version_label')}"
    )
    if (
        identity.get("archive_sha256") != config.archive_sha256
        or identity.get("bundle_sha256") != config.bundle_sha256
        or expected_standard_ref != config.standard_version_ref
    ):
        raise ValueError("JQDLTB semantic audit identity does not match candidate config")
    target_candidates = _semantic_targets(audit)

    source_identity_before = _verify_source_identity(
        config.source_path,
        expected_bundle_sha256=config.bundle_sha256,
        allow_non_shapefile_fixture=config.allow_non_shapefile_fixture,
    )
    features, source_crs = _read_features(config.source_path)
    source_identity_after = _verify_source_identity(
        config.source_path,
        expected_bundle_sha256=config.bundle_sha256,
        allow_non_shapefile_fixture=config.allow_non_shapefile_fixture,
    )
    if source_identity_before != source_identity_after:
        raise ValueError("JQDLTB source changed while candidate was being read")
    expected_count = identity.get("feature_count")
    if (
        expected_count is not None
        and not config.allow_non_shapefile_fixture
        and int(expected_count) != len(features)
    ):
        raise ValueError("JQDLTB candidate feature count differs from semantic audit")
    expected_crs = identity.get("source_crs")
    if (
        expected_crs is not None
        and not config.allow_non_shapefile_fixture
        and source_crs != expected_crs
    ):
        raise ValueError("JQDLTB candidate CRS differs from semantic audit")

    quarantine = _quarantine_artifact(
        config=config,
        audit=audit,
        features=features,
        target_candidates=target_candidates,
    )
    candidate_features = [_strip_unresolved_targets(item) for item in features]
    layer_data = {
        "raw": _feature_collection(features),
        "ods": _feature_collection(candidate_features),
        "dim": _feature_collection(candidate_features),
        "dwd": _feature_collection(candidate_features),
        "ads": _feature_collection(candidate_features),
    }
    layers = {
        name: {
            "relative_path": f"{name}/jqdltb.json",
            "records": len(value["features"]),
            "sha256": canonical_json_fingerprint(value),
            "candidate_only": True,
            "semantic_targets_omitted": list(TARGET_FIELDS) if name != "raw" else [],
        }
        for name, value in layer_data.items()
    }
    quality = _quality_summary(features, config.canonical_key)
    quality["semantic_field_quarantine"] = {
        "artifact_sha256": quarantine.artifact_sha256,
        "records_quarantined": quarantine.records_quarantined,
        "target_fields": list(TARGET_FIELDS),
    }
    quality["verdict"] = "failed"
    quality["promotion_ready"] = False
    quality["blockers"] = [
        "semantic_derivation_unresolved.SJNF",
        "semantic_derivation_unresolved.MSSM",
        "candidate_only_not_promotable",
    ]
    if any(quality["nonpositive_area_by_field"].values()):
        quality["blockers"].append("source_quality_failed.nonpositive_declared_area")
    if quality["area_deviation_outside_tolerance_count"]:
        quality["blockers"].append("source_quality_failed.area_deviation_outside_tolerance")
    lineage = {
        "schema": "gda.jqdltb_semantic_candidate_lineage.v1",
        "source_resource_version_id": str(config.source_resource_version_id),
        "semantic_candidate_audit_sha256": audit_sha256,
        "events": [
            {"event_type": "copy", "from": "source", "to": "raw"},
            {"event_type": "candidate_projection", "from": "raw", "to": "ods"},
            {"event_type": "candidate_projection", "from": "ods", "to": "dim"},
            {"event_type": "candidate_projection", "from": "dim", "to": "dwd"},
            {"event_type": "candidate_projection", "from": "dwd", "to": "ads"},
            {
                "event_type": "semantic_field_quarantine",
                "from": "raw",
                "to": "quarantine",
                "artifact_sha256": quarantine.artifact_sha256,
            },
        ],
    }
    candidate_identity = {
        "schema": CANDIDATE_SCHEMA,
        "source_resource_version_id": str(config.source_resource_version_id),
        "source_resource_urn": config.source_resource_urn,
        "archive_sha256": config.archive_sha256,
        "bundle_sha256": config.bundle_sha256,
        "standard_version_ref": config.standard_version_ref,
        "standard_fingerprint": config.standard_fingerprint,
        "semantic_candidate_audit_sha256": audit_sha256,
        "quarantine_artifact_sha256": quarantine.artifact_sha256,
        "layers": layers,
    }
    candidate_sha256 = canonical_json_fingerprint(candidate_identity)
    output_dir = (
        config.output_root.resolve()
        / config.tenant_id
        / str(config.source_resource_version_id)
        / f"jqdltb-semantic-candidate-{candidate_sha256[:16]}"
    )
    result = JqdltbSemanticCandidateResult(
        status="completed_non_promotable_candidate",
        candidate_sha256=candidate_sha256,
        source_resource_version_id=config.source_resource_version_id,
        output_root=str(output_dir),
        records_read=len(features),
        records_materialized=len(candidate_features),
        semantic_fields_quarantined=quarantine.records_quarantined,
    )
    report = {
        "schema": CANDIDATE_SCHEMA,
        "candidate_sha256": candidate_sha256,
        "evaluated_at": evaluated_at.isoformat(),
        "source_identity": source_identity_after,
        "source_crs": source_crs,
        "source_resource_version_id": str(config.source_resource_version_id),
        "source_resource_urn": config.source_resource_urn,
        "semantic_candidate_audit_sha256": audit_sha256,
        "layers": layers,
        "quarantine": {
            "relative_path": "quarantine/semantic-fields.json",
            "artifact_sha256": quarantine.artifact_sha256,
            "records_quarantined": quarantine.records_quarantined,
        },
        "quality": quality,
        "lineage": lineage,
        "authority_state_created": False,
        "data_product_version_created": False,
        "result": result.model_dump(mode="json", by_alias=True),
    }
    staging = output_dir.parent / f".{output_dir.name}.{os.getpid()}.tmp"
    if staging.exists():
        shutil.rmtree(staging)
    if output_dir.exists():
        existing_path = output_dir / "candidate-evidence.json"
        if existing_path.is_file():
            existing = _read_json(existing_path)
            if existing.get("candidate_sha256") != candidate_sha256:
                raise ValueError("existing JQDLTB candidate conflicts with this identity")
            if existing.get("result", {}).get("status") == result.status:
                return result.model_copy(update={"replayed": True})
        shutil.rmtree(output_dir)
    staging.mkdir(parents=True)
    try:
        for name, value in layer_data.items():
            _write_json(staging / name / "jqdltb.json", value)
        _write_json(
            staging / "quarantine" / "semantic-fields.json",
            quarantine.model_dump(mode="json", by_alias=True),
        )
        _write_json(staging / "layer-manifest.json", layers)
        _write_json(staging / "lineage" / "jqdltb.json", lineage)
        _write_json(staging / "candidate-evidence.json", report)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        if output_dir.exists():
            raise ValueError("JQDLTB candidate output appeared concurrently")
        os.replace(staging, output_dir)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return result


__all__ = [
    "JqdltbSemanticCandidateConfig",
    "JqdltbSemanticCandidateResult",
    "build_semantic_candidate",
    "QUARANTINE_SCHEMA",
]
