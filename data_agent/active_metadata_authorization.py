"""Content-bound authorization for promoting an Active Metadata request."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .active_metadata_change_contract import (
    METADATA_PROJECTION_ROUTE,
    MetadataActivationRequest,
    WorkloadSubject,
)
from .platform_authorization import (
    AuthorizationEvidenceError,
    parse_policy_decision_artifact,
    validate_run_authorization_evidence,
)
from .platform_contracts import (
    Artifact,
    PlatformDefinitionVersion,
    PlatformRun,
    ResourceVersion,
    RunStatus,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)

AUTHORIZATION_SCHEMA = "gda.metadata_activation_authorization.v1"
DISPATCH_ACTION = "dolphinscheduler.dispatch"


class MetadataActivationAuthorizationError(RuntimeError):
    """The activation request is not bound to valid dispatch evidence."""


class MetadataActivationAuthorization(BaseModel):
    """Immutable proof that one inert request may enqueue one dispatch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authorization_schema: Literal[
        "gda.metadata_activation_authorization.v1"
    ] = Field(default=AUTHORIZATION_SCHEMA, alias="schema")
    authorization_id: UUID
    tenant_id: TenantId
    request_id: UUID
    request_sha256: Sha256
    resource_urn: str
    resource_version_id: UUID
    content_sha256: Sha256
    definition_version_id: UUID
    definition_sha256: Sha256
    run_id: UUID
    execution_plan_artifact_id: UUID
    execution_plan_sha256: Sha256
    policy_decision_artifact_id: UUID
    policy_decision_sha256: Sha256
    approval_artifact_id: UUID
    approval_sha256: Sha256
    command_id: UUID
    route: Literal["metadata_fabric.projection_plan"] = METADATA_PROJECTION_ROUTE
    status: Literal["authorized_for_dispatch"] = "authorized_for_dispatch"
    authorized_by: WorkloadSubject
    authorized_at: datetime
    scheduler_command_enqueued: Literal[True] = True
    provider_apply_authorized: Literal[False] = False
    provider_mutations_executed: Literal[False] = False
    production_scheduler_submission_verified: Literal[False] = False
    production_ingestion_verified: Literal[False] = False
    production_ready: Literal[False] = False
    authorization_sha256: Sha256

    @field_validator("authorized_at")
    @classmethod
    def _utc_authorized_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authorization time must include a timezone")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _content_bound(self) -> Self:
        identity = _authorization_identity(self.model_dump(mode="json", by_alias=True))
        expected_id = uuid5(
            self.request_id,
            f"metadata-activation-authorization:{canonical_json_fingerprint(identity)}",
        )
        if self.authorization_id != expected_id:
            raise ValueError("authorization ID does not match its evidence binding")
        stable = self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"authorization_sha256"},
        )
        if self.authorization_sha256 != canonical_json_fingerprint(stable):
            raise ValueError("authorization SHA-256 does not match")
        return self


def dispatch_dedupe_key(run_id: UUID, execution_plan_artifact_id: UUID) -> str:
    return f"dolphinscheduler.dispatch:{run_id}:{execution_plan_artifact_id}"


def dispatch_command_id(run_id: UUID, execution_plan_artifact_id: UUID) -> UUID:
    dedupe_key = dispatch_dedupe_key(run_id, execution_plan_artifact_id)
    return uuid5(run_id, dedupe_key)


def _authorization_identity(values: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "authorization_id",
        "authorization_sha256",
        "authorized_at",
        "status",
        "scheduler_command_enqueued",
        "provider_apply_authorized",
        "provider_mutations_executed",
        "production_scheduler_submission_verified",
        "production_ingestion_verified",
        "production_ready",
    }
    return {key: value for key, value in values.items() if key not in excluded}


