from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from data_agent.dataops_manual import (
    DataOpsManualTriggerSpec,
    build_manual_dataops_submission,
    dataops_manual_idempotency_key,
    dataops_manual_lock_keys,
    dataops_manual_request_fingerprint,
    dataops_manual_request_identity,
    dataops_manual_run_id,
)
from data_agent.platform_authorization import parse_policy_decision_artifact
from data_agent.platform_contracts import ResourceBinding

TENANT = "tenant-a"
DEFINITION_ID = UUID("30000000-0000-4000-8000-000000000010")
SOURCE_ID = UUID("30000000-0000-4000-8000-000000000020")
PLAN_ID = UUID("30000000-0000-4000-8000-000000000030")
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 2, tzinfo=UTC)
ADMITTED_AT = datetime(2026, 8, 1, 2, 3, 4, tzinfo=UTC)


def _spec(**overrides):
    values = {
        "tenant_id": TENANT,
        "client_request_id": "operator-console-20260801-001",
        "definition_version_id": DEFINITION_ID,
        "logical_start": START,
        "logical_end": END,
        "input_bindings": (
            ResourceBinding(
                binding_name="source",
                resource_version_id=SOURCE_ID,
                semantic_type="gis.land_use.parcels",
            ),
        ),
        "execution_plan_artifact_id": PLAN_ID,
        "requester_subject": "human:data-platform-operator",
        "workload_subject_id": "dataops-adapter",
        "purpose": "execute a governed operator-requested land-use audit",
        "policy_version_ref": "gda://tenant-a/policy/dataops-manual:v1",
        "policy_evaluator_subject": "workload:policy-evaluator",
        "config_fingerprint": "a" * 64,
    }
    values.update(overrides)
    return DataOpsManualTriggerSpec(**values)


def test_manual_request_retry_identity_is_stable_across_process_restarts():
    spec = _spec()
    first = build_manual_dataops_submission(spec, admitted_at=ADMITTED_AT)
    retried = build_manual_dataops_submission(
        spec,
        admitted_at=ADMITTED_AT + timedelta(hours=2),
    )

    assert first.request_sha256 == retried.request_sha256
    assert first.run.run_id == retried.run.run_id == dataops_manual_run_id(spec)
    assert (
        first.run.idempotency_key
        == retried.run.idempotency_key
        == dataops_manual_idempotency_key(spec)
    )
    assert first.invocation.client_request_id == spec.client_request_id
    assert first.invocation.requested_at == ADMITTED_AT
    assert first.invocation_version != retried.invocation_version
    assert first.policy_artifact != retried.policy_artifact


def test_manual_submission_records_human_to_workload_delegation_and_policy_scope():
    submission = build_manual_dataops_submission(_spec(), admitted_at=ADMITTED_AT)
    decision = parse_policy_decision_artifact(submission.policy_artifact)
    bindings = {item.binding_name: item for item in submission.run.input_bindings}

    assert submission.invocation.trigger_kind == "manual"
    assert submission.invocation.requested_by == "human:data-platform-operator"
    assert submission.run.subject_context.subject_type.value == "workload"
    assert submission.run.subject_context.subject_id == "dataops-adapter"
    assert (
        submission.run.subject_context.delegated_by
        == submission.invocation.requested_by
    )
    assert tuple(bindings) == ("invocation", "source")
    assert decision.subject_context == submission.run.subject_context
    assert decision.obligations == ()
    assert decision.resource_version_ids == tuple(
        sorted(
            {
                DEFINITION_ID,
                SOURCE_ID,
                submission.invocation_version.resource_version_id,
            },
            key=str,
        )
    )


def test_same_client_request_id_keeps_one_identity_but_payload_drift_is_visible():
    first = _spec()
    changed = _spec(logical_end=END + timedelta(days=1))

    assert dataops_manual_request_identity(first) == dataops_manual_request_identity(
        changed
    )
    assert dataops_manual_run_id(first) == dataops_manual_run_id(changed)
    assert dataops_manual_lock_keys(first) == dataops_manual_lock_keys(changed)
    assert dataops_manual_request_fingerprint(first) != (
        dataops_manual_request_fingerprint(changed)
    )
    assert build_manual_dataops_submission(
        first, admitted_at=ADMITTED_AT
    ).invocation != build_manual_dataops_submission(
        changed, admitted_at=ADMITTED_AT
    ).invocation


def test_manual_request_identity_is_tenant_scoped():
    first = _spec()
    second = _spec(
        tenant_id="tenant-b",
        policy_version_ref="gda://tenant-b/policy/dataops-manual:v1",
    )

    assert dataops_manual_request_identity(first) != dataops_manual_request_identity(
        second
    )
    assert dataops_manual_run_id(first) != dataops_manual_run_id(second)


@pytest.mark.parametrize(
    "overrides",
    (
        {"logical_end": START},
        {"requester_subject": "workload:not-a-human"},
        {"policy_evaluator_subject": "workload:dataops-adapter"},
        {"workload_roles": ()},
        {
            "input_bindings": (
                ResourceBinding(
                    binding_name="invocation",
                    resource_version_id=SOURCE_ID,
                    semantic_type="tampered",
                ),
            )
        },
    ),
)
def test_manual_request_rejects_ambiguous_or_unsafe_contracts(overrides):
    with pytest.raises(ValueError):
        _spec(**overrides)
