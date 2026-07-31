"""Ingest a bounded real Chongqing feature slice into JDBC/S3 Iceberg.

M3-22 consumes the checked M3-21 runtime-bound promotion, reads the same local
Shapefile through an explicit CLI path, and creates a path-free row-set binding.
One authorized Spark/Sedona Job writes the rows and immediately replays the
same plan as a readback-proven no-op. Source paths, feature payloads and runtime
credentials never enter the committed evidence.

The result remains local evidence. It does not persist the output candidate to
GDA Control or establish protected identity, production object storage, full
engine conformance, production ingestion or production readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid5

import geopandas as gpd
import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from . import metadata_fabric_durable_active_metadata_promotion as durable
from . import metadata_fabric_ingestion_replay as replay
from . import metadata_fabric_object_store_active_metadata_promotion as m321
from . import metadata_fabric_spark_object_store_interoperability as m310
from .platform_authorization import (
    build_approval_artifact,
    build_policy_decision_artifact,
    validate_run_authorization_evidence,
)
from .platform_contracts import (
    ApprovalRecord,
    Artifact,
    ArtifactRole,
    LineageEvent,
    LineageEventType,
    PlatformRun,
    PolicyDecision,
    QualityResult,
    QualityVerdict,
    ResourceVersion,
    RunPolicyReferences,
    SubjectContext,
    canonical_json_bytes,
    canonical_json_fingerprint,
    quality_result_fingerprint,
)
from .spatial_dataset_bundle import (
    build_shapefile_bundle_inventory,
    validate_shapefile_bundle_inventory,
)

PROFILE_SCHEMA = "gda.real_feature_ingestion_profile.v1"
PLAN_SCHEMA = "gda.real_feature_ingestion_plan.v1"
ROW_SET_SCHEMA = "gda.real_feature_row_set.v1"
CONTRACT_SCHEMA = "gda.real_feature_ingestion_contract.v1"
OBSERVATION_SCHEMA = "gda.real_feature_ingestion_observation.v1"
EVIDENCE_SCHEMA = "gda.real_feature_ingestion_evidence.v1"
VALIDATION_SCHEMA = "gda.real_feature_ingestion_validation.v1"
PROBE_RESULT_SCHEMA = "gda.real_feature_ingestion_probe_result.v1"
ACTION = "metadata_fabric.ingest_real_feature_slice"
TENANT = m321.TENANT
SOURCE_RESOURCE_VERSION_ID = m321.RESOURCE_VERSION_ID
OUTPUT_RESOURCE_VERSION_ID = UUID("a6000000-0000-4000-8000-000000000002")
DEFINITION_VERSION_ID = UUID("a9000000-0000-4000-8000-000000000008")
RUN_ID = UUID("a9000000-0000-4000-8000-000000000009")
OUTPUT_RESOURCE_URN = (
    "gda://metadata-authorization-local/data_product/chongqing-cultural-districts-iceberg"
)
WORKLOAD = "workload:real-feature-ingestion-executor"
QUALITY_EVALUATOR = "workload:real-feature-spatial-quality-evaluator"
M321_EVIDENCE_SHA256 = (
    "d73754c53cf16d888aa345baa5d079cc7fd98d8b84db747f52188c1a69bf1628"
)
M310_EVIDENCE_FINGERPRINT = m321.M310_EVIDENCE_FINGERPRINT

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = REPO_ROOT / "config/metadata-fabric-real-feature-ingestion.local.yaml"
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT / "docs/evidence/metadata-fabric-real-feature-ingestion-2026-07-31.json"
)
DEFAULT_WRAPPER_PATH = REPO_ROOT / "scripts/metadata-fabric-real-feature-ingestion.sh"
DEFAULT_JOB_PATH = REPO_ROOT / "k8s/metadata-fabric-real-feature-ingestion/spark-job.yaml"

GRAVITINO_COLUMNS = (
    {"name": "BSM", "type": "string", "nullable": False},
    {"name": "geometry", "type": "binary", "nullable": False},
    {"name": "srid", "type": "integer", "nullable": False},
    {"name": "min_x", "type": "double", "nullable": False},
    {"name": "min_y", "type": "double", "nullable": False},
    {"name": "max_x", "type": "double", "nullable": False},
    {"name": "max_y", "type": "double", "nullable": False},
    {"name": "row_sha256", "type": "string", "nullable": False},
)
ICEBERG_FIELDS = (
    {"name": "BSM", "required": True, "type": "string"},
    {"name": "geometry", "required": True, "type": "binary"},
    {"name": "srid", "required": True, "type": "int"},
    {"name": "min_x", "required": True, "type": "double"},
    {"name": "min_y", "required": True, "type": "double"},
    {"name": "max_x", "required": True, "type": "double"},
    {"name": "max_y", "required": True, "type": "double"},
    {"name": "row_sha256", "required": True, "type": "string"},
)
SPARK_COLUMNS = tuple(item["name"] for item in ICEBERG_FIELDS)
FALSE_CLAIMS = (
    "predecessor_history_changed",
    "ingestion_persisted_to_gda_control",
    "source_dataset_committed",
    "source_absolute_path_committed",
    "source_feature_payload_committed",
    "protected_workload_identity_verified",
    "durable_catalog_verified",
    "production_object_store_verified",
    "oidc_verified",
    "tls_verified",
    "flink_conformance_verified",
    "spark_conformance_verified",
    "production_ingestion_verified",
    "platform_run_succeeded",
    "production_ready",
)


class RealFeatureIngestionError(RuntimeError):
    """The real feature ingestion contract failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DependencyProfile(_FrozenModel):
    m321_profile_path: str
    m321_evidence_path: str
    m321_evidence_sha256: Literal[M321_EVIDENCE_SHA256]
    m310_profile_path: str
    m310_evidence_path: str
    m310_evidence_fingerprint: Literal[M310_EVIDENCE_FINGERPRINT]


class SourceProfile(_FrozenModel):
    source_label: Literal["chongqing-central-cultural-districts"]
    identifier_field: Literal["Bsm"]
    expected_feature_count: Literal[20]
    expected_srid: Literal[4490]
    expected_geometry_dimension: Literal[3]
    expected_geometry_family: Literal["polygon"]


class ClaimProfile(_FrozenModel):
    predecessor_history_changed: Literal[False]
    ingestion_persisted_to_gda_control: Literal[False]
    protected_workload_identity_verified: Literal[False]
    durable_catalog_verified: Literal[False]
    production_object_store_verified: Literal[False]
    oidc_verified: Literal[False]
    tls_verified: Literal[False]
    flink_conformance_verified: Literal[False]
    production_ingestion_verified: Literal[False]
    production_ready: Literal[False]


class AuthorizationProfile(_FrozenModel):
    policy_version_ref: Literal["policy://gda/metadata-fabric/real-feature-ingestion/v1"]
    evaluator_subject: Literal["workload:real-feature-ingestion-policy-evaluator"]
    approver_subject: Literal["human:metadata-platform-owner"]
    approval_reason: str


class RealFeatureIngestionProfile(_FrozenModel):
    profile_schema: Literal[PROFILE_SCHEMA] = Field(alias="schema")
    environment: Literal["local_docker_desktop"]
    dependencies: DependencyProfile
    source: SourceProfile
    target: m321.ObjectStoreTarget
    identity: m321.IdentityProfile
    authorization: AuthorizationProfile
    claims: ClaimProfile


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _resolve_repo_path(value: str) -> Path:
    path = Path(value)
    candidate = path if path.is_absolute() else REPO_ROOT / path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT)
    except (OSError, ValueError) as exc:
        raise RealFeatureIngestionError("dependency path escapes the repository") from exc
    return resolved


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON document must be an object")
    return value


def _file_record(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(REPO_ROOT)),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> RealFeatureIngestionProfile:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("profile must be an object")
        profile = RealFeatureIngestionProfile.model_validate(value)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise RealFeatureIngestionError(
            f"real feature ingestion profile is invalid: {type(exc).__name__}"
        ) from exc
    if profile.target.table_location != (
        "s3://gda-metadata-warehouse/warehouse/cultural_heritage/cultural_districts"
    ):
        raise RealFeatureIngestionError("real feature target location drifted")
    return profile


