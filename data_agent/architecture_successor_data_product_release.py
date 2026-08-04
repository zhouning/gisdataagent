"""Approval-bound release of an adopted architecture successor as a DataProductVersion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from .approval_case_authority import ApprovalCaseAuthority
from .architecture_successor_adoption import (
    ARCHITECTURE_SUCCESSOR_ADOPTION_ACTION,
    ArchitectureSuccessorPlan,
    build_architecture_successor_adoption_case,
)
from .data_product_registry import (
    DataProductRegistry,
    DataProductSpec,
    DataProductVersionSpec,
)
from .platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    Artifact,
    ArtifactRole,
    ResourceURNText,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
)

ARCHITECTURE_SUCCESSOR_RELEASE_SCHEMA = (
    "gda.architecture_successor_data_product_release.v1"
)
ARCHITECTURE_SUCCESSOR_RELEASE_ACTION = "data_product.publish_architecture_successor"


class ArchitectureSuccessorDataProductReleaseError(ValueError):
    """The release plan, evidence, or approval binding is inconsistent."""


def _request_binding(case: ApprovalCase) -> tuple[Any, ...]:
    return (
        case.tenant_id,
        case.approval_case_ref,
        case.target_resource_urn,
        case.target_fingerprint,
        case.action,
        case.requester_subject,
        case.request_reason,
        case.request_context,
        case.requested_at,
        case.expires_at,
    )


def _distribution_artifact_refs(
    distribution_manifest: dict[str, Any],
) -> dict[UUID, dict[str, Any]]:
    formats = distribution_manifest.get("formats")
    if not isinstance(formats, list) or not formats:
        raise ArchitectureSuccessorDataProductReleaseError(
            "architecture successor release requires at least one distribution Artifact"
        )
    refs: dict[UUID, dict[str, Any]] = {}
    for item in formats:
        if not isinstance(item, dict):
            raise ArchitectureSuccessorDataProductReleaseError(
                "distribution format entries must be objects"
            )
        try:
            artifact_id = UUID(str(item["artifact_id"]))
            content_sha256 = str(item["content_sha256"])
            size_bytes = int(item["size_bytes"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ArchitectureSuccessorDataProductReleaseError(
                "each distribution format must bind artifact_id, content_sha256 and size_bytes"
            ) from exc
        if artifact_id in refs:
            raise ArchitectureSuccessorDataProductReleaseError(
                "distribution Artifact identities must be unique"
            )
        refs[artifact_id] = {
            "content_sha256": content_sha256,
            "size_bytes": size_bytes,
        }
    return refs


def architecture_successor_release_fingerprint(
    *,
    tenant_id: str,
    product_urn: str,
    product: DataProductSpec,
    predecessor_data_product_version: DataProductVersionSpec,
    successor_data_product_version: DataProductVersionSpec,
    architecture_successor_plan: ArchitectureSuccessorPlan,
    architecture_adoption_case: ApprovalCase,
    quality_evidence_artifact: Artifact,
    distribution_artifacts: tuple[Artifact, ...],
    rollback_target_version_id: UUID,
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": ARCHITECTURE_SUCCESSOR_RELEASE_SCHEMA,
            "tenant_id": tenant_id,
            "product_urn": product_urn,
            "product": product.model_dump(mode="json"),
            "predecessor_data_product_version": (
                predecessor_data_product_version.model_dump(mode="json")
            ),
            "successor_data_product_version": (
                successor_data_product_version.model_dump(mode="json")
            ),
            "architecture_successor_plan": architecture_successor_plan.model_dump(
                mode="json"
            ),
            "architecture_adoption_case": architecture_adoption_case.model_dump(
                mode="json"
            ),
            "quality_evidence_artifact": quality_evidence_artifact.model_dump(
                mode="json"
            ),
            "distribution_artifacts": [
                artifact.model_dump(mode="json") for artifact in distribution_artifacts
            ],
            "rollback_target_version_id": str(rollback_target_version_id),
        }
    )


class ArchitectureSuccessorDataProductReleasePlan(BaseModel):
    """Complete immutable evidence authorized for one successor product release."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    product_urn: ResourceURNText
    product: DataProductSpec
    predecessor_data_product_version: DataProductVersionSpec
    successor_data_product_version: DataProductVersionSpec
    architecture_successor_plan: ArchitectureSuccessorPlan
    architecture_adoption_case: ApprovalCase
    quality_evidence_artifact: Artifact
    distribution_artifacts: tuple[Artifact, ...]
    rollback_target_version_id: UUID
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_plan(self) -> ArchitectureSuccessorDataProductReleasePlan:
        identity = parse_resource_urn(self.product_urn)
        if (
            identity["tenant_id"] != self.tenant_id
            or identity["resource_kind"] != "data_product"
        ):
            raise ValueError("release target must be a tenant DataProduct ResourceURN")
        predecessor = self.predecessor_data_product_version
        successor = self.successor_data_product_version
        adoption_plan = self.architecture_successor_plan
        adoption_case = self.architecture_adoption_case
        if (
            self.product.tenant_id != self.tenant_id
            or self.product.product_urn != self.product_urn
            or predecessor.tenant_id != self.tenant_id
            or predecessor.product_urn != self.product_urn
            or successor.tenant_id != self.tenant_id
            or successor.product_urn != self.product_urn
        ):
            raise ValueError("release product and version identities must match")
        if successor.predecessor_version_id != predecessor.data_product_version_id:
            raise ValueError("successor product version must name the released predecessor")
        if self.rollback_target_version_id != predecessor.data_product_version_id:
            raise ValueError("rollback target must be the immediate product predecessor")
        if (
            adoption_plan.tenant_id != self.tenant_id
            or predecessor.output_resource_version_id
            != adoption_plan.predecessor_resource_version_id
            or successor.output_resource_version_id
            != adoption_plan.successor_resource_version.resource_version_id
        ):
            raise ValueError(
                "product output versions must follow the adopted architecture successor chain"
            )
        expected_adoption_case = build_architecture_successor_adoption_case(
            adoption_plan,
            requester_subject=adoption_case.requester_subject,
            request_reason=adoption_case.request_reason,
            requested_at=adoption_case.requested_at,
            expires_at=adoption_case.expires_at,
        )
        if (
            adoption_case.status is not ApprovalCaseStatus.APPROVED
            or adoption_case.action != ARCHITECTURE_SUCCESSOR_ADOPTION_ACTION
            or _request_binding(adoption_case) != _request_binding(expected_adoption_case)
        ):
            raise ValueError("release requires the approved architecture adoption plan")
        if (
            adoption_case.decided_at is None
            or adoption_case.decided_at > successor.published_at
        ):
            raise ValueError("product publication time must follow architecture adoption")

        output_version_id = successor.output_resource_version_id
        quality = self.quality_evidence_artifact
        if (
            quality.tenant_id != self.tenant_id
            or quality.artifact_id != successor.quality_evidence_artifact_id
            or quality.artifact_role is not ArtifactRole.EVIDENCE
            or quality.resource_version_id != output_version_id
        ):
            raise ValueError(
                "quality evidence Artifact must be bound to the successor output version"
            )

        refs = _distribution_artifact_refs(successor.distribution_manifest)
        if tuple(sorted(refs, key=str)) != tuple(
            artifact.artifact_id for artifact in self.distribution_artifacts
        ):
            raise ValueError(
                "distribution Artifacts must exactly match the successor manifest"
            )
        for artifact in self.distribution_artifacts:
            expected = refs[artifact.artifact_id]
            if (
                artifact.tenant_id != self.tenant_id
                or artifact.artifact_role is not ArtifactRole.OUTPUT
                or artifact.resource_version_id != output_version_id
                or artifact.content_sha256 != expected["content_sha256"]
                or artifact.size_bytes != expected["size_bytes"]
            ):
                raise ValueError(
                    "distribution Artifact content must be bound to the successor output version"
                )

        expected_sha256 = architecture_successor_release_fingerprint(
            tenant_id=self.tenant_id,
            product_urn=self.product_urn,
            product=self.product,
            predecessor_data_product_version=predecessor,
            successor_data_product_version=successor,
            architecture_successor_plan=adoption_plan,
            architecture_adoption_case=adoption_case,
            quality_evidence_artifact=quality,
            distribution_artifacts=self.distribution_artifacts,
            rollback_target_version_id=self.rollback_target_version_id,
        )
        if self.plan_sha256 != expected_sha256:
            raise ValueError("plan_sha256 does not match architecture successor release")
        return self

    def approval_context(self) -> dict[str, Any]:
        successor = self.successor_data_product_version
        architecture = self.architecture_successor_plan
        return {
            "schema": ARCHITECTURE_SUCCESSOR_RELEASE_SCHEMA,
            "plan_sha256": self.plan_sha256,
            "data_product_version_id": str(successor.data_product_version_id),
            "predecessor_data_product_version_id": str(
                self.predecessor_data_product_version.data_product_version_id
            ),
            "successor_output_resource_version_id": str(
                successor.output_resource_version_id
            ),
            "predecessor_output_resource_version_id": str(
                self.predecessor_data_product_version.output_resource_version_id
            ),
            "architecture_adoption_case_ref": (
                self.architecture_adoption_case.approval_case_ref
            ),
            "architecture_successor_plan_sha256": architecture.plan_sha256,
            "architecture_binding_sha256": (
                architecture.successor_architecture.binding.binding_sha256
            ),
            "data_product_manifest_sha256": successor.manifest_sha256,
            "quality_evidence_artifact_id": str(
                self.quality_evidence_artifact.artifact_id
            ),
            "distribution_artifact_ids": [
                str(artifact.artifact_id) for artifact in self.distribution_artifacts
            ],
            "rollback_target_version_id": str(self.rollback_target_version_id),
            "release_plan": self.model_dump(mode="json"),
        }


