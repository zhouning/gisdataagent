"""Approval-bound, atomic adoption of one architecture successor version."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, model_validator

from .approval_case_authority import ApprovalCaseAuthority
from .architecture_change_assessment import (
    ASSESSED_ARCHITECTURE_CHANGE_ACTION,
    SUCCESSOR_BLOCKERS,
)
from .data_architecture_ledger import (
    ArchitectureProviderObservation,
    DataArchitectureRegistration,
    ProviderObjectState,
    ResourceVersionArchitecture,
    physical_location_fingerprint,
    schema_version_fingerprint,
)
from .platform_contracts import (
    ApprovalCase,
    ApprovalCaseStatus,
    Artifact,
    ArtifactRole,
    LineageEvent,
    ResourceURNText,
    ResourceVersion,
    Sha256,
    TenantId,
    build_resource_urn,
    canonical_json_fingerprint,
    parse_resource_urn,
)
from .platform_gateway import GatewayWriteResult, PlatformGateway
from .postgis_schema_evidence import (
    POSTGIS_SCHEMA_EVIDENCE_MEDIA_TYPE,
    POSTGIS_SCHEMA_SNAPSHOT_SCHEMA,
)

ARCHITECTURE_SUCCESSOR_PLAN_SCHEMA = "gda.architecture_successor_plan.v1"
ARCHITECTURE_SUCCESSOR_ADOPTION_ACTION = "data_architecture.create_successor_version"
ARCHITECTURE_SUCCESSOR_PRODUCER = "workload:architecture-successor-controller"
_IDENTITY_NAMESPACE = UUID("a48edbe9-9099-4d8b-8f8d-f75fa863fe35")

ClearedSuccessorBlocker = Literal[
    "new_content_snapshot_required",
    "successor_data_contract_required",
]
CLEARED_SUCCESSOR_BLOCKERS: tuple[ClearedSuccessorBlocker, ...] = SUCCESSOR_BLOCKERS


class ArchitectureSuccessorAdoptionError(ValueError):
    """A successor plan or its live approval/evidence facts are inconsistent."""


def architecture_successor_plan_fingerprint(
    *,
    tenant_id: str,
    target_resource_urn: str,
    predecessor_resource_version_id: UUID,
    assessed_approval_case_ref: str,
    assessed_review_sha256: str,
    observation_id: UUID,
    observation_sha256: str,
    predecessor_binding_sha256: str,
    candidate_schema_artifact_id: UUID,
    candidate_schema_artifact_sha256: str,
    successor_resource_version: ResourceVersion,
    successor_architecture: DataArchitectureRegistration,
    cleared_blockers: tuple[ClearedSuccessorBlocker, ...],
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": ARCHITECTURE_SUCCESSOR_PLAN_SCHEMA,
            "tenant_id": tenant_id,
            "target_resource_urn": target_resource_urn,
            "predecessor_resource_version_id": str(predecessor_resource_version_id),
            "assessed_approval_case_ref": assessed_approval_case_ref,
            "assessed_review_sha256": assessed_review_sha256,
            "observation_id": str(observation_id),
            "observation_sha256": observation_sha256,
            "predecessor_binding_sha256": predecessor_binding_sha256,
            "candidate_schema_artifact_id": str(candidate_schema_artifact_id),
            "candidate_schema_artifact_sha256": candidate_schema_artifact_sha256,
            "successor_resource_version": successor_resource_version.model_dump(mode="json"),
            "successor_architecture": successor_architecture.model_dump(mode="json"),
            "cleared_blockers": list(cleared_blockers),
        }
    )


def _successor_lineage_event(
    *,
    tenant_id: str,
    predecessor_resource_version_id: UUID,
    successor_resource_version_id: UUID,
    assessed_approval_case_ref: str,
    plan_sha256: str,
    occurred_at: datetime,
) -> LineageEvent:
    event_values = {
        "schema": ARCHITECTURE_SUCCESSOR_PLAN_SCHEMA,
        "operation": "create_successor_version",
        "tenant_id": tenant_id,
        "predecessor_resource_version_id": str(predecessor_resource_version_id),
        "successor_resource_version_id": str(successor_resource_version_id),
        "assessed_approval_case_ref": assessed_approval_case_ref,
        "plan_sha256": plan_sha256,
    }
    event_sha256 = canonical_json_fingerprint(event_values)
    return LineageEvent(
        tenant_id=tenant_id,
        lineage_event_id=uuid5(
            _IDENTITY_NAMESPACE,
            f"architecture-successor-lineage:{tenant_id}:{plan_sha256}",
        ),
        event_type="derive",
        source_resource_version_id=predecessor_resource_version_id,
        target_resource_version_id=successor_resource_version_id,
        producer=ARCHITECTURE_SUCCESSOR_PRODUCER,
        event_sha256=event_sha256,
        facets={
            "operation": "create_successor_version",
            "assessed_approval_case_ref": assessed_approval_case_ref,
            "architecture_successor_plan_sha256": plan_sha256,
        },
        occurred_at=occurred_at,
    )


class ArchitectureSuccessorPlan(BaseModel):
    """Immutable plan authorized by the second, adoption-specific decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: TenantId
    target_resource_urn: ResourceURNText
    predecessor_resource_version_id: UUID
    assessed_approval_case_ref: ResourceURNText
    assessed_review_sha256: Sha256
    observation_id: UUID
    observation_sha256: Sha256
    predecessor_binding_sha256: Sha256
    candidate_schema_artifact_id: UUID
    candidate_schema_artifact_sha256: Sha256
    successor_resource_version: ResourceVersion
    successor_architecture: DataArchitectureRegistration
    cleared_blockers: tuple[ClearedSuccessorBlocker, ...]
    lineage_event: LineageEvent
    plan_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_plan(self) -> ArchitectureSuccessorPlan:
        target = parse_resource_urn(self.target_resource_urn)
        if target["tenant_id"] != self.tenant_id or target["resource_kind"] != "dataset":
            raise ValueError("successor plan target must be a tenant dataset")
        assessed = parse_resource_urn(self.assessed_approval_case_ref)
        if assessed["tenant_id"] != self.tenant_id or assessed["resource_kind"] != "approval_case":
            raise ValueError("successor plan assessment must be a tenant ApprovalCase")
        successor = self.successor_resource_version
        registration = self.successor_architecture
        if (
            successor.tenant_id != self.tenant_id
            or successor.resource_urn != self.target_resource_urn
        ):
            raise ValueError("successor ResourceVersion must match plan target")
        if successor.predecessor_version_id != self.predecessor_resource_version_id:
            raise ValueError("successor ResourceVersion must name the assessed predecessor")
        if registration.binding.tenant_id != self.tenant_id:
            raise ValueError("successor architecture tenant must match plan")
        if registration.binding.resource_version_id != successor.resource_version_id:
            raise ValueError("successor architecture must bind the successor ResourceVersion")
        if self.cleared_blockers != CLEARED_SUCCESSOR_BLOCKERS:
            raise ValueError("successor plan must explicitly satisfy both assessed blockers")
        location = registration.physical_location
        if location.checksum_algorithm != "sha256":
            raise ValueError("successor content snapshot must use sha256")
        if location.content_checksum != successor.content_sha256:
            raise ValueError("successor content hash must match its physical snapshot")
        authority_ref = successor.authority_version_ref
        required_authority_ref = {
            "snapshot_ref": location.snapshot_ref,
            "revision_ref": location.revision_ref,
            "content_sha256": successor.content_sha256,
            "provider_observation_id": str(self.observation_id),
            "schema_evidence_artifact_id": str(self.candidate_schema_artifact_id),
        }
        if any(authority_ref.get(key) != value for key, value in required_authority_ref.items()):
            raise ValueError("successor authority_version_ref does not bind its evidence")
        expected_plan_sha256 = architecture_successor_plan_fingerprint(
            tenant_id=self.tenant_id,
            target_resource_urn=self.target_resource_urn,
            predecessor_resource_version_id=self.predecessor_resource_version_id,
            assessed_approval_case_ref=self.assessed_approval_case_ref,
            assessed_review_sha256=self.assessed_review_sha256,
            observation_id=self.observation_id,
            observation_sha256=self.observation_sha256,
            predecessor_binding_sha256=self.predecessor_binding_sha256,
            candidate_schema_artifact_id=self.candidate_schema_artifact_id,
            candidate_schema_artifact_sha256=self.candidate_schema_artifact_sha256,
            successor_resource_version=self.successor_resource_version,
            successor_architecture=self.successor_architecture,
            cleared_blockers=self.cleared_blockers,
        )
        if self.plan_sha256 != expected_plan_sha256:
            raise ValueError("plan_sha256 does not match successor plan")
        expected_lineage = _successor_lineage_event(
            tenant_id=self.tenant_id,
            predecessor_resource_version_id=self.predecessor_resource_version_id,
            successor_resource_version_id=successor.resource_version_id,
            assessed_approval_case_ref=self.assessed_approval_case_ref,
            plan_sha256=self.plan_sha256,
            occurred_at=successor.created_at,
        )
        if self.lineage_event != expected_lineage:
            raise ValueError("successor lineage does not match the immutable plan")
        return self

    def approval_context(self) -> dict[str, Any]:
        registration = self.successor_architecture
        return {
            "schema": ARCHITECTURE_SUCCESSOR_PLAN_SCHEMA,
            "plan_sha256": self.plan_sha256,
            "assessed_approval_case_ref": self.assessed_approval_case_ref,
            "assessed_review_sha256": self.assessed_review_sha256,
            "predecessor_resource_version_id": str(self.predecessor_resource_version_id),
            "observation_id": str(self.observation_id),
            "observation_sha256": self.observation_sha256,
            "predecessor_binding_sha256": self.predecessor_binding_sha256,
            "candidate_schema_artifact_id": str(self.candidate_schema_artifact_id),
            "candidate_schema_artifact_sha256": self.candidate_schema_artifact_sha256,
            "successor_resource_version_id": str(
                self.successor_resource_version.resource_version_id
            ),
            "successor_version_key": self.successor_resource_version.version_key,
            "successor_content_sha256": self.successor_resource_version.content_sha256,
            "successor_schema_sha256": registration.schema_version.schema_sha256,
            "successor_contract_sha256": (
                registration.data_contract_version.contract_sha256
            ),
            "successor_location_sha256": registration.physical_location.location_sha256,
            "successor_binding_sha256": registration.binding.binding_sha256,
            "lineage_event_id": str(self.lineage_event.lineage_event_id),
            "lineage_event_sha256": self.lineage_event.event_sha256,
            "cleared_blockers": list(self.cleared_blockers),
        }