def _load_dependencies(
    profile: RealFeatureIngestionProfile,
) -> tuple[dict[str, Any], m310.SparkObjectStoreInteroperabilityProfile]:
    m321_profile = _resolve_repo_path(profile.dependencies.m321_profile_path)
    m321_evidence_path = _resolve_repo_path(profile.dependencies.m321_evidence_path)
    report = m321.build_validation_report(
        profile_path=m321_profile,
        evidence_path=m321_evidence_path,
    )
    if report.get("status") != "valid":
        raise RealFeatureIngestionError("M3-21 dependency evidence is invalid")
    evidence = _load_json_object(m321_evidence_path)
    if evidence.get("evidence_sha256") != M321_EVIDENCE_SHA256:
        raise RealFeatureIngestionError("M3-21 dependency evidence SHA drifted")
    if evidence.get("source_feature_rows_ingested") is not False:
        raise RealFeatureIngestionError("M3-21 predecessor is not an empty-table promotion")

    m310_profile_path = _resolve_repo_path(profile.dependencies.m310_profile_path)
    m310_evidence_path = _resolve_repo_path(profile.dependencies.m310_evidence_path)
    object_report = m310.build_validation_report(
        profile_path=m310_profile_path,
        evidence_path=m310_evidence_path,
    )
    if object_report.get("errors"):
        raise RealFeatureIngestionError("M3-10 dependency evidence is invalid")
    object_evidence = _load_json_object(m310_evidence_path)
    if object_evidence.get("evidence_fingerprint") != M310_EVIDENCE_FINGERPRINT:
        raise RealFeatureIngestionError("M3-10 dependency evidence fingerprint drifted")
    return evidence, m310.load_profile(m310_profile_path)


def _manifest_errors(path: Path = DEFAULT_JOB_PATH) -> list[str]:
    errors: list[str] = []
    try:
        documents = [item for item in yaml.safe_load_all(path.read_text()) if item]
    except (OSError, yaml.YAMLError) as exc:
        return [f"real feature Spark manifest is invalid: {type(exc).__name__}"]
    if any(_mapping(item).get("kind") == "Secret" for item in documents):
        errors.append("real feature Spark manifest may not commit Secret values")
    configmap = next(
        (item for item in documents if _mapping(item).get("kind") == "ConfigMap"),
        None,
    )
    job = next((item for item in documents if _mapping(item).get("kind") == "Job"), None)
    if configmap is None or job is None or len(documents) != 2:
        return errors + ["real feature Spark manifest is incomplete"]
    probe = str(_mapping(configmap.get("data")).get("probe.py") or "")
    for marker in (
        "SedonaContext.create",
        "ST_GeomFromWKB",
        "ST_IsValid",
        "ST_SRID",
        "ST_Area",
        "ST_XMin",
        ".writeTo(TABLE).append()",
        "existing Iceberg table is partial or content-drifted",
        "GDA_REAL_FEATURE_INGESTION_RESULT=",
    ):
        if marker not in probe:
            errors.append(f"real feature Spark probe is missing marker: {marker}")
    spec = _mapping(job.get("spec"))
    pod_spec = _mapping(_mapping(spec.get("template")).get("spec"))
    containers = _list(pod_spec.get("containers"))
    container = _mapping(containers[0]) if len(containers) == 1 else {}
    volumes = _list(pod_spec.get("volumes"))
    volume_names = {str(_mapping(item).get("name")) for item in volumes}
    mounts = _list(container.get("volumeMounts"))
    if spec.get("suspend") is not True or spec.get("backoffLimit") != 0:
        errors.append("real feature Spark Job must start suspended without retries")
    if pod_spec.get("automountServiceAccountToken") is not False:
        errors.append("real feature Spark Job must disable token automount")
    if any("persistentVolumeClaim" in _mapping(item) for item in volumes):
        errors.append("real feature Spark Job may not mount a warehouse PVC")
    if volume_names != {"probe", "input", "tmp"} or {
        str(_mapping(item).get("name")) for item in mounts
    } != volume_names:
        errors.append("real feature Spark Job input boundary is incomplete")
    if container.get("image") != "gisdataagent/mmfe-spark-runtime:local":
        errors.append("real feature Spark image does not match the certified local runtime")
    return errors


def build_contract_report(
    *,
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
    job_path: Path = DEFAULT_JOB_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: RealFeatureIngestionProfile | None = None
    predecessor: str | None = None
    try:
        profile = load_profile(profile_path)
        evidence, _ = _load_dependencies(profile)
        predecessor = str(evidence.get("promotion_candidate_sha256"))
    except RealFeatureIngestionError as exc:
        errors.append(f"real feature dependency contract is invalid: {type(exc).__name__}")
    errors.extend(_manifest_errors(job_path))
    try:
        wrapper = wrapper_path.read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_real_feature_ingestion",
            '"$@"',
        ):
            if marker not in wrapper:
                errors.append(f"real feature wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"real feature wrapper is invalid: {type(exc).__name__}")
    files = {
        "implementation": _file_record(Path(__file__)),
        "profile": _file_record(profile_path),
        "spark_job": _file_record(job_path),
        "wrapper": _file_record(wrapper_path),
    }
    stable = {
        "schema": CONTRACT_SCHEMA,
        "m321_evidence_sha256": M321_EVIDENCE_SHA256,
        "m310_evidence_fingerprint": M310_EVIDENCE_FINGERPRINT,
        "predecessor_promotion_candidate_sha256": predecessor,
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "output_resource_version_id": str(OUTPUT_RESOURCE_VERSION_ID),
        "authorization_action": ACTION,
        "expected_feature_count": profile.source.expected_feature_count if profile else None,
        "expected_srid": profile.source.expected_srid if profile else None,
        "target_identity": profile.target.identity if profile else None,
        "target_location": profile.target.table_location if profile else None,
        "table_columns": list(GRAVITINO_COLUMNS),
        "files": files,
        "ingestion_persisted_to_gda_control": False,
        "production_ingestion_verified": False,
        "production_ready": False,
    }
    return {
        **stable,
        "contract_sha256": canonical_json_fingerprint(stable),
        "local_static_contract_verified": not errors,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
    }


def _output_content_sha256(
    *,
    source_content_sha256: str,
    row_set_sha256: str,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": ROW_SET_SCHEMA,
            "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
            "source_content_sha256": source_content_sha256,
            "row_set_sha256": row_set_sha256,
            "table_fields": list(ICEBERG_FIELDS),
        }
    )


