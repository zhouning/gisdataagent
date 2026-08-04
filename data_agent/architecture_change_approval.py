"""Typed admission of provider architecture drift into ApprovalCase authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from .approval_case_authority import ApprovalCaseAuthority
from .data_architecture_ledger import (
    ArchitectureReconciliationAction,
    ArchitectureReconciliationStatus,
    ProviderObjectState,
    ResourceVersionArchitectureReconciliation,
)
from .platform_contracts import (
    ApprovalCase,
    ResourceURNText,
    ResourceVersion,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
)
from .platform_gateway import PlatformGateway

ARCHITECTURE_CHANGE_REVIEW_SCHEMA = "gda.architecture_change_review.v1"
ARCHITECTURE_CHANGE_REVIEW_ACTION = "data_architecture.change_review"

_REVIEW_ACTIONS: dict[
    ArchitectureReconciliationStatus,
    tuple[ArchitectureReconciliationAction, ...],
] = {
    ArchitectureReconciliationStatus.SCHEMA_DRIFT: ("review_schema_drift",),
    ArchitectureReconciliationStatus.LOCATION_DRIFT: ("review_location_drift",),
    ArchitectureReconciliationStatus.SCHEMA_AND_LOCATION_DRIFT: (
        "review_schema_drift",
        "review_location_drift",
    ),
    ArchitectureReconciliationStatus.TOMBSTONED: ("investigate_tombstone",),
}


class ArchitectureChangeApprovalError(ValueError):
    """The reconciliation is not eligible for architecture-change review."""


def architecture_change_review_fingerprint(
    *,
    tenant_id: str,
    target_resource_urn: str,
    resource_version_id: UUID,
    observation_id: UUID,
    observation_sha256: str,
    binding_sha256: str,
    reconciliation_status: ArchitectureReconciliationStatus | str,
    candidate_schema_sha256: str | None,
    candidate_location_sha256: str | None,
    required_actions: tuple[ArchitectureReconciliationAction, ...],
) -> str:
    """Bind the complete bounded review scope to one canonical fingerprint."""

    return canonical_json_fingerprint(
        {
            "schema": ARCHITECTURE_CHANGE_REVIEW_SCHEMA,
            "tenant_id": tenant_id,
            "target_resource_urn": target_resource_urn,
            "resource_version_id": str(resource_version_id),
            "observation_id": str(observation_id),
            "observation_sha256": observation_sha256,
            "binding_sha256": binding_sha256,
            "reconciliation_status": ArchitectureReconciliationStatus(reconciliation_status).value,
            "candidate_schema_sha256": candidate_schema_sha256,
            "candidate_location_sha256": candidate_location_sha256,
            "required_actions": list(required_actions),
        }
    )


class ArchitectureChangeReview(BaseModel):
    """Bounded evidence reviewed by one architecture ApprovalCase."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    target_resource_urn: ResourceURNText
    resource_version_id: UUID
    observation_id: UUID
    observation_sha256: Sha256
    binding_sha256: Sha256
    reconciliation_status: ArchitectureReconciliationStatus
    candidate_schema_sha256: Sha256 | None = None
    candidate_location_sha256: Sha256 | None = None
    required_actions: tuple[ArchitectureReconciliationAction, ...]
    review_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_review(self) -> ArchitectureChangeReview:
        identity = parse_resource_urn(self.target_resource_urn)
        if identity["tenant_id"] != self.tenant_id:
            raise ValueError("architecture review target tenant must match")
        if identity["resource_kind"] != "dataset":
            raise ValueError("architecture review target must be a dataset ResourceURN")
        expected_actions = _REVIEW_ACTIONS.get(self.reconciliation_status)
        if expected_actions is None:
            raise ValueError("architecture reconciliation status is not reviewable")
        if self.required_actions != expected_actions:
            raise ValueError("architecture review actions do not match drift status")
        if self.reconciliation_status is ArchitectureReconciliationStatus.TOMBSTONED:
            if (
                self.candidate_schema_sha256 is not None
                or self.candidate_location_sha256 is not None
            ):
                raise ValueError("tombstone review cannot carry candidate fingerprints")
        elif self.candidate_schema_sha256 is None or self.candidate_location_sha256 is None:
            raise ValueError("drift review requires schema and location candidates")
        expected = architecture_change_review_fingerprint(
            tenant_id=self.tenant_id,
            target_resource_urn=self.target_resource_urn,
            resource_version_id=self.resource_version_id,
            observation_id=self.observation_id,
            observation_sha256=self.observation_sha256,
            binding_sha256=self.binding_sha256,
            reconciliation_status=self.reconciliation_status,
            candidate_schema_sha256=self.candidate_schema_sha256,
            candidate_location_sha256=self.candidate_location_sha256,
            required_actions=self.required_actions,
        )
        if self.review_sha256 != expected:
            raise ValueError("review_sha256 does not match architecture review")
        return self

    def approval_context(self) -> dict[str, Any]:
        """Return the deliberately bounded context persisted by ApprovalCase."""

        return {
            "resource_version_id": str(self.resource_version_id),
            "observation_id": str(self.observation_id),
            "observation_sha256": self.observation_sha256,
            "binding_sha256": self.binding_sha256,
            "reconciliation_status": self.reconciliation_status.value,
            "candidate_schema_sha256": self.candidate_schema_sha256,
            "candidate_location_sha256": self.candidate_location_sha256,
            "required_actions": list(self.required_actions),
        }


