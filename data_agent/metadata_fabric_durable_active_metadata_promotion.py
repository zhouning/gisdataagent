"""Promote a real Active Metadata projection into a restart-continuous catalog.

M3-20 consumes the checked M3-19 Chongqing binding evidence, verifies the
retained OpenMetadata projection without writing it, and creates a new
Gravitino projection through a schema-bounded principal. The target uses the
isolated JDBC/PVC runtime already proven by M3-8. The exact projection must be
a no-op both immediately and on the first request after ordered PostgreSQL and
Gravitino restarts.

The resulting promotion candidate binds the logical provider refs to the
observed cluster, namespace, service, StatefulSet and PVC identities. It does
not alter the M3-19 binding schema or ledger and does not establish production
durability, protected identity, production ingestion or terminal run success.
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

from . import metadata_fabric_active_metadata_binding_reconciliation as m319
from . import metadata_fabric_active_metadata_projection_execution as execution
from . import metadata_fabric_bridge as bridge
from . import metadata_fabric_gravitino_identity as identity
from . import metadata_fabric_gravitino_jdbc_restart as jdbc_restart
from . import metadata_fabric_ingestion_replay as replay
from . import metadata_fabric_provider_metrics as provider_metrics
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

PROFILE_SCHEMA = "gda.durable_active_metadata_promotion_profile.v1"
PLAN_SCHEMA = "gda.durable_active_metadata_projection_plan.v1"
PROMOTION_SCHEMA = "gda.runtime_bound_metadata_promotion_candidate.v1"
CONTRACT_SCHEMA = "gda.durable_active_metadata_promotion_contract.v1"
OBSERVATION_SCHEMA = "gda.durable_active_metadata_promotion_observation.v1"
EVIDENCE_SCHEMA = "gda.durable_active_metadata_promotion_evidence.v1"
VALIDATION_SCHEMA = "gda.durable_active_metadata_promotion_validation.v1"
ACTION = "metadata_fabric.promote_durable_projection"
TENANT = m319.TENANT
RESOURCE_VERSION_ID = m319.SOURCE_ID
DEFINITION_ID = UUID("a9000000-0000-4000-8000-000000000004")
RUN_ID = UUID("a9000000-0000-4000-8000-000000000005")
WORKLOAD = "workload:durable-active-metadata-promoter"
POLICY_EVALUATOR = "workload:durable-metadata-policy-evaluator"
APPROVER = "human:metadata-platform-owner"
M319_EVIDENCE_SHA256 = (
    "e6d0e3ac4e052029dad0c18d0804626a8af61554a54081c37d8cc9a80c55cd33"
)
JDBC_RESTART_EVIDENCE_FINGERPRINT = (
    "34792bb47ad71041a87adeb644439bf9b6aa3f4855cdc98782d6e3b4282bf1aa"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_PATH = (
    REPO_ROOT / "config/metadata-fabric-durable-active-metadata-promotion.local.yaml"
)
DEFAULT_EVIDENCE_PATH = (
    REPO_ROOT
    / "docs/evidence/metadata-fabric-durable-active-metadata-promotion-2026-07-30.json"
)
DEFAULT_WRAPPER_PATH = (
    REPO_ROOT / "scripts/metadata-fabric-durable-active-metadata-promotion.sh"
)
FALSE_CLAIMS = (
    "binding_schema_changed",
    "durable_candidate_persisted_to_gda_control",
    "dataset_source_committed",
    "dataset_absolute_path_committed",
    "dataset_required_in_ci",
    "deployment_applied",
    "protected_workload_identity_verified",
    "provider_minimum_privilege_verified",
    "durable_catalog_verified",
    "production_object_store_verified",
    "oidc_verified",
    "tls_verified",
    "production_scheduler_submission_verified",
    "production_ingestion_verified",
    "platform_run_succeeded",
    "production_ready",
)


class DurableActiveMetadataPromotionError(RuntimeError):
    """The runtime-bound durable projection promotion failed closed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DependencyProfile(_FrozenModel):
    m319_evidence_path: str
    m319_evidence_sha256: Literal[
        "e6d0e3ac4e052029dad0c18d0804626a8af61554a54081c37d8cc9a80c55cd33"
    ]
    jdbc_restart_profile_path: str
    jdbc_restart_evidence_path: str
    jdbc_restart_evidence_fingerprint: Literal[
        "34792bb47ad71041a87adeb644439bf9b6aa3f4855cdc98782d6e3b4282bf1aa"
    ]