def build_source_input(
    profile: RealFeatureIngestionProfile,
    predecessor: Mapping[str, Any],
    *,
    shapefile_path: Path,
    ogrinfo_path: Path,
    proj_data_path: Path | None,
) -> dict[str, Any]:
    inventory = build_shapefile_bundle_inventory(
        shapefile_path,
        source_label=profile.source.source_label,
        ogrinfo_path=ogrinfo_path,
        proj_data_path=proj_data_path,
    )
    expected_inventory = _mapping(predecessor.get("dataset_bundle"))
    if inventory != dict(expected_inventory):
        raise RealFeatureIngestionError("source bundle does not match M3-21 ResourceVersion")
    frame = gpd.read_file(shapefile_path)
    columns = {str(item).lower(): str(item) for item in frame.columns}
    identifier = columns.get(profile.source.identifier_field.lower())
    if identifier is None:
        raise RealFeatureIngestionError("source identifier field is unavailable")
    epsg = frame.crs.to_epsg() if frame.crs is not None else None
    geometry_types = set(frame.geometry.geom_type.tolist())
    if (
        len(frame) != profile.source.expected_feature_count
        or frame[identifier].isna().any()
        or frame[identifier].nunique() != len(frame)
        or epsg != profile.source.expected_srid
        or not geometry_types.issubset({"Polygon", "MultiPolygon"})
        or not bool(frame.geometry.is_valid.all())
        or bool(frame.geometry.is_empty.any())
        or not bool(frame.geometry.has_z.all())
    ):
        raise RealFeatureIngestionError("real feature source quality boundary does not match")
    rows: list[dict[str, Any]] = []
    row_hashes: list[str] = []
    for _, item in frame.sort_values(identifier).iterrows():
        min_x, min_y, max_x, max_y = item.geometry.bounds
        stable = {
            "BSM": str(item[identifier]),
            "geometry_wkb_hex": item.geometry.wkb_hex.lower(),
            "srid": profile.source.expected_srid,
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
        }
        row_sha256 = canonical_json_fingerprint(stable)
        rows.append({**stable, "row_sha256": row_sha256})
        row_hashes.append(row_sha256)
    row_set_sha256 = canonical_json_fingerprint(
        [{key: value for key, value in row.items() if key != "row_sha256"} for row in rows]
    )
    source_content_sha256 = str(expected_inventory.get("content_sha256"))
    output_content_sha256 = _output_content_sha256(
        source_content_sha256=source_content_sha256,
        row_set_sha256=row_set_sha256,
    )
    raw_payload = {
        "schema": ROW_SET_SCHEMA,
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "source_content_sha256": source_content_sha256,
        "output_resource_version_id": str(OUTPUT_RESOURCE_VERSION_ID),
        "output_content_sha256": output_content_sha256,
        "row_set_sha256": row_set_sha256,
        "expected_feature_count": profile.source.expected_feature_count,
        "expected_row_sha256": sorted(row_hashes),
        "rows": rows,
    }
    payload_bytes = canonical_json_bytes(raw_payload)
    if len(payload_bytes) >= 900_000:
        raise RealFeatureIngestionError("real feature input exceeds the bounded ConfigMap size")
    return {
        "inventory": inventory,
        "payload": raw_payload,
        "projection": {
            "schema": ROW_SET_SCHEMA,
            "feature_count": len(rows),
            "unique_identifier_count": len(set(row["BSM"] for row in rows)),
            "valid_geometry_count": int(frame.geometry.is_valid.sum()),
            "non_empty_geometry_count": int((~frame.geometry.is_empty).sum()),
            "geometry_z_count": int(frame.geometry.has_z.sum()),
            "geometry_types": sorted(geometry_types),
            "srid": epsg,
            "bounds": frame.total_bounds.tolist(),
            "row_set_sha256": row_set_sha256,
            "row_sha256": sorted(row_hashes),
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "payload_size_bytes": len(payload_bytes),
            "source_payload_recorded": False,
        },
    }


class RealFeatureIngestionPlan(_FrozenModel):
    plan_schema: Literal[PLAN_SCHEMA] = Field(default=PLAN_SCHEMA, alias="schema")
    tenant_id: Literal[TENANT]
    run_id: UUID
    definition_version_id: UUID
    source_resource_urn: str
    source_resource_version_id: UUID
    source_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_resource_urn: Literal[OUTPUT_RESOURCE_URN]
    output_resource_version_id: UUID
    output_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    row_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_feature_count: Literal[20]
    predecessor_promotion_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target: m321.ObjectStoreTarget
    runtime_binding: dict[str, Any]
    runtime_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    table_columns: tuple[dict[str, Any], ...]
    writes_to_gda_control: Literal[False] = False
    writes_to_legacy: Literal[False] = False
    ingestion_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _fingerprints_match(self) -> RealFeatureIngestionPlan:
        if (
            self.run_id != RUN_ID
            or self.definition_version_id != DEFINITION_VERSION_ID
            or self.source_resource_version_id != SOURCE_RESOURCE_VERSION_ID
            or self.output_resource_version_id != OUTPUT_RESOURCE_VERSION_ID
        ):
            raise ValueError("real feature plan identity does not match")
        if self.runtime_binding_sha256 != canonical_json_fingerprint(self.runtime_binding):
            raise ValueError("runtime binding fingerprint does not match")
        expected_output = _output_content_sha256(
            source_content_sha256=self.source_content_sha256,
            row_set_sha256=self.row_set_sha256,
        )
        if self.output_content_sha256 != expected_output:
            raise ValueError("output content fingerprint does not match")
        if self.table_columns != GRAVITINO_COLUMNS:
            raise ValueError("real feature table schema does not match")
        stable = self.model_dump(mode="json", by_alias=True, exclude={"ingestion_plan_sha256"})
        if self.ingestion_plan_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("ingestion plan fingerprint does not match")
        return self


def build_ingestion_plan(
    profile: RealFeatureIngestionProfile,
    predecessor: Mapping[str, Any],
    source: Mapping[str, Any],
    runtime_binding: Mapping[str, Any],
) -> RealFeatureIngestionPlan:
    dataset = _mapping(predecessor.get("dataset_bundle"))
    source_urn = str(
        _mapping(_mapping(predecessor.get("observation")).get("plan")).get(
            "resource_urn"
        )
    )
    values: dict[str, Any] = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_VERSION_ID,
        "source_resource_urn": source_urn,
        "source_resource_version_id": SOURCE_RESOURCE_VERSION_ID,
        "source_content_sha256": dataset.get("content_sha256"),
        "output_resource_urn": OUTPUT_RESOURCE_URN,
        "output_resource_version_id": OUTPUT_RESOURCE_VERSION_ID,
        "output_content_sha256": _mapping(source.get("payload")).get(
            "output_content_sha256"
        ),
        "row_set_sha256": _mapping(source.get("projection")).get("row_set_sha256"),
        "expected_feature_count": profile.source.expected_feature_count,
        "predecessor_promotion_candidate_sha256": predecessor.get(
            "promotion_candidate_sha256"
        ),
        "target": profile.target,
        "runtime_binding": dict(runtime_binding),
        "runtime_binding_sha256": canonical_json_fingerprint(runtime_binding),
        "table_columns": GRAVITINO_COLUMNS,
    }
    stable = {
        "schema": PLAN_SCHEMA,
        **{
            key: value.model_dump(mode="json", by_alias=True)
            if isinstance(value, BaseModel)
            else str(value)
            if isinstance(value, UUID)
            else value
            for key, value in values.items()
        },
        "writes_to_gda_control": False,
        "writes_to_legacy": False,
    }
    return RealFeatureIngestionPlan(
        **values,
        ingestion_plan_sha256=canonical_json_fingerprint(stable),
    )


def _execution_plan_artifact(
    plan: RealFeatureIngestionPlan,
    *,
    created_at: datetime,
) -> Artifact:
    manifest = {
        "schema": "gda.real_feature_ingestion_execution_plan.v1",
        "plan": plan.model_dump(mode="json", by_alias=True),
    }
    artifact_id = uuid5(RUN_ID, f"real-feature-ingestion:{plan.ingestion_plan_sha256}")
    content = canonical_json_bytes(manifest)
    return Artifact(
        tenant_id=TENANT,
        artifact_id=artifact_id,
        artifact_key=f"real-feature-ingestion:{artifact_id}",
        artifact_role=ArtifactRole.EXECUTION_PLAN,
        storage_uri=f"postgresql://gda-control/execution-plans/{TENANT}/{artifact_id}",
        media_type="application/vnd.gda.real-feature-ingestion-plan+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(content),
        resource_version_id=DEFINITION_VERSION_ID,
        manifest=manifest,
        created_by=WORKLOAD,
        created_at=created_at,
    )


