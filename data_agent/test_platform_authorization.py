from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from data_agent.platform_authorization import (
    APPROVAL_MEDIA_TYPE,
    POLICY_DECISION_MEDIA_TYPE,
    AuthorizationEvidenceError,
    build_approval_artifact,
    build_policy_decision_artifact,
    parse_approval_artifact,
    parse_policy_decision_artifact,
    validate_run_authorization_evidence,
)
from data_agent.platform_contracts import (
    ApprovalRecord,
    Artifact,
    PlatformRun,
    PolicyDecision,
    PolicyEffect,
    SubjectContext,
    canonical_json_fingerprint,
)

TENANT = "tenant-a"
DEFINITION_ID = UUID("30000000-0000-4000-8000-000000000010")
RUN_ID = UUID("30000000-0000-4000-8000-000000000020")
SOURCE_ID = UUID("30000000-0000-4000-8000-000000000030")
PLAN_ID = UUID("30000000-0000-4000-8000-000000000040")
NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
EXECUTOR = "workload:dataops-adapter"
EVALUATOR = "workload:policy-evaluator"
APPROVER = "human:dataops-approver"


def _run() -> PlatformRun:
    return PlatformRun(
        tenant_id=TENANT,
        run_id=RUN_ID,
        definition_version_id=DEFINITION_ID,
        orchestration_class="dataops",
        subject_context=SubjectContext(
            tenant_id=TENANT,
            subject_id="dataops-adapter",
            subject_type="workload",
            roles=("platform_operator",),
            purpose="publish governed land-use data",
        ),
        input_bindings=(
            {
                "binding_name": "source",
                "resource_version_id": SOURCE_ID,
                "semantic_type": "gis.land_use.parcels",
            },
        ),
        idempotency_key="publish:controlled-parcels",
        submitted_at=NOW,
    )


def _plan() -> Artifact:
    manifest = {"schema": "gda.test_execution_plan.v1"}
    return Artifact(
        tenant_id=TENANT,
        artifact_id=PLAN_ID,
        artifact_key="test-execution-plan",
        artifact_role="execution_plan",
        storage_uri=f"postgresql://gda-control/execution-plans/{TENANT}/{PLAN_ID}",
        media_type="application/vnd.gda.test-plan+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=len(b'{"schema":"gda.test_execution_plan.v1"}'),
        run_id=None,
        resource_version_id=DEFINITION_ID,
        manifest=manifest,
        created_by=EXECUTOR,
        created_at=NOW - timedelta(hours=2),
    )


def _decision(**overrides) -> PolicyDecision:
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "subject_context": _run().subject_context,
        "action": "dolphinscheduler.dispatch",
        "definition_version_id": DEFINITION_ID,
        "resource_version_ids": (SOURCE_ID, DEFINITION_ID),
        "execution_plan_artifact_id": PLAN_ID,
        "effect": PolicyEffect.ALLOW,
        "policy_version_ref": "gda://tenant-a/policy/dataops-dispatch:v1",
        "evaluator_subject": EVALUATOR,
        "requires_approval": False,
        "decided_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(hours=1),
    }
    values.update(overrides)
    return PolicyDecision(**values)


def _approval(decision_artifact: Artifact, **overrides) -> ApprovalRecord:
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_ID,
        "policy_decision_artifact_id": decision_artifact.artifact_id,
        "policy_decision_sha256": decision_artifact.content_sha256,
        "verdict": "approved",
        "approver_subject": APPROVER,
        "reason": "approved controlled publication",
        "decided_at": NOW - timedelta(minutes=30),
        "expires_at": NOW + timedelta(minutes=30),
    }
    values.update(overrides)
    return ApprovalRecord(**values)


def test_policy_and_approval_artifacts_round_trip_with_stable_identity():
    decision = _decision(requires_approval=True)
    first = build_policy_decision_artifact(decision)
    second = build_policy_decision_artifact(decision)
    approval = _approval(first)
    approval_artifact = build_approval_artifact(approval)

    assert first.artifact_id == second.artifact_id
    assert first.media_type == POLICY_DECISION_MEDIA_TYPE
    assert approval_artifact.media_type == APPROVAL_MEDIA_TYPE
    assert parse_policy_decision_artifact(first) == decision
    assert parse_approval_artifact(approval_artifact) == approval


def test_authorization_artifact_metadata_tampering_fails_closed():
    artifact = build_policy_decision_artifact(_decision()).model_copy(
        update={"content_sha256": "f" * 64}
    )

    with pytest.raises(AuthorizationEvidenceError, match="metadata"):
        parse_policy_decision_artifact(artifact)


def test_allow_decision_authorizes_exact_run_scope_without_approval():
    decision_artifact = build_policy_decision_artifact(_decision())

    decision, approval = validate_run_authorization_evidence(
        _run(),
        decision_artifact,
        None,
        _plan(),
        at=NOW,
        expected_action="dolphinscheduler.dispatch",
    )

    assert decision.effect == PolicyEffect.ALLOW
    assert approval is None


@pytest.mark.parametrize(
    ("decision", "message"),
    (
        (_decision(effect=PolicyEffect.DENY), "does not allow"),
        (_decision(resource_version_ids=(DEFINITION_ID,)), "resource scope"),
        (_decision(obligations=("emit_audit",)), "unsupported obligations"),
        (
            _decision(expires_at=NOW - timedelta(minutes=1)),
            "not active",
        ),
    ),
)
def test_policy_scope_effect_expiry_and_obligations_fail_closed(decision, message):
    with pytest.raises(AuthorizationEvidenceError, match=message):
        validate_run_authorization_evidence(
            _run(),
            build_policy_decision_artifact(decision),
            None,
            _plan(),
            at=NOW,
            expected_action="dolphinscheduler.dispatch",
        )


def test_required_independent_approval_is_enforced():
    decision_artifact = build_policy_decision_artifact(
        _decision(requires_approval=True)
    )
    with pytest.raises(AuthorizationEvidenceError, match="requires approval"):
        validate_run_authorization_evidence(
            _run(), decision_artifact, None, _plan(), at=NOW
        )

    approval_artifact = build_approval_artifact(_approval(decision_artifact))
    _decision_value, approval = validate_run_authorization_evidence(
        _run(), decision_artifact, approval_artifact, _plan(), at=NOW
    )
    assert approval is not None
    assert approval.approver_subject == APPROVER


def test_rejected_or_mismatched_approval_fails_closed():
    decision_artifact = build_policy_decision_artifact(
        _decision(requires_approval=True)
    )
    rejected = build_approval_artifact(_approval(decision_artifact, verdict="rejected"))
    with pytest.raises(AuthorizationEvidenceError, match="does not authorize"):
        validate_run_authorization_evidence(
            _run(), decision_artifact, rejected, _plan(), at=NOW
        )

    mismatched = build_approval_artifact(
        _approval(decision_artifact, policy_decision_sha256="e" * 64)
    )
    with pytest.raises(AuthorizationEvidenceError, match="does not authorize"):
        validate_run_authorization_evidence(
            _run(), decision_artifact, mismatched, _plan(), at=NOW
        )
