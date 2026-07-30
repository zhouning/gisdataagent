from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.active_metadata_authorization import (
    MetadataActivationAuthorization,
    MetadataActivationAuthorizationError,
    build_metadata_activation_authorization,
    dispatch_command_id,
)
from data_agent.active_metadata_change_contract import (
    build_active_metadata_registration,
    build_metadata_activation_intent,
    build_metadata_activation_request,
)
from data_agent.platform_authorization import (
    build_approval_artifact,
    build_policy_decision_artifact,
)
from data_agent.platform_contracts import (
    ApprovalRecord,
    Artifact,
    PlatformDefinitionVersion,
    PlatformRun,
    PolicyDecision,
    ResourceVersion,
    RunPolicyReferences,
    SubjectContext,
    canonical_json_fingerprint,
    platform_definition_fingerprint,
)

TENANT = "metadata-auth"
SOURCE_ID = UUID("a5000000-0000-4000-8000-000000000001")
DEFINITION_ID = UUID("a5000000-0000-4000-8000-000000000002")
RUN_ID = UUID("a5000000-0000-4000-8000-000000000003")
PLAN_ID = UUID("a5000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)


def _source() -> ResourceVersion:
    return ResourceVersion(
        tenant_id=TENANT,
        resource_urn=f"gda://{TENANT}/dataset/cultural-districts",
        resource_version_id=SOURCE_ID,
        version_key="bundle-v1",
        content_sha256="a" * 64,
        authority_version_ref={"bundle": "local-acceptance"},
        created_by="workload:metadata-registrar",
        created_at=NOW - timedelta(hours=2),
    )


def _request():
    registration = build_active_metadata_registration(
        _source(), consumer_subject="workload:active-metadata-consumer"
    )
    intent = build_metadata_activation_intent(
        registration.event,
        routed_by="workload:active-metadata-consumer",
    )
    return build_metadata_activation_request(intent)


def _definition() -> PlatformDefinitionVersion:
    document = {"tasks": ["project-governance-metadata"]}
    input_contract = {"metadata_change": "dataset"}
    output_contract = {"projection_plan": "artifact"}
    fingerprint = platform_definition_fingerprint(
        orchestration_class="dataops",
        capability_id="metadata_fabric.projection_plan",
        portability_class="portable",
        definition_document=document,
        input_contract=input_contract,
        output_contract=output_contract,
    )
    return PlatformDefinitionVersion(
        tenant_id=TENANT,
        definition_urn=f"gda://{TENANT}/definition/metadata-projection",
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        capability_id="metadata_fabric.projection_plan",
        portability_class="portable",
        definition_document=document,
        input_contract=input_contract,
        output_contract=output_contract,
        definition_sha256=fingerprint,
    )


def _plan() -> Artifact:
    manifest = {"schema": "gda.metadata_projection_execution_plan.v1"}
    return Artifact(
        tenant_id=TENANT,
        artifact_id=PLAN_ID,
        artifact_key="metadata-projection-plan",
        artifact_role="execution_plan",
        storage_uri=f"postgresql://gda-control/execution-plans/{TENANT}/{PLAN_ID}",
        media_type="application/vnd.gda.metadata-projection-plan+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(b'{"schema":"gda.metadata_projection_execution_plan.v1"}'),
        resource_version_id=DEFINITION_ID,
        manifest=manifest,
        created_by="workload:metadata-plan-compiler",
        created_at=NOW - timedelta(minutes=30),
    )


def _chain():
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id="metadata-projection-runner",
        subject_type="workload",
        roles=("metadata_projector",),
        purpose="project active metadata change",
    )
    provisional = PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        subject_context=subject,
        input_bindings=(
            {
                "binding_name": "metadata_change",
                "resource_version_id": SOURCE_ID,
                "semantic_type": "gis.cultural_districts",
            },
        ),
        idempotency_key="metadata-projection:cultural-districts:v1",
        submitted_at=NOW - timedelta(minutes=20),
    )
    decision = PolicyDecision(
        tenant_id=TENANT,
        run_id=RUN_ID,
        subject_context=subject,
        action="dolphinscheduler.dispatch",
        definition_version_id=DEFINITION_ID,
        resource_version_ids=(DEFINITION_ID, SOURCE_ID),
        execution_plan_artifact_id=PLAN_ID,
        effect="allow",
        policy_version_ref=f"gda://{TENANT}/policy/metadata-dispatch-v1",
        evaluator_subject="workload:metadata-policy-evaluator",
        requires_approval=True,
        decided_at=NOW - timedelta(minutes=15),
        expires_at=NOW + timedelta(hours=1),
    )
    policy_artifact = build_policy_decision_artifact(decision)
    approval = ApprovalRecord(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        policy_decision_artifact_id=policy_artifact.artifact_id,
        policy_decision_sha256=policy_artifact.content_sha256,
        verdict="approved",
        approver_subject="human:metadata-governance-approver",
        reason="approved bounded metadata projection",
        decided_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(minutes=45),
    )
    approval_artifact = build_approval_artifact(approval)
    run = provisional.model_copy(
        update={
            "policy_refs": RunPolicyReferences(
                policy_decision_artifact_id=policy_artifact.artifact_id,
                approval_artifact_id=approval_artifact.artifact_id,
            )
        }
    )
    return run, policy_artifact, approval_artifact