def build_ingestion_authorization(
    plan: RealFeatureIngestionPlan,
    profile: RealFeatureIngestionProfile,
    *,
    authorized_at: datetime,
) -> tuple[PlatformRun, Artifact, Artifact, Artifact, str]:
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id=WORKLOAD.removeprefix("workload:"),
        subject_type="workload",
        roles=("spatial_ingestion_executor",),
        purpose="ingest one content-bound real feature slice into local Iceberg",
    )
    execution_plan = _execution_plan_artifact(
        plan,
        created_at=authorized_at - timedelta(seconds=3),
    )
    decision = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=subject,
        action=ACTION,
        definition_version_id=DEFINITION_VERSION_ID,
        resource_version_ids=(
            DEFINITION_VERSION_ID,
            SOURCE_RESOURCE_VERSION_ID,
        ),
        execution_plan_artifact_id=execution_plan.artifact_id,
        effect="allow",
        policy_version_ref=profile.authorization.policy_version_ref,
        evaluator_subject=profile.authorization.evaluator_subject,
        requires_approval=True,
        decided_at=authorized_at - timedelta(seconds=3),
        expires_at=authorized_at + timedelta(days=365),
    )
    policy_artifact = build_policy_decision_artifact(decision)
    approval = ApprovalRecord(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_VERSION_ID,
        policy_decision_artifact_id=policy_artifact.artifact_id,
        policy_decision_sha256=policy_artifact.content_sha256,
        verdict="approved",
        approver_subject=profile.authorization.approver_subject,
        reason=profile.authorization.approval_reason,
        decided_at=authorized_at - timedelta(seconds=2),
        expires_at=authorized_at + timedelta(days=180),
    )
    approval_artifact = build_approval_artifact(approval)
    run = PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_VERSION_ID,
        orchestration_class="dataops",
        subject_context=subject,
        input_bindings=(
            {
                "binding_name": "source_dataset",
                "resource_version_id": SOURCE_RESOURCE_VERSION_ID,
                "semantic_type": "gis.cultural_districts",
            },
        ),
        idempotency_key=f"real-feature-ingestion:{plan.output_content_sha256}",
        policy_refs=RunPolicyReferences(
            policy_decision_artifact_id=policy_artifact.artifact_id,
            approval_artifact_id=approval_artifact.artifact_id,
        ),
        submitted_at=authorized_at - timedelta(seconds=1),
    )
    validate_run_authorization_evidence(
        run,
        policy_artifact,
        approval_artifact,
        execution_plan,
        at=authorized_at,
        expected_action=ACTION,
    )
    stable = {
        "run": run.model_dump(mode="json"),
        "execution_plan": execution_plan.model_dump(mode="json"),
        "policy_decision": policy_artifact.model_dump(mode="json"),
        "approval": approval_artifact.model_dump(mode="json"),
    }
    return (
        run,
        execution_plan,
        policy_artifact,
        approval_artifact,
        canonical_json_fingerprint(stable),
    )


def validate_ingestion_authorization(
    plan: RealFeatureIngestionPlan,
    authorization: tuple[PlatformRun, Artifact, Artifact, Artifact, str],
    *,
    at: datetime,
) -> None:
    run, execution_plan, policy_artifact, approval_artifact, fingerprint = authorization
    if _mapping(execution_plan.manifest.get("plan")) != plan.model_dump(
        mode="json", by_alias=True
    ):
        raise RealFeatureIngestionError("authorization does not bind the exact plan")
    validate_run_authorization_evidence(
        run,
        policy_artifact,
        approval_artifact,
        execution_plan,
        at=at,
        expected_action=ACTION,
    )
    stable = {
        "run": run.model_dump(mode="json"),
        "execution_plan": execution_plan.model_dump(mode="json"),
        "policy_decision": policy_artifact.model_dump(mode="json"),
        "approval": approval_artifact.model_dump(mode="json"),
    }
    if fingerprint != canonical_json_fingerprint(stable):
        raise RealFeatureIngestionError("authorization fingerprint does not match")


def create_target_table(
    rehearsal: m321.ObjectStoreProjectionRehearsal,
    profile: RealFeatureIngestionProfile,
    plan: RealFeatureIngestionPlan,
) -> dict[str, Any]:
    if rehearsal.bounded is None:
        raise RealFeatureIngestionError("bounded Gravitino identity is unavailable")
    rehearsal.bounded.request(
        "POST",
        f"{rehearsal._schema_path(profile.target)}/tables",
        json_body={
            "name": profile.target.table,
            "comment": "Authorized real Chongqing cultural district Iceberg slice",
            "columns": [
                {
                    **column,
                    "comment": "Content-bound cross-engine spatial field",
                }
                for column in GRAVITINO_COLUMNS
            ],
            "properties": {
                "gda.resource_urn": plan.output_resource_urn,
                "gda.resource_version_id": str(plan.output_resource_version_id),
                "gda.content_sha256": plan.output_content_sha256,
                "gda.source_resource_urn": plan.source_resource_urn,
                "gda.source_resource_version_id": str(plan.source_resource_version_id),
                "gda.source_content_sha256": plan.source_content_sha256,
                "gda.row_set_sha256": plan.row_set_sha256,
                "gda.provider_revision": "m3-22-real-feature-ingestion-v1",
            },
        },
        label="bounded real feature table create",
    )
    _, payload = rehearsal.bounded.request(
        "GET",
        rehearsal._table_path(profile.target),
        label="real feature table exact readback",
    )
    assert payload is not None
    projection = durable._table_projection(payload)
    expected = {
        "name": profile.target.table,
        "columns": [dict(item) for item in GRAVITINO_COLUMNS],
        "resource_urn": plan.output_resource_urn,
        "resource_version_id": str(plan.output_resource_version_id),
        "content_sha256": plan.output_content_sha256,
        "provider_revision": "m3-22-real-feature-ingestion-v1",
    }
    if projection != expected:
        raise RealFeatureIngestionError("real feature table projection drifted")
    properties = _mapping(_mapping(payload.get("table")).get("properties"))
    drifted_source_properties: list[str] = []
    for key, expected_value in (
        ("gda.source_resource_urn", plan.source_resource_urn),
        ("gda.source_resource_version_id", str(plan.source_resource_version_id)),
        ("gda.source_content_sha256", plan.source_content_sha256),
        ("gda.row_set_sha256", plan.row_set_sha256),
    ):
        if properties.get(key) != expected_value:
            drifted_source_properties.append(key)
    if drifted_source_properties:
        raise RealFeatureIngestionError(
            "real feature source binding drifted: "
            + ", ".join(drifted_source_properties)
        )
    return {
        "status": "created",
        "mutation_count": 1,
        "mutations": ["gravitino.table.create"],
        "table_projection": projection,
        "table_projection_sha256": canonical_json_fingerprint(projection),
        "source_binding_verified": True,
    }


