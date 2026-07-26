"""Immutable policy and approval evidence for PlatformRun authorization."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from .platform_contracts import (
    ApprovalRecord,
    Artifact,
    ArtifactRole,
    PlatformRun,
    PolicyDecision,
    PolicyEffect,
    canonical_json_bytes,
    canonical_json_fingerprint,
)

POLICY_DECISION_ARTIFACT_SCHEMA = "gda.policy_decision_artifact.v1"
APPROVAL_ARTIFACT_SCHEMA = "gda.approval_artifact.v1"
POLICY_DECISION_MEDIA_TYPE = "application/vnd.gda.policy-decision+json"
APPROVAL_MEDIA_TYPE = "application/vnd.gda.approval+json"


class AuthorizationEvidenceError(RuntimeError):
    code = "authorization_evidence_invalid"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyDecisionEnvelope(_FrozenModel):
    artifact_schema: Literal["gda.policy_decision_artifact.v1"] = Field(
        default=POLICY_DECISION_ARTIFACT_SCHEMA,
        alias="schema",
    )
    decision: PolicyDecision


class ApprovalEnvelope(_FrozenModel):
    artifact_schema: Literal["gda.approval_artifact.v1"] = Field(
        default=APPROVAL_ARTIFACT_SCHEMA,
        alias="schema",
    )
    approval: ApprovalRecord


def _storage_uri(kind: str, tenant_id: str, artifact_id: UUID) -> str:
    return f"postgresql://gda-control/{kind}/{tenant_id}/{artifact_id}"


def _artifact_id(namespace: UUID, kind: str, manifest: dict[str, Any]) -> UUID:
    return uuid5(namespace, f"{kind}:{canonical_json_fingerprint(manifest)}")


def _validate_artifact_metadata(
    artifact: Artifact, expected: dict[str, Any], kind: str
) -> None:
    actual = artifact.model_dump(mode="python", include=set(expected))
    actual["artifact_role"] = getattr(
        artifact.artifact_role, "value", artifact.artifact_role
    )
    if any(actual[name] != value for name, value in expected.items()):
        raise AuthorizationEvidenceError(
            f"{kind} artifact metadata does not match its manifest"
        )


def build_policy_decision_artifact(decision: PolicyDecision) -> Artifact:
    envelope = PolicyDecisionEnvelope(decision=decision)
    manifest = envelope.model_dump(mode="json", by_alias=True)
    artifact_id = _artifact_id(decision.run_id, "policy-decision", manifest)
    content = canonical_json_bytes(manifest)
    return Artifact(
        tenant_id=decision.tenant_id,
        artifact_id=artifact_id,
        artifact_key=f"policy-decision:{artifact_id}",
        artifact_role="evidence",
        storage_uri=_storage_uri("policy-decisions", decision.tenant_id, artifact_id),
        media_type=POLICY_DECISION_MEDIA_TYPE,
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(content),
        run_id=None,
        resource_version_id=decision.definition_version_id,
        manifest=manifest,
        created_by=decision.evaluator_subject,
        created_at=decision.decided_at,
    )


def parse_policy_decision_artifact(artifact: Artifact) -> PolicyDecision:
    try:
        envelope = PolicyDecisionEnvelope.model_validate(artifact.manifest)
    except Exception as exc:
        raise AuthorizationEvidenceError(
            "policy decision artifact manifest is invalid"
        ) from exc
    decision = envelope.decision
    artifact_id = _artifact_id(decision.run_id, "policy-decision", artifact.manifest)
    expected = {
        "tenant_id": decision.tenant_id,
        "artifact_id": artifact_id,
        "artifact_key": f"policy-decision:{artifact_id}",
        "artifact_role": "evidence",
        "storage_uri": _storage_uri(
            "policy-decisions", decision.tenant_id, artifact_id
        ),
        "media_type": POLICY_DECISION_MEDIA_TYPE,
        "content_sha256": canonical_json_fingerprint(artifact.manifest),
        "size_bytes": len(canonical_json_bytes(artifact.manifest)),
        "run_id": None,
        "resource_version_id": decision.definition_version_id,
        "created_by": decision.evaluator_subject,
        "created_at": decision.decided_at,
    }
    _validate_artifact_metadata(artifact, expected, "policy decision")
    return decision


def build_approval_artifact(approval: ApprovalRecord) -> Artifact:
    envelope = ApprovalEnvelope(approval=approval)
    manifest = envelope.model_dump(mode="json", by_alias=True)
    artifact_id = _artifact_id(approval.run_id, "approval", manifest)
    content = canonical_json_bytes(manifest)
    return Artifact(
        tenant_id=approval.tenant_id,
        artifact_id=artifact_id,
        artifact_key=f"approval:{artifact_id}",
        artifact_role="evidence",
        storage_uri=_storage_uri("approvals", approval.tenant_id, artifact_id),
        media_type=APPROVAL_MEDIA_TYPE,
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(content),
        run_id=None,
        resource_version_id=approval.definition_version_id,
        manifest=manifest,
        created_by=approval.approver_subject,
        created_at=approval.decided_at,
    )


def parse_approval_artifact(artifact: Artifact) -> ApprovalRecord:
    try:
        envelope = ApprovalEnvelope.model_validate(artifact.manifest)
    except Exception as exc:
        raise AuthorizationEvidenceError(
            "approval artifact manifest is invalid"
        ) from exc
    approval = envelope.approval
    artifact_id = _artifact_id(approval.run_id, "approval", artifact.manifest)
    expected = {
        "tenant_id": approval.tenant_id,
        "artifact_id": artifact_id,
        "artifact_key": f"approval:{artifact_id}",
        "artifact_role": "evidence",
        "storage_uri": _storage_uri("approvals", approval.tenant_id, artifact_id),
        "media_type": APPROVAL_MEDIA_TYPE,
        "content_sha256": canonical_json_fingerprint(artifact.manifest),
        "size_bytes": len(canonical_json_bytes(artifact.manifest)),
        "run_id": None,
        "resource_version_id": approval.definition_version_id,
        "created_by": approval.approver_subject,
        "created_at": approval.decided_at,
    }
    _validate_artifact_metadata(artifact, expected, "approval")
    return approval


def validate_run_authorization_evidence(
    run: PlatformRun,
    decision_artifact: Artifact,
    approval_artifact: Artifact | None,
    execution_plan_artifact: Artifact,
    *,
    at: datetime,
    expected_action: str | None = None,
) -> tuple[PolicyDecision, ApprovalRecord | None]:
    if at.tzinfo is None or at.utcoffset() is None:
        raise AuthorizationEvidenceError("authorization time must include a timezone")
    decision = parse_policy_decision_artifact(decision_artifact)
    run_actor = (
        f"{run.subject_context.subject_type.value}:{run.subject_context.subject_id}"
    )
    expected_resources = tuple(
        sorted(
            {
                run.definition_version_id,
                *(binding.resource_version_id for binding in run.input_bindings),
            },
            key=str,
        )
    )
    scope_matches = (
        decision.tenant_id == run.tenant_id
        and decision.run_id == run.run_id
        and decision.subject_context == run.subject_context
        and decision.definition_version_id == run.definition_version_id
        and decision.resource_version_ids == expected_resources
        and decision.execution_plan_artifact_id == execution_plan_artifact.artifact_id
        and execution_plan_artifact.tenant_id == run.tenant_id
        and execution_plan_artifact.artifact_role == ArtifactRole.EXECUTION_PLAN
        and execution_plan_artifact.run_id is None
        and execution_plan_artifact.resource_version_id == run.definition_version_id
    )
    if not scope_matches:
        raise AuthorizationEvidenceError(
            "policy decision does not match the immutable run resource scope"
        )
    if expected_action is not None and decision.action != expected_action:
        raise AuthorizationEvidenceError(
            "policy decision action does not match command"
        )
    if decision.effect != PolicyEffect.ALLOW:
        raise AuthorizationEvidenceError("policy decision does not allow the command")
    if decision.obligations:
        raise AuthorizationEvidenceError("policy decision has unsupported obligations")
    if decision.evaluator_subject == run_actor:
        raise AuthorizationEvidenceError(
            "policy evaluator must be independent from the run workload"
        )
    if not (decision.decided_at <= at < decision.expires_at):
        raise AuthorizationEvidenceError("policy decision is not active")

    if decision.requires_approval and approval_artifact is None:
        raise AuthorizationEvidenceError("policy decision requires approval evidence")
    if not decision.requires_approval and approval_artifact is not None:
        raise AuthorizationEvidenceError("unexpected approval evidence is not allowed")
    if approval_artifact is None:
        return decision, None

    approval = parse_approval_artifact(approval_artifact)
    approval_matches = (
        approval.tenant_id == run.tenant_id
        and approval.run_id == run.run_id
        and approval.definition_version_id == run.definition_version_id
        and approval.policy_decision_artifact_id == decision_artifact.artifact_id
        and approval.policy_decision_sha256 == decision_artifact.content_sha256
        and approval.verdict.value == "approved"
    )
    if not approval_matches:
        raise AuthorizationEvidenceError(
            "approval does not authorize the referenced policy decision"
        )
    if approval.approver_subject in {run_actor, decision.evaluator_subject}:
        raise AuthorizationEvidenceError(
            "approval must be independent from executor and policy evaluator"
        )
    if approval.decided_at < decision.decided_at:
        raise AuthorizationEvidenceError("approval predates the policy decision")
    if approval.expires_at > decision.expires_at:
        raise AuthorizationEvidenceError("approval outlives the policy decision")
    if not (approval.decided_at <= at < approval.expires_at):
        raise AuthorizationEvidenceError("approval is not active")
    return decision, approval
