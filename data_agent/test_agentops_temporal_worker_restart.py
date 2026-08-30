from __future__ import annotations

import pytest

from scripts.rehearse_agentops_temporal_worker_restart import (
    RESTART_ACTIVITY_TYPE,
    RESTART_WORKFLOW_TYPE,
    build_attempt_schedule,
)


def test_restart_attempts_are_explicit_and_identity_stable() -> None:
    first = build_attempt_schedule(
        workflow_id="gda-agentops-worker-restart-contract-001",
        namespace_ref="gda-agentops-sandbox",
        task_queue_ref="agentops-gis-worker-restart",
        attempt_no=1,
    )
    first_replay = build_attempt_schedule(
        workflow_id="gda-agentops-worker-restart-contract-001",
        namespace_ref="gda-agentops-sandbox",
        task_queue_ref="agentops-gis-worker-restart",
        attempt_no=1,
    )
    second = build_attempt_schedule(
        workflow_id="gda-agentops-worker-restart-contract-001",
        namespace_ref="gda-agentops-sandbox",
        task_queue_ref="agentops-gis-worker-restart",
        attempt_no=2,
    )

    assert first == first_replay
    assert first.activity_type == RESTART_ACTIVITY_TYPE
    assert second.activity_type == RESTART_ACTIVITY_TYPE
    assert first.sdk_maximum_attempts == second.sdk_maximum_attempts == 1
    assert first.attempt_no == 1
    assert second.attempt_no == 2
    assert first.activity_id != second.activity_id
    assert first.request.request_sha256 != second.request.request_sha256
    assert first.schedule_sha256 != second.schedule_sha256
    assert first.request.tool_call_id == second.request.tool_call_id
    assert first.request.idempotency_key == second.request.idempotency_key


def test_restart_attempt_rejects_non_positive_attempt() -> None:
    with pytest.raises(ValueError, match="attempt_no"):
        build_attempt_schedule(
            workflow_id="gda-agentops-worker-restart-contract-002",
            namespace_ref="gda-agentops-sandbox",
            task_queue_ref="agentops-gis-worker-restart",
            attempt_no=0,
        )


def test_restart_workflow_and_activity_names_are_provider_stable() -> None:
    assert RESTART_WORKFLOW_TYPE == "gda.agentops.worker-restart.v1"
    assert RESTART_ACTIVITY_TYPE == "gda.agentops.worker-restart.activity"