def _run_spark_ingestion(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
    *,
    input_payload: Mapping[str, Any],
) -> dict[str, Any]:
    namespace = runtime.profile.cluster.rehearsal_namespace
    input_resource = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": "real-feature-ingestion-input",
            "namespace": namespace,
        },
        "immutable": True,
        "data": {
            "ingestion.json": json.dumps(
                input_payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        },
    }
    runtime.kubectl.run(
        ["create", "-f", "-"],
        input_text=json.dumps(input_resource, ensure_ascii=True, separators=(",", ":")),
        label="ephemeral real feature input create",
    )
    runtime.kubectl.run(
        ["apply", "-f", str(DEFAULT_JOB_PATH)],
        label="real feature Spark Job apply",
    )
    job_name = "real-feature-ingestion-probe"
    runtime.kubectl.run(
        [
            "-n",
            namespace,
            "patch",
            "job",
            job_name,
            "--type=merge",
            "-p",
            '{"spec":{"suspend":false}}',
        ],
        label="real feature Spark Job release",
    )
    deadline = time.monotonic() + 900
    terminal: str | None = None
    while time.monotonic() < deadline:
        current = runtime.kubectl.get_json(
            ["-n", namespace, "get", "job", job_name],
            label="real feature Spark Job wait",
        )
        assert current is not None
        for condition in _list(_mapping(current.get("status")).get("conditions")):
            item = _mapping(condition)
            if item.get("status") == "True" and item.get("type") in {"Complete", "Failed"}:
                terminal = str(item.get("type"))
                break
        if terminal is not None:
            break
        time.sleep(2)
    job = runtime.kubectl.get_json(
        ["-n", namespace, "get", "job", job_name],
        label="real feature Spark Job observation",
    )
    pod_list = runtime.kubectl.get_json(
        ["-n", namespace, "get", "pods", "-l", f"job-name={job_name}"],
        label="real feature Spark pod observation",
    )
    assert job is not None and pod_list is not None
    pod = m310._single_list_item(pod_list, "real feature Spark Job")
    pod_name = str(_mapping(pod.get("metadata")).get("name"))
    logs = runtime.kubectl.run(
        ["-n", namespace, "logs", pod_name, "-c", "spark"],
        expected=frozenset({0, 1}),
        timeout=120,
        label="real feature Spark result collection",
    )
    lines = [
        line.removeprefix("GDA_REAL_FEATURE_INGESTION_RESULT=")
        for line in logs.stdout.splitlines()
        if line.startswith("GDA_REAL_FEATURE_INGESTION_RESULT=")
    ]
    result: dict[str, Any] | None = None
    if len(lines) == 1:
        candidate = json.loads(lines[0])
        if isinstance(candidate, dict):
            result = candidate
    diagnostic: list[str] = []
    if result is None:
        for line in logs.stdout.splitlines()[-100:]:
            if any(
                marker in line.lower()
                for marker in (
                    "access-key",
                    "authorization:",
                    "credential",
                    "password",
                    "secret",
                    "token",
                )
            ):
                diagnostic.append("<redacted sensitive log line>")
            else:
                diagnostic.append(line[:1000])
    pod_spec = _mapping(pod.get("spec"))
    claims = sorted(
        str(_mapping(_mapping(item).get("persistentVolumeClaim")).get("claimName"))
        for item in _list(pod_spec.get("volumes"))
        if _mapping(_mapping(item).get("persistentVolumeClaim")).get("claimName")
    )
    container = m310._container_status(pod, "spark")
    status = _mapping(job.get("status"))
    return {
        "wait_completed": terminal == "Complete",
        "terminal_condition": terminal,
        "job": {
            "name": job_name,
            "uid": _mapping(job.get("metadata")).get("uid"),
            "succeeded": status.get("succeeded", 0),
            "failed": status.get("failed", 0),
            "completion_time": status.get("completionTime"),
        },
        "pod": {
            "name": pod_name,
            "uid": _mapping(pod.get("metadata")).get("uid"),
            "phase": _mapping(pod.get("status")).get("phase"),
            "node_name": pod_spec.get("nodeName"),
            "service_account": pod_spec.get("serviceAccountName"),
            "service_account_automount_disabled": (
                pod_spec.get("automountServiceAccountToken") is False
            ),
            "image": container.get("image"),
            "image_id": container.get("imageID"),
            "persistent_volume_claims": claims,
        },
        "result_line_count": len(lines),
        "log_sha256": hashlib.sha256(logs.stdout.encode()).hexdigest(),
        "log_recorded": False,
        "failure_diagnostic": diagnostic,
        "result": result,
    }


def observe_ingested_table(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
    profile: RealFeatureIngestionProfile,
    *,
    endpoint_url: str,
    object_store_user: SecretStr,
    object_store_material: SecretStr,
) -> dict[str, Any]:
    client = runtime._s3_client(
        endpoint_url=endpoint_url,
        object_store_user=object_store_user,
        object_store_material=object_store_material,
    )
    try:
        objects: list[dict[str, Any]] = []
        continuation: str | None = None
        while True:
            request: dict[str, Any] = {
                "Bucket": profile.target.bucket,
                "Prefix": profile.target.object_prefix,
            }
            if continuation:
                request["ContinuationToken"] = continuation
            response = client.list_objects_v2(**request)
            for item in response.get("Contents") or []:
                objects.append(
                    {
                        "key": item.get("Key"),
                        "size": item.get("Size"),
                        "etag": str(item.get("ETag") or "").strip('"'),
                    }
                )
            if response.get("IsTruncated") is not True:
                break
            continuation = response.get("NextContinuationToken")
            if not continuation:
                raise RealFeatureIngestionError("S3 listing continuation is invalid")
        objects.sort(key=lambda item: str(item.get("key")))
        data_keys = sorted(
            str(item["key"])
            for item in objects
            if str(item.get("key") or "").endswith(".parquet")
        )
        metadata_keys = sorted(
            str(item["key"])
            for item in objects
            if str(item.get("key") or "").endswith(".metadata.json")
        )
        manifest_keys = sorted(
            str(item["key"])
            for item in objects
            if str(item.get("key") or "").endswith(".avro")
        )
        if len(data_keys) != 1 or not metadata_keys or not manifest_keys:
            raise RealFeatureIngestionError("direct S3 Iceberg object classes are incomplete")
        latest_key = metadata_keys[-1]
        response = client.get_object(Bucket=profile.target.bucket, Key=latest_key)
        body = response["Body"].read()
        metadata = json.loads(body)
        if not isinstance(metadata, dict):
            raise TypeError("Iceberg metadata must be an object")
        current_schema_id = metadata.get("current-schema-id")
        current_schema = next(
            (
                _mapping(item)
                for item in _list(metadata.get("schemas"))
                if _mapping(item).get("schema-id") == current_schema_id
            ),
            {},
        )
        fields = tuple(
            {
                "name": _mapping(item).get("name"),
                "required": _mapping(item).get("required"),
                "type": _mapping(item).get("type"),
            }
            for item in _list(current_schema.get("fields"))
        )
        if (
            fields != ICEBERG_FIELDS
            or metadata.get("location") != profile.target.table_location
            or metadata.get("current-snapshot-id") is None
        ):
            raise RealFeatureIngestionError("direct S3 Iceberg metadata drifted")
        return {
            "bucket": profile.target.bucket,
            "prefix": profile.target.object_prefix,
            "object_count": len(objects),
            "objects": objects,
            "object_inventory_sha256": canonical_json_fingerprint(objects),
            "data_keys": data_keys,
            "metadata_keys": metadata_keys,
            "manifest_keys": manifest_keys,
            "latest_metadata": {
                "key": latest_key,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
                "location": metadata.get("location"),
                "current_snapshot_id": metadata.get("current-snapshot-id"),
                "current_schema_id": current_schema_id,
                "fields": list(fields),
            },
            "source_feature_payload_recorded": False,
            "material_recorded": False,
        }
    finally:
        client.close()