def _assessment_context_value(case: ApprovalCase, key: str) -> Any:
    try:
        return case.request_context[key]
    except KeyError as exc:
        raise ArchitectureSuccessorAdoptionError(
            f"assessed ApprovalCase has no {key} binding"
        ) from exc


def validate_architecture_successor_plan_against_facts(
    plan: ArchitectureSuccessorPlan,
    *,
    predecessor: ResourceVersion,
    predecessor_architecture: ResourceVersionArchitecture,
    observation: ArchitectureProviderObservation,
    candidate_schema_artifact: Artifact,
    assessed_case: ApprovalCase,
) -> None:
    """Recheck the plan against immutable facts loaded in the adoption transaction."""

    if assessed_case.status is not ApprovalCaseStatus.APPROVED:
        raise ArchitectureSuccessorAdoptionError(
            "architecture assessment must be independently approved"
        )
    if assessed_case.action != ASSESSED_ARCHITECTURE_CHANGE_ACTION:
        raise ArchitectureSuccessorAdoptionError("ApprovalCase is not an assessed change review")
    if (
        assessed_case.approval_case_ref != plan.assessed_approval_case_ref
        or assessed_case.target_resource_urn != plan.target_resource_urn
        or assessed_case.target_fingerprint != plan.assessed_review_sha256
    ):
        raise ArchitectureSuccessorAdoptionError("assessed ApprovalCase does not match plan")
    expected_assessment_context = {
        "resource_version_id": str(plan.predecessor_resource_version_id),
        "observation_id": str(plan.observation_id),
        "observation_sha256": plan.observation_sha256,
        "binding_sha256": plan.predecessor_binding_sha256,
        "candidate_schema_artifact_id": str(plan.candidate_schema_artifact_id),
        "successor_blockers": list(SUCCESSOR_BLOCKERS),
    }
    for key, expected in expected_assessment_context.items():
        if _assessment_context_value(assessed_case, key) != expected:
            raise ArchitectureSuccessorAdoptionError(
                f"assessed ApprovalCase {key} does not match successor plan"
            )
    if predecessor.resource_version_id != plan.predecessor_resource_version_id:
        raise ArchitectureSuccessorAdoptionError("predecessor identity changed")
    if predecessor.resource_urn != plan.target_resource_urn:
        raise ArchitectureSuccessorAdoptionError("predecessor resource changed")
    if predecessor.content_sha256 == plan.successor_resource_version.content_sha256:
        raise ArchitectureSuccessorAdoptionError("successor requires a new content snapshot")
    if not predecessor_architecture.architecture_ready:
        raise ArchitectureSuccessorAdoptionError("predecessor architecture is incomplete")
    baseline_binding = predecessor_architecture.binding
    baseline_contract = predecessor_architecture.data_contract_version_record
    baseline_location = predecessor_architecture.physical_location
    if baseline_binding is None or baseline_contract is None or baseline_location is None:
        raise ArchitectureSuccessorAdoptionError("predecessor architecture facts are incomplete")
    if baseline_binding.binding_sha256 != plan.predecessor_binding_sha256:
        raise ArchitectureSuccessorAdoptionError("predecessor architecture binding changed")
    successor_contract = plan.successor_architecture.data_contract_version
    if (
        successor_contract.data_contract_version_id
        == baseline_contract.data_contract_version_id
        or successor_contract.authority_version_ref == baseline_contract.authority_version_ref
    ):
        raise ArchitectureSuccessorAdoptionError(
            "successor requires a distinct data-contract version"
        )
    successor_location = plan.successor_architecture.physical_location
    if (
        successor_location.snapshot_ref is None
        or successor_location.snapshot_ref == baseline_location.snapshot_ref
    ):
        raise ArchitectureSuccessorAdoptionError(
            "successor requires a distinct immutable snapshot reference"
        )
    if observation.object_state is not ProviderObjectState.PRESENT:
        raise ArchitectureSuccessorAdoptionError("tombstoned provider state cannot be adopted")
    if (
        observation.observation_id != plan.observation_id
        or observation.observation_sha256 != plan.observation_sha256
        or observation.resource_version_id != plan.predecessor_resource_version_id
    ):
        raise ArchitectureSuccessorAdoptionError("provider observation changed")
    successor_timestamps = (
        plan.successor_resource_version.created_at,
        plan.successor_architecture.schema_version.created_at,
        plan.successor_architecture.data_contract_version.created_at,
        plan.successor_architecture.physical_location.created_at,
        plan.successor_architecture.binding.bound_at,
    )
    if any(value < observation.observed_at for value in successor_timestamps):
        raise ArchitectureSuccessorAdoptionError(
            "successor authority facts cannot predate their provider observation"
        )
    successor_schema = plan.successor_architecture.schema_version
    if (
        successor_schema.authority_system.value != "provider"
        or successor_schema.authority_namespace != observation.provider_namespace
        or successor_schema.authority_object_id != observation.provider_object_id
        or successor_schema.authority_version_ref != observation.source_revision
    ):
        raise ArchitectureSuccessorAdoptionError(
            "successor schema does not re-key the observed provider schema"
        )
    predecessor_schema_sha256 = schema_version_fingerprint(
        tenant_id=plan.tenant_id,
        resource_version_id=plan.predecessor_resource_version_id,
        schema_format=successor_schema.schema_format,
        authority_system=successor_schema.authority_system,
        authority_namespace=successor_schema.authority_namespace,
        authority_object_id=successor_schema.authority_object_id,
        authority_version_ref=successor_schema.authority_version_ref,
    )
    if predecessor_schema_sha256 != observation.schema_version_sha256:
        raise ArchitectureSuccessorAdoptionError(
            "successor schema is not the assessed observation candidate"
        )
    if (
        successor_location.provider_system != observation.provider_system
        or successor_location.provider_namespace != observation.provider_namespace
    ):
        raise ArchitectureSuccessorAdoptionError(
            "successor location does not match observed provider identity"
        )
    predecessor_location_sha256 = physical_location_fingerprint(
        tenant_id=plan.tenant_id,
        resource_version_id=plan.predecessor_resource_version_id,
        location_kind=successor_location.location_kind,
        provider_system=successor_location.provider_system,
        provider_namespace=successor_location.provider_namespace,
        provider_locator=successor_location.provider_locator,
        snapshot_ref=successor_location.snapshot_ref,
        revision_ref=successor_location.revision_ref,
        checksum_algorithm=successor_location.checksum_algorithm,
        content_checksum=successor_location.content_checksum,
    )
    if predecessor_location_sha256 != observation.physical_location_sha256:
        raise ArchitectureSuccessorAdoptionError(
            "successor location is not the assessed observation candidate"
        )
    expected_manifest = {
        "schema": POSTGIS_SCHEMA_SNAPSHOT_SCHEMA,
        "observation_id": str(observation.observation_id),
        "observation_sha256": observation.observation_sha256,
        "snapshot_sha256": observation.schema_content_sha256,
    }
    if (
        candidate_schema_artifact.tenant_id != plan.tenant_id
        or candidate_schema_artifact.artifact_id != plan.candidate_schema_artifact_id
        or candidate_schema_artifact.artifact_role is not ArtifactRole.EVIDENCE
        or candidate_schema_artifact.media_type != POSTGIS_SCHEMA_EVIDENCE_MEDIA_TYPE
        or candidate_schema_artifact.resource_version_id
        != plan.predecessor_resource_version_id
        or candidate_schema_artifact.content_sha256
        != plan.candidate_schema_artifact_sha256
        or candidate_schema_artifact.manifest != expected_manifest
    ):
        raise ArchitectureSuccessorAdoptionError(
            "candidate schema Artifact does not match assessed observation"
        )


