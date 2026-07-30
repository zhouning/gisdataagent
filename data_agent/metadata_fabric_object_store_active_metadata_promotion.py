"""Promote the real Chongqing Active Metadata target into a JDBC/S3 runtime.

M3-21 consumes the checked M3-20 runtime-bound promotion and M3-10 cross-node
object-store evidence. It creates a new Gravitino projection in a JDBC catalog
whose Iceberg warehouse is MinIO rather than a shared filesystem. The provider
projection and the direct S3 metadata must remain unchanged across ordered
PostgreSQL and Gravitino restarts.

The result is local evidence only. It does not change predecessor history,
persist a promotion to GDA Control, ingest source feature rows, or establish
production object-store durability, protected identity, or readiness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from uuid import UUID, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from . import metadata_fabric_active_metadata_projection_execution as execution
from . import metadata_fabric_bridge as bridge
from . import metadata_fabric_durable_active_metadata_promotion as durable
from . import metadata_fabric_gravitino_identity as identity
from . import metadata_fabric_ingestion_replay as replay
from . import metadata_fabric_provider_metrics as provider_metrics
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
    PlatformRun,
    PolicyDecision,
    RunPolicyReferences,
    SubjectContext,
    canonical_json_bytes,
    canonical_json_fingerprint,
)
from .spatial_dataset_bundle import validate_shapefile_bundle_inventory

PROFILE_SCHEMA = "gda.object_store_active_metadata_promotion_profile.v1"
PLAN_SCHEMA = "gda.object_store_active_metadata_projection_plan.v1"
PROMOTION_SCHEMA = "gda.object_store_runtime_bound_metadata_promotion_candidate.v1"
CONTRACT_SCHEMA = "gda.object_store_active_metadata_promotion_contract.v1"
OBSERVATION_SCHEMA = "gda.object_store_active_metadata_promotion_observation.v1"
EVIDENCE_SCHEMA = "gda.object_store_active_metadata_promotion_evidence.v1"
VALIDATION_SCHEMA = "gda.object_store_active_metadata_promotion_validation.v1"
RUNTIME_BINDING_SCHEMA = "gda.object_store_provider_runtime_binding.v1"
ACTION = "metadata_fabric.promote_object_store_projection"
TENANT = durable.TENANT
RESOURCE_VERSION_ID = durable.RESOURCE_VERSION_ID
DEFINITION_ID = UUID("a9000000-0000-4000-8000-000000000006")
RUN_ID = UUID("a9000000-0000-4000-8000-000000000007")
WORKLOAD = "workload:object-store-active-metadata-promoter"
M320_EVIDENCE_SHA256 = "53773e9417668e03ad3ab2b5c3cdbd627fb3bc397d63c5860755ec5318eebe8b"
M310_EVIDENCE_FINGERPRINT = "05844457efb378581fb7fc2e7ed3c706819b2d8fa5a52b2f82577051d38c2cd1"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-object-store-active-metadata-promotion.local.yaml"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-object-store-active-metadata-promotion-2026-07-31.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-object-store-active-metadata-promotion.sh"
)
FALSE_CLAIMS = (
    "predecessor_history_changed",
    "promotion_persisted_to_gda_control",
    "dataset_source_committed",
    "dataset_absolute_path_committed",
    "dataset_required_in_ci",
    "deployment_applied",
    "source_feature_rows_ingested",
    "protected_workload_identity_verified",
    "provider_minimum_privilege_verified",
    "durable_catalog_verified",
    "production_object_store_verified",
    "oidc_verified",
    "tls_verified",
    "production_scheduler_submission_verified",
    "production_ingestion_verified",
    "spark_conformance_verified",
    "flink_conformance_verified",
    "platform_run_succeeded",
    "production_ready",
)


class ObjectStoreActiveMetadataPromotionError(RuntimeError):
    """The JDBC/S3 Active Metadata promotion failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DependencyProfile(_FrozenModel):
    m320_profile_path: str
    m320_evidence_path: str
    m320_evidence_sha256: Literal[M320_EVIDENCE_SHA256]
    m310_profile_path: str
    m310_evidence_path: str
    m310_evidence_fingerprint: Literal[M310_EVIDENCE_FINGERPRINT]


