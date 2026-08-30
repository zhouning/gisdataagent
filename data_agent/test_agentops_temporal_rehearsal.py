from __future__ import annotations

from scripts.rehearse_agentops_temporal import (
    REHEARSAL_ACTIVITY_TYPE,
    REHEARSAL_WORKFLOW_TYPE,
    WORKER_IDENTITY,
    build_schedule_plan,
)


def test_rehearsal_schedule_is_deterministic_and_single_attempt():
    first = build_schedule_plan(
        workflow_id="gda-agentops-rehearsal-contract-001",
        namespace_ref="gda-agentops-sandbox",
        task_queue_ref="agentops-gis-rehearsal",
    )
    replay = build_schedule_plan(
        workflow_id="gda-agentops-rehearsal-contract-001",
        namespace_ref="gda-agentops-sandbox",
        task_queue_ref="agentops-gis-rehearsal",
    )
    changed_queue = build_schedule_plan(
        workflow_id="gda-agentops-rehearsal-contract-001",
        namespace_ref="gda-agentops-sandbox",
        task_queue_ref="agentops-gis-rehearsal-other",
    )

    assert first == replay
    assert first.activity_type == REHEARSAL_ACTIVITY_TYPE
    assert first.attempt_no == 1
    assert first.sdk_maximum_attempts == 1
    assert first.request.workflow_id == first.workflow_id
    assert first.request.activity_id == first.activity_id
    assert first.request_sha256 == first.request.request_sha256
    assert first.schedule_sha256 != changed_queue.schedule_sha256
    assert first.task_queue_sha256 != changed_queue.task_queue_sha256


def test_rehearsal_worker_registration_binds_workflow_activity_and_revision_hashes():
    from scripts.rehearse_agentops_temporal import _worker_config

    config = _worker_config(
        frontend_target="127.0.0.1:7233",
        namespace_ref="gda-agentops-sandbox",
        task_queue_ref="agentops-gis-rehearsal",
    )
    registration = config.registration()

    assert registration.tenant_id == "planning"
    assert registration.namespace_ref == "gda-agentops-sandbox"
    assert registration.task_queue_ref == "agentops-gis-rehearsal"
    assert registration.worker_identity_ref == WORKER_IDENTITY
    assert registration.workflow_type == REHEARSAL_WORKFLOW_TYPE
    assert registration.activity_types == (REHEARSAL_ACTIVITY_TYPE,)
    assert len(registration.agent_spec_sha256) == 64
    assert len(registration.deployment_revision_sha256) == 64
    assert registration.max_concurrent_activities == 1
    assert registration.max_concurrent_workflow_tasks == 1