def build_architecture_successor_plan(
    *,
    predecessor: ResourceVersion,
    predecessor_architecture: ResourceVersionArchitecture,
    observation: ArchitectureProviderObservation,
    candidate_schema_artifact: Artifact,
    assessed_case: ApprovalCase,
    successor_resource_version: ResourceVersion,
    successor_architecture: DataArchitectureRegistration,
) -> ArchitectureSuccessorPlan:
    if predecessor_architecture.binding is None:
        raise ArchitectureSuccessorAdoptionError("predecessor architecture has no binding")
    values = {
        "tenant_id": predecessor.tenant_id,
        "target_resource_urn": predecessor.resource_urn,
        "predecessor_resource_version_id": predecessor.resource_version_id,
        "assessed_approval_case_ref": assessed_case.approval_case_ref,
        "assessed_review_sha256": assessed_case.target_fingerprint,
        "observation_id": observation.observation_id,
        "observation_sha256": observation.observation_sha256,
        "predecessor_binding_sha256": predecessor_architecture.binding.binding_sha256,
        "candidate_schema_artifact_id": candidate_schema_artifact.artifact_id,
        "candidate_schema_artifact_sha256": candidate_schema_artifact.content_sha256,
        "successor_resource_version": successor_resource_version,
        "successor_architecture": successor_architecture,
        "cleared_blockers": CLEARED_SUCCESSOR_BLOCKERS,
    }
    plan_sha256 = architecture_successor_plan_fingerprint(**values)
    lineage_event = _successor_lineage_event(
        tenant_id=predecessor.tenant_id,
        predecessor_resource_version_id=predecessor.resource_version_id,
        successor_resource_version_id=successor_resource_version.resource_version_id,
        assessed_approval_case_ref=assessed_case.approval_case_ref,
        plan_sha256=plan_sha256,
        occurred_at=successor_resource_version.created_at,
    )
    plan = ArchitectureSuccessorPlan(
        plan_sha256=plan_sha256,
        lineage_event=lineage_event,
        **values,
    )
    validate_architecture_successor_plan_against_facts(
        plan,
        predecessor=predecessor,
        predecessor_architecture=predecessor_architecture,
        observation=observation,
        candidate_schema_artifact=candidate_schema_artifact,
        assessed_case=assessed_case,
    )
    return plan