class DurableTarget(_FrozenModel):
    metalake: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
    catalog: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
    schema_name: str = Field(alias="schema", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
    table: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
    catalog_type: Literal["RELATIONAL"]
    catalog_provider: Literal["lakehouse-iceberg"]
    catalog_backend: Literal["jdbc"]
    uri: Literal[
        "jdbc:postgresql://gravitino-persistence-postgresql:5432/iceberg"
    ]
    warehouse: Literal["file:///var/lib/gravitino/warehouse"]
    jdbc_driver: Literal["org.postgresql.Driver"]

    @property
    def identity(self) -> str:
        return f"{self.metalake}/{self.catalog}/{self.schema_name}/{self.table}"


class IdentityProfile(_FrozenModel):
    service_admin: Literal["gda-persistence-admin"]
    user: Literal["gda-active-metadata-promoter"]
    role: Literal["gda-cultural-district-projector"]
    material_delivery: Literal["runtime_generated_ephemeral_kubernetes_object"]


class AuthorizationProfile(_FrozenModel):
    policy_version_ref: str
    evaluator_subject: Literal["workload:durable-metadata-policy-evaluator"]
    approver_subject: Literal["human:metadata-platform-owner"]
    approval_reason: str


class ClaimProfile(_FrozenModel):
    binding_schema_changed: Literal[False]
    durable_candidate_persisted_to_gda_control: Literal[False]
    protected_workload_identity_verified: Literal[False]
    provider_minimum_privilege_verified: Literal[False]
    durable_catalog_verified: Literal[False]
    production_object_store_verified: Literal[False]
    oidc_verified: Literal[False]
    tls_verified: Literal[False]
    production_ingestion_verified: Literal[False]
    production_ready: Literal[False]


class DurablePromotionProfile(_FrozenModel):
    profile_schema: Literal["gda.durable_active_metadata_promotion_profile.v1"] = Field(
        alias="schema"
    )
    environment: Literal["local_docker_desktop"]
    dependencies: DependencyProfile
    target: DurableTarget
    identity: IdentityProfile
    authorization: AuthorizationProfile
    claims: ClaimProfile


class DurableProjectionPlan(_FrozenModel):
    plan_schema: Literal["gda.durable_active_metadata_projection_plan.v1"] = Field(
        default=PLAN_SCHEMA, alias="schema"
    )
    tenant_id: str
    run_id: UUID
    definition_version_id: UUID
    resource_urn: str
    resource_version_id: UUID
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    openmetadata_ref: bridge.OpenMetadataTableRef
    openmetadata_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gravitino_ref: bridge.GravitinoTableRef
    target: DurableTarget
    runtime_binding: dict[str, Any]
    runtime_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    logical_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    promotion_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    writes_to_gda_control: Literal[False] = False
    writes_to_legacy: Literal[False] = False
    apply_plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _fingerprints_match(self) -> DurableProjectionPlan:
        if self.target.identity != self.gravitino_ref.identity:
            raise ValueError("durable target does not match Gravitino ref")
        if self.runtime_binding_sha256 != canonical_json_fingerprint(
            self.runtime_binding
        ):
            raise ValueError("runtime binding fingerprint does not match")
        expected_logical = bridge.metadata_fabric_binding_fingerprint(
            tenant_id=self.tenant_id,
            resource_urn=self.resource_urn,
            resource_version_id=self.resource_version_id,
            content_sha256=self.content_sha256,
            openmetadata=self.openmetadata_ref,
            gravitino=(self.gravitino_ref,),
        )
        if self.logical_binding_sha256 != expected_logical:
            raise ValueError("logical binding fingerprint does not match")
        candidate = _promotion_candidate_payload(
            tenant_id=self.tenant_id,
            resource_urn=self.resource_urn,
            resource_version_id=self.resource_version_id,
            content_sha256=self.content_sha256,
            source_binding_sha256=self.source_binding_sha256,
            logical_binding_sha256=self.logical_binding_sha256,
            runtime_binding_sha256=self.runtime_binding_sha256,
            openmetadata_ref=self.openmetadata_ref,
            gravitino_ref=self.gravitino_ref,
        )
        if self.promotion_candidate_sha256 != canonical_json_fingerprint(candidate):
            raise ValueError("promotion candidate fingerprint does not match")
        stable = self.model_dump(
            mode="json", by_alias=True, exclude={"apply_plan_sha256"}
        )
        if self.apply_plan_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("durable apply plan fingerprint does not match")
        return self


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DurableActiveMetadataPromotionError(
            f"{path.name} is not valid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise DurableActiveMetadataPromotionError(f"{path.name} must be an object")
    return value


def _resolve_repo_path(value: str) -> Path:
    path = (REPO_ROOT / value).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise DurableActiveMetadataPromotionError(
            "profile dependency path leaves repository"
        ) from exc
    return path


def load_profile(path: Path = DEFAULT_PROFILE_PATH) -> DurablePromotionProfile:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise TypeError("profile must be an object")
        replay._reject_sensitive_fields(value)
        profile = DurablePromotionProfile.model_validate(value)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise DurableActiveMetadataPromotionError(
            "durable promotion profile is invalid"
        ) from exc
    return profile


def _load_dependencies(
    profile: DurablePromotionProfile,
) -> tuple[dict[str, Any], jdbc_restart.GravitinoJdbcRestartProfile]:
    dependencies = profile.dependencies
    m319_evidence = _load_json_object(
        _resolve_repo_path(dependencies.m319_evidence_path)
    )
    errors = m319.validate_rehearsal_evidence(m319_evidence)
    if errors or m319_evidence.get("evidence_sha256") != M319_EVIDENCE_SHA256:
        raise DurableActiveMetadataPromotionError(
            "M3-19 binding reconciliation evidence does not match"
        )
    jdbc_evidence = _load_json_object(
        _resolve_repo_path(dependencies.jdbc_restart_evidence_path)
    )
    runtime_profile_path = _resolve_repo_path(
        dependencies.jdbc_restart_profile_path
    )
    jdbc_validation = jdbc_restart.build_validation_report(
        profile_path=runtime_profile_path,
        evidence_path=_resolve_repo_path(dependencies.jdbc_restart_evidence_path),
    )
    if (
        jdbc_validation.get("errors")
        or jdbc_restart.verify_evidence_integrity(jdbc_evidence)
        or jdbc_evidence.get("evidence_fingerprint")
        != JDBC_RESTART_EVIDENCE_FINGERPRINT
    ):
        raise DurableActiveMetadataPromotionError(
            "M3-8 JDBC restart evidence does not match"
        )
    runtime_profile = jdbc_restart.load_profile(runtime_profile_path)
    return m319_evidence, runtime_profile


def _file_record(path: Path) -> dict[str, str | None]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(REPO_ROOT).as_posix(),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()
        if resolved.is_file()
        else None,
    }


def _promotion_candidate_payload(
    *,
    tenant_id: str,
    resource_urn: str,
    resource_version_id: UUID,
    content_sha256: str,
    source_binding_sha256: str,
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
        "source_binding_sha256": source_binding_sha256,
        "logical_binding_sha256": logical_binding_sha256,
        "runtime_binding_sha256": runtime_binding_sha256,
        "openmetadata_ref": openmetadata_ref.model_dump(mode="json"),
        "gravitino_ref": gravitino_ref.model_dump(mode="json"),
        "binding_schema_changed": False,
        "persisted_to_gda_control": False,
    }


def _provider_runtime_binding(
    snapshot: Mapping[str, Any],
    *,
    cluster_uid: str,
    target: DurableTarget,
) -> dict[str, Any]:
    namespace = _mapping(snapshot.get("namespace"))
    service = _mapping(snapshot.get("service"))
    postgresql = _mapping(snapshot.get("postgresql"))
    gravitino = _mapping(snapshot.get("gravitino"))
    postgresql_pvc = _mapping(postgresql.get("pvc"))
    warehouse_pvc = _mapping(gravitino.get("pvc"))
    binding = {
        "schema": "gda.provider_runtime_binding.v1",
        "context": snapshot.get("context"),
        "cluster_uid": cluster_uid,
        "namespace": {
            "name": namespace.get("name"),
            "uid": namespace.get("uid"),
        },
        "service": {
            "name": service.get("name"),
            "uid": service.get("uid"),
        },
        "workloads": {
            "postgresql_statefulset_uid": postgresql.get("statefulset_uid"),
            "gravitino_statefulset_uid": gravitino.get("statefulset_uid"),
        },
        "storage": {
            "postgresql_pvc_uid": postgresql_pvc.get("uid"),
            "postgresql_volume_name": postgresql_pvc.get("volume_name"),
            "warehouse_pvc_uid": warehouse_pvc.get("uid"),
            "warehouse_volume_name": warehouse_pvc.get("volume_name"),
        },
        "images": {
            "postgresql_image_id": postgresql.get("image_id"),
            "gravitino_image_id": gravitino.get("image_id"),
        },
        "catalog": {
            "backend": target.catalog_backend,
            "uri": target.uri,
            "warehouse": target.warehouse,
        },
    }
    serialized = json.dumps(binding, ensure_ascii=True, sort_keys=True)
    if not cluster_uid or any(
        token in serialized for token in ('null', '"uid": ""')
    ):
        raise DurableActiveMetadataPromotionError(
            "provider runtime identity is incomplete"
        )
    return binding


def _verify_openmetadata(
    payload: dict[str, Any],
    source: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> bridge.OpenMetadataObservation:
    expected = _mapping(_mapping(source.get("first_readback")).get("openmetadata"))
    ref = bridge.OpenMetadataTableRef(
        entity_id=UUID(str(payload["id"])),
        fully_qualified_name=str(expected["fully_qualified_name"]),
        entity_version=str(payload["version"]),
        server_version="1.13.1",
    )
    observation = bridge.parse_openmetadata_table_observation(
        ref, payload, observed_at=observed_at
    )
    actual = {
        "entity_id": str(observation.ref.entity_id),
        "fully_qualified_name": observation.ref.fully_qualified_name,
        "entity_version": observation.ref.entity_version,
        "resource_urn": observation.resource_urn,
        "resource_version_id": str(observation.resource_version_id),
        "content_sha256": observation.content_sha256,
        "owner_refs": sorted(observation.owner_refs),
        "domain_refs": sorted(observation.domain_refs),
        "tag_refs": sorted(observation.tag_refs),
        "snapshot_sha256": observation.snapshot_sha256,
    }
    normalized_expected = {
        **dict(expected),
        "owner_refs": sorted(expected.get("owner_refs", [])),
        "domain_refs": sorted(expected.get("domain_refs", [])),
        "tag_refs": sorted(expected.get("tag_refs", [])),
    }
    if actual != normalized_expected:
        raise DurableActiveMetadataPromotionError(
            "retained OpenMetadata projection drifted from M3-19"
        )
    return observation


def build_projection_plan(
    profile: DurablePromotionProfile,
    source: Mapping[str, Any],
    openmetadata: bridge.OpenMetadataObservation,
    runtime_binding: dict[str, Any],
) -> DurableProjectionPlan:
    first = _mapping(source.get("first_readback"))
    resource_urn = openmetadata.resource_urn
    content_sha256 = openmetadata.content_sha256
    provider_revision = f"shapefile-bundle-{content_sha256[:16]}"
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
        resource_urn=resource_urn,
        resource_version_id=openmetadata.resource_version_id,
        content_sha256=content_sha256,
        openmetadata=openmetadata.ref,
        gravitino=(gravitino_ref,),
    )
    runtime_binding_sha256 = canonical_json_fingerprint(runtime_binding)
    candidate = _promotion_candidate_payload(
        tenant_id=TENANT,
        resource_urn=resource_urn,
        resource_version_id=openmetadata.resource_version_id,
        content_sha256=content_sha256,
        source_binding_sha256=str(first["binding_candidate_sha256"]),
        logical_binding_sha256=logical_binding_sha256,
        runtime_binding_sha256=runtime_binding_sha256,
        openmetadata_ref=openmetadata.ref,
        gravitino_ref=gravitino_ref,
    )
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_ID,
        "resource_urn": resource_urn,
        "resource_version_id": openmetadata.resource_version_id,
        "content_sha256": content_sha256,
        "source_binding_sha256": str(first["binding_candidate_sha256"]),
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
    return DurableProjectionPlan(
        **values,
        apply_plan_sha256=canonical_json_fingerprint(stable),
    )


def _build_execution_plan_artifact(
    plan: DurableProjectionPlan, *, created_at: datetime
) -> Artifact:
    manifest = {
        "schema": "gda.durable_active_metadata_execution_plan.v1",
        "plan": plan.model_dump(mode="json", by_alias=True),
    }
    artifact_id = uuid5(RUN_ID, f"durable-promotion:{plan.apply_plan_sha256}")
    content = canonical_json_bytes(manifest)
    return Artifact(
        tenant_id=TENANT,
        artifact_id=artifact_id,
        artifact_key=f"durable-active-metadata:{artifact_id}",
        artifact_role=ArtifactRole.EXECUTION_PLAN,
        storage_uri=f"postgresql://gda-control/execution-plans/{TENANT}/{artifact_id}",
        media_type="application/vnd.gda.durable-active-metadata-plan+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(content),
        run_id=None,
        resource_version_id=DEFINITION_ID,
        manifest=manifest,
        created_by=WORKLOAD,
        created_at=created_at,
    )


def build_apply_authorization(
    plan: DurableProjectionPlan,
    profile: DurablePromotionProfile,
    *,
    authorized_at: datetime,
) -> tuple[PlatformRun, Artifact, Artifact, Artifact, str]:
    if authorized_at.tzinfo is None or authorized_at.utcoffset() is None:
        raise DurableActiveMetadataPromotionError(
            "authorization timestamp must include a timezone"
        )
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id=WORKLOAD.removeprefix("workload:"),
        subject_type="workload",
        roles=("metadata_projector",),
        purpose="promote a content-bound projection into a durable local catalog",
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
        idempotency_key=(
            f"durable-active-metadata:{plan.promotion_candidate_sha256}"
        ),
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
    plan: DurableProjectionPlan,
    authorization: tuple[PlatformRun, Artifact, Artifact, Artifact, str],
    *,
    at: datetime,
) -> None:
    run, execution_plan, policy_artifact, approval_artifact, fingerprint = (
        authorization
    )
    if _mapping(execution_plan.manifest.get("plan")) != plan.model_dump(
        mode="json", by_alias=True
    ):
        raise DurableActiveMetadataPromotionError(
            "execution plan artifact does not contain the exact durable plan"
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
        raise DurableActiveMetadataPromotionError(
            "durable apply authorization fingerprint does not match"
        )


def _expected_role(profile: DurablePromotionProfile) -> list[dict[str, Any]]:
    return [
        {
            "fullName": profile.target.catalog,
            "type": "CATALOG",
            "privileges": [{"name": "USE_CATALOG", "condition": "ALLOW"}],
        },
        {
            "fullName": (
                f"{profile.target.catalog}.{profile.target.schema_name}"
            ),
            "type": "SCHEMA",
            "privileges": [
                {"name": "CREATE_TABLE", "condition": "ALLOW"},
                {"name": "USE_SCHEMA", "condition": "ALLOW"},
            ],
        },
    ]


def _table_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    table = _mapping(payload.get("table"))
    columns = []
    for value in table.get("columns", []):
        column = _mapping(value)
        columns.append(
            {
                "name": column.get("name"),
                "type": column.get("type"),
                "nullable": column.get("nullable"),
            }
        )
    properties = _mapping(table.get("properties"))
    return {
        "name": table.get("name"),
        "columns": columns,
        "resource_urn": properties.get("gda.resource_urn"),
        "resource_version_id": properties.get("gda.resource_version_id"),
        "content_sha256": properties.get("gda.content_sha256"),
        "provider_revision": properties.get("gda.provider_revision"),
    }


class DurableProjectionRehearsal:
    """Bootstrap a JDBC catalog and apply through one bounded Basic principal."""

    def __init__(
        self,
        *,
        base_url: str,
        admin_name: str,
        admin_material: SecretStr,
    ) -> None:
        self.base_url = base_url
        self.admin = identity._BasicApi(
            base_url=base_url,
            username=admin_name,
            material=admin_material,
        )
        self.clients: list[identity._BasicApi] = []
        self.bounded: identity._BasicApi | None = None

    def close(self) -> None:
        for client in self.clients:
            client.close()
        self.clients.clear()
        self.bounded = None
        self.admin.close()

    @staticmethod
    def _catalog_path(target: DurableTarget, catalog: str | None = None) -> str:
        return (
            f"metalakes/{quote(target.metalake)}/catalogs/"
            f"{quote(catalog or target.catalog)}"
        )

    @classmethod
    def _schema_path(cls, target: DurableTarget) -> str:
        return (
            f"{cls._catalog_path(target)}/schemas/{quote(target.schema_name)}"
        )

    @classmethod
    def _table_path(cls, target: DurableTarget) -> str:
        return f"{cls._schema_path(target)}/tables/{quote(target.table)}"

    def _bounded_api(
        self, profile: DurablePromotionProfile, material: SecretStr
    ) -> identity._BasicApi:
        client = identity._BasicApi(
            base_url=self.base_url,
            username=profile.identity.user,
            material=material,
        )
        self.clients.append(client)
        self.bounded = client
        return client

    def bootstrap(
        self,
        profile: DurablePromotionProfile,
        *,
        database_material: SecretStr,
        user_material: SecretStr,
    ) -> dict[str, Any]:
        admin_status, version_payload = self.admin.request(
            "GET", "version", label="durable promotion admin authentication"
        )
        version = _mapping(_mapping(version_payload).get("version")).get("version")
        if version is None:
            version = _mapping(version_payload).get("version")
        _, metalake_payload = self.admin.request(
            "POST",
            "metalakes",
            json_body={
                "name": profile.target.metalake,
                "comment": "Real Chongqing durable Active Metadata promotion",
                "properties": {"gda.environment": "local_durable_promotion"},
            },
            label="durable promotion metalake create",
        )
        metalake = identity._response_entity(
            metalake_payload, "metalake", "durable promotion metalake"
        )
        _, catalog_payload = self.admin.request(
            "POST",
            f"metalakes/{quote(profile.target.metalake)}/catalogs",
            json_body={
                "name": profile.target.catalog,
                "type": profile.target.catalog_type,
                "provider": profile.target.catalog_provider,
                "comment": "JDBC-backed real Active Metadata projection catalog",
                "properties": {
                    "catalog-backend": profile.target.catalog_backend,
                    "uri": profile.target.uri,
                    "warehouse": profile.target.warehouse,
                    "jdbc-user": "gravitino",
                    "jdbc-password": database_material.get_secret_value(),
                    "gravitino.bypass.jdbc-driver": profile.target.jdbc_driver,
                    "gravitino.bypass.jdbc-initialize": "true",
                },
            },
            label="durable promotion JDBC catalog create",
        )
        catalog = identity._response_entity(
            catalog_payload, "catalog", "durable promotion catalog"
        )
        _, schema_payload = self.admin.request(
            "POST",
            f"{self._catalog_path(profile.target)}/schemas",
            json_body={
                "name": profile.target.schema_name,
                "comment": "Content-bound cultural heritage projection schema",
                "properties": {},
            },
            label="durable promotion schema create",
        )
        schema = identity._response_entity(
            schema_payload, "schema", "durable promotion schema"
        )
        self.admin.request(
            "POST",
            "idp/users",
            json_body={
                "user": profile.identity.user,
                "password": user_material.get_secret_value(),
            },
            label="durable promotion IdP user create",
        )
        self.admin.request(
            "POST",
            f"metalakes/{quote(profile.target.metalake)}/users",
            json_body={"name": profile.identity.user},
            label="durable promotion metalake user register",
        )
        self.admin.request(
            "POST",
            f"metalakes/{quote(profile.target.metalake)}/roles",
            json_body={
                "name": profile.identity.role,
                "properties": {"gda.scope": "cultural_district_table_projection"},
                "securableObjects": _expected_role(profile),
            },
            label="durable promotion bounded role create",
        )
        self.admin.request(
            "PUT",
            (
                f"metalakes/{quote(profile.target.metalake)}/permissions/users/"
                f"{quote(profile.identity.user)}/grant"
            ),
            json_body={"roleNames": [profile.identity.role]},
            label="durable promotion bounded role grant",
        )
        _, role_payload = self.admin.request(
            "GET",
            (
                f"metalakes/{quote(profile.target.metalake)}/roles/"
                f"{quote(profile.identity.role)}"
            ),
            label="durable promotion role readback",
        )
        role = identity._response_entity(
            role_payload, "role", "durable promotion role readback"
        )
        bounded = self._bounded_api(profile, user_material)
        bounded_status, _ = bounded.request(
            "GET", "version", label="durable promotion bounded authentication"
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
            label="durable promotion catalog administration denial",
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
        plan: DurableProjectionPlan,
        authorization: tuple[PlatformRun, Artifact, Artifact, Artifact, str],
        *,
        at: datetime,
        create: bool = False,
    ) -> dict[str, Any]:
        validate_apply_authorization(plan, authorization, at=at)
        if self.bounded is None:
            raise DurableActiveMetadataPromotionError(
                "bounded Gravitino principal is unavailable"
            )
        path = self._table_path(plan.target)
        mutations: list[str] = []
        if create:
            _, payload = self.bounded.request(
                "POST",
                f"{self._schema_path(plan.target)}/tables",
                json_body={
                    "name": plan.target.table,
                    "comment": "Real Chongqing cultural district projection",
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
                label="bounded durable projection table create",
            )
            mutations.append("gravitino.table.create")
        else:
            _, payload = self.bounded.request(
                "GET",
                path,
                label="durable projection table lookup",
            )
        assert payload is not None
        _, read_payload = self.bounded.request(
            "GET", path, label="durable projection exact readback"
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
            raise DurableActiveMetadataPromotionError(
                "durable Gravitino projection does not match the ResourceVersion"
            )
        projection = _table_projection(read_payload)
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
            raise DurableActiveMetadataPromotionError(
                "durable Gravitino table projection drifted"
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

    def reconnect_bounded(
        self, profile: DurablePromotionProfile, user_material: SecretStr
    ) -> dict[str, Any]:
        bounded = self._bounded_api(profile, user_material)
        status, _ = bounded.request(
            "GET", "version", label="post-restart bounded authentication"
        )
        _, role_payload = self.admin.request(
            "GET",
            (
                f"metalakes/{quote(profile.target.metalake)}/roles/"
                f"{quote(profile.identity.role)}"
            ),
            label="post-restart durable promotion role readback",
        )
        role = identity._response_entity(
            role_payload, "role", "post-restart durable promotion role"
        )
        denied_status, _ = bounded.request(
            "POST",
            f"metalakes/{quote(profile.target.metalake)}/catalogs",
            json_body={
                "name": "unauthorized_catalog",
                "type": "RELATIONAL",
                "provider": "lakehouse-iceberg",
                "comment": "must remain denied after restart",
                "properties": {
                    "catalog-backend": "memory",
                    "uri": "file:///tmp/gda-denied",
                    "warehouse": "file:///tmp/gda-denied",
                },
            },
            expected=frozenset({200, 403}),
            label="post-restart catalog administration denial",
        )
        return {
            "bounded_authentication_status": status,
            "role": {
                "name": role.get("name"),
                "securable_objects": identity._normalize_securable_objects(
                    role.get("securableObjects")
                ),
            },
            "denied_catalog_create_status": denied_status,
            "material_recorded": False,
        }


def _runtime_continuity_errors(
    restart: Mapping[str, Any],
    runtime_binding: Mapping[str, Any],
    *,
    cluster_uid: str,
    target: DurableTarget,
) -> list[str]:
    errors = jdbc_restart._restart_errors(restart)
    before = _mapping(restart.get("before"))
    after = _mapping(restart.get("after"))
    try:
        before_binding = _provider_runtime_binding(
            before, cluster_uid=cluster_uid, target=target
        )
        after_binding = _provider_runtime_binding(
            after, cluster_uid=cluster_uid, target=target
        )
    except DurableActiveMetadataPromotionError:
        errors.append("durable provider runtime identity is incomplete")
        return errors
    if before_binding != after_binding or dict(runtime_binding) != before_binding:
        errors.append("durable provider runtime identity changed across restart")
    return errors


def build_contract_report(
    *,
    profile_path: Path = DEFAULT_PROFILE_PATH,
    wrapper_path: Path = DEFAULT_WRAPPER_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    source_sha: str | None = None
    jdbc_fingerprint: str | None = None
    profile: DurablePromotionProfile | None = None
    try:
        profile = load_profile(profile_path)
        source, _runtime_profile = _load_dependencies(profile)
        source_sha = str(source.get("evidence_sha256"))
        jdbc_evidence = _load_json_object(
            _resolve_repo_path(profile.dependencies.jdbc_restart_evidence_path)
        )
        jdbc_fingerprint = str(jdbc_evidence.get("evidence_fingerprint"))
    except DurableActiveMetadataPromotionError as exc:
        errors.append(f"M3-20 dependency contract is invalid: {type(exc).__name__}")
    try:
        wrapper = wrapper_path.read_text(encoding="utf-8")
        for marker in (
            "set -euo pipefail",
            "metadata_fabric_durable_active_metadata_promotion",
            '"$@"',
        ):
            if marker not in wrapper:
                errors.append(f"M3-20 wrapper is missing marker: {marker}")
    except OSError as exc:
        errors.append(f"M3-20 wrapper is invalid: {type(exc).__name__}")
    files = {
        "implementation": _file_record(Path(__file__)),
        "profile": _file_record(profile_path),
        "wrapper": _file_record(wrapper_path),
    }
    stable = {
        "schema": CONTRACT_SCHEMA,
        "source_m319_evidence_sha256": source_sha,
        "jdbc_restart_evidence_fingerprint": jdbc_fingerprint,
        "target_identity": profile.target.identity if profile else None,
        "runtime_binding_scope": (
            "cluster_namespace_service_statefulsets_persistent_volumes"
        ),
        "promotion_mode": (
            "bounded_create_then_pre_and_post_restart_zero_mutation_replay"
        ),
        "binding_ledger_mode": "promotion_candidate_only_no_ledger_write",
        "files": files,
        "errors": errors,
    }
    return {
        **stable,
        "status": "valid" if not errors else "invalid",
        "contract_sha256": canonical_json_fingerprint(stable),
        "provider_mutations_executed": False,
        "durable_candidate_persisted_to_gda_control": False,
        "durable_catalog_verified": False,
        "production_ready": False,
    }


def build_evidence(
    observation: Mapping[str, Any],
    *,
    profile: DurablePromotionProfile,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        replay._reject_sensitive_fields(observation)
    except ValueError:
        errors.append("durable promotion observation contains sensitive material")
    if observation.get("schema") != OBSERVATION_SCHEMA:
        errors.append("durable promotion observation schema does not match")
    contract = build_contract_report()
    observed_contract = _mapping(observation.get("contract"))
    if (
        observed_contract.get("contract_sha256")
        != contract.get("contract_sha256")
        or observed_contract.get("source_m319_evidence_sha256")
        != M319_EVIDENCE_SHA256
        or observed_contract.get("jdbc_restart_evidence_fingerprint")
        != JDBC_RESTART_EVIDENCE_FINGERPRINT
    ):
        errors.append("durable promotion contract binding does not match")
    dataset = _mapping(observation.get("dataset_bundle"))
    errors.extend(validate_shapefile_bundle_inventory(dict(dataset)))
    plan = _mapping(observation.get("plan"))
    if (
        plan.get("resource_version_id") != str(RESOURCE_VERSION_ID)
        or plan.get("content_sha256") != dataset.get("content_sha256")
        or plan.get("target", {}).get("metalake") != profile.target.metalake
        or plan.get("target", {}).get("catalog") != profile.target.catalog
        or plan.get("target", {}).get("schema") != profile.target.schema_name
        or plan.get("target", {}).get("table") != profile.target.table
    ):
        errors.append("durable projection plan does not bind the real ResourceVersion")
    runtime_binding = _mapping(observation.get("runtime_binding"))
    if observation.get("runtime_binding_sha256") != canonical_json_fingerprint(
        runtime_binding
    ):
        errors.append("runtime-bound promotion fingerprint does not match")
    errors.extend(
        _runtime_continuity_errors(
            _mapping(observation.get("restart")),
            runtime_binding,
            cluster_uid=str(observation.get("cluster_uid") or ""),
            target=profile.target,
        )
    )
    openmetadata = _mapping(observation.get("openmetadata"))
    source_openmetadata = _mapping(
        _mapping(observation.get("source_m319_first_readback")).get("openmetadata")
    )
    if dict(openmetadata) != dict(source_openmetadata):
        errors.append("retained OpenMetadata readback does not match M3-19")
    if observation.get("openmetadata_mutation_count") != 0:
        errors.append("durable promotion may not mutate retained OpenMetadata")
    bootstrap = _mapping(observation.get("bootstrap"))
    post_security = _mapping(observation.get("post_restart_security"))
    expected_role = identity._normalize_securable_objects(_expected_role(profile))
    if (
        bootstrap.get("admin_authentication_status") != 200
        or bootstrap.get("bounded_authentication_status") != 200
        or bootstrap.get("server_version") != "1.3.0"
        or bootstrap.get("catalog_backend") != "jdbc"
        or bootstrap.get("denied_catalog_create_status") != 403
        or _mapping(bootstrap.get("role")).get("securable_objects")
        != expected_role
        or bootstrap.get("material_recorded") is not False
        or post_security.get("bounded_authentication_status") != 200
        or post_security.get("denied_catalog_create_status") != 403
        or _mapping(post_security.get("role")).get("securable_objects")
        != expected_role
        or post_security.get("material_recorded") is not False
    ):
        errors.append("bounded Gravitino identity did not survive restart")
    first = _mapping(observation.get("first_apply"))
    immediate = _mapping(observation.get("immediate_replay"))
    post = _mapping(observation.get("post_restart_first_replay"))
    if (
        first.get("status") != "created"
        or first.get("mutation_count") != 1
        or first.get("mutations") != ["gravitino.table.create"]
    ):
        errors.append("first durable projection apply was not one bounded create")
    for label, result in (("immediate", immediate), ("post-restart", post)):
        if result.get("status") != "no_op" or result.get("mutation_count") != 0:
            errors.append(f"{label} durable projection replay was not no-op")
    for key in (
        "gravitino",
        "table_projection",
        "table_projection_sha256",
        "logical_binding_sha256",
        "promotion_candidate_sha256",
    ):
        if first.get(key) != immediate.get(key) or first.get(key) != post.get(key):
            errors.append(f"durable provider projection drifted across replay: {key}")
    if (
        first.get("logical_binding_sha256") != plan.get("logical_binding_sha256")
        or first.get("promotion_candidate_sha256")
        != plan.get("promotion_candidate_sha256")
        or plan.get("source_binding_sha256")
        == plan.get("logical_binding_sha256")
    ):
        errors.append("runtime-bound durable promotion candidate does not match plan")
    authorization = _mapping(observation.get("authorization"))
    if (
        authorization.get("action") != ACTION
        or authorization.get("provider_apply_authorized") is not True
        or not authorization.get("authorization_sha256")
    ):
        errors.append("durable provider apply authorization is not bound")
    checks = _mapping(observation.get("runtime_checks"))
    if (
        checks.get("openmetadata_port_forward_stopped") is not True
        or checks.get("gravitino_port_forwards_stopped") is not True
        or checks.get("namespace_delete_completed") is not True
        or checks.get("namespace_absent") is not True
        or checks.get("provider_objects_retained") is not False
        or checks.get("persistent_volumes_retained") is not False
        or checks.get("material_recorded") is not False
    ):
        errors.append("durable promotion runtime cleanup is incomplete")
    verified = not errors
    stable = {
        "schema": EVIDENCE_SCHEMA,
        "environment": "local_docker_desktop",
        "status": (
            "local_durable_active_metadata_promotion_verified"
            if verified
            else "blocked"
        ),
        "contract_sha256": contract.get("contract_sha256"),
        "source_m319_evidence_sha256": M319_EVIDENCE_SHA256,
        "jdbc_restart_evidence_fingerprint": JDBC_RESTART_EVIDENCE_FINGERPRINT,
        "dataset_bundle": dict(dataset),
        "resource_version_id": plan.get("resource_version_id"),
        "resource_version_content_sha256": plan.get("content_sha256"),
        "source_binding_sha256": plan.get("source_binding_sha256"),
        "logical_binding_sha256": plan.get("logical_binding_sha256"),
        "runtime_binding_sha256": observation.get("runtime_binding_sha256"),
        "promotion_candidate_sha256": plan.get("promotion_candidate_sha256"),
        "local_durable_active_metadata_promotion_verified": verified,
        "real_dataset_resource_version_bound": verified,
        "openmetadata_read_only_verified": verified,
        "bounded_gravitino_projection_verified": verified,
        "local_jdbc_catalog_restart_continuity_verified": verified,
        "local_provider_runtime_identity_bound": verified,
        "pre_restart_replay_no_op_verified": verified,
        "post_restart_first_replay_no_op_verified": verified,
        "m319_binding_ledger_untouched": verified,
        "binding_schema_changed": False,
        "durable_candidate_persisted_to_gda_control": False,
        "dataset_source_committed": False,
        "dataset_absolute_path_committed": False,
        "dataset_required_in_ci": False,
        "deployment_applied": False,
        "protected_workload_identity_verified": False,
        "provider_minimum_privilege_verified": False,
        "durable_catalog_verified": False,
        "production_object_store_verified": False,
        "oidc_verified": False,
        "tls_verified": False,
        "production_scheduler_submission_verified": False,
        "production_ingestion_verified": False,
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
        errors.append("durable promotion evidence contains sensitive material")
    stable = {key: value for key, value in evidence.items() if key != "evidence_sha256"}
    if evidence.get("evidence_sha256") != canonical_json_fingerprint(stable):
        errors.append("durable promotion evidence SHA-256 does not match")
    if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("errors") != []:
        errors.append("durable promotion evidence is not verified")
    for claim in (
        "local_durable_active_metadata_promotion_verified",
        "real_dataset_resource_version_bound",
        "openmetadata_read_only_verified",
        "bounded_gravitino_projection_verified",
        "local_jdbc_catalog_restart_continuity_verified",
        "local_provider_runtime_identity_bound",
        "pre_restart_replay_no_op_verified",
        "post_restart_first_replay_no_op_verified",
        "m319_binding_ledger_untouched",
    ):
        if evidence.get(claim) is not True:
            errors.append(f"durable promotion evidence claim is false: {claim}")
    for claim in FALSE_CLAIMS:
        if evidence.get(claim) is not False:
            errors.append(f"durable promotion evidence may not claim {claim}")
    serialized = json.dumps(evidence, ensure_ascii=True, sort_keys=True)
    for forbidden in (
        "/Users/",
        "Downloads/",
        ".tmp/",
        "host.docker.internal",
        '"password"',
        '"secret"',
        '"token"',
        '"session"',
    ):
        if forbidden in serialized:
            errors.append("durable promotion evidence contains local or secret material")
            break
    return errors


def run_live_rehearsal(
    profile_path: Path = DEFAULT_PROFILE_PATH,
) -> dict[str, Any]:
    profile = load_profile(profile_path)
    source, runtime_profile = _load_dependencies(profile)
    contract = build_contract_report(profile_path=profile_path)
    if contract.get("status") != "valid":
        raise DurableActiveMetadataPromotionError(
            "durable promotion static contract is invalid"
        )
    provider_profile = execution.build_projection_profile(datetime.now(UTC))
    try:
        openmetadata_username = os.environ[
            provider_profile.providers.openmetadata.username_env
        ]
        openmetadata_password = SecretStr(
            os.environ[provider_profile.providers.openmetadata.password_env]
        )
    except KeyError as exc:
        raise DurableActiveMetadataPromotionError(
            "OpenMetadata local bootstrap credential environment is missing"
        ) from exc
    admin_material = SecretStr(secrets.token_urlsafe(24))
    database_material = SecretStr(secrets.token_urlsafe(24))
    user_material = SecretStr(secrets.token_urlsafe(24))
    runtime = jdbc_restart.IsolatedJdbcRestartRuntime(runtime_profile)
    om_forward: provider_metrics._PortForward | None = None
    before_forward: provider_metrics._PortForward | None = None
    after_forward: provider_metrics._PortForward | None = None
    om_client: replay.OpenMetadataApplyClient | None = None
    rehearsal: DurableProjectionRehearsal | None = None
    initial_runtime: dict[str, Any] | None = None
    restart: dict[str, Any] | None = None
    openmetadata_observation: bridge.OpenMetadataObservation | None = None
    plan: DurableProjectionPlan | None = None
    authorization: tuple[PlatformRun, Artifact, Artifact, Artifact, str] | None = None
    bootstrap: dict[str, Any] | None = None
    first_apply: dict[str, Any] | None = None
    immediate_replay: dict[str, Any] | None = None
    post_restart_security: dict[str, Any] | None = None
    post_restart_replay: dict[str, Any] | None = None
    cluster_uid: str | None = None
    runtime_binding: dict[str, Any] | None = None
    om_forward_stopped = False
    before_forward_stopped = False
    after_forward_stopped = False
    cleanup = {
        "namespace_delete_completed": False,
        "namespace_absent": False,
        "provider_objects_retained": True,
        "persistent_volumes_retained": True,
    }
    try:
        initial_runtime = runtime.start(
            admin_material=admin_material,
            database_material=database_material,
        )
        cluster = runtime.kubectl.get_json(
            ["get", "namespace", "kube-system"],
            label="durable promotion cluster identity",
        )
        cluster_uid = str(_mapping(_mapping(cluster).get("metadata")).get("uid"))
        runtime_binding = _provider_runtime_binding(
            initial_runtime,
            cluster_uid=cluster_uid,
            target=profile.target,
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
        om_payload = om_client.get_table(
            provider_profile.targets.openmetadata.table_fqn
        )
        if om_payload is None:
            raise DurableActiveMetadataPromotionError(
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

        plan = build_projection_plan(
            profile, source, openmetadata_observation, runtime_binding
        )
        authorized_at = datetime.now(UTC)
        authorization = build_apply_authorization(
            plan, profile, authorized_at=authorized_at
        )
        before_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=runtime_profile.cluster.context,
            namespace=runtime_profile.cluster.rehearsal_namespace,
            service=runtime_profile.runtime.service,
            target_port=runtime_profile.runtime.service_port,
        )
        before_forward.start()
        rehearsal = DurableProjectionRehearsal(
            base_url=f"http://127.0.0.1:{before_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        bootstrap = rehearsal.bootstrap(
            profile,
            database_material=database_material,
            user_material=user_material,
        )
        first_apply = rehearsal.apply_once(
            plan, authorization, at=authorized_at, create=True
        )
        immediate_replay = rehearsal.apply_once(
            plan, authorization, at=authorized_at + timedelta(seconds=1)
        )
        rehearsal.close()
        rehearsal = None
        before_forward_stopped = before_forward.stop()
        before_forward = None

        restart = runtime.restart()

        after_forward = provider_metrics._PortForward(
            kubectl="kubectl",
            context=runtime_profile.cluster.context,
            namespace=runtime_profile.cluster.rehearsal_namespace,
            service=runtime_profile.runtime.service,
            target_port=runtime_profile.runtime.service_port,
        )
        after_forward.start()
        rehearsal = DurableProjectionRehearsal(
            base_url=f"http://127.0.0.1:{after_forward.local_port}/api",
            admin_name=profile.identity.service_admin,
            admin_material=admin_material,
        )
        post_restart_security = rehearsal.reconnect_bounded(
            profile, user_material
        )
        post_restart_replay = rehearsal.apply_once(
            plan, authorization, at=authorized_at + timedelta(seconds=2)
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
        cleanup = runtime.cleanup()
    required = (
        initial_runtime,
        restart,
        openmetadata_observation,
        plan,
        authorization,
        bootstrap,
        first_apply,
        immediate_replay,
        post_restart_security,
        post_restart_replay,
        cluster_uid,
        runtime_binding,
    )
    if any(value is None for value in required):
        raise DurableActiveMetadataPromotionError(
            "durable promotion rehearsal did not produce a complete outcome"
        )
    assert isinstance(openmetadata_observation, bridge.OpenMetadataObservation)
    assert isinstance(plan, DurableProjectionPlan)
    run, execution_plan, policy_artifact, approval_artifact, auth_sha = authorization
    source_openmetadata = _mapping(
        _mapping(source.get("first_readback")).get("openmetadata")
    )
    observation = {
        "schema": OBSERVATION_SCHEMA,
        "observed_at": datetime.now(UTC).isoformat(),
        "contract": {
            "contract_sha256": contract["contract_sha256"],
            "source_m319_evidence_sha256": M319_EVIDENCE_SHA256,
            "jdbc_restart_evidence_fingerprint": (
                JDBC_RESTART_EVIDENCE_FINGERPRINT
            ),
        },
        "dataset_bundle": source["dataset_bundle"],
        "source_m319_first_readback": source["first_readback"],
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
        "post_restart_security": post_restart_security,
        "post_restart_first_replay": post_restart_replay,
        "runtime_checks": {
            **cleanup,
            "openmetadata_port_forward_stopped": om_forward_stopped,
            "gravitino_port_forwards_stopped": (
                before_forward_stopped and after_forward_stopped
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
        if evidence.get("contract_sha256") != contract.get("contract_sha256"):
            errors.append("durable promotion evidence contract fingerprint is stale")
    except DurableActiveMetadataPromotionError as exc:
        errors.append(f"durable promotion evidence is invalid: {type(exc).__name__}")
    verified = not errors
    return {
        "schema": VALIDATION_SCHEMA,
        "status": "valid" if verified else "invalid",
        "local_static_contract_verified": contract.get("status") == "valid",
        "local_durable_active_metadata_promotion_verified": (
            verified
            and evidence is not None
            and evidence.get("local_durable_active_metadata_promotion_verified")
            is True
        ),
        "local_provider_runtime_identity_bound": (
            verified
            and evidence is not None
            and evidence.get("local_provider_runtime_identity_bound") is True
        ),
        "durable_candidate_persisted_to_gda_control": False,
        "durable_catalog_verified": False,
        "production_ingestion_verified": False,
        "production_ready": False,
        "contract_sha256": contract.get("contract_sha256"),
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
    rehearse = subparsers.add_parser("rehearse")
    rehearse.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_PATH)
    rehearse.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate":
        report = build_validation_report(
            profile_path=args.profile, evidence_path=args.evidence
        )
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if not report["errors"] else 1

    evidence = run_live_rehearsal(args.profile)
    _write_json(args.evidence_out, evidence)
    print(json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if not evidence["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
