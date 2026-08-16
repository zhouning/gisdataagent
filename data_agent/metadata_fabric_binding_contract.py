"""Content-bound contract for the Metadata Fabric binding ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from .metadata_fabric_bridge import MetadataFabricBinding
from .metadata_fabric_ingestion import ProviderProjection
from .platform_contracts import (
    Artifact,
    ArtifactRole,
    Sha256,
    TenantId,
    canonical_json_bytes,
    canonical_json_fingerprint,
)

BINDING_RECORD_SCHEMA = "gda.metadata_fabric_binding_record.v1"
APPLY_PLAN_SCHEMA = "gda.metadata_fabric_local_apply_plan.v1"
EXECUTION_PLAN_SCHEMA = "gda.metadata_fabric_local_apply_execution_plan.v1"
EXECUTION_PLAN_MEDIA_TYPE = (
    "application/vnd.gda.metadata-fabric-apply-plan+json"
)
PROVIDER_EVIDENCE_SCHEMA = "gda.metadata_fabric_provider_binding_evidence.v1"
PROVIDER_EVIDENCE_MEDIA_TYPE = (
    "application/vnd.gda.metadata-fabric-provider-binding-evidence+json"
)
SOURCE_EVIDENCE_SCHEMA = "gda.metadata_fabric_local_ingestion_evidence.v1"

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]


class MetadataFabricBindingContractError(ValueError):
    """A binding record or its provider evidence is not content-bound."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("fingerprinted time must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class MetadataFabricApplyPlan(_FrozenModel):
    apply_schema: Literal["gda.metadata_fabric_local_apply_plan.v1"] = Field(
        default=APPLY_PLAN_SCHEMA,
        alias="schema",
    )
    source_plan_sha256: Sha256
    tenant_id: TenantId
    run_id: UUID
    definition_version_id: UUID
    source_resource_version_id: UUID
    resource_urn: NonEmptyText
    resource_version_id: UUID
    content_sha256: Sha256
    openmetadata_fqn: NonEmptyText
    gravitino_identity: NonEmptyText
    projections: tuple[ProviderProjection, ...]
    provider_apply_authorized: Literal[False] = False
    writes_to_gda_control: Literal[False] = False
    writes_to_legacy: Literal[False] = False
    apply_plan_sha256: Sha256

    @model_validator(mode="after")
    def _content_bound(self) -> Self:
        if [item.provider for item in self.projections] != [
            "openmetadata",
            "gravitino",
        ]:
            raise ValueError("Metadata Fabric plan requires two ordered providers")
        expected_identity = (
            self.resource_urn,
            str(self.resource_version_id),
            self.content_sha256,
        )
        for projection in self.projections:
            observed = tuple(
                projection.desired_state[key]
                for key in (
                    "resource_urn",
                    "resource_version_id",
                    "content_sha256",
                )
            )
            if observed != expected_identity:
                raise ValueError(
                    "Metadata Fabric projection identity does not match plan"
                )
        stable = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"apply_plan_sha256"},
        )
        if self.apply_plan_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("Metadata Fabric apply plan SHA-256 does not match")
        return self


def parse_metadata_fabric_execution_plan_artifact(
    artifact: Artifact,
) -> MetadataFabricApplyPlan:
    try:
        if set(artifact.manifest) != {"schema", "plan"}:
            raise ValueError("execution plan envelope fields do not match")
        if artifact.manifest["schema"] != EXECUTION_PLAN_SCHEMA:
            raise ValueError("execution plan envelope schema does not match")
        plan = MetadataFabricApplyPlan.model_validate(artifact.manifest["plan"])
        artifact_id = uuid5(
            plan.run_id,
            f"metadata-fabric-apply:{plan.apply_plan_sha256}",
        )
        manifest = {
            "schema": EXECUTION_PLAN_SCHEMA,
            "plan": plan.model_dump(mode="json", by_alias=True),
        }
        expected = Artifact(
            tenant_id=plan.tenant_id,
            artifact_id=artifact_id,
            artifact_key=f"metadata-fabric-apply:{artifact_id}",
            artifact_role=ArtifactRole.EXECUTION_PLAN,
            storage_uri=(
                "postgresql://gda-control/execution-plans/"
                f"{plan.tenant_id}/{artifact_id}"
            ),
            media_type=EXECUTION_PLAN_MEDIA_TYPE,
            content_sha256=canonical_json_fingerprint(manifest),
            size_bytes=len(canonical_json_bytes(manifest)),
            run_id=None,
            resource_version_id=plan.definition_version_id,
            manifest=manifest,
            created_by=artifact.created_by,
            created_at=artifact.created_at,
        )
    except Exception as exc:
        raise MetadataFabricBindingContractError(
            "Metadata Fabric execution plan Artifact is invalid"
        ) from exc
    if artifact != expected:
        raise MetadataFabricBindingContractError(
            "Metadata Fabric execution plan Artifact is not content-bound"
        )
    return plan