class ObjectStoreTarget(_FrozenModel):
    metalake: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
    catalog: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
    schema_name: str = Field(alias="schema", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
    table: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
    catalog_type: Literal["RELATIONAL"]
    catalog_provider: Literal["lakehouse-iceberg"]
    catalog_backend: Literal["jdbc"]
    uri: Literal["jdbc:postgresql://gravitino-persistence-postgresql:5432/iceberg"]
    warehouse: Literal["s3://gda-metadata-warehouse/warehouse"]
    jdbc_driver: Literal["org.postgresql.Driver"]
    io_impl: Literal["org.apache.iceberg.aws.s3.S3FileIO"]
    s3_endpoint: Literal["http://metadata-object-store:9000"]
    s3_region: Literal["us-east-1"]
    s3_path_style_access: Literal[True]
    bucket: Literal["gda-metadata-warehouse"]
    object_prefix: Literal["warehouse/cultural_heritage/cultural_districts/"]

    @property
    def identity(self) -> str:
        return f"{self.metalake}/{self.catalog}/{self.schema_name}/{self.table}"

    @property
    def table_location(self) -> str:
        return f"s3://{self.bucket}/{self.object_prefix.rstrip('/')}"


class IdentityProfile(_FrozenModel):
    service_admin: Literal["gda-object-store-admin"]
    user: Literal["gda-object-store-active-metadata-promoter"]
    role: Literal["gda-object-store-cultural-district-projector"]
    material_delivery: Literal["runtime_generated_ephemeral_kubernetes_object"]


class AuthorizationProfile(_FrozenModel):
    policy_version_ref: str
    evaluator_subject: Literal["workload:object-store-metadata-policy-evaluator"]
    approver_subject: Literal["human:metadata-platform-owner"]
    approval_reason: str


class ClaimProfile(_FrozenModel):
    predecessor_history_changed: Literal[False]
    promotion_persisted_to_gda_control: Literal[False]
    protected_workload_identity_verified: Literal[False]
    provider_minimum_privilege_verified: Literal[False]
    durable_catalog_verified: Literal[False]
    production_object_store_verified: Literal[False]
    oidc_verified: Literal[False]
    tls_verified: Literal[False]
    production_ingestion_verified: Literal[False]
    production_ready: Literal[False]


class ObjectStorePromotionProfile(_FrozenModel):
    profile_schema: Literal[PROFILE_SCHEMA] = Field(alias="schema")
    environment: Literal["local_docker_desktop"]
    dependencies: DependencyProfile
    target: ObjectStoreTarget
    identity: IdentityProfile
    authorization: AuthorizationProfile
    claims: ClaimProfile


def _promotion_candidate_payload(
    *,
    tenant_id: str,
    resource_urn: str,
    resource_version_id: UUID,
    content_sha256: str,
    predecessor_promotion_candidate_sha256: str,
    logical_binding_sha256: str,
    runtime_binding_sha256: str,
    openmetadata_ref: bridge.OpenMetadataTableRef,
    gravitino_ref: bridge.GravitinoTableRef,
) -> dict[str, Any]:
    return {
        "schema": PROMOTION_SCHEMA,
        "tenant_id": tenant_id,
        "resource_urn": resource_urn,
        "resource_version_id": str(resource_version_id),
        "content_sha256": content_sha256,
        "predecessor_promotion_candidate_sha256": (predecessor_promotion_candidate_sha256),
        "logical_binding_sha256": logical_binding_sha256,
        "runtime_binding_sha256": runtime_binding_sha256,
        "openmetadata_ref": openmetadata_ref.model_dump(mode="json"),
        "gravitino_ref": gravitino_ref.model_dump(mode="json"),
        "predecessor_history_changed": False,
        "persisted_to_gda_control": False,
    }


class ObjectStoreProjectionPlan(_FrozenModel):
    plan_schema: Literal[PLAN_SCHEMA] = Field(default=PLAN_SCHEMA, alias="schema")
    tenant_id: str
    run_id: UUID
    definition_version_id: UUID
    resource_urn: str
    resource_version_id: UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessor_promotion_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    openmetadata_ref: bridge.OpenMetadataTableRef
    openmetadata_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gravitino_ref: bridge.GravitinoTableRef
    target: ObjectStoreTarget
    runtime_binding: dict[str, Any]
    runtime_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    logical_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    promotion_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    writes_to_gda_control: Literal[False] = False
    writes_to_legacy: Literal[False] = False
    apply_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _fingerprints_match(self) -> ObjectStoreProjectionPlan:
        if self.target.identity != self.gravitino_ref.identity:
            raise ValueError("object-store target does not match Gravitino ref")
        if self.runtime_binding_sha256 != canonical_json_fingerprint(self.runtime_binding):
            raise ValueError("object-store runtime binding fingerprint does not match")
        expected_logical = bridge.metadata_fabric_binding_fingerprint(
            tenant_id=self.tenant_id,
            resource_urn=self.resource_urn,
            resource_version_id=self.resource_version_id,
            content_sha256=self.content_sha256,
            openmetadata=self.openmetadata_ref,
            gravitino=(self.gravitino_ref,),
        )
        if self.logical_binding_sha256 != expected_logical:
            raise ValueError("object-store logical binding fingerprint does not match")
        candidate = _promotion_candidate_payload(
            tenant_id=self.tenant_id,
            resource_urn=self.resource_urn,
            resource_version_id=self.resource_version_id,
            content_sha256=self.content_sha256,
            predecessor_promotion_candidate_sha256=(self.predecessor_promotion_candidate_sha256),
            logical_binding_sha256=self.logical_binding_sha256,
            runtime_binding_sha256=self.runtime_binding_sha256,
            openmetadata_ref=self.openmetadata_ref,
            gravitino_ref=self.gravitino_ref,
        )
        if self.promotion_candidate_sha256 != canonical_json_fingerprint(candidate):
            raise ValueError("object-store promotion candidate fingerprint does not match")
        stable = self.model_dump(mode="json", by_alias=True, exclude={"apply_plan_sha256"})
        if self.apply_plan_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("object-store apply plan fingerprint does not match")
        return self


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ObjectStoreActiveMetadataPromotionError(f"{path.name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ObjectStoreActiveMetadataPromotionError(f"{path.name} must be an object")
    return value


def _resolve_repo_path(value: str) -> Path:
    path = (REPO_ROOT / value).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ObjectStoreActiveMetadataPromotionError(
            "profile dependency path leaves repository"
        ) from exc
    return path


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> ObjectStorePromotionProfile:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("profile must be an object")
        replay._reject_sensitive_fields(value)
        return ObjectStorePromotionProfile.model_validate(value)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ObjectStoreActiveMetadataPromotionError(
            "object-store promotion profile is invalid"
        ) from exc


def _load_dependencies(
    profile: ObjectStorePromotionProfile,
) -> tuple[dict[str, Any], m310.SparkObjectStoreInteroperabilityProfile]:
    dependencies = profile.dependencies
    m320_path = _resolve_repo_path(dependencies.m320_evidence_path)
    m320_evidence = _load_json_object(m320_path)
    m320_validation = durable.build_validation_report(
        profile_path=_resolve_repo_path(dependencies.m320_profile_path),
        evidence_path=m320_path,
    )
    if (
        m320_validation.get("errors")
        or durable.verify_evidence_integrity(m320_evidence)
        or m320_evidence.get("evidence_sha256") != M320_EVIDENCE_SHA256
    ):
        raise ObjectStoreActiveMetadataPromotionError(
            "M3-20 durable promotion evidence does not match"
        )
    m310_path = _resolve_repo_path(dependencies.m310_evidence_path)
    m310_evidence = _load_json_object(m310_path)
    m310_validation = m310.build_validation_report(
        profile_path=_resolve_repo_path(dependencies.m310_profile_path),
        evidence_path=m310_path,
    )
    if (
        m310_validation.get("errors")
        or m310.verify_evidence_integrity(m310_evidence)
        or m310_evidence.get("evidence_fingerprint") != M310_EVIDENCE_FINGERPRINT
    ):
        raise ObjectStoreActiveMetadataPromotionError(
            "M3-10 object-store interoperability evidence does not match"
        )
    return m320_evidence, m310.load_profile(_resolve_repo_path(dependencies.m310_profile_path))


def _file_record(path: Path) -> dict[str, str | None]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest() if resolved.is_file() else None,
    }


def _provider_runtime_binding(
    snapshot: Mapping[str, Any],
    *,
    cluster_uid: str,
    target: ObjectStoreTarget,
) -> dict[str, Any]:
    namespace = _mapping(snapshot.get("namespace"))
    service = _mapping(snapshot.get("service"))
    object_service = _mapping(snapshot.get("object_store_service"))
    postgresql = _mapping(snapshot.get("postgresql"))
    gravitino = _mapping(snapshot.get("gravitino"))
    object_store = _mapping(snapshot.get("object_store"))
    postgresql_pvc = _mapping(postgresql.get("pvc"))
    object_store_pvc = _mapping(object_store.get("pvc"))
    gravitino_claims = gravitino.get("persistent_volume_claims")
    if gravitino.get("pvc") is not None or gravitino_claims != []:
        raise ObjectStoreActiveMetadataPromotionError(
            "Gravitino may not mount an object-store warehouse PVC"
        )
    binding = {
        "schema": RUNTIME_BINDING_SCHEMA,
        "context": snapshot.get("context"),
        "cluster_uid": cluster_uid,
        "namespace": {
            "name": namespace.get("name"),
            "uid": namespace.get("uid"),
        },
        "services": {
            "gravitino": {"name": service.get("name"), "uid": service.get("uid")},
            "object_store": {
                "name": object_service.get("name"),
                "uid": object_service.get("uid"),
            },
        },
        "workloads": {
            "postgresql_statefulset_uid": postgresql.get("statefulset_uid"),
            "gravitino_statefulset_uid": gravitino.get("statefulset_uid"),
            "object_store_statefulset_uid": object_store.get("statefulset_uid"),
        },
        "storage": {
            "postgresql_pvc_uid": postgresql_pvc.get("uid"),
            "postgresql_volume_name": postgresql_pvc.get("volume_name"),
            "object_store_pvc_uid": object_store_pvc.get("uid"),
            "object_store_volume_name": object_store_pvc.get("volume_name"),
            "gravitino_persistent_volume_claims": gravitino_claims,
        },
        "topology": {
            "object_store_node": object_store.get("node_name"),
            "provider_node": gravitino.get("node_name"),
        },
        "images": {
            "postgresql_image_id": postgresql.get("image_id"),
            "gravitino_image_id": gravitino.get("image_id"),
            "object_store_image_id": object_store.get("image_id"),
        },
        "catalog": {
            "backend": target.catalog_backend,
            "uri": target.uri,
            "warehouse": target.warehouse,
            "io_impl": target.io_impl,
            "s3_endpoint": target.s3_endpoint,
            "s3_region": target.s3_region,
            "s3_path_style_access": target.s3_path_style_access,
            "bucket": target.bucket,
        },
    }
    serialized = json.dumps(binding, ensure_ascii=True, sort_keys=True)
    if (
        not cluster_uid
        or "null" in serialized
        or '"uid": ""' in serialized
        or binding["topology"]["object_store_node"] == binding["topology"]["provider_node"]
    ):
        raise ObjectStoreActiveMetadataPromotionError(
            "object-store provider runtime identity is incomplete"
        )
    return binding


def _verify_openmetadata(
    payload: dict[str, Any],
    source: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> bridge.OpenMetadataObservation:
    expected = _mapping(_mapping(source.get("observation")).get("openmetadata"))
    return durable._verify_openmetadata(
        payload,
        {"first_readback": {"openmetadata": dict(expected)}},
        observed_at=observed_at,
    )


def build_projection_plan(
    profile: ObjectStorePromotionProfile,
    source: Mapping[str, Any],
    openmetadata: bridge.OpenMetadataObservation,
    runtime_binding: dict[str, Any],
) -> ObjectStoreProjectionPlan:
    provider_revision = f"shapefile-bundle-{openmetadata.content_sha256[:16]}"
    gravitino_ref = bridge.GravitinoTableRef(
        metalake=profile.target.metalake,
        catalog=profile.target.catalog,
        schema_name=profile.target.schema_name,
        table_name=profile.target.table,
        provider_revision=provider_revision,
        server_version="1.3.0",
    )
    logical_binding_sha256 = bridge.metadata_fabric_binding_fingerprint(
        tenant_id=TENANT,
        resource_urn=openmetadata.resource_urn,
        resource_version_id=openmetadata.resource_version_id,
        content_sha256=openmetadata.content_sha256,
        openmetadata=openmetadata.ref,
        gravitino=(gravitino_ref,),
    )
    runtime_binding_sha256 = canonical_json_fingerprint(runtime_binding)
    predecessor = str(source["promotion_candidate_sha256"])
    candidate = _promotion_candidate_payload(
        tenant_id=TENANT,
        resource_urn=openmetadata.resource_urn,
        resource_version_id=openmetadata.resource_version_id,
        content_sha256=openmetadata.content_sha256,
        predecessor_promotion_candidate_sha256=predecessor,
        logical_binding_sha256=logical_binding_sha256,
        runtime_binding_sha256=runtime_binding_sha256,
        openmetadata_ref=openmetadata.ref,
        gravitino_ref=gravitino_ref,
    )
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_ID,
        "resource_urn": openmetadata.resource_urn,
        "resource_version_id": openmetadata.resource_version_id,
        "content_sha256": openmetadata.content_sha256,
        "predecessor_promotion_candidate_sha256": predecessor,
        "openmetadata_ref": openmetadata.ref,
        "openmetadata_snapshot_sha256": openmetadata.snapshot_sha256,
        "gravitino_ref": gravitino_ref,
        "target": profile.target,
        "runtime_binding": runtime_binding,
        "runtime_binding_sha256": runtime_binding_sha256,
        "logical_binding_sha256": logical_binding_sha256,
        "promotion_candidate_sha256": canonical_json_fingerprint(candidate),
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
    return ObjectStoreProjectionPlan(
        **values,
        apply_plan_sha256=canonical_json_fingerprint(stable),
    )


def _build_execution_plan_artifact(
    plan: ObjectStoreProjectionPlan, *, created_at: datetime
) -> Artifact:
    manifest = {
        "schema": "gda.object_store_active_metadata_execution_plan.v1",
        "plan": plan.model_dump(mode="json", by_alias=True),
    }
    artifact_id = uuid5(RUN_ID, f"object-store-promotion:{plan.apply_plan_sha256}")
    content = canonical_json_bytes(manifest)
    return Artifact(
        tenant_id=TENANT,
        artifact_id=artifact_id,
        artifact_key=f"object-store-active-metadata:{artifact_id}",
        artifact_role=ArtifactRole.EXECUTION_PLAN,
        storage_uri=f"postgresql://gda-control/execution-plans/{TENANT}/{artifact_id}",
        media_type="application/vnd.gda.object-store-active-metadata-plan+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(content),
        run_id=None,
        resource_version_id=DEFINITION_ID,
        manifest=manifest,
        created_by=WORKLOAD,
        created_at=created_at,
    )


def build_apply_authorization(
    plan: ObjectStoreProjectionPlan,
    profile: ObjectStorePromotionProfile,
    *,
    authorized_at: datetime,
) -> tuple[PlatformRun, Artifact, Artifact, Artifact, str]:
    if authorized_at.tzinfo is None or authorized_at.utcoffset() is None:
        raise ObjectStoreActiveMetadataPromotionError(
            "authorization timestamp must include a timezone"
        )
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id=WORKLOAD.removeprefix("workload:"),
        subject_type="workload",
        roles=("metadata_projector",),
        purpose="promote a content-bound projection into a local S3 warehouse",
    )
    execution_plan = _build_execution_plan_artifact(
        plan, created_at=authorized_at - timedelta(seconds=3)
    )
    decision = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=subject,
        action=ACTION,
        definition_version_id=DEFINITION_ID,
        resource_version_ids=(DEFINITION_ID, RESOURCE_VERSION_ID),
        execution_plan_artifact_id=execution_plan.artifact_id,
        effect="allow",
        policy_version_ref=profile.authorization.policy_version_ref,
        evaluator_subject=profile.authorization.evaluator_subject,
        requires_approval=True,
        obligations=(),
        decided_at=authorized_at - timedelta(seconds=3),
        expires_at=authorized_at + timedelta(days=365),
    )
    policy_artifact = build_policy_decision_artifact(decision)
    approval = ApprovalRecord(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
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
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        subject_context=subject,
        input_bindings=(
            {
                "binding_name": "metadata_change",
                "resource_version_id": RESOURCE_VERSION_ID,
                "semantic_type": "gis.cultural_districts",
            },
        ),
        idempotency_key=(f"object-store-active-metadata:{plan.promotion_candidate_sha256}"),
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


def validate_apply_authorization(
    plan: ObjectStoreProjectionPlan,
    authorization: tuple[PlatformRun, Artifact, Artifact, Artifact, str],
    *,
    at: datetime,
) -> None:
    run, execution_plan, policy_artifact, approval_artifact, fingerprint = authorization
    if _mapping(execution_plan.manifest.get("plan")) != plan.model_dump(mode="json", by_alias=True):
        raise ObjectStoreActiveMetadataPromotionError(
            "execution plan artifact does not contain the exact object-store plan"
        )
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
        raise ObjectStoreActiveMetadataPromotionError(
            "object-store apply authorization fingerprint does not match"
        )


def build_contract_report(
    *,
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    profile: ObjectStorePromotionProfile | None = None
    source_sha: str | None = None
    object_store_fingerprint: str | None = None
    try:
        profile = load_profile(profile_path)
        source, _runtime_profile = _load_dependencies(profile)
        source_sha = str(source.get("evidence_sha256"))
        m310_evidence = _load_json_object(
            _resolve_repo_path(profile.dependencies.m310_evidence_path)
        )
        object_store_fingerprint = str(m310_evidence.get("evidence_fingerprint"))
    except ObjectStoreActiveMetadataPromotionError as exc:
        errors.append(f"M3-21 dependency contract is invalid: {type(exc).__name__}")
    try:
        wrapper = wrapper_path.read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_object_store_active_metadata_promotion",
            '"$@"',
        ):
            if marker not in wrapper:
                errors.append(f"M3-21 wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"M3-21 wrapper is invalid: {type(exc).__name__}")
    files = {
        "implementation": _file_record(Path(__file__)),
        "profile": _file_record(profile_path),
        "wrapper": _file_record(wrapper_path),
    }
    stable = {
        "schema": CONTRACT_SCHEMA,
        "source_m320_evidence_sha256": source_sha,
        "m310_evidence_fingerprint": object_store_fingerprint,
        "target_identity": profile.target.identity if profile else None,
        "target_warehouse": profile.target.warehouse if profile else None,
        "target_object_prefix": profile.target.object_prefix if profile else None,
        "runtime_binding_schema": RUNTIME_BINDING_SCHEMA,
        "authorization_action": ACTION,
        "files": files,
        "predecessor_history_changed": False,
        "promotion_persisted_to_gda_control": False,
        "production_object_store_verified": False,
        "production_ready": False,
    }
    return {
        **stable,
        "contract_sha256": canonical_json_fingerprint(stable),
        "local_static_contract_verified": not errors,
        "status": "valid" if not errors else "invalid",
        "errors": errors,
    }


class ObjectStoreProjectionRehearsal(durable.DurableProjectionRehearsal):
    """Bootstrap a JDBC/S3 catalog and apply through one bounded principal."""

    def bootstrap(
        self,
        profile: ObjectStorePromotionProfile,
        *,
        database_material: SecretStr,
        user_material: SecretStr,
        object_store_user: SecretStr,
        object_store_material: SecretStr,
    ) -> dict[str, Any]:
        admin_status, version_payload = self.admin.request(
            "GET", "version", label="object-store promotion admin authentication"
        )
        version = _mapping(_mapping(version_payload).get("version")).get("version")
        if version is None:
            version = _mapping(version_payload).get("version")
        _, metalake_payload = self.admin.request(
            "POST",
            "metalakes",
            json_body={
                "name": profile.target.metalake,
                "comment": "Real Chongqing object-store Active Metadata promotion",
                "properties": {"gda.environment": "local_object_store_promotion"},
            },
            label="object-store promotion metalake create",
        )
        metalake = identity._response_entity(
            metalake_payload, "metalake", "object-store promotion metalake"
        )
        _, catalog_payload = self.admin.request(
            "POST",
            f"metalakes/{quote(profile.target.metalake)}/catalogs",
            json_body={
                "name": profile.target.catalog,
                "type": profile.target.catalog_type,
                "provider": profile.target.catalog_provider,
                "comment": "JDBC catalog with S3-compatible Active Metadata warehouse",
                "properties": {
                    "catalog-backend": profile.target.catalog_backend,
                    "uri": profile.target.uri,
                    "warehouse": profile.target.warehouse,
                    "jdbc-user": "gravitino",
                    "jdbc-password": database_material.get_secret_value(),
                    "gravitino.bypass.jdbc-driver": profile.target.jdbc_driver,
                    "gravitino.bypass.jdbc-initialize": "true",
                    "io-impl": profile.target.io_impl,
                    "s3-access-key-id": object_store_user.get_secret_value(),
                    "s3-secret-access-key": object_store_material.get_secret_value(),
                    "s3-endpoint": profile.target.s3_endpoint,
                    "s3-region": profile.target.s3_region,
                    "s3-path-style-access": "true",
                },
            },
            label="object-store promotion JDBC catalog create",
        )
        catalog = identity._response_entity(
            catalog_payload, "catalog", "object-store promotion catalog"
        )
        _, schema_payload = self.admin.request(
            "POST",
            f"{self._catalog_path(profile.target)}/schemas",
            json_body={
                "name": profile.target.schema_name,
                "comment": "Content-bound cultural heritage projection schema",
                "properties": {},
            },
            label="object-store promotion schema create",
        )
        schema = identity._response_entity(
            schema_payload, "schema", "object-store promotion schema"
        )
        self.admin.request(
            "POST",
            "idp/users",
            json_body={
                "user": profile.identity.user,
                "password": user_material.get_secret_value(),
            },
            label="object-store promotion IdP user create",
        )
        self.admin.request(
            "POST",
            f"metalakes/{quote(profile.target.metalake)}/users",
            json_body={"name": profile.identity.user},
            label="object-store promotion metalake user register",
        )
        self.admin.request(
            "POST",
            f"metalakes/{quote(profile.target.metalake)}/roles",
            json_body={
                "name": profile.identity.role,
                "properties": {"gda.scope": "cultural_district_table_projection"},
                "securableObjects": durable._expected_role(profile),
            },
            label="object-store promotion bounded role create",
        )
        self.admin.request(
            "PUT",
            (
                f"metalakes/{quote(profile.target.metalake)}/permissions/users/"
                f"{quote(profile.identity.user)}/grant"
            ),
            json_body={"roleNames": [profile.identity.role]},
            label="object-store promotion bounded role grant",
        )
        _, role_payload = self.admin.request(
            "GET",
            (f"metalakes/{quote(profile.target.metalake)}/roles/{quote(profile.identity.role)}"),
            label="object-store promotion role readback",
        )
        role = identity._response_entity(
            role_payload, "role", "object-store promotion role readback"
        )
        bounded = self._bounded_api(profile, user_material)
        bounded_status, _ = bounded.request(
            "GET", "version", label="object-store promotion bounded authentication"
        )
        denied_status, _ = bounded.request(
            "POST",
            f"metalakes/{quote(profile.target.metalake)}/catalogs",
            json_body={
                "name": "unauthorized_catalog",
                "type": "RELATIONAL",
                "provider": "lakehouse-iceberg",
                "comment": "must remain denied",
                "properties": {
                    "catalog-backend": "memory",
                    "uri": "file:///tmp/gda-denied",
                    "warehouse": "file:///tmp/gda-denied",
                },
            },
            expected=frozenset({200, 403}),
            label="object-store promotion catalog administration denial",
        )
        return {
            "admin_authentication_status": admin_status,
            "bounded_authentication_status": bounded_status,
            "server_version": version,
            "metalake": metalake.get("name"),
            "catalog": catalog.get("name"),
            "schema": schema.get("name"),
            "catalog_backend": profile.target.catalog_backend,
            "catalog_uri": profile.target.uri,
            "warehouse": profile.target.warehouse,
            "io_impl": profile.target.io_impl,
            "s3_endpoint": profile.target.s3_endpoint,
            "s3_region": profile.target.s3_region,
            "s3_path_style_access": profile.target.s3_path_style_access,
            "bucket": profile.target.bucket,
            "role": {
                "name": role.get("name"),
                "securable_objects": identity._normalize_securable_objects(
                    role.get("securableObjects")
                ),
            },
            "denied_catalog_create_status": denied_status,
            "material_recorded": False,
        }

    def apply_once(
        self,
        plan: ObjectStoreProjectionPlan,
        authorization: tuple[PlatformRun, Artifact, Artifact, Artifact, str],
        *,
        at: datetime,
        create: bool = False,
    ) -> dict[str, Any]:
        validate_apply_authorization(plan, authorization, at=at)
        if self.bounded is None:
            raise ObjectStoreActiveMetadataPromotionError(
                "bounded Gravitino principal is unavailable"
            )
        path = self._table_path(plan.target)
        mutations: list[str] = []
        if create:
            self.bounded.request(
                "POST",
                f"{self._schema_path(plan.target)}/tables",
                json_body={
                    "name": plan.target.table,
                    "comment": "Real Chongqing cultural district object-store projection",
                    "columns": [
                        {
                            "name": "BSM",
                            "type": "string",
                            "nullable": False,
                            "comment": "Cultural district identifier",
                        },
                        {
                            "name": "geometry",
                            "type": "binary",
                            "nullable": False,
                            "comment": "PolygonZ geometry bytes",
                        },
                    ],
                    "properties": {
                        "gda.resource_urn": plan.resource_urn,
                        "gda.resource_version_id": str(plan.resource_version_id),
                        "gda.content_sha256": plan.content_sha256,
                        "gda.provider_revision": plan.gravitino_ref.provider_revision,
                    },
                },
                label="bounded object-store projection table create",
            )
            mutations.append("gravitino.table.create")
        else:
            self.bounded.request("GET", path, label="object-store projection table lookup")
        _, read_payload = self.bounded.request(
            "GET", path, label="object-store projection exact readback"
        )
        assert read_payload is not None
        observation = bridge.parse_gravitino_table_observation(
            plan.gravitino_ref, read_payload, observed_at=at
        )
        if (
            observation.resource_urn != plan.resource_urn
            or observation.resource_version_id != plan.resource_version_id
            or observation.content_sha256 != plan.content_sha256
            or observation.provider_revision != plan.gravitino_ref.provider_revision
        ):
            raise ObjectStoreActiveMetadataPromotionError(
                "object-store Gravitino projection does not match the ResourceVersion"
            )
        projection = durable._table_projection(read_payload)
        expected_projection = {
            "name": plan.target.table,
            "columns": [
                {"name": "BSM", "type": "string", "nullable": False},
                {"name": "geometry", "type": "binary", "nullable": False},
            ],
            "resource_urn": plan.resource_urn,
            "resource_version_id": str(plan.resource_version_id),
            "content_sha256": plan.content_sha256,
            "provider_revision": plan.gravitino_ref.provider_revision,
        }
        if projection != expected_projection:
            raise ObjectStoreActiveMetadataPromotionError(
                "object-store Gravitino table projection drifted"
            )
        return {
            "status": "created" if mutations else "no_op",
            "mutations": mutations,
            "mutation_count": len(mutations),
            "gravitino": {
                "identity": observation.ref.identity,
                "resource_urn": observation.resource_urn,
                "resource_version_id": str(observation.resource_version_id),
                "content_sha256": observation.content_sha256,
                "provider_revision": observation.provider_revision,
                "snapshot_sha256": observation.snapshot_sha256,
            },
            "table_projection": projection,
            "table_projection_sha256": canonical_json_fingerprint(projection),
            "logical_binding_sha256": plan.logical_binding_sha256,
            "promotion_candidate_sha256": plan.promotion_candidate_sha256,
        }


def observe_table_object_store(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
    profile: ObjectStorePromotionProfile,
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
            if not isinstance(continuation, str) or not continuation:
                raise ObjectStoreActiveMetadataPromotionError(
                    "object-store listing continuation is invalid"
                )
        objects.sort(key=lambda item: str(item.get("key")))
        data_keys = sorted(
            str(item["key"]) for item in objects if str(item.get("key") or "").endswith(".parquet")
        )
        metadata_keys = sorted(
            str(item["key"])
            for item in objects
            if str(item.get("key") or "").endswith(".metadata.json")
        )
        manifest_keys = sorted(
            str(item["key"]) for item in objects if str(item.get("key") or "").endswith(".avro")
        )
        if not metadata_keys:
            raise ObjectStoreActiveMetadataPromotionError(
                "object-store Active Metadata table has no Iceberg metadata"
            )
        latest_key = metadata_keys[-1]
        metadata_response = client.get_object(
            Bucket=profile.target.bucket,
            Key=latest_key,
        )
        body = metadata_response["Body"].read()
        metadata = json.loads(body)
        if not isinstance(metadata, dict):
            raise TypeError("Iceberg metadata object must be an object")
        current_schema_id = metadata.get("current-schema-id")
        schemas = metadata.get("schemas")
        schema_items = schemas if isinstance(schemas, list) else []
        current_schema = next(
            (
                _mapping(item)
                for item in schema_items
                if _mapping(item).get("schema-id") == current_schema_id
            ),
            {},
        )
        fields = current_schema.get("fields")
        field_items = fields if isinstance(fields, list) else []
        latest = {
            "key": latest_key,
            "body_sha256": hashlib.sha256(body).hexdigest(),
            "location": metadata.get("location"),
            "current_snapshot_id": metadata.get("current-snapshot-id"),
            "current_schema_id": current_schema_id,
            "fields": [
                {
                    "name": _mapping(item).get("name"),
                    "required": _mapping(item).get("required"),
                    "type": _mapping(item).get("type"),
                }
                for item in field_items
            ],
        }
        expected_fields = [
            {"name": "BSM", "required": True, "type": "string"},
            {"name": "geometry", "required": True, "type": "binary"},
        ]
        if (
            latest["location"] != profile.target.table_location
            or latest["fields"] != expected_fields
            or data_keys
            or manifest_keys
            or any(
                not str(item.get("key") or "").startswith(profile.target.object_prefix)
                for item in objects
            )
        ):
            raise ObjectStoreActiveMetadataPromotionError(
                "direct object-store table metadata does not match the projection"
            )
        return {
            "bucket": profile.target.bucket,
            "prefix": profile.target.object_prefix,
            "object_count": len(objects),
            "objects": objects,
            "data_keys": data_keys,
            "metadata_keys": metadata_keys,
            "manifest_keys": manifest_keys,
            "latest_metadata": latest,
            "source_feature_rows_present": False,
            "material_recorded": False,
        }
    finally:
        client.close()


def restart_provider_runtime(
    runtime: m310.IsolatedSparkObjectStoreRuntime,
) -> dict[str, Any]:
    before = runtime.observe_runtime()
    namespace = runtime.profile.cluster.rehearsal_namespace
    for workload in (
        "statefulset/gravitino-persistence-postgresql",
        "statefulset/gravitino-persistence",
    ):
        runtime.kubectl.run(
            ["-n", namespace, "rollout", "restart", workload],
            label=f"object-store promotion {workload} restart",
        )
        runtime.kubectl.run(
            ["-n", namespace, "rollout", "status", workload, "--timeout=10m"],
            timeout=660,
            label=f"object-store promotion {workload} restart rollout",
        )
    return {"before": before, "after": runtime.observe_runtime()}


def _runtime_continuity_errors(
    restart: Mapping[str, Any],
    runtime_binding: Mapping[str, Any],
    *,
    cluster_uid: str,
    target: ObjectStoreTarget,
) -> list[str]:
    errors: list[str] = []
    before = _mapping(restart.get("before"))
    after = _mapping(restart.get("after"))
    errors.extend(m310._runtime_errors(before))
    errors.extend(m310._runtime_errors(after))
    try:
        before_binding = _provider_runtime_binding(before, cluster_uid=cluster_uid, target=target)
        after_binding = _provider_runtime_binding(after, cluster_uid=cluster_uid, target=target)
    except ObjectStoreActiveMetadataPromotionError:
        errors.append("object-store provider runtime identity is incomplete")
        return errors
    if before_binding != after_binding or dict(runtime_binding) != before_binding:
        errors.append("object-store provider runtime identity changed across restart")
    for workload_name in ("postgresql", "gravitino"):
        old = _mapping(before.get(workload_name))
        new = _mapping(after.get(workload_name))
        if old.get("statefulset_uid") != new.get("statefulset_uid"):
            errors.append(f"{workload_name} StatefulSet identity changed")
        if not old.get("pod_uid") or old.get("pod_uid") == new.get("pod_uid"):
            errors.append(f"{workload_name} pod did not restart")
        if old.get("ready_replicas") != 1 or new.get("ready_replicas") != 1:
            errors.append(f"{workload_name} was not ready around restart")
    old_object_store = _mapping(before.get("object_store"))
    new_object_store = _mapping(after.get("object_store"))
    for key in ("statefulset_uid", "pod_uid", "pvc", "image_id"):
        if old_object_store.get(key) != new_object_store.get(key):
            errors.append(f"object-store runtime changed across provider restart: {key}")
    return errors


def build_evidence(
    observation: Mapping[str, Any],
    *,
    profile: ObjectStorePromotionProfile,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        replay._reject_sensitive_fields(observation)
    except ValueError:
        errors.append("object-store promotion observation contains sensitive material")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("object-store promotion observation schema does not match")
    contract = build_contract_report()
    observed_contract = _mapping(observation.get("contract"))
    if (
        observed_contract.get("contract_sha256") != contract.get("contract_sha256")
        or observed_contract.get("source_m320_evidence_sha256") != M320_EVIDENCE_SHA256
        or observed_contract.get("m310_evidence_fingerprint") != M310_EVIDENCE_FINGERPRINT
    ):
        errors.append("object-store promotion contract binding does not match")
    dataset = _mapping(observation.get("dataset_bundle"))
    errors.extend(validate_shapefile_bundle_inventory(dict(dataset)))
    plan = _mapping(observation.get("plan"))
    target = _mapping(plan.get("target"))
    if (
        plan.get("resource_version_id") != str(RESOURCE_VERSION_ID)
        or plan.get("content_sha256") != dataset.get("content_sha256")
        or plan.get("predecessor_promotion_candidate_sha256")
        != observation.get("predecessor_promotion_candidate_sha256")
        or target.get("metalake") != profile.target.metalake
        or target.get("catalog") != profile.target.catalog
        or target.get("schema") != profile.target.schema_name
        or target.get("table") != profile.target.table
        or target.get("warehouse") != profile.target.warehouse
        or target.get("object_prefix") != profile.target.object_prefix
    ):
        errors.append("object-store plan does not bind the real ResourceVersion")
    runtime_binding = _mapping(observation.get("runtime_binding"))
    if observation.get("runtime_binding_sha256") != canonical_json_fingerprint(runtime_binding):
        errors.append("object-store runtime-bound promotion fingerprint does not match")
    errors.extend(
        _runtime_continuity_errors(
            _mapping(observation.get("restart")),
            runtime_binding,
            cluster_uid=str(observation.get("cluster_uid") or ""),
            target=profile.target,
        )
    )
    openmetadata = _mapping(observation.get("openmetadata"))
    source_openmetadata = _mapping(observation.get("source_m320_openmetadata"))
    if dict(openmetadata) != dict(source_openmetadata):
        errors.append("retained OpenMetadata readback does not match M3-20")
    if observation.get("openmetadata_mutation_count") != 0:
        errors.append("object-store promotion may not mutate retained OpenMetadata")
    bootstrap = _mapping(observation.get("bootstrap"))
    post_security = _mapping(observation.get("post_restart_security"))
    expected_role = identity._normalize_securable_objects(durable._expected_role(profile))
    if (
        bootstrap.get("admin_authentication_status") != 200
        or bootstrap.get("bounded_authentication_status") != 200
        or bootstrap.get("server_version") != "1.3.0"
        or bootstrap.get("catalog_backend") != "jdbc"
        or bootstrap.get("warehouse") != profile.target.warehouse
        or bootstrap.get("io_impl") != profile.target.io_impl
        or bootstrap.get("s3_endpoint") != profile.target.s3_endpoint
        or bootstrap.get("bucket") != profile.target.bucket
        or bootstrap.get("denied_catalog_create_status") != 403
        or _mapping(bootstrap.get("role")).get("securable_objects") != expected_role
        or bootstrap.get("material_recorded") is not False
        or post_security.get("bounded_authentication_status") != 200
        or post_security.get("denied_catalog_create_status") != 403
        or _mapping(post_security.get("role")).get("securable_objects") != expected_role
        or post_security.get("material_recorded") is not False
    ):
        errors.append("bounded object-store Gravitino identity did not survive restart")
    first = _mapping(observation.get("first_apply"))
    immediate = _mapping(observation.get("immediate_replay"))
    post = _mapping(observation.get("post_restart_first_replay"))
    if (
        first.get("status") != "created"
        or first.get("mutation_count") != 1
        or first.get("mutations") != ["gravitino.table.create"]
    ):
        errors.append("first object-store projection apply was not one bounded create")
    for label, result in (("immediate", immediate), ("post-restart", post)):
        if result.get("status") != "no_op" or result.get("mutation_count") != 0:
            errors.append(f"{label} object-store projection replay was not no-op")
    for key in (
        "gravitino",
        "table_projection",
        "table_projection_sha256",
        "logical_binding_sha256",
        "promotion_candidate_sha256",
    ):
        if first.get(key) != immediate.get(key) or first.get(key) != post.get(key):
            errors.append(f"object-store provider projection drifted: {key}")
    if (
        first.get("logical_binding_sha256") != plan.get("logical_binding_sha256")
        or first.get("promotion_candidate_sha256") != plan.get("promotion_candidate_sha256")
        or plan.get("predecessor_promotion_candidate_sha256")
        == plan.get("promotion_candidate_sha256")
    ):
        errors.append("object-store promotion candidate does not match plan")
    authorization = _mapping(observation.get("authorization"))
    if (
        authorization.get("action") != ACTION
        or authorization.get("provider_apply_authorized") is not True
        or not authorization.get("authorization_sha256")
    ):
        errors.append("object-store provider apply authorization is not bound")
    before_objects = _mapping(observation.get("object_store_before_restart"))
    after_objects = _mapping(observation.get("object_store_after_restart"))
    if (
        dict(before_objects) != dict(after_objects)
        or before_objects.get("bucket") != profile.target.bucket
        or before_objects.get("prefix") != profile.target.object_prefix
        or not before_objects.get("metadata_keys")
        or before_objects.get("data_keys") != []
        or before_objects.get("manifest_keys") != []
        or _mapping(before_objects.get("latest_metadata")).get("location")
        != profile.target.table_location
        or before_objects.get("source_feature_rows_present") is not False
        or before_objects.get("material_recorded") is not False
    ):
        errors.append("direct S3 Iceberg metadata did not survive provider restart")
    checks = _mapping(observation.get("runtime_checks"))
    if (
        checks.get("openmetadata_port_forward_stopped") is not True
        or checks.get("all_runtime_port_forwards_stopped") is not True
        or checks.get("namespace_delete_completed") is not True
        or checks.get("namespace_absent") is not True
        or checks.get("persistent_volumes_absent") is not True
        or checks.get("provider_objects_retained") is not False
        or checks.get("object_store_objects_retained") is not False
        or checks.get("material_recorded") is not False
    ):
        errors.append("object-store promotion runtime cleanup is incomplete")
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_docker_desktop",
        "status": (
            "local_object_store_active_metadata_promotion_verified" if verified else "blocked"
        ),
        "contract_sha256": contract.get("contract_sha256"),
        "source_m320_evidence_sha256": M320_EVIDENCE_SHA256,
        "m310_evidence_fingerprint": M310_EVIDENCE_FINGERPRINT,
        "dataset_bundle": dict(dataset),
        "resource_version_id": plan.get("resource_version_id"),
        "resource_version_content_sha256": plan.get("content_sha256"),
        "predecessor_promotion_candidate_sha256": plan.get(
            "predecessor_promotion_candidate_sha256"
        ),
        "logical_binding_sha256": plan.get("logical_binding_sha256"),
        "runtime_binding_sha256": observation.get("runtime_binding_sha256"),
        "promotion_candidate_sha256": plan.get("promotion_candidate_sha256"),
        "local_object_store_active_metadata_promotion_verified": verified,
        "real_dataset_resource_version_bound": verified,
        "openmetadata_read_only_verified": verified,
        "bounded_gravitino_projection_verified": verified,
        "local_jdbc_s3_catalog_restart_continuity_verified": verified,
        "local_cross_node_object_store_runtime_bound": verified,
        "direct_object_store_metadata_verified": verified,
        "pre_restart_replay_no_op_verified": verified,
        "post_restart_first_replay_no_op_verified": verified,
        "m320_history_untouched": verified,
        "predecessor_history_changed": False,
        "promotion_persisted_to_gda_control": False,
        "dataset_source_committed": False,
        "dataset_absolute_path_committed": False,
        "dataset_required_in_ci": False,
        "deployment_applied": False,
        "source_feature_rows_ingested": False,
        "protected_workload_identity_verified": False,
        "provider_minimum_privilege_verified": False,
        "durable_catalog_verified": False,
        "production_object_store_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "production_scheduler_submission_verified": False,
        "production_ingestion_verified": False,
        "spark_conformance_verified": False,
        "flink_conformance_verified": False,
        "platform_run_succeeded": False,
        "production_ready": False,
        "observation": dict(observation),
        "errors": errors,
    }
    return {**stable, "evidence_sha256": canonical_json_fingerprint(stable)}


def verify_evidence_integrity(evidence: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        replay._reject_sensitive_fields(evidence)
    except ValueError:
        errors.append("object-store promotion evidence contains sensitive material")
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("object-store promotion evidence SHA-256 does not match")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("errors") != []:
        errors.append("object-store promotion evidence is not verified")
    for claim in (
        "local_object_store_active_metadata_promotion_verified",
        "real_dataset_resource_version_bound",
        "openmetadata_read_only_verified",
        "bounded_gravitino_projection_verified",
        "local_jdbc_s3_catalog_restart_continuity_verified",
        "local_cross_node_object_store_runtime_bound",
        "direct_object_store_metadata_verified",
        "pre_restart_replay_no_op_verified",
        "post_restart_first_replay_no_op_verified",
        "m320_history_untouched",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"object-store promotion evidence claim is false: {claim}")
    for claim in FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"object-store promotion evidence may not claim {claim}")
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    for forbidden in (
        "/Users/",
        "/home/",
        "Downloads/",
        ".tmp/",
        "host.docker.internal",
        '"password"',
        '"secret"',
        '"token"',
        '"session"',
        '"access_key"',
        '"access-key"',
    ):
        if forbidden in serialized:
            errors.append("object-store promotion evidence contains local or secret material")
            break
    return errors


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    source, runtime_profile = _load_dependencies(profile)
    contract = build_contract_report(profile_path=profile_path)
    if contract.get("status") != "valid":
        raise ObjectStoreActiveMetadataPromotionError(
            "object-store promotion static contract is invalid"
        )
    provider_profile = execution.build_projection_profile(datetime.now(UTC))
    try:
        openmetadata_username = os.environ[provider_profile.providers.openmetadata.username_env]
        openmetadata_password = SecretStr(
            os.environ[provider_profile.providers.openmetadata.password_env]
        )
    except KeyError as exc:
        raise ObjectStoreActiveMetadataPromotionError(
            "OpenMetadata local bootstrap credential environment is missing"
        ) from exc
    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    user_material = SecretStr(secrets.token_urlsafe(24))
    object_store_user = SecretStr("gda" + secrets.token_hex(8))
    object_store_material = SecretStr(secrets.token_urlsafe(32))
    runtime = m310.IsolatedSparkObjectStoreRuntime(runtime_profile)
    om_forward: provider_metrics._PortForward | None = None
    object_forward: provider_metrics._PortForward | None = None
    before_forward: provider_metrics._PortForward | None = None
    after_forward: provider_metrics._PortForward | None = None
    om_client: replay.OpenMetadataApplyClient | None = None
    rehearsal: ObjectStoreProjectionRehearsal | None = None
    initial_runtime: dict[str, Any] | None = None
    restart: dict[str, Any] | None = None
    object_store_prepared: dict[str, Any] | None = None
    openmetadata_observation: bridge.OpenMetadataObservation | None = None
    plan: ObjectStoreProjectionPlan | None = None
    authorization: tuple[PlatformRun, Artifact, Artifact, Artifact, str] | None = None
    bootstrap: dict[str, Any] | None = None
    first_apply: dict[str, Any] | None = None
    immediate_replay: dict[str, Any] | None = None
    object_store_before: dict[str, Any] | None = None
    post_restart_security: dict[str, Any] | None = None
    post_restart_replay: dict[str, Any] | None = None
    object_store_after: dict[str, Any] | None = None
    cluster_uid: str | None = None
    runtime_binding: dict[str, Any] | None = None
    openmetadata_mutation_count = -1
    om_forward_stopped = False
    object_forward_stopped = False
    before_forward_stopped = False
    after_forward_stopped = False
    cleanup = {
        "namespace_delete_completed": False,
        "namespace_absent": False,
        "persistent_volumes_absent": False,
        "provider_objects_retained": True,
        "object_store_objects_retained": True,
    }
    try:
        initial_runtime = runtime.start(
            admin_material=admin_material,
            database_material=database_material,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        cluster = runtime.kubectl.get_json(
            ["get", "namespace", "kube-system"],
            label="object-store promotion cluster identity",
        )
        cluster_uid = str(_mapping(_mapping(cluster).get("metadata")).get("uid"))
        runtime_binding = _provider_runtime_binding(
            initial_runtime,
            cluster_uid=cluster_uid,
            target=profile.target,
        )

        object_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=runtime_profile.cluster.context,
            namespace=runtime_profile.cluster.rehearsal_namespace,
            service=runtime_profile.runtime.object_store_service,
            target_port=runtime_profile.runtime.object_store_service_port,
        )
        object_forward.start()
        object_endpoint = f"http://127.0.0.1:{object_forward.local_port}"
        object_store_prepared = runtime.prepare_object_store(
            endpoint_url=object_endpoint,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )

        om_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=provider_profile.cluster.context,
            namespace=provider_profile.cluster.namespace,
            service=provider_profile.providers.openmetadata.service,
            target_port=provider_profile.providers.openmetadata.service_port,
        )
        om_forward.start()
        om_client = replay.OpenMetadataApplyClient(
            base_url=f"http://127.0.0.1:{om_forward.local_port}/api/v1",
            username=openmetadata_username,
            password=openmetadata_password,
        )
        om_payload = om_client.get_table(provider_profile.targets.openmetadata.table_fqn)
        if om_payload is None:
            raise ObjectStoreActiveMetadataPromotionError(
                "retained OpenMetadata projection is missing"
            )
        openmetadata_observation = _verify_openmetadata(
            om_payload, source, observed_at=datetime.now(UTC)
        )
        openmetadata_mutation_count = len(om_client.mutations)
        om_client.close()
        om_client = None
        om_forward_stopped = om_forward.stop()
        om_forward = None

        plan = build_projection_plan(profile, source, openmetadata_observation, runtime_binding)
        authorized_at = datetime.now(UTC)
        authorization = build_apply_authorization(plan, profile, authorized_at=authorized_at)
        before_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=runtime_profile.cluster.context,
            namespace=runtime_profile.cluster.rehearsal_namespace,
            service=runtime_profile.runtime.service,
            target_port=runtime_profile.runtime.gravitino_service_port,
        )
        before_forward.start()
        rehearsal = ObjectStoreProjectionRehearsal(
            base_url=f"http://127.0.0.1:{before_forward.local_port}/api",
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
        first_apply = rehearsal.apply_once(plan, authorization, at=authorized_at, create=True)
        immediate_replay = rehearsal.apply_once(
            plan, authorization, at=authorized_at + timedelta(seconds=1)
        )
        object_store_before = observe_table_object_store(
            runtime,
            profile,
            endpoint_url=object_endpoint,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
        rehearsal.close()
        rehearsal = None
        before_forward_stopped = before_forward.stop()
        before_forward = None

        restart = restart_provider_runtime(runtime)

        after_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=runtime_profile.cluster.context,
            namespace=runtime_profile.cluster.rehearsal_namespace,
            service=runtime_profile.runtime.service,
            target_port=runtime_profile.runtime.gravitino_service_port,
        )
        after_forward.start()
        rehearsal = ObjectStoreProjectionRehearsal(
            base_url=f"http://127.0.0.1:{after_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        post_restart_security = rehearsal.reconnect_bounded(profile, user_material)
        post_restart_replay = rehearsal.apply_once(
            plan, authorization, at=authorized_at + timedelta(seconds=2)
        )
        object_store_after = observe_table_object_store(
            runtime,
            profile,
            endpoint_url=object_endpoint,
            object_store_user=object_store_user,
            object_store_material=object_store_material,
        )
    finally:
        if om_client is not None:
            om_client.close()
        if rehearsal is not None:
            rehearsal.close()
        if om_forward is not None:
            om_forward_stopped = om_forward.stop()
        if before_forward is not None:
            before_forward_stopped = before_forward.stop()
        if after_forward is not None:
            after_forward_stopped = after_forward.stop()
        if object_forward is not None:
            object_forward_stopped = object_forward.stop()
        cleanup = runtime.cleanup()
    required = (
        initial_runtime,
        restart,
        object_store_prepared,
        openmetadata_observation,
        plan,
        authorization,
        bootstrap,
        first_apply,
        immediate_replay,
        object_store_before,
        post_restart_security,
        post_restart_replay,
        object_store_after,
        cluster_uid,
        runtime_binding,
    )
    if any(value is None for value in required):
        raise ObjectStoreActiveMetadataPromotionError(
            "object-store promotion rehearsal did not produce a complete outcome"
        )
    assert isinstance(openmetadata_observation, bridge.OpenMetadataObservation)
    assert isinstance(plan, ObjectStoreProjectionPlan)
    run, execution_plan, policy_artifact, approval_artifact, auth_sha = authorization
    source_openmetadata = _mapping(_mapping(source.get("observation")).get("openmetadata"))
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_sha256": contract["contract_sha256"],
            "source_m320_evidence_sha256": M320_EVIDENCE_SHA256,
            "m310_evidence_fingerprint": M310_EVIDENCE_FINGERPRINT,
        },
        "dataset_bundle": source["dataset_bundle"],
        "predecessor_promotion_candidate_sha256": source["promotion_candidate_sha256"],
        "source_m320_openmetadata": dict(source_openmetadata),
        "openmetadata": {
            **dict(source_openmetadata),
            "owner_refs": sorted(openmetadata_observation.owner_refs),
            "domain_refs": sorted(openmetadata_observation.domain_refs),
            "tag_refs": sorted(openmetadata_observation.tag_refs),
        },
        "openmetadata_mutation_count": openmetadata_mutation_count,
        "cluster_uid": cluster_uid,
        "runtime_binding": runtime_binding,
        "runtime_binding_sha256": canonical_json_fingerprint(runtime_binding),
        "initial_runtime": initial_runtime,
        "object_store_prepared": object_store_prepared,
        "restart": restart,
        "plan": plan.model_dump(mode="json", by_alias=True),
        "authorization": {
            "action": ACTION,
            "provider_apply_authorized": True,
            "authorization_sha256": auth_sha,
            "run_id": str(run.run_id),
            "execution_plan_artifact_id": str(execution_plan.artifact_id),
            "policy_decision_artifact_id": str(policy_artifact.artifact_id),
            "approval_artifact_id": str(approval_artifact.artifact_id),
        },
        "bootstrap": bootstrap,
        "first_apply": first_apply,
        "immediate_replay": immediate_replay,
        "object_store_before_restart": object_store_before,
        "post_restart_security": post_restart_security,
        "post_restart_first_replay": post_restart_replay,
        "object_store_after_restart": object_store_after,
        "runtime_checks": {
            **cleanup,
            "openmetadata_port_forward_stopped": om_forward_stopped,
            "all_runtime_port_forwards_stopped": (
                object_forward_stopped and before_forward_stopped and after_forward_stopped
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
        observed_contract = _mapping(_mapping(evidence.get("observation")).get("contract")).get(
            "contract_sha256"
        )
        if observed_contract != contract.get("contract_sha256"):
            errors.append("object-store promotion evidence contract SHA drift")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"object-store promotion evidence is invalid: {type(exc).__name__}")
    verified = not errors
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if verified else "invalid",
        "local_static_contract_verified": contract["local_static_contract_verified"],
        "local_object_store_active_metadata_promotion_verified": (
            verified
            and evidence is not None
            and evidence.get("local_object_store_active_metadata_promotion_verified") is True
        ),
        "local_cross_node_object_store_runtime_bound": (
            verified
            and evidence is not None
            and evidence.get("local_cross_node_object_store_runtime_bound") is True
        ),
        "direct_object_store_metadata_verified": (
            verified
            and evidence is not None
            and evidence.get("direct_object_store_metadata_verified") is True
        ),
        "promotion_persisted_to_gda_control": False,
        "durable_catalog_verified": False,
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
    parser = argparse.ArgumentParser(
        description="Validate or run the object-store Active Metadata promotion"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    validate_parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE_PATH)
    contract_parser = subparsers.add_parser("contract")
    contract_parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    live_parser = subparsers.add_parser("live")
    live_parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    live_parser.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE_PATH)
    args = parser.parse_args(argv)
    if args.command == "contract":
        report = build_contract_report(profile_path=args.profile)
    elif args.command == "live":
        report = run_live_rehearsal(args.profile)
        _write_json(args.output, report)
    else:
        report = build_validation_report(profile_path=args.profile, evidence_path=args.evidence)
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