def _authorization(**overrides):
    run, policy, approval = _chain()
    values = {
        "request": _request(),
        "resource_version": _source(),
        "definition": _definition(),
        "run": run,
        "execution_plan_artifact": _plan(),
        "policy_decision_artifact": policy,
        "approval_artifact": approval,
        "authorized_by": "workload:metadata-activation-authorizer",
        "authorized_at": NOW,
    }
    values.update(overrides)
    return build_metadata_activation_authorization(**values)


def test_authorization_binds_complete_chain_with_stable_identity():
    first = _authorization()
    second = _authorization()

    assert first == second
    assert first.command_id == dispatch_command_id(RUN_ID, PLAN_ID)
    assert first.scheduler_command_enqueued is True
    assert first.provider_apply_authorized is False
    assert first.production_scheduler_submission_verified is False


def test_authorization_rejects_unbound_source_definition_and_authorizer():
    with pytest.raises(
        MetadataActivationAuthorizationError, match="ResourceVersion"
    ):
        _authorization(
            resource_version=_source().model_copy(
                update={"content_sha256": "b" * 64}
            )
        )

    with pytest.raises(
        MetadataActivationAuthorizationError, match="DefinitionVersion"
    ):
        _authorization(
            definition=_definition().model_copy(
                update={"capability_id": "metadata_fabric.apply"}
            )
        )

    with pytest.raises(MetadataActivationAuthorizationError, match="independent"):
        _authorization(authorized_by="workload:metadata-policy-evaluator")


def test_authorization_requires_active_independent_approval():
    run, policy, approval = _chain()
    expired_approval = build_approval_artifact(
        ApprovalRecord.model_validate(
            approval.manifest["approval"]
            | {
                "decided_at": (NOW - timedelta(minutes=10)).isoformat(),
                "expires_at": (NOW - timedelta(minutes=1)).isoformat(),
            }
        )
    )
    run = run.model_copy(
        update={
            "policy_refs": RunPolicyReferences(
                policy_decision_artifact_id=policy.artifact_id,
                approval_artifact_id=expired_approval.artifact_id,
            )
        }
    )
    with pytest.raises(MetadataActivationAuthorizationError, match="not active"):
        build_metadata_activation_authorization(
            _request(),
            _source(),
            _definition(),
            run,
            _plan(),
            policy,
            expired_approval,
            authorized_by="workload:metadata-activation-authorizer",
            authorized_at=NOW,
        )


def test_authorization_document_tampering_fails_closed():
    authorization = _authorization()
    payload = authorization.model_dump(mode="json", by_alias=True)
    payload["content_sha256"] = "f" * 64

    with pytest.raises(ValidationError, match="authorization"):
        MetadataActivationAuthorization.model_validate(payload)