def metadata_fabric_provider_evidence_fingerprint(
    *,
    binding: MetadataFabricBinding,
    source_evidence_sha256: str,
    openmetadata_snapshot_sha256: str,
    gravitino_snapshot_sha256: str,
    first_apply_status: str,
    first_apply_mutation_count: int,
    replay_status: str,
    replay_mutation_count: int,
    observed_at: datetime,
) -> str:
    return canonical_json_fingerprint(
        {
            "binding": binding.model_dump(mode="json", by_alias=True),
            "source_evidence_schema": SOURCE_EVIDENCE_SCHEMA,
            "source_evidence_sha256": source_evidence_sha256,
            "openmetadata_snapshot_sha256": openmetadata_snapshot_sha256,
            "gravitino_snapshot_sha256": gravitino_snapshot_sha256,
            "first_apply_status": first_apply_status,
            "first_apply_mutation_count": first_apply_mutation_count,
            "replay_status": replay_status,
            "replay_mutation_count": replay_mutation_count,
            "observed_at": _utc_iso(observed_at),
            "local_provider_evidence": True,
            "production_ready": False,
        }
    )


class MetadataFabricProviderEvidence(_FrozenModel):
    evidence_schema: Literal[
        "gda.metadata_fabric_provider_binding_evidence.v1"
    ] = Field(default=PROVIDER_EVIDENCE_SCHEMA, alias="schema")
    binding: MetadataFabricBinding
    source_evidence_schema: Literal[
        "gda.metadata_fabric_local_ingestion_evidence.v1"
    ] = SOURCE_EVIDENCE_SCHEMA
    source_evidence_sha256: Sha256
    openmetadata_snapshot_sha256: Sha256
    gravitino_snapshot_sha256: Sha256
    first_apply_status: Literal["created", "no_op"]
    first_apply_mutation_count: Annotated[int, Field(ge=0)]
    replay_status: Literal["no_op"]
    replay_mutation_count: Literal[0]
    observed_at: datetime
    local_provider_evidence: Literal[True] = True
    production_ready: Literal[False] = False
    evidence_sha256: Sha256

    @field_validator("observed_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider evidence time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _content_bound(self) -> Self:
        if (self.first_apply_status == "no_op") != (
            self.first_apply_mutation_count == 0
        ):
            raise ValueError("first apply status does not match its mutation count")
        expected = metadata_fabric_provider_evidence_fingerprint(
            binding=self.binding,
            source_evidence_sha256=self.source_evidence_sha256,
            openmetadata_snapshot_sha256=self.openmetadata_snapshot_sha256,
            gravitino_snapshot_sha256=self.gravitino_snapshot_sha256,
            first_apply_status=self.first_apply_status,
            first_apply_mutation_count=self.first_apply_mutation_count,
            replay_status=self.replay_status,
            replay_mutation_count=self.replay_mutation_count,
            observed_at=self.observed_at,
        )
        if self.evidence_sha256 != expected:
            raise ValueError("provider evidence SHA-256 does not match its payload")
        return self


def build_metadata_fabric_provider_evidence(
    *,
    binding: MetadataFabricBinding,
    source_evidence_sha256: str,
    openmetadata_snapshot_sha256: str,
    gravitino_snapshot_sha256: str,
    first_apply_status: Literal["created", "no_op"],
    first_apply_mutation_count: int,
    observed_at: datetime,
) -> MetadataFabricProviderEvidence:
    values: dict[str, Any] = {
        "binding": binding,
        "source_evidence_sha256": source_evidence_sha256,
        "openmetadata_snapshot_sha256": openmetadata_snapshot_sha256,
        "gravitino_snapshot_sha256": gravitino_snapshot_sha256,
        "first_apply_status": first_apply_status,
        "first_apply_mutation_count": first_apply_mutation_count,
        "replay_status": "no_op",
        "replay_mutation_count": 0,
        "observed_at": observed_at,
    }
    return MetadataFabricProviderEvidence(
        **values,
        evidence_sha256=metadata_fabric_provider_evidence_fingerprint(**values),
    )


def _provider_evidence_artifact_id(evidence: MetadataFabricProviderEvidence) -> UUID:
    return uuid5(
        evidence.binding.resource_version_id,
        f"metadata-fabric-provider-evidence:{evidence.evidence_sha256}",
    )


def build_metadata_fabric_provider_evidence_artifact(
    evidence: MetadataFabricProviderEvidence,
    *,
    created_by: str,
) -> Artifact:
    if not created_by.startswith("workload:"):
        raise MetadataFabricBindingContractError(
            "provider evidence creator must use workload identity"
        )
    manifest = evidence.model_dump(mode="json", by_alias=True)
    artifact_id = _provider_evidence_artifact_id(evidence)
    return Artifact(
        tenant_id=evidence.binding.tenant_id,
        artifact_id=artifact_id,
        artifact_key=f"metadata-fabric-provider-evidence:{artifact_id}",
        artifact_role=ArtifactRole.EVIDENCE,
        storage_uri=(
            "postgresql://gda-control/metadata-fabric-provider-evidence/"
            f"{evidence.binding.tenant_id}/{artifact_id}"
        ),
        media_type=PROVIDER_EVIDENCE_MEDIA_TYPE,
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(canonical_json_bytes(manifest)),
        run_id=None,
        resource_version_id=evidence.binding.resource_version_id,
        manifest=manifest,
        created_by=created_by,
        created_at=evidence.observed_at,
    )


def parse_metadata_fabric_provider_evidence_artifact(
    artifact: Artifact,
) -> MetadataFabricProviderEvidence:
    try:
        evidence = MetadataFabricProviderEvidence.model_validate(artifact.manifest)
    except Exception as exc:
        raise MetadataFabricBindingContractError(
            "provider binding evidence manifest is invalid"
        ) from exc
    expected = build_metadata_fabric_provider_evidence_artifact(
        evidence,
        created_by=artifact.created_by,
    )
    if artifact != expected:
        raise MetadataFabricBindingContractError(
            "provider binding evidence Artifact metadata does not match its manifest"
        )
    return evidence


def metadata_fabric_binding_id(resource_version_id: UUID) -> UUID:
    return uuid5(resource_version_id, BINDING_RECORD_SCHEMA)


def metadata_fabric_binding_record_fingerprint(
    *,
    binding: MetadataFabricBinding,
    execution_plan_artifact_id: UUID,
    policy_decision_artifact_id: UUID,
    approval_artifact_id: UUID,
    provider_evidence_artifact_id: UUID,
    recorded_by: str,
    recorded_at: datetime,
) -> str:
    return canonical_json_fingerprint(
        {
            "binding": binding.model_dump(mode="json", by_alias=True),
            "execution_plan_artifact_id": str(execution_plan_artifact_id),
            "policy_decision_artifact_id": str(policy_decision_artifact_id),
            "approval_artifact_id": str(approval_artifact_id),
            "provider_evidence_artifact_id": str(provider_evidence_artifact_id),
            "recorded_by": recorded_by,
            "recorded_at": _utc_iso(recorded_at),
        }
    )


class MetadataFabricBindingRecord(_FrozenModel):
    record_schema: Literal["gda.metadata_fabric_binding_record.v1"] = Field(
        default=BINDING_RECORD_SCHEMA,
        alias="schema",
    )
    tenant_id: TenantId
    binding_id: UUID
    binding: MetadataFabricBinding
    execution_plan_artifact_id: UUID
    policy_decision_artifact_id: UUID
    approval_artifact_id: UUID
    provider_evidence_artifact_id: UUID
    recorded_by: NonEmptyText
    recorded_at: datetime
    record_sha256: Sha256

    @field_validator("recorded_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("binding record time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _content_bound(self) -> Self:
        if self.tenant_id != self.binding.tenant_id:
            raise ValueError("binding record tenant does not match binding")
        if self.binding_id != metadata_fabric_binding_id(
            self.binding.resource_version_id
        ):
            raise ValueError("binding ID does not match target ResourceVersion")
        artifact_ids = {
            self.execution_plan_artifact_id,
            self.policy_decision_artifact_id,
            self.approval_artifact_id,
            self.provider_evidence_artifact_id,
        }
        if len(artifact_ids) != 4:
            raise ValueError("binding record Artifact references must be distinct")
        if not self.recorded_by.startswith("workload:"):
            raise ValueError("binding recorder must use workload identity")
        expected = metadata_fabric_binding_record_fingerprint(
            binding=self.binding,
            execution_plan_artifact_id=self.execution_plan_artifact_id,
            policy_decision_artifact_id=self.policy_decision_artifact_id,
            approval_artifact_id=self.approval_artifact_id,
            provider_evidence_artifact_id=self.provider_evidence_artifact_id,
            recorded_by=self.recorded_by,
            recorded_at=self.recorded_at,
        )
        if self.record_sha256 != expected:
            raise ValueError("binding record SHA-256 does not match its payload")
        return self


def build_metadata_fabric_binding_record(
    *,
    binding: MetadataFabricBinding,
    execution_plan_artifact_id: UUID,
    policy_decision_artifact_id: UUID,
    approval_artifact_id: UUID,
    provider_evidence_artifact_id: UUID,
    recorded_by: str,
    recorded_at: datetime,
) -> MetadataFabricBindingRecord:
    values = {
        "binding": binding,
        "execution_plan_artifact_id": execution_plan_artifact_id,
        "policy_decision_artifact_id": policy_decision_artifact_id,
        "approval_artifact_id": approval_artifact_id,
        "provider_evidence_artifact_id": provider_evidence_artifact_id,
        "recorded_by": recorded_by,
        "recorded_at": recorded_at,
    }
    return MetadataFabricBindingRecord(
        tenant_id=binding.tenant_id,
        binding_id=metadata_fabric_binding_id(binding.resource_version_id),
        **values,
        record_sha256=metadata_fabric_binding_record_fingerprint(**values),
    )