def build_architecture_successor_data_product_release_plan(
    *,
    product: DataProductSpec,
    predecessor_data_product_version: DataProductVersionSpec,
    successor_data_product_version: DataProductVersionSpec,
    architecture_successor_plan: ArchitectureSuccessorPlan,
    architecture_adoption_case: ApprovalCase,
    quality_evidence_artifact: Artifact,
    distribution_artifacts: tuple[Artifact, ...],
) -> ArchitectureSuccessorDataProductReleasePlan:
    ordered_artifacts = tuple(
        sorted(distribution_artifacts, key=lambda artifact: str(artifact.artifact_id))
    )
    values = {
        "tenant_id": product.tenant_id,
        "product_urn": product.product_urn,
        "product": product,
        "predecessor_data_product_version": predecessor_data_product_version,
        "successor_data_product_version": successor_data_product_version,
        "architecture_successor_plan": architecture_successor_plan,
        "architecture_adoption_case": architecture_adoption_case,
        "quality_evidence_artifact": quality_evidence_artifact,
        "distribution_artifacts": ordered_artifacts,
        "rollback_target_version_id": (
            predecessor_data_product_version.data_product_version_id
        ),
    }
    return ArchitectureSuccessorDataProductReleasePlan(
        plan_sha256=architecture_successor_release_fingerprint(**values),
        **values,
    )


