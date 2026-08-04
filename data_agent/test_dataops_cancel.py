from datetime import UTC, datetime
from uuid import UUID

import pytest

from data_agent.dataops_cancel import (
    DataOpsCancelSpec,
    build_dataops_cancel_submission,
    dataops_cancel_command_id,
    dataops_cancel_request_fingerprint,
    dataops_cancel_request_identity,
)
from data_agent.platform_contracts import (
    Artifact,
    PlatformRun,
    SubjectContext,
    canonical_json_fingerprint,
)

TENANT = "tenant-a"
RUN_ID = UUID("50000000-0000-4000-8000-000000000010")
DEFINITION_ID = UUID("50000000-0000-4000-8000-000000000020")
PLAN_ID = UUID("50000000-0000-4000-8000-000000000030")
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _spec(**overrides):
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "client_request_id": "cancel-console-20260801-001",
        "expected_state_version": 2,
        "requester_subject": "human:operator-1",
        "reason": "operator cancelled an obsolete source refresh",
        "workload_subject": "workload:dataops-adapter",
        "policy_version_ref": "gda://tenant-a/policy/dataops-cancel:v1",
        "policy_evaluator_subject": "workload:policy-evaluator",
    }
    values.update(overrides)
    return DataOpsCancelSpec(**values)


def _run(**overrides):
    values = {
        "tenant_id": TENANT,
        "run_id": RUN_ID,
        "definition_version_id": DEFINITION_ID,
        "orchestration_class": "dataops",
        "subject_context": SubjectContext(
            tenant_id=TENANT,
            subject_id="dataops-adapter",
            subject_type="workload",
            roles=("platform_operator",),
            purpose="refresh the governed source",
        ),
        "input_bindings": (),
        "idempotency_key": "refresh:source:1",
        "status": "running",
        "state_version": 2,
        "submitted_at": NOW,
    }
    values.update(overrides)
    return PlatformRun(**values)


def _plan():
    manifest = {"schema": "gda.test_execution_plan.v1"}
    return Artifact(
        tenant_id=TENANT,
        artifact_id=PLAN_ID,
        artifact_key="test-execution-plan",
        artifact_role="execution_plan",
        storage_uri="postgresql://gda-control/execution-plans/tenant-a/test",
        media_type="application/vnd.gda.test-plan+json",
        content_sha256=canonical_json_fingerprint(manifest),
        size_bytes=39,
        run_id=None,
        resource_version_id=DEFINITION_ID,
        manifest=manifest,
        created_by="workload:dataops-adapter",
        created_at=NOW,
    )


def test_cancel_identity_is_stable_but_payload_drift_is_visible():
    spec = _spec()
    drifted = _spec(reason="operator cancelled after detecting stale input")

    assert dataops_cancel_request_identity(spec) == dataops_cancel_request_identity(drifted)
    assert dataops_cancel_command_id(spec) == dataops_cancel_command_id(drifted)
    assert dataops_cancel_request_fingerprint(spec) != dataops_cancel_request_fingerprint(drifted)


def test_cancel_submission_binds_policy_request_and_workload():
    submission = build_dataops_cancel_submission(_spec(), _run(), _plan(), admitted_at=NOW)

    assert submission.command.command_type.value == "dolphinscheduler.cancel"
    assert submission.command.actor_subject == "workload:dataops-adapter"
    assert submission.command.payload["request_sha256"] == submission.request_sha256
    decision = submission.policy_artifact.manifest["decision"]
    assert decision["action"] == "dolphinscheduler.cancel"
    assert decision["effect"] == "allow"
    assert decision["obligations"] == []


def test_cancel_submission_rejects_a_different_executor_profile():
    with pytest.raises(ValueError, match="configured cancel executor"):
        build_dataops_cancel_submission(
            _spec(workload_subject="workload:other-adapter"),
            _run(),
            _plan(),
            admitted_at=NOW,
        )