def build_architecture_change_review(
    resource_version: ResourceVersion,
    reconciliation: ResourceVersionArchitectureReconciliation,
) -> ArchitectureChangeReview:
    """Validate a current immutable binding and provider observation for review."""

    if reconciliation.status not in _REVIEW_ACTIONS:
        raise ArchitectureChangeApprovalError(
            f"architecture status {reconciliation.status.value!r} is not reviewable"
        )
    if (
        reconciliation.tenant_id != resource_version.tenant_id
        or reconciliation.resource_version_id != resource_version.resource_version_id
    ):
        raise ArchitectureChangeApprovalError(
            "ResourceVersion does not match architecture reconciliation"
        )
    identity = parse_resource_urn(resource_version.resource_urn)
    if identity["resource_kind"] != "dataset":
        raise ArchitectureChangeApprovalError(
            "architecture change approval currently supports dataset resources"
        )
    architecture = reconciliation.architecture
    observation = reconciliation.latest_observation
    if (
        architecture.tenant_id != reconciliation.tenant_id
        or architecture.resource_version_id != reconciliation.resource_version_id
    ):
        raise ArchitectureChangeApprovalError(
            "architecture projection does not match reconciliation identity"
        )
    if not architecture.architecture_ready or architecture.binding is None:
        raise ArchitectureChangeApprovalError(
            "architecture change review requires an accepted immutable binding"
        )
    if observation is None:
        raise ArchitectureChangeApprovalError(
            "architecture change review requires a provider observation"
        )
    if (
        observation.tenant_id != reconciliation.tenant_id
        or observation.resource_version_id != reconciliation.resource_version_id
    ):
        raise ArchitectureChangeApprovalError(
            "provider observation does not match reconciliation identity"
        )
    if reconciliation.required_actions != _REVIEW_ACTIONS[reconciliation.status]:
        raise ArchitectureChangeApprovalError(
            "reconciliation actions do not match the reviewable status"
        )

    candidate_schema = observation.schema_version_sha256
    candidate_location = observation.physical_location_sha256
    if reconciliation.status is ArchitectureReconciliationStatus.TOMBSTONED:
        if observation.object_state is not ProviderObjectState.TOMBSTONED:
            raise ArchitectureChangeApprovalError(
                "tombstone review requires a tombstoned provider observation"
            )
        if reconciliation.schema_matches is not None or reconciliation.location_matches is not None:
            raise ArchitectureChangeApprovalError(
                "tombstone reconciliation cannot report component matches"
            )
    else:
        if observation.object_state is not ProviderObjectState.PRESENT:
            raise ArchitectureChangeApprovalError(
                "drift review requires a present provider observation"
            )
        if observation.fresh_until <= reconciliation.evaluated_at:
            raise ArchitectureChangeApprovalError(
                "drift review requires a fresh provider observation"
            )
        accepted_schema = architecture.schema_version_record
        accepted_location = architecture.physical_location
        if accepted_schema is None or accepted_location is None:
            raise ArchitectureChangeApprovalError(
                "drift review requires accepted schema and location facts"
            )
        schema_matches = candidate_schema == accepted_schema.schema_sha256
        location_matches = candidate_location == accepted_location.location_sha256
        expected_status = (
            ArchitectureReconciliationStatus.IN_SYNC
            if schema_matches and location_matches
            else ArchitectureReconciliationStatus.SCHEMA_AND_LOCATION_DRIFT
            if not schema_matches and not location_matches
            else ArchitectureReconciliationStatus.SCHEMA_DRIFT
            if not schema_matches
            else ArchitectureReconciliationStatus.LOCATION_DRIFT
        )
        if reconciliation.status is not expected_status:
            raise ArchitectureChangeApprovalError(
                "reconciliation status does not match provider candidates"
            )
        if (
            reconciliation.schema_matches is not schema_matches
            or reconciliation.location_matches is not location_matches
        ):
            raise ArchitectureChangeApprovalError(
                "reconciliation match flags do not match provider candidates"
            )

    values = {
        "tenant_id": reconciliation.tenant_id,
        "target_resource_urn": resource_version.resource_urn,
        "resource_version_id": reconciliation.resource_version_id,
        "observation_id": observation.observation_id,
        "observation_sha256": observation.observation_sha256,
        "binding_sha256": architecture.binding.binding_sha256,
        "reconciliation_status": reconciliation.status,
        "candidate_schema_sha256": candidate_schema,
        "candidate_location_sha256": candidate_location,
        "required_actions": reconciliation.required_actions,
    }
    return ArchitectureChangeReview(
        review_sha256=architecture_change_review_fingerprint(**values),
        **values,
    )


