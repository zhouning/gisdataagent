from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from data_agent.agentops_temporal_adapter import (
    TEMPORAL_START_RESULT_SCHEMA,
    TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA,
    TemporalProviderStartResult,
    TemporalProviderStartStatus,
    TemporalProviderWorkflowInputObservation,
    TemporalStartReconciliation,
    TemporalStartReconciliationVerdict,
    build_temporal_start_request,
)
from data_agent.agentops_temporal_contracts import temporal_contract_fingerprint
from data_agent.agentops_temporal_reconciler_worker import (
    AgentOpsTemporalReconcilerDiscoveryConfig,
    AgentOpsTemporalReconcilerDiscoveryWorker,
)
from data_agent.agentops_temporal_start_target_authority import (
    AgentOpsTemporalStartTargetStatus,
    TemporalStartTarget,
    build_unknown_start_reconciliation,
)
from data_agent.test_agentops_temporal_checkpoint_authority import (
    _checkpoint,
    _observation,
)
from data_agent.test_agentops_temporal_reconciler_worker import _Authority


def _unknown_target() -> tuple[TemporalStartTarget, Any, Any]:
    workflow_input = _checkpoint().workflow_input
    request = build_temporal_start_request(workflow_input)
    values: dict[str, Any] = {
        "tenant_id": workflow_input.tenant_id,
        "namespace_ref": workflow_input.identity.namespace.namespace_ref,
        "workflow_id": workflow_input.identity.workflow_id,
        "status": TemporalProviderStartStatus.UNKNOWN,
        "provider_run_id": None,
        "provider_receipt_ref": "temporal://receipt/unknown-target",
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_START_RESULT_SCHEMA, values, "result_sha256"
    )
    result = TemporalProviderStartResult(**values)
    pending_values = {
        "tenant_id": request.tenant_id,
        "namespace_ref": request.namespace_ref,
        "workflow_id": request.workflow_id,
            "provider_status": result.status,
            "verdict": TemporalStartReconciliationVerdict.UNKNOWN_PENDING,
            "provider_run_id": None,
            "provider_receipt_ref": result.provider_receipt_ref,
            "request_sha256": request.payload_sha256,
            "observed_input_sha256": None,
    }
    pending_values["reconciliation_sha256"] = temporal_contract_fingerprint(
        "gda.temporal_start_reconciliation.v1",
        pending_values,
        "reconciliation_sha256",
    )
    reconciliation = TemporalStartReconciliation(**pending_values)
    now = datetime.now(UTC)
    target = TemporalStartTarget(
        tenant_id=request.tenant_id,
        target_id=uuid4(),
        namespace_ref=request.namespace_ref,
        workflow_id=request.workflow_id,
        workflow_type=request.workflow_type,
        task_queue_ref=request.task_queue_ref,
        idempotency_key=workflow_input.identity.idempotency_key,
        start_request_sha256=request.payload_sha256,
        start_request_document=request.model_dump(mode="json"),
        start_result_sha256=result.result_sha256,
        start_result_document=result.model_dump(mode="json"),
        start_reconciliation_sha256=reconciliation.reconciliation_sha256,
        start_reconciliation_document=reconciliation.model_dump(mode="json"),
        status=AgentOpsTemporalStartTargetStatus.CLAIMED,
        attempt_count=1,
        available_at=now,
        claimed_by="workload:target-worker",
        claimed_until=now + timedelta(seconds=30),
        registered_by="workload:start-gateway",
        registered_at=now,
        updated_at=now,
    )
    return target, request, result


def test_unknown_target_stays_pending_until_matching_input_observation() -> None:
    target, _request, _result = _unknown_target()
    observation_values: dict[str, Any] = {
        "tenant_id": target.tenant_id,
        "namespace_ref": target.namespace_ref,
        "workflow_id": target.workflow_id,
        "provider_run_id": _observation().provider_run_id,
        "provider_receipt_ref": "temporal://receipt/observed-input",
        "observed_input_sha256": target.start_request_sha256,
    }
    observation_values["observation_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA,
        observation_values,
        "observation_sha256",
    )
    observation = TemporalProviderWorkflowInputObservation(**observation_values)
    reconciliation = build_unknown_start_reconciliation(target, observation)
    assert reconciliation.verdict is TemporalStartReconciliationVerdict.ALREADY_EXISTS_MATCHED
    assert reconciliation.provider_run_id == observation.provider_run_id

    mismatched = observation.model_copy(update={"observed_input_sha256": "0" * 64})
    with pytest.raises(ValueError, match="does not match"):
        build_unknown_start_reconciliation(target, mismatched)


def test_known_started_target_requires_reconciliation_evidence() -> None:
    workflow_input = _checkpoint().workflow_input
    request = build_temporal_start_request(workflow_input)
    values: dict[str, Any] = {
        "tenant_id": workflow_input.tenant_id,
        "namespace_ref": workflow_input.identity.namespace.namespace_ref,
        "workflow_id": workflow_input.identity.workflow_id,
        "status": TemporalProviderStartStatus.STARTED,
        "provider_run_id": "temporal-run:known-target",
        "provider_receipt_ref": "temporal://receipt/known-target",
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_START_RESULT_SCHEMA, values, "result_sha256"
    )
    result = TemporalProviderStartResult(**values)
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="requires reconciliation evidence"):
        TemporalStartTarget(
            tenant_id=request.tenant_id,
            target_id=uuid4(),
            namespace_ref=request.namespace_ref,
            workflow_id=request.workflow_id,
            workflow_type=request.workflow_type,
            task_queue_ref=request.task_queue_ref,
            idempotency_key=workflow_input.identity.idempotency_key,
            start_request_sha256=request.payload_sha256,
            start_request_document=request.model_dump(mode="json"),
            start_result_sha256=result.result_sha256,
            start_result_document=result.model_dump(mode="json"),
            status=AgentOpsTemporalStartTargetStatus.CLAIMED,
            attempt_count=1,
            available_at=now,
            claimed_by="workload:target-worker",
            claimed_until=now + timedelta(seconds=30),
            registered_by="workload:start-gateway",
            registered_at=now,
            updated_at=now,
        )


