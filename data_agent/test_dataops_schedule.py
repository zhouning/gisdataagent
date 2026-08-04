from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from data_agent.dataops_schedule import (
    DataOpsScheduleController,
    DataOpsScheduleWindowSpec,
    build_scheduled_dataops_submission,
    dataops_schedule_idempotency_key,
    dataops_schedule_lock_keys,
    dataops_schedule_run_id,
    dataops_schedule_window_fingerprint,
)
from data_agent.platform_authorization import parse_policy_decision_artifact
from data_agent.platform_contracts import ResourceBinding

TENANT = "tenant-a"
DEFINITION_ID = UUID("20000000-0000-4000-8000-000000000010")
SOURCE_ID = UUID("20000000-0000-4000-8000-000000000020")
PLAN_ID = UUID("20000000-0000-4000-8000-000000000030")
START = datetime(2026, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 2, tzinfo=UTC)
SCHEDULED_FOR = END + timedelta(minutes=5)
ADMITTED_AT = datetime(2026, 8, 1, 2, 3, 4, tzinfo=UTC)


def _spec(**overrides):
    values = {
        "tenant_id": TENANT,
        "definition_version_id": DEFINITION_ID,
        "schedule_ref": "gda://tenant-a/schedule/land-use-daily",
        "scheduled_for": SCHEDULED_FOR,
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
        "workload_subject_id": "dataops-adapter",
        "purpose": "execute governed daily land-use production",
        "policy_version_ref": "gda://tenant-a/policy/dataops-schedule:v1",
        "policy_evaluator_subject": "workload:policy-evaluator",
        "config_fingerprint": "a" * 64,
    }
    values.update(overrides)
    return DataOpsScheduleWindowSpec(**values)


def test_schedule_window_identity_is_stable_across_missed_window_recovery():
    spec = _spec()
    first = build_scheduled_dataops_submission(spec, admitted_at=ADMITTED_AT)
    recovered = build_scheduled_dataops_submission(
        spec,
        admitted_at=ADMITTED_AT + timedelta(hours=2),
    )

    assert first.window_sha256 == recovered.window_sha256
    assert first.run.run_id == recovered.run.run_id == dataops_schedule_run_id(spec)
    assert (
        first.run.idempotency_key
        == recovered.run.idempotency_key
        == dataops_schedule_idempotency_key(spec)
    )
    assert first.invocation.requested_at == ADMITTED_AT
    assert first.invocation.schedule_times == (SCHEDULED_FOR,)
    assert first.invocation.trigger_kind == "schedule"
    assert first.invocation.schedule_ref == spec.schedule_ref
    assert first.invocation_version != recovered.invocation_version
    assert first.policy_artifact != recovered.policy_artifact


def test_schedule_submission_binds_invocation_into_policy_scope():
    submission = build_scheduled_dataops_submission(_spec(), admitted_at=ADMITTED_AT)
    decision = parse_policy_decision_artifact(submission.policy_artifact)
    bindings = {item.binding_name: item for item in submission.run.input_bindings}

    assert tuple(bindings) == ("invocation", "source")
    assert bindings["invocation"].resource_version_id == (
        submission.invocation_version.resource_version_id
    )
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
    assert decision.run_id == submission.run.run_id
    assert decision.execution_plan_artifact_id == PLAN_ID
    assert decision.decided_at == ADMITTED_AT


def test_schedule_window_identity_and_lock_are_tenant_scoped():
    first = _spec()
    second = _spec(
        tenant_id="tenant-b",
        schedule_ref="gda://tenant-b/schedule/land-use-daily",
        policy_version_ref="gda://tenant-b/policy/dataops-schedule:v1",
    )

    assert dataops_schedule_window_fingerprint(first) != (
        dataops_schedule_window_fingerprint(second)
    )
    assert dataops_schedule_run_id(first) != dataops_schedule_run_id(second)
    assert dataops_schedule_lock_keys(first) != dataops_schedule_lock_keys(second)


@pytest.mark.parametrize(
    "overrides",
    (
        {"logical_end": START},
        {
            "input_bindings": (
                ResourceBinding(
                    binding_name="invocation",
                    resource_version_id=SOURCE_ID,
                    semantic_type="tampered",
                ),
            )
        },
        {"policy_evaluator_subject": "workload:dataops-adapter"},
    ),
)
def test_schedule_window_rejects_ambiguous_or_unsafe_contracts(overrides):
    with pytest.raises(ValueError):
        _spec(**overrides)


class _RecordingGateway:
    def __init__(self):
        self.specs = []

    def submit_schedule_window(self, spec):
        self.specs.append(spec)
        return spec


def test_recovery_admits_exact_windows_in_schedule_order_without_cron_logic():
    gateway = _RecordingGateway()
    controller = DataOpsScheduleController(gateway)
    later = _spec(
        logical_start=START + timedelta(days=1),
        logical_end=END + timedelta(days=1),
        scheduled_for=SCHEDULED_FOR + timedelta(days=1),
    )
    earlier = _spec()

    results = controller.recover_windows((later, earlier))

    assert results == (earlier, later)
    assert gateway.specs == [earlier, later]
    with pytest.raises(ValueError, match="duplicate schedule windows"):
        controller.recover_windows((earlier, earlier))