def build_architecture_change_approval_case(
    review: ArchitectureChangeReview,
    *,
    requester_subject: str,
    request_reason: str,
    requested_at: datetime,
    expires_at: datetime,
) -> ApprovalCase:
    """Build the deterministic ApprovalCase for one provider observation."""

    resource_id = f"architecture-change-{review.observation_id.hex}"
    return ApprovalCase(
        tenant_id=review.tenant_id,
        approval_case_ref=build_resource_urn(
            review.tenant_id,
            "approval_case",
            resource_id,
        ),
        target_resource_urn=review.target_resource_urn,
        target_fingerprint=review.review_sha256,
        action=ARCHITECTURE_CHANGE_REVIEW_ACTION,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=review.approval_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )


@dataclass(frozen=True)
class ArchitectureChangeApprovalRequestResult:
    reconciliation: ResourceVersionArchitectureReconciliation
    review: ArchitectureChangeReview
    approval_case: ApprovalCase
    created: bool


class ArchitectureChangeApprovalService:
    """Read current facts and admit an eligible drift into ApprovalCase authority."""

    def __init__(
        self,
        gateway: PlatformGateway,
        approval_authority: ApprovalCaseAuthority,
    ) -> None:
        self._gateway = gateway
        self._approval_authority = approval_authority

    def request_review(
        self,
        *,
        tenant_id: str,
        resource_version_id: UUID,
        requester_subject: str,
        request_reason: str,
        owner_ref: str,
        requested_at: datetime,
        expires_at: datetime,
        evaluated_at: datetime | None = None,
    ) -> ArchitectureChangeApprovalRequestResult:
        resource_version = self._gateway.get_resource_version(
            tenant_id,
            resource_version_id,
        )
        reconciliation = self._gateway.reconcile_resource_version_architecture(
            tenant_id,
            resource_version_id,
            evaluated_at=evaluated_at or requested_at,
        )
        review = build_architecture_change_review(resource_version, reconciliation)
        case = build_architecture_change_approval_case(
            review,
            requester_subject=requester_subject,
            request_reason=request_reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return ArchitectureChangeApprovalRequestResult(
            reconciliation=reconciliation,
            review=review,
            approval_case=written.approval_case,
            created=written.created,
        )