def test_unknown_target_cannot_attach_a_second_provider_run() -> None:
    target, _request, _result = _unknown_target()
    observation_values: dict[str, Any] = {
        "tenant_id": target.tenant_id,
        "namespace_ref": target.namespace_ref,
        "workflow_id": target.workflow_id,
        "provider_run_id": _observation().provider_run_id,
        "provider_receipt_ref": "temporal://receipt/observed-input",
        "observed_input_sha256": target.start_request_sha256,
    }
    observation_values["observation_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA,
        observation_values,
        "observation_sha256",
    )
    first_reconciliation = build_unknown_start_reconciliation(
        target, TemporalProviderWorkflowInputObservation(**observation_values)
    )
    reconciled = target.model_copy(
        update={
            "provider_run_id": observation_values["provider_run_id"],
            "start_reconciliation_sha256": first_reconciliation.reconciliation_sha256,
            "start_reconciliation_document": first_reconciliation.model_dump(mode="json"),
        }
    )
    with pytest.raises(ValueError, match="already has a provider run"):
        build_unknown_start_reconciliation(
            reconciled, TemporalProviderWorkflowInputObservation(**observation_values)
        )


class _TargetAuthority:
    def __init__(self, target: TemporalStartTarget):
        self.target = target
        self.claims = 0
        self.completed = 0
        self.released = 0
        self.release_error: str | None = None

    def claim_due_targets(self, **_kwargs: Any):
        self.claims += 1
        return (self.target,) if self.claims == 1 else ()

    def renew_target_claim(self, target, **_kwargs: Any):
        return target

    def attach_provider_run(self, target, observation, **_kwargs: Any):
        reconciliation = build_unknown_start_reconciliation(target, observation)
        return target.model_copy(
            update={
                "provider_run_id": observation.provider_run_id,
                "start_reconciliation_sha256": reconciliation.reconciliation_sha256,
                "start_reconciliation_document": reconciliation.model_dump(mode="json"),
            }
        )

    def complete_target(self, target, **_kwargs: Any):
        self.completed += 1
        return target

    def release_target_claim(self, target, **_kwargs: Any):
        self.released += 1
        self.release_error = _kwargs.get("error")
        return target

    def fail_target(self, target, **_kwargs: Any):
        return target


class _Provider:
    def __init__(self, target: TemporalStartTarget):
        self.target = target
        self.input_calls = 0

    async def observe_workflow_input(self, **_kwargs: Any):
        self.input_calls += 1
        values: dict[str, Any] = {
            "tenant_id": self.target.tenant_id,
            "namespace_ref": self.target.namespace_ref,
            "workflow_id": self.target.workflow_id,
            "provider_run_id": _observation().provider_run_id,
            "provider_receipt_ref": "temporal://receipt/observed-input",
            "observed_input_sha256": self.target.start_request_sha256,
        }
        values["observation_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA,
            values,
            "observation_sha256",
        )
        return TemporalProviderWorkflowInputObservation(**values)

    async def observe_workflow_history(self, **_kwargs: Any):
        return _observation()


def test_discovery_worker_claims_unknown_target_and_completes_after_reconciliation() -> None:
    target, _request, _result = _unknown_target()
    target_authority = _TargetAuthority(target)
    checkpoint_authority = _Authority()
    config = AgentOpsTemporalReconcilerDiscoveryConfig(
        tenant_id=target.tenant_id,
        namespace_ref=target.namespace_ref,
        worker_id="workload:target-worker",
        lease_seconds=5,
        heartbeat_interval_seconds=0.1,
        observation_timeout_seconds=2,
        poll_interval_seconds=0.1,
    )
    worker = AgentOpsTemporalReconcilerDiscoveryWorker(
        config,
        provider=_Provider(target),
        target_authority=target_authority,
        checkpoint_authority=checkpoint_authority,
    )
    cycle = asyncio.run(worker.run_once())
    assert cycle.claimed_count == 1
    assert cycle.completed_count == 1
    assert cycle.pending_count == 0
    assert target_authority.completed == 1
    assert checkpoint_authority.recorded == 1


def test_discovery_worker_does_not_complete_without_checkpoint() -> None:
    target, _request, _result = _unknown_target()
    target_authority = _TargetAuthority(target)
    checkpoint_authority = _Authority()
    checkpoint_authority.checkpoint = None
    config = AgentOpsTemporalReconcilerDiscoveryConfig(
        tenant_id=target.tenant_id,
        namespace_ref=target.namespace_ref,
        worker_id="workload:target-worker",
        lease_seconds=5,
        heartbeat_interval_seconds=0.1,
        observation_timeout_seconds=2,
        poll_interval_seconds=0.1,
    )
    cycle = asyncio.run(
        AgentOpsTemporalReconcilerDiscoveryWorker(
            config,
            provider=_Provider(target),
            target_authority=target_authority,
            checkpoint_authority=checkpoint_authority,
        ).run_once()
    )
    assert cycle.pending_count == 1
    assert target_authority.completed == 0
    assert target_authority.released == 1
