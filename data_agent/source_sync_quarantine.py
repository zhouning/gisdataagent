"""Provider-neutral recording for SourceSync rejected-record outputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from .platform_contracts import (
    Artifact,
    ArtifactRole,
    Resource,
    ResourceVersion,
    SourceSyncCommit,
    SourceSyncDefinitionVersion,
    SourceSyncQuarantineEvidence,
    parse_resource_urn,
    source_sync_quarantine_evidence_fingerprint,
)
from .platform_gateway import PlatformGateway

_MANIFEST_SCHEMA = "gda.source_sync_quarantine.v1"
_CORE_MANIFEST_KEYS = frozenset(
    {
        "schema",
        "source_slice_sha256",
        "sync_definition_version_id",
        "records_rejected",
        "reason_counts",
        "target_content_sha256",
        "rejected_content_sha256",
    }
)


@dataclass(frozen=True)
class SourceSyncQuarantineContract:
    """Stable provider and ownership identity for one quarantine Resource."""

    quarantine_resource_urn: str
    authority_system: str
    authority_locator: str
    owner_ref: str
    artifact_key_prefix: str
    governance_ref: dict[str, Any] = field(default_factory=dict)
    technical_refs: tuple[dict[str, Any], ...] = ()

    @staticmethod
    def resource_version_id(sync_commit_id: UUID) -> UUID:
        return uuid5(sync_commit_id, "source-sync:quarantine-resource-version")

    @staticmethod
    def artifact_id(sync_commit_id: UUID) -> UUID:
        return uuid5(sync_commit_id, "source-sync:quarantine-artifact")


@dataclass(frozen=True)
class ProviderQuarantineReceipt:
    """Physical rejection output already committed by a provider adapter."""

    storage_uri: str
    media_type: str
    content_sha256: str
    size_bytes: int
    records_rejected: int
    reason_counts: dict[str, int]
    manifest_facets: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceSyncQuarantineRecord:
    resource: Resource
    resource_version: ResourceVersion
    artifact: Artifact
    evidence: SourceSyncQuarantineEvidence
    replayed: bool


class SourceSyncQuarantineRecorder:
    """Register a provider receipt before the authority atomically binds it."""

    def __init__(
        self,
        contract: SourceSyncQuarantineContract,
        *,
        gateway: PlatformGateway,
    ) -> None:
        self.contract = contract
        self.gateway = gateway

    def record(
        self,
        *,
        definition: SourceSyncDefinitionVersion,
        commit: SourceSyncCommit,
        receipt: ProviderQuarantineReceipt,
        recorded_at: datetime,
    ) -> SourceSyncQuarantineRecord:
        governance = definition.governance_contract
        target_layer = governance.target_layer.value if governance is not None else None
        if target_layer not in {"silver", "gold"}:
            raise ValueError("quarantine receipts require a Silver or Gold definition")
        if governance.quarantine_resource_urn != self.contract.quarantine_resource_urn:
            raise ValueError("quarantine contract does not match the SourceSync definition")
        if (
            commit.tenant_id != definition.tenant_id
            or commit.sync_definition_version_id
            != definition.sync_definition_version_id
        ):
            raise ValueError("quarantine commit does not match the SourceSync definition")
        if recorded_at > commit.committed_at:
            raise ValueError("quarantine receipt cannot be recorded after its commit")
        overlapping_keys = _CORE_MANIFEST_KEYS.intersection(receipt.manifest_facets)
        if overlapping_keys:
            raise ValueError("provider facets cannot override quarantine receipt identity")
        if receipt.records_rejected > 0 and receipt.size_bytes == 0:
            raise ValueError("rejected records require a non-empty physical artifact")

        resource_identity = parse_resource_urn(
            self.contract.quarantine_resource_urn
        )
        resource = Resource(
            tenant_id=commit.tenant_id,
            resource_urn=self.contract.quarantine_resource_urn,
            resource_kind=resource_identity["resource_kind"],
            authority_system=self.contract.authority_system,
            authority_locator=self.contract.authority_locator,
            owner_ref=self.contract.owner_ref,
            governance_ref=self.contract.governance_ref,
            technical_refs=self.contract.technical_refs,
        )
        resource_version_id = self.contract.resource_version_id(
            commit.sync_commit_id
        )
        resource_version = ResourceVersion(
            tenant_id=commit.tenant_id,
            resource_urn=self.contract.quarantine_resource_urn,
            resource_version_id=resource_version_id,
            version_key=f"commit-{commit.sync_commit_id}",
            content_sha256=receipt.content_sha256,
            authority_version_ref={
                "schema": _MANIFEST_SCHEMA,
                "sync_commit_id": str(commit.sync_commit_id),
                "run_id": str(commit.run_id),
                "source_slice_sha256": commit.source_slice_sha256,
                "records_rejected": receipt.records_rejected,
                "reason_counts": receipt.reason_counts,
            },
            created_by=commit.committed_by,
            created_at=recorded_at,
        )
        artifact_id = self.contract.artifact_id(commit.sync_commit_id)
        manifest = {
            "schema": _MANIFEST_SCHEMA,
            "source_slice_sha256": commit.source_slice_sha256,
            "sync_definition_version_id": str(
                commit.sync_definition_version_id
            ),
            "records_rejected": receipt.records_rejected,
            "reason_counts": receipt.reason_counts,
            "target_content_sha256": commit.target_content_sha256,
            "rejected_content_sha256": receipt.content_sha256,
            **receipt.manifest_facets,
        }
        artifact = Artifact(
            tenant_id=commit.tenant_id,
            artifact_id=artifact_id,
            artifact_key=(
                f"{self.contract.artifact_key_prefix}_"
                f"{commit.sync_commit_id.hex[:12]}"
            ),
            artifact_role=ArtifactRole.QUARANTINE,
            storage_uri=receipt.storage_uri,
            media_type=receipt.media_type,
            content_sha256=receipt.content_sha256,
            size_bytes=receipt.size_bytes,
            run_id=commit.run_id,
            resource_version_id=resource_version_id,
            manifest=manifest,
            created_by=commit.committed_by,
            created_at=recorded_at,
        )
        evidence_values = {
            "tenant_id": commit.tenant_id,
            "sync_commit_id": commit.sync_commit_id,
            "source_slice_sha256": commit.source_slice_sha256,
            "quarantine_resource_version_id": resource_version_id,
            "quarantine_artifact_id": artifact_id,
            "records_rejected": receipt.records_rejected,
            "reason_counts": receipt.reason_counts,
        }
        evidence = SourceSyncQuarantineEvidence(
            **evidence_values,
            evidence_sha256=source_sync_quarantine_evidence_fingerprint(
                **evidence_values
            ),
        )

        resource_result = self.gateway.register_resource(resource)
        version_result = self.gateway.register_resource_version(resource_version)
        artifact_result = self.gateway.record_artifact(artifact)
        return SourceSyncQuarantineRecord(
            resource=resource,
            resource_version=resource_version,
            artifact=artifact,
            evidence=evidence,
            replayed=not any(
                result.created
                for result in (
                    resource_result,
                    version_result,
                    artifact_result,
                )
            ),
        )
