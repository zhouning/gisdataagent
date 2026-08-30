from __future__ import annotations

from scripts.rehearse_agentops_temporal_checkpoint_reconciliation import (
    ACTIVITY_TYPE,
    WORKFLOW_TYPE,
    build_checkpoint_projection,
    build_workflow_input,
)


def test_checkpoint_reconciliation_rehearsal_input_and_schedule_are_replayable():
    kwargs = {
        "namespace_ref": "gda-agentops-sandbox",
        "task_queue_ref": "agentops-checkpoint-reconciliation",
        "rehearsal_id": "contract-001",
    }
    first = build_workflow_input(**kwargs)
    second = build_workflow_input(**kwargs)
    first_harness, first_schedule = build_checkpoint_projection(first)
    second_harness, second_schedule = build_checkpoint_projection(second)

    assert first == second
    assert first.identity.workflow_type == WORKFLOW_TYPE
    assert first_schedule == second_schedule
    assert first_schedule.activity_type == ACTIVITY_TYPE
    assert first_schedule.sdk_maximum_attempts == 1
    assert first_harness.checkpoint(first.identity.workflow_id) == second_harness.checkpoint(
        second.identity.workflow_id
    )


def test_checkpoint_reconciliation_projection_persists_schedule_without_evidence():
    workflow_input = build_workflow_input(
        namespace_ref="gda-agentops-sandbox",
        task_queue_ref="agentops-checkpoint-reconciliation",
        rehearsal_id="contract-002",
    )
    harness, schedule = build_checkpoint_projection(workflow_input)
    checkpoint = harness.checkpoint(workflow_input.identity.workflow_id)

    assert checkpoint.run.status.value == "running"
    assert checkpoint.activity_schedules == (schedule,)
    assert checkpoint.activity_evidence == ()
    assert checkpoint.execution.tool_calls[0].status.value == "running"