def build_output_contracts(
    plan: RealFeatureIngestionPlan,
    spark: Mapping[str, Any],
    store: Mapping[str, Any],
    *,
    created_at: datetime,
) -> dict[str, Any]:
    result = _mapping(spark.get("result"))
    quality_metrics = dict(_mapping(result.get("quality")))
    first = _mapping(result.get("first_execution"))
    snapshots = _list(first.get("snapshots"))
    snapshot_id = _mapping(snapshots[0]).get("snapshot_id") if snapshots else None
    output = ResourceVersion(
        tenant_id=TENANT,
        resource_urn=OUTPUT_RESOURCE_URN,
        resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
        version_key=f"rows-{plan.output_content_sha256[:12]}",
        content_sha256=plan.output_content_sha256,
        authority_version_ref={
            "catalog": plan.target.catalog,
            "schema": plan.target.schema_name,
            "table": plan.target.table,
            "snapshot_id": snapshot_id,
            "row_set_sha256": plan.row_set_sha256,
        },
        created_by=WORKLOAD,
        created_at=created_at,
    )
    data_objects = [
        item
        for item in _list(store.get("objects"))
        if str(_mapping(item).get("key") or "").endswith(".parquet")
    ]
    output_artifact_id = uuid5(RUN_ID, f"output:{plan.output_content_sha256}")
    output_artifact = Artifact(
        tenant_id=TENANT,
        artifact_id=output_artifact_id,
        artifact_key=f"cultural-districts-iceberg:{output_artifact_id}",
        artifact_role=ArtifactRole.OUTPUT,
        storage_uri=plan.target.table_location,
        media_type="application/vnd.apache.iceberg.table",
        content_sha256=plan.output_content_sha256,
        size_bytes=sum(int(_mapping(item).get("size") or 0) for item in data_objects),
        run_id=RUN_ID,
        resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
        manifest={
            "snapshot_id": snapshot_id,
            "row_set_sha256": plan.row_set_sha256,
            "feature_count": plan.expected_feature_count,
            "data_file_count": len(data_objects),
        },
        created_by=WORKLOAD,
        created_at=created_at,
    )
    latest = _mapping(store.get("latest_metadata"))
    quality_artifact_id = uuid5(RUN_ID, f"quality-evidence:{latest.get('body_sha256')}")
    quality_artifact = Artifact(
        tenant_id=TENANT,
        artifact_id=quality_artifact_id,
        artifact_key=f"real-feature-quality:{quality_artifact_id}",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri=f"s3://{plan.target.bucket}/{latest.get('key')}",
        media_type="application/vnd.apache.iceberg+json",
        content_sha256=str(latest.get("body_sha256")),
        size_bytes=int(latest.get("size_bytes") or 0),
        run_id=RUN_ID,
        resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
        manifest={
            "rule_version_ref": "quality://gda/spatial/real-feature-ingestion/v1",
            "metrics": quality_metrics,
            "row_set_sha256": plan.row_set_sha256,
        },
        created_by=WORKLOAD,
        created_at=created_at,
    )
    evaluated_at = created_at + timedelta(seconds=1)
    quality_sha = quality_result_fingerprint(
        tenant_id=TENANT,
        run_id=RUN_ID,
        resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
        rule_version_ref="quality://gda/spatial/real-feature-ingestion/v1",
        verdict=QualityVerdict.PASSED,
        metrics=quality_metrics,
        evidence_artifact_id=quality_artifact_id,
        evaluated_by=QUALITY_EVALUATOR,
        evaluated_at=evaluated_at,
    )
    quality = QualityResult(
        tenant_id=TENANT,
        quality_result_id=uuid5(RUN_ID, f"quality:{quality_sha}"),
        run_id=RUN_ID,
        resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
        rule_version_ref="quality://gda/spatial/real-feature-ingestion/v1",
        verdict=QualityVerdict.PASSED,
        metrics=quality_metrics,
        evidence_artifact_id=quality_artifact_id,
        result_sha256=quality_sha,
        evaluated_by=QUALITY_EVALUATOR,
        evaluated_at=evaluated_at,
    )
    lineage_values = {
        "event_type": LineageEventType.DERIVE.value,
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "target_resource_version_id": str(OUTPUT_RESOURCE_VERSION_ID),
        "run_id": str(RUN_ID),
        "definition_version_id": str(DEFINITION_VERSION_ID),
        "artifact_id": str(output_artifact_id),
        "producer": WORKLOAD,
        "facets": {
            "row_set_sha256": plan.row_set_sha256,
            "snapshot_id": snapshot_id,
            "feature_count": plan.expected_feature_count,
        },
        "occurred_at": created_at.isoformat().replace("+00:00", "Z"),
    }
    lineage_sha = canonical_json_fingerprint(lineage_values)
    lineage = LineageEvent(
        tenant_id=TENANT,
        lineage_event_id=uuid5(RUN_ID, f"lineage:{lineage_sha}"),
        event_type=LineageEventType.DERIVE,
        source_resource_version_id=SOURCE_RESOURCE_VERSION_ID,
        target_resource_version_id=OUTPUT_RESOURCE_VERSION_ID,
        producer=WORKLOAD,
        event_sha256=lineage_sha,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_VERSION_ID,
        artifact_id=output_artifact_id,
        facets=lineage_values["facets"],
        occurred_at=created_at,
    )
    return {
        "output_resource_version": output.model_dump(mode="json"),
        "output_artifact": output_artifact.model_dump(mode="json"),
        "quality_evidence_artifact": quality_artifact.model_dump(mode="json"),
        "quality_result": quality.model_dump(mode="json"),
        "lineage_event": lineage.model_dump(mode="json"),
        "persisted_to_gda_control": False,
    }


def _spark_errors(
    spark: Mapping[str, Any],
    plan: RealFeatureIngestionPlan,
    source: Mapping[str, Any],
    *,
    expected_authorization_sha256: str,
) -> list[str]:
    errors: list[str] = []
    pod = _mapping(spark.get("pod"))
    result = _mapping(spark.get("result"))
    first = _mapping(result.get("first_execution"))
    replay_result = _mapping(result.get("immediate_replay"))
    expected_hashes = _list(_mapping(source.get("projection")).get("row_sha256"))
    quality = _mapping(result.get("quality"))
    if (
        spark.get("wait_completed") is not True
        or spark.get("terminal_condition") != "Complete"
        or _mapping(spark.get("job")).get("succeeded") != 1
        or _mapping(spark.get("job")).get("failed") != 0
        or spark.get("result_line_count") != 1
        or spark.get("failure_diagnostic") != []
    ):
        errors.append("real feature Spark Job did not complete exactly once")
    if (
        pod.get("node_name") != "desktop-worker"
        or pod.get("service_account") != "spark-object-store-probe"
        or pod.get("service_account_automount_disabled") is not True
        or pod.get("persistent_volume_claims") != []
    ):
        errors.append("real feature Spark execution boundary does not match")
    if (
        result.get("schema") != PROBE_RESULT_SCHEMA
        or result.get("plan_sha256") != plan.ingestion_plan_sha256
        or result.get("source_resource_version_id") != str(SOURCE_RESOURCE_VERSION_ID)
        or result.get("source_content_sha256") != plan.source_content_sha256
        or result.get("output_resource_version_id") != str(OUTPUT_RESOURCE_VERSION_ID)
        or result.get("output_content_sha256") != plan.output_content_sha256
        or result.get("row_set_sha256") != plan.row_set_sha256
        or result.get("spark_version") != "3.5.0"
        or result.get("sedona_version") != "1.9.0"
        or result.get("iceberg_runtime") != "1.6.1"
        or tuple(result.get("table_columns") or ()) != SPARK_COLUMNS
        or result.get("source_payload_recorded") is not False
        or result.get("material_recorded") is not False
    ):
        errors.append("real feature Spark result binding does not match")
    if any(
        quality.get(key) != plan.expected_feature_count
        for key in (
            "feature_count",
            "unique_bsm_count",
            "valid_geometry_count",
            "srid_match_count",
            "positive_area_count",
            "bbox_match_count",
        )
    ):
        errors.append("Sedona spatial quality gate did not verify every feature")
    if (
        first.get("status") != "appended"
        or first.get("mutation_count") != 1
        or replay_result.get("status") != "no_op"
        or replay_result.get("mutation_count") != 0
        or first.get("row_sha256") != expected_hashes
        or replay_result.get("row_sha256") != expected_hashes
        or first.get("snapshots") != replay_result.get("snapshots")
        or first.get("data_files") != replay_result.get("data_files")
        or len(_list(first.get("snapshots"))) != 1
        or len(_list(first.get("data_files"))) != 1
    ):
        errors.append("real feature ingestion replay is not an exact no-op")
    if result.get("authorization_sha256") != expected_authorization_sha256:
        errors.append("real feature Spark result is not authorization-bound")
    return errors


def _object_store_errors(
    store: Mapping[str, Any],
    spark: Mapping[str, Any],
    profile: RealFeatureIngestionProfile,
) -> list[str]:
    errors: list[str] = []
    result = _mapping(spark.get("result"))
    first = _mapping(result.get("first_execution"))
    snapshots = _list(first.get("snapshots"))
    data_files = _list(first.get("data_files"))
    expected_data_keys = sorted(
        str(_mapping(item).get("file_path") or "").removeprefix(
            f"s3://{profile.target.bucket}/"
        )
        for item in data_files
    )
    if (
        store.get("bucket") != profile.target.bucket
        or store.get("prefix") != profile.target.object_prefix
        or store.get("data_keys") != expected_data_keys
        or len(_list(store.get("data_keys"))) != 1
        or not store.get("metadata_keys")
        or not store.get("manifest_keys")
        or _mapping(store.get("latest_metadata")).get("location")
        != profile.target.table_location
        or tuple(_mapping(store.get("latest_metadata")).get("fields") or ())
        != ICEBERG_FIELDS
        or not snapshots
        or _mapping(store.get("latest_metadata")).get("current_snapshot_id")
        != _mapping(snapshots[0]).get("snapshot_id")
        or store.get("source_feature_payload_recorded") is not False
        or store.get("material_recorded") is not False
    ):
        errors.append("direct S3 Iceberg data projection does not match Spark readback")
    return errors