def build_architecture_successor_adoption_case(
    plan: ArchitectureSuccessorPlan,
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
            f"architecture-successor-{plan.successor_resource_version.resource_version_id.hex}",
        ),
        target_resource_urn=plan.target_resource_urn,
        target_fingerprint=plan.plan_sha256,
        action=ARCHITECTURE_SUCCESSOR_ADOPTION_ACTION,
        requester_subject=requester_subject,
        request_reason=request_reason,
        request_context=plan.approval_context(),
        requested_at=requested_at,
        expires_at=expires_at,
    )


@dataclass(frozen=True)
class ArchitectureSuccessorAdoptionRequestResult:
    plan: ArchitectureSuccessorPlan
    approval_case: ApprovalCase
    created: bool


class ArchitectureSuccessorAdoptionService:
    """Build, request and execute the independently approved successor plan."""

    def __init__(
        self,
        gateway: PlatformGateway,
        approval_authority: ApprovalCaseAuthority,
    ) -> None:
        self._gateway = gateway
        self._approval_authority = approval_authority

    def request_adoption(
        self,
        *,
        tenant_id: str,
        assessed_approval_case_ref: str,
        successor_resource_version: ResourceVersion,
        successor_architecture: DataArchitectureRegistration,
        requester_subject: str,
        request_reason: str,
        owner_ref: str,
        requested_at: datetime,
        expires_at: datetime,
    ) -> ArchitectureSuccessorAdoptionRequestResult:
        assessed_case = self._approval_authority.get(
            tenant_id,
            assessed_approval_case_ref,
        )
        try:
            predecessor_id = UUID(str(_assessment_context_value(
                assessed_case, "resource_version_id"
            )))
            artifact_id = UUID(str(_assessment_context_value(
                assessed_case, "candidate_schema_artifact_id"
            )))
        except ValueError as exc:
            raise ArchitectureSuccessorAdoptionError(
                "assessed ApprovalCase contains an invalid evidence identity"
            ) from exc
        predecessor = self._gateway.get_resource_version(tenant_id, predecessor_id)
        predecessor_architecture = self._gateway.get_resource_version_architecture(
            tenant_id,
            predecessor_id,
        )
        observation = self._gateway.get_latest_architecture_provider_observation(
            tenant_id,
            predecessor_id,
        )
        candidate_artifact = self._gateway.get_artifact(tenant_id, artifact_id)
        plan = build_architecture_successor_plan(
            predecessor=predecessor,
            predecessor_architecture=predecessor_architecture,
            observation=observation,
            candidate_schema_artifact=candidate_artifact,
            assessed_case=assessed_case,
            successor_resource_version=successor_resource_version,
            successor_architecture=successor_architecture,
        )
        case = build_architecture_successor_adoption_case(
            plan,
            requester_subject=requester_subject,
            request_reason=request_reason,
            requested_at=requested_at,
            expires_at=expires_at,
        )
        written = self._approval_authority.create(case, owner_ref=owner_ref)
        return ArchitectureSuccessorAdoptionRequestResult(
            plan=plan,
            approval_case=written.approval_case,
            created=written.created,
        )

    def adopt(
        self,
        plan: ArchitectureSuccessorPlan,
        *,
        adoption_approval_case_ref: str,
        evaluated_at: datetime,
    ) -> GatewayWriteResult:
        return self._gateway.adopt_architecture_successor(
            plan,
            adoption_approval_case_ref=adoption_approval_case_ref,
            evaluated_at=evaluated_at,
        )