def build_architecture_successor_release_approval_case(
    plan: ArchitectureSuccessorDataProductReleasePlan,
    *,
    requester_subject: str,
    request_reason: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ApprovalCase:
    return ApprovalCase(
        tenant_id=plan.tenant_id,
        approval_case_ref=build_resource_urn(
            plan.tenant_id,
            "approval_case",
            f"architecture-product-release-{plan.successor_data_product_version.data_product_version_id.hex}",
        ),
        target_resource_urn=plan.product_urn,
        target_fingerprint=plan.plan_sha256,
        action=ARCHITECTURE_SUCCESSOR_RELEASE_ACTION,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=plan.approval_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )


@dataclass(frozen=True)
class ArchitectureSuccessorReleaseRequestResult:
    plan: ArchitectureSuccessorDataProductReleasePlan
    approval_case: ApprovalCase
    created: bool


class ArchitectureSuccessorDataProductReleaseService:
    """Request independent approval and atomically publish one approved plan."""

    def __init__(
        self,
        registry: DataProductRegistry,
        approval_authority: ApprovalCaseAuthority,
    ) -> None:
        self._registry = registry
        self._approval_authority = approval_authority

    def request_release(
        self,
        plan: ArchitectureSuccessorDataProductReleasePlan,
        *,
        requester_subject: str,
        request_reason: str,
        owner_ref: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> ArchitectureSuccessorReleaseRequestResult:
        case = build_architecture_successor_release_approval_case(
            plan,
            requester_subject=requester_subject,
            request_reason=request_reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return ArchitectureSuccessorReleaseRequestResult(
            plan=plan,
            approval_case=written.approval_case,
            created=written.created,
        )

    def publish(
        self,
        plan: ArchitectureSuccessorDataProductReleasePlan,
        *,
        release_approval_case_ref: str,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._registry.publish(
            plan.product,
            plan.successor_data_product_version,
            idempotency_key=idempotency_key,
            reason=reason,
            architecture_release_plan=plan,
            release_approval_case_ref=release_approval_case_ref,
        )