def build_evidence(
    observation: Mapping[str, Any],
    *,
    profile: RealFeatureIngestionProfile,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        replay._reject_sensitive_fields(observation)
    except ValueError:
        errors.append("real feature observation contains sensitive material")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("real feature observation schema does not match")
    contract = build_contract_report()
    if _mapping(observation.get("contract")).get("contract_sha256") != contract.get(
        "contract_sha256"
    ):
        errors.append("real feature contract binding does not match")
    dataset = dict(_mapping(observation.get("dataset_bundle")))
    errors.extend(validate_shapefile_bundle_inventory(dataset))
    try:
        plan = RealFeatureIngestionPlan.model_validate(observation.get("plan"))
    except ValueError:
        errors.append("real feature ingestion plan is invalid")
        plan = None
    source = _mapping(observation.get("source_projection"))
    authorization = _mapping(observation.get("authorization"))
    if plan is not None:
        if (
            plan.source_content_sha256 != dataset.get("content_sha256")
            or source.get("feature_count") != plan.expected_feature_count
            or source.get("unique_identifier_count") != plan.expected_feature_count
            or source.get("valid_geometry_count") != plan.expected_feature_count
            or source.get("non_empty_geometry_count") != plan.expected_feature_count
            or source.get("geometry_z_count") != plan.expected_feature_count
            or source.get("srid") != 4490
            or source.get("row_set_sha256") != plan.row_set_sha256
            or len(_list(source.get("row_sha256"))) != plan.expected_feature_count
            or source.get("source_payload_recorded") is not False
        ):
            errors.append("real feature source projection does not match the plan")
        errors.extend(
            _spark_errors(
                _mapping(observation.get("spark")),
                plan,
                {"projection": source},
                expected_authorization_sha256=str(
                    authorization.get("authorization_sha256") or ""
                ),
            )
        )
        errors.extend(
            _object_store_errors(
                _mapping(observation.get("object_store")),
                _mapping(observation.get("spark")),
                profile,
            )
        )
    if (
        authorization.get("action") != ACTION
        or authorization.get("provider_apply_authorized") is not True
        or not authorization.get("authorization_sha256")
    ):
        errors.append("real feature ingestion authorization is incomplete")
    table_create = _mapping(observation.get("table_create"))
    if (
        table_create.get("status") != "created"
        or table_create.get("mutation_count") != 1
        or table_create.get("mutations") != ["gravitino.table.create"]
        or table_create.get("source_binding_verified") is not True
    ):
        errors.append("real feature target table was not created exactly once")
    contracts = _mapping(observation.get("output_contracts"))
    try:
        output = ResourceVersion.model_validate(contracts.get("output_resource_version"))
        output_artifact = Artifact.model_validate(contracts.get("output_artifact"))
        quality_artifact = Artifact.model_validate(contracts.get("quality_evidence_artifact"))
        quality = QualityResult.model_validate(contracts.get("quality_result"))
        lineage = LineageEvent.model_validate(contracts.get("lineage_event"))
        if (
            plan is None
            or output.resource_version_id != OUTPUT_RESOURCE_VERSION_ID
            or output.content_sha256 != plan.output_content_sha256
            or output_artifact.resource_version_id != OUTPUT_RESOURCE_VERSION_ID
            or output_artifact.content_sha256 != plan.output_content_sha256
            or quality.evidence_artifact_id != quality_artifact.artifact_id
            or quality.resource_version_id != OUTPUT_RESOURCE_VERSION_ID
            or quality.verdict != QualityVerdict.PASSED
            or quality.evaluated_by == WORKLOAD
            or lineage.event_type != LineageEventType.DERIVE
            or lineage.source_resource_version_id != SOURCE_RESOURCE_VERSION_ID
            or lineage.target_resource_version_id != OUTPUT_RESOURCE_VERSION_ID
            or lineage.artifact_id != output_artifact.artifact_id
            or contracts.get("persisted_to_gda_control") is not False
        ):
            errors.append("real feature output/quality/lineage contracts drifted")
    except ValueError:
        errors.append("real feature output contracts are invalid")
    runtime = _mapping(observation.get("runtime_checks"))
    if (
        runtime.get("all_runtime_port_forwards_stopped") is not True
        or runtime.get("namespace_delete_completed") is not True
        or runtime.get("namespace_absent") is not True
        or runtime.get("persistent_volumes_absent") is not True
        or runtime.get("provider_objects_retained") is not False
        or runtime.get("object_store_objects_retained") is not False
        or runtime.get("material_recorded") is not False
    ):
        errors.append("real feature ingestion runtime cleanup is incomplete")
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_docker_desktop",
        "status": "local_real_feature_ingestion_verified" if verified else "blocked",
        "contract_sha256": contract.get("contract_sha256"),
        "m321_evidence_sha256": M321_EVIDENCE_SHA256,
        "m310_evidence_fingerprint": M310_EVIDENCE_FINGERPRINT,
        "dataset_bundle": dataset,
        "source_projection": dict(source),
        "source_resource_version_id": str(SOURCE_RESOURCE_VERSION_ID),
        "output_resource_version_id": str(OUTPUT_RESOURCE_VERSION_ID),
        "predecessor_promotion_candidate_sha256": (
            plan.predecessor_promotion_candidate_sha256 if plan else None
        ),
        "local_real_feature_ingestion_verified": verified,
        "real_dataset_resource_version_bound": verified,
        "authorized_spark_execution_verified": verified,
        "sedona_spatial_quality_verified": verified,
        "iceberg_single_snapshot_verified": verified,
        "exact_ingestion_replay_no_op_verified": verified,
        "direct_object_store_data_verified": verified,
        "path_free_lineage_candidate_verified": verified,
        **{claim: False for claim in FALSE_CLAIMS},
        "observation": dict(observation),
        "errors": errors,
    }
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def verify_evidence_integrity(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        replay._reject_sensitive_fields(evidence)
    except ValueError:
        errors.append("real feature evidence contains sensitive material")
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("real feature evidence SHA-256 does not match")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("errors") != []:
        errors.append("real feature evidence is not verified")
    for claim in (
        "local_real_feature_ingestion_verified",
        "real_dataset_resource_version_bound",
        "authorized_spark_execution_verified",
        "sedona_spatial_quality_verified",
        "iceberg_single_snapshot_verified",
        "exact_ingestion_replay_no_op_verified",
        "direct_object_store_data_verified",
        "path_free_lineage_candidate_verified",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"real feature evidence claim is false: {claim}")
    for claim in FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"real feature evidence may not claim {claim}")
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    for forbidden in (
        "/Users/",
        "/home/",
        "Downloads/",
        ".tmp/",
        "geometry_wkb_hex",
        '"rows"',
        '"password"',
        '"secret"',
        '"token"',
        '"access_key"',
        '"access-key"',
    ):
        if forbidden in serialized:
            errors.append("real feature evidence contains source or secret material")
            break
    return errors