def build_metadata_activation_authorization(
    request: MetadataActivationRequest,
    resource_version: ResourceVersion,
    definition: PlatformDefinitionVersion,
    run: PlatformRun,
    execution_plan_artifact: Artifact,
    policy_decision_artifact: Artifact,
    approval_artifact: Artifact,
    *,
    authorized_by: str,
    authorized_at: datetime,
) -> MetadataActivationAuthorization:
    """Validate the complete chain and return its deterministic authorization."""
    if authorized_at.tzinfo is None or authorized_at.utcoffset() is None:
        raise MetadataActivationAuthorizationError(
            "authorization time must include a timezone"
        )
    authorized_at = authorized_at.astimezone(UTC)
    if not authorized_by.startswith("workload:"):
        raise MetadataActivationAuthorizationError(
            "activation authorizer must use workload identity"
        )
    intent = request.intent
    if (
        resource_version.tenant_id != intent.tenant_id
        or resource_version.resource_urn != intent.resource_urn
        or resource_version.resource_version_id != intent.resource_version_id
        or resource_version.content_sha256 != intent.content_sha256
    ):
        raise MetadataActivationAuthorizationError(
            "activation request does not match the ResourceVersion"
        )
    if (
        definition.tenant_id != intent.tenant_id
        or definition.definition_version_id != run.definition_version_id
        or definition.orchestration_class != run.orchestration_class
        or definition.orchestration_class.value != "dataops"
        or definition.capability_id != intent.route
    ):
        raise MetadataActivationAuthorizationError(
            "activation request does not match the DataOps DefinitionVersion"
        )
    run_actor = (
        f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
    )
    if (
        run.tenant_id != intent.tenant_id
        or run.status != RunStatus.ACCEPTED
        or run.subject_context.subject_type.value != "workload"
        or authorized_at < run.submitted_at
        or intent.resource_version_id
        not in {binding.resource_version_id for binding in run.input_bindings}
    ):
        raise MetadataActivationAuthorizationError(
            "activation request does not match an accepted workload Run input"
        )
    if run.policy_refs is None:
        raise MetadataActivationAuthorizationError(
            "activation Run requires immutable policy references"
        )
    if (
        run.policy_refs.policy_decision_artifact_id
        != policy_decision_artifact.artifact_id
        or run.policy_refs.approval_artifact_id != approval_artifact.artifact_id
    ):
        raise MetadataActivationAuthorizationError(
            "activation Run policy references do not match supplied evidence"
        )
    try:
        decision, approval = validate_run_authorization_evidence(
            run,
            policy_decision_artifact,
            approval_artifact,
            execution_plan_artifact,
            at=authorized_at,
            expected_action=DISPATCH_ACTION,
        )
    except AuthorizationEvidenceError as exc:
        raise MetadataActivationAuthorizationError(str(exc)) from exc
    decision = parse_policy_decision_artifact(policy_decision_artifact)
    independent_subjects = {run_actor, decision.evaluator_subject}
    if approval is None:
        raise MetadataActivationAuthorizationError(
            "Active Metadata dispatch requires approval evidence"
        )
    independent_subjects.add(approval.approver_subject)
    if authorized_by in independent_subjects:
        raise MetadataActivationAuthorizationError(
            "activation authorizer must be independent from execution and review"
        )
    if execution_plan_artifact.created_at > authorized_at:
        raise MetadataActivationAuthorizationError(
            "execution plan artifact postdates authorization"
        )

    command_id = dispatch_command_id(run.run_id, execution_plan_artifact.artifact_id)
    values: dict[str, Any] = {
        "tenant_id": intent.tenant_id,
        "request_id": request.request_id,
        "request_sha256": request.request_sha256,
        "resource_urn": intent.resource_urn,
        "resource_version_id": intent.resource_version_id,
        "content_sha256": intent.content_sha256,
        "definition_version_id": definition.definition_version_id,
        "definition_sha256": definition.definition_sha256,
        "run_id": run.run_id,
        "execution_plan_artifact_id": execution_plan_artifact.artifact_id,
        "execution_plan_sha256": execution_plan_artifact.content_sha256,
        "policy_decision_artifact_id": policy_decision_artifact.artifact_id,
        "policy_decision_sha256": policy_decision_artifact.content_sha256,
        "approval_artifact_id": approval_artifact.artifact_id,
        "approval_sha256": approval_artifact.content_sha256,
        "command_id": command_id,
        "authorized_by": authorized_by,
        "authorized_at": authorized_at,
    }
    json_values = MetadataActivationAuthorization.model_construct(
        authorization_id=UUID(int=0),
        authorization_sha256="0" * 64,
        **values,
    ).model_dump(mode="json", by_alias=True)
    authorization_id = uuid5(
        request.request_id,
        "metadata-activation-authorization:"
        + canonical_json_fingerprint(_authorization_identity(json_values)),
    )
    stable_model = MetadataActivationAuthorization.model_construct(
        authorization_id=authorization_id,
        authorization_sha256="0" * 64,
        **values,
    )
    stable = stable_model.model_dump(
        mode="json", by_alias=True, exclude={"authorization_sha256"}
    )
    return MetadataActivationAuthorization(
        authorization_id=authorization_id,
        authorization_sha256=canonical_json_fingerprint(stable),
        **values,
    )