def run_live_rehearsal(
    *,
    profile_path: Path,
    shapefile_path: Path,
    ogrinfo_path: Path,
    proj_data_path: Path | None,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    predecessor, runtime_profile = _load_dependencies(profile)
    contract = build_contract_report(profile_path=profile_path)
    if contract.get("status") != "valid":
        raise RealFeatureIngestionError("real feature static contract is invalid")
    source = build_source_input(
        profile,
        predecessor,
        shapefile_path=shapefile_path,
        ogrinfo_path=ogrinfo_path,
        proj_data_path=proj_data_path,
    )
    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    user_material = SecretStr(secrets.token_urlsafe(24))
    object_store_user = SecretStr("gda" + secrets.token_hex(8))
    object_store_material = SecretStr(secrets.token_urlsafe(32))
    runtime = m310.IsolatedSparkObjectStoreRuntime(runtime_profile)
    object_forward: Any = None
    gravitino_forward: Any = None
    rehearsal: m321.ObjectStoreProjectionRehearsal | None = None
    object_forward_stopped = False
    gravitino_forward_stopped = False
    cleanup = {
        "namespace_delete_completed": False,
        "namespace_absent": False,
        "persistent_volumes_absent": False,
        "provider_objects_retained": True,
        "object_store_objects_retained": True,
    }
    initial_runtime: dict[str, Any] | None = None
    object_store_prepared: dict[str, Any] | None = None
    plan: RealFeatureIngestionPlan | None = None
    authorization: tuple[PlatformRun, Artifact, Artifact, Artifact, str] | None = None
    bootstrap: dict[str, Any] | None = None
    table_create: dict[str, Any] | None = None
    spark: dict[str, Any] | None = None
    store: dict[str, Any] | None = None
    output_contracts: dict[str, Any] | None = None
    runtime_binding: dict[str, Any] | None = None
    cluster_uid: str | None = None
    authorized_at: datetime | None = None
    try:
        initial_runtime = runtime.start(
            admin_material=admin_material,
            database_material=database_material,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        cluster = runtime.kubectl.get_json(
            ["get", "namespace", "kube-system"],
            label="real feature cluster identity",
        )
        cluster_uid = str(_mapping(_mapping(cluster).get("metadata")).get("uid"))
        runtime_binding = m321._provider_runtime_binding(
            initial_runtime,
            cluster_uid=cluster_uid,
            target=profile.target,
        )
        plan = build_ingestion_plan(profile, predecessor, source, runtime_binding)
        authorized_at = datetime.now(UTC)
        authorization = build_ingestion_authorization(
            plan,
            profile,
            authorized_at=authorized_at,
        )
        validate_ingestion_authorization(plan, authorization, at=authorized_at)

        object_forward = m321.provider_metrics._PortForward(
            kubectl="kubectl",
            context=runtime_profile.cluster.context,
            namespace=runtime_profile.cluster.rehearsal_namespace,
            service=runtime_profile.runtime.object_store_service,
            target_port=runtime_profile.runtime.object_store_service_port,
        )
        object_forward.start()
        endpoint = f"http://127.0.0.1:{object_forward.local_port}"
        object_store_prepared = runtime.prepare_object_store(
            endpoint_url=endpoint,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )

        gravitino_forward = m321.provider_metrics._PortForward(
            kubectl="kubectl",
            context=runtime_profile.cluster.context,
            namespace=runtime_profile.cluster.rehearsal_namespace,
            service=runtime_profile.runtime.service,
            target_port=runtime_profile.runtime.gravitino_service_port,
        )
        gravitino_forward.start()
        rehearsal = m321.ObjectStoreProjectionRehearsal(
            base_url=f"http://127.0.0.1:{gravitino_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        bootstrap = rehearsal.bootstrap(
            profile,
            database_material=database_material,
            user_material=user_material,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        table_create = create_target_table(rehearsal, profile, plan)
        rehearsal.close()
        rehearsal = None
        gravitino_forward_stopped = gravitino_forward.stop()
        gravitino_forward = None

        run, execution_plan, policy, approval, auth_sha = authorization
        input_payload = {
            **dict(_mapping(source.get("payload"))),
            "plan_sha256": plan.ingestion_plan_sha256,
            "authorization_sha256": auth_sha,
        }
        spark = _run_spark_ingestion(runtime, input_payload=input_payload)
        store = observe_ingested_table(
            runtime,
            profile,
            endpoint_url=endpoint,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        output_contracts = build_output_contracts(
            plan,
            spark,
            store,
            created_at=datetime.now(UTC),
        )
    finally:
        if rehearsal is not None:
            rehearsal.close()
        if gravitino_forward is not None:
            gravitino_forward_stopped = gravitino_forward.stop()
        if object_forward is not None:
            object_forward_stopped = object_forward.stop()
        cleanup = runtime.cleanup()
    required = (
        initial_runtime,
        object_store_prepared,
        plan,
        authorization,
        bootstrap,
        table_create,
        spark,
        store,
        output_contracts,
        runtime_binding,
        cluster_uid,
        authorized_at,
    )
    if any(item is None for item in required):
        raise RealFeatureIngestionError("real feature rehearsal outcome is incomplete")
    assert plan is not None and authorization is not None
    run, execution_plan, policy, approval, auth_sha = authorization
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_sha256": contract["contract_sha256"],
            "m321_evidence_sha256": M321_EVIDENCE_SHA256,
            "m310_evidence_fingerprint": M310_EVIDENCE_FINGERPRINT,
        },
        "dataset_bundle": source["inventory"],
        "source_projection": source["projection"],
        "cluster_uid": cluster_uid,
        "runtime_binding": runtime_binding,
        "runtime_binding_sha256": canonical_json_fingerprint(runtime_binding),
        "initial_runtime": initial_runtime,
        "object_store_prepared": object_store_prepared,
        "plan": plan.model_dump(mode="json", by_alias=True),
        "authorization": {
            "action": ACTION,
            "provider_apply_authorized": True,
            "authorization_sha256": auth_sha,
            "run_id": str(run.run_id),
            "execution_plan_artifact_id": str(execution_plan.artifact_id),
            "policy_decision_artifact_id": str(policy.artifact_id),
            "approval_artifact_id": str(approval.artifact_id),
        },
        "bootstrap": bootstrap,
        "table_create": table_create,
        "spark": spark,
        "object_store": store,
        "output_contracts": output_contracts,
        "runtime_checks": {
            **cleanup,
            "all_runtime_port_forwards_stopped": (
                object_forward_stopped and gravitino_forward_stopped
            ),
            "material_recorded": False,
        },
    }
    return build_evidence(observation, profile=profile)


def build_validation_report(
    *,
    profile_path: Path = DEFAULT_PROFILE_PATH,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
) -> dict[str, Any]:
    contract = build_contract_report(profile_path=profile_path)
    errors = list(contract["errors"])
    evidence: dict[str, Any] | None = None
    try:
        evidence = _load_json_object(evidence_path)
        errors.extend(verify_evidence_integrity(evidence))
        observed_contract = _mapping(_mapping(evidence.get("observation")).get("contract"))
        if observed_contract.get("contract_sha256") != contract.get("contract_sha256"):
            errors.append("real feature evidence contract SHA drift")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"real feature evidence is invalid: {type(exc).__name__}")
    verified = not errors
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if verified else "invalid",
        "local_static_contract_verified": contract["local_static_contract_verified"],
        "local_real_feature_ingestion_verified": (
            verified
            and evidence is not None
            and evidence.get("local_real_feature_ingestion_verified") is True
        ),
        "sedona_spatial_quality_verified": (
            verified
            and evidence is not None
            and evidence.get("sedona_spatial_quality_verified") is True
        ),
        "exact_ingestion_replay_no_op_verified": (
            verified
            and evidence is not None
            and evidence.get("exact_ingestion_replay_no_op_verified") is True
        ),
        "ingestion_persisted_to_gda_control": False,
        "protected_workload_identity_verified": False,
        "production_object_store_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "contract_sha256": contract["contract_sha256"],
        "evidence_sha256": evidence.get("evidence_sha256") if evidence else None,
        "errors": errors,
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    validate.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    contract = subparsers.add_parser("contract")
    contract.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    live = subparsers.add_parser("live")
    live.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    live.add_argument("--shapefile", type=Path, required=True)
    live.add_argument("--ogrinfo", type=Path, required=True)
    live.add_argument("--proj-data", type=Path)
    live.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE_PATH)
    args = parser.parse_args(argv)
    try:
        if args.command == "contract":
            report = build_contract_report(profile_path=args.profile)
        elif args.command == "live":
            report = run_live_rehearsal(
                profile_path=args.profile,
                shapefile_path=args.shapefile,
                ogrinfo_path=args.ogrinfo,
                proj_data_path=args.proj_data,
            )
            _write_json(args.output, report)
        else:
            report = build_validation_report(
                profile_path=args.profile,
                evidence_path=args.evidence,
            )
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report.get("errors") else 1
    except (
        OSError,
        TypeError,
        ValueError,
        RealFeatureIngestionError,
        m310.MetadataFabricSparkObjectStoreInteroperabilityError,
        m310.identity.MetadataFabricGravitinoIdentityError,
        m321.ObjectStoreActiveMetadataPromotionError,
    ) as exc:
        print(f"metadata fabric real feature ingestion: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
