from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from data_agent.agentops_contracts import (
    AgentRun,
    AgentRunStatus,
    AgentSideEffect,
    agent_run_fingerprint,
)
from data_agent.agentops_temporal_adapter import (
    TEMPORAL_ACTIVITY_RESULT_SCHEMA,
    TEMPORAL_SIGNAL_RESULT_SCHEMA,
    TEMPORAL_START_RESULT_SCHEMA,
    TemporalActivityAdapter,
    TemporalAdapterError,
    TemporalAdapterProtocolError,
    TemporalProviderActivityResult,
    TemporalProviderSignalResult,
    TemporalProviderSignalStatus,
    TemporalProviderStartResult,
    TemporalProviderStartStatus,
    TemporalStartReconciliationVerdict,
    TemporalWorkflowAdapter,
    build_temporal_start_request,
)
from data_agent.agentops_temporal_contracts import (
    TemporalActivityOutcome,
    TemporalSignalKind,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporal_workflow import TemporalTaskGraphWorkflowHarness
from data_agent.test_agentops_contracts import (
    _deployment,
    _evaluation,
    _signal,
    _spec,
    _temporal_input,
)


class _FakeTemporalClient:
    def __init__(self) -> None:
        self.start_calls: list[dict[str, Any]] = []
        self.signal_calls: list[dict[str, Any]] = []
        self.start_status = TemporalProviderStartStatus.STARTED

    def start_workflow(self, **kwargs: Any) -> TemporalProviderStartResult:
        self.start_calls.append(kwargs)
        values = {
            "tenant_id": "planning",
            "namespace_ref": kwargs["namespace_ref"],
            "workflow_id": kwargs["workflow_id"],
            "status": self.start_status,
            "provider_run_id": (
                "temporal-run:901"
                if self.start_status is not TemporalProviderStartStatus.UNKNOWN
                else None
            ),
            "provider_receipt_ref": "temporal://receipt/start-901",
        }
        values["result_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_START_RESULT_SCHEMA, values, "result_sha256"
        )
        return TemporalProviderStartResult(**values)

    def signal_workflow(self, **kwargs: Any) -> TemporalProviderSignalResult:
        self.signal_calls.append(kwargs)
        values = {
            "tenant_id": "planning",
            "workflow_id": kwargs["workflow_id"],
            "signal_id": kwargs["signal"]["signal_id"],
            "status": TemporalProviderSignalStatus.ACCEPTED,
            "provider_receipt_ref": "temporal://receipt/signal-901",
        }
        values["result_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_SIGNAL_RESULT_SCHEMA, values, "result_sha256"
        )
        return TemporalProviderSignalResult(**values)


class _FakeAsyncTemporalClient(_FakeTemporalClient):
    async def start_workflow(self, **kwargs: Any) -> TemporalProviderStartResult:
        return super().start_workflow(**kwargs)

    async def signal_workflow(self, **kwargs: Any) -> TemporalProviderSignalResult:
        return super().signal_workflow(**kwargs)


def _input():
    spec = _spec()
    deployment = _deployment(spec, _evaluation(spec))
    return _temporal_input(deployment)


def test_start_request_is_canonical_and_policy_bound():
    workflow_input = _input()
    request = build_temporal_start_request(workflow_input)
    assert request.workflow_id == workflow_input.identity.workflow_id
    assert request.task_queue_ref == workflow_input.identity.task_queue.queue_ref
    assert request.payload["policy_decision_ref"] == workflow_input.policy_decision_ref
    assert request.payload["task_graph"]["graph_sha256"] == workflow_input.task_graph.graph_sha256
    assert request.payload["task_graph"]["coordinator_agent_id"] == "coordinator"
    assert request.payload_sha256 == temporal_contract_fingerprint(
        "gda.temporal_start_request.v1",
        request.model_dump(mode="json"),
        "payload_sha256",
    )


def test_adapter_forwards_identity_payload_and_retry_policy_once():
    workflow_input = _input()
    client = _FakeTemporalClient()
    result = TemporalWorkflowAdapter(client).start(workflow_input)

    assert result.status is TemporalProviderStartStatus.STARTED
    assert len(client.start_calls) == 1
    call = client.start_calls[0]
    assert call["workflow_id"] == workflow_input.identity.workflow_id
    assert call["workflow_type"] == workflow_input.identity.workflow_type
    assert call["retry_policy"]["max_attempts"] == 3
    assert call["payload"]["agent_run"]["run_id"] == str(workflow_input.agent_run.run_id)


def test_unknown_start_receipt_is_returned_without_automatic_retry():
    workflow_input = _input()
    client = _FakeTemporalClient()
    client.start_status = TemporalProviderStartStatus.UNKNOWN

    result = TemporalWorkflowAdapter(client).start(workflow_input)

    assert result.status is TemporalProviderStartStatus.UNKNOWN
    assert len(client.start_calls) == 1


def test_start_reconciliation_requires_matching_input_for_already_exists():
    workflow_input = _input()
    client = _FakeTemporalClient()
    client.start_status = TemporalProviderStartStatus.ALREADY_EXISTS
    adapter = TemporalWorkflowAdapter(client)

    result = adapter.start(workflow_input)
    request = build_temporal_start_request(workflow_input)
    reconciliation = adapter.reconcile_start(
        workflow_input,
        result,
        observed_input_sha256=request.payload_sha256,
    )

    assert reconciliation.verdict is TemporalStartReconciliationVerdict.ALREADY_EXISTS_MATCHED
    assert reconciliation.provider_run_id == result.provider_run_id

    with pytest.raises(TemporalAdapterProtocolError, match="input fingerprint"):
        adapter.reconcile_start(
            workflow_input,
            result,
            observed_input_sha256="0" * 64,
        )

    with pytest.raises(TemporalAdapterProtocolError, match="requires observed"):
        adapter.reconcile_start(workflow_input, result)


def test_unknown_start_reconciliation_remains_pending_without_retry():
    workflow_input = _input()
    client = _FakeTemporalClient()
    client.start_status = TemporalProviderStartStatus.UNKNOWN
    adapter = TemporalWorkflowAdapter(client)
    result = adapter.start(workflow_input)

    reconciliation = adapter.reconcile_start(workflow_input, result)
    assert reconciliation.verdict is TemporalStartReconciliationVerdict.UNKNOWN_PENDING
    assert reconciliation.provider_run_id is None
    assert len(client.start_calls) == 1

    with pytest.raises(TemporalAdapterProtocolError, match="input fingerprint"):
        adapter.reconcile_start(
            workflow_input,
            result,
            observed_input_sha256="0" * 64,
        )


def test_async_adapter_forwards_to_async_provider_without_event_loop_nesting():
    workflow_input = _input()
    client = _FakeAsyncTemporalClient()

    result = asyncio.run(TemporalWorkflowAdapter(client).start_async(workflow_input))

    assert result.status is TemporalProviderStartStatus.STARTED
    assert len(client.start_calls) == 1
    assert client.start_calls[0]["workflow_id"] == workflow_input.identity.workflow_id


def test_sync_entrypoint_rejects_async_provider_instead_of_blocking():
    workflow_input = _input()
    client = _FakeAsyncTemporalClient()

    with pytest.raises(RuntimeError, match="requires start_async"):
        TemporalWorkflowAdapter(client).start(workflow_input)


def test_async_signal_preserves_signal_identity():
    workflow_input = _input()
    client = _FakeAsyncTemporalClient()
    signal = _signal(
        workflow_input,
        kind=TemporalSignalKind.CANCEL,
        expected_state_version=0,
    )

    result = asyncio.run(
        TemporalWorkflowAdapter(client).signal_async(workflow_input.identity, signal)
    )

    assert result.status is TemporalProviderSignalStatus.ACCEPTED
    assert client.signal_calls[0]["signal"]["signal_id"] == str(signal.signal_id)


def test_adapter_rejects_mismatched_start_receipt():
    workflow_input = _input()

    class _WrongReceiptClient(_FakeTemporalClient):
        def start_workflow(self, **kwargs: Any) -> TemporalProviderStartResult:
            values = {
                "tenant_id": "planning",
                "namespace_ref": kwargs["namespace_ref"],
                "workflow_id": "gda-agent-planning-invalid",
                "status": TemporalProviderStartStatus.STARTED,
                "provider_run_id": "temporal-run:wrong",
                "provider_receipt_ref": "temporal://receipt/wrong",
            }
            values["result_sha256"] = temporal_contract_fingerprint(
                TEMPORAL_START_RESULT_SCHEMA, values, "result_sha256"
            )
            return TemporalProviderStartResult(**values)

    with pytest.raises(TemporalAdapterProtocolError, match="correlation"):
        TemporalWorkflowAdapter(_WrongReceiptClient()).start(workflow_input)


def test_signal_requires_matching_identity_and_preserves_signal_id():
    workflow_input = _input()
    client = _FakeTemporalClient()
    adapter = TemporalWorkflowAdapter(client)
    signal = _signal(
        workflow_input,
        kind=TemporalSignalKind.CANCEL,
        expected_state_version=0,
    )
    result = adapter.signal(workflow_input.identity, signal)
    assert result.status is TemporalProviderSignalStatus.ACCEPTED
    assert client.signal_calls[0]["signal"]["signal_id"] == str(signal.signal_id)

    changed = workflow_input.identity.model_copy(
        update={"workflow_id": "gda-agent-planning-invalid"}
    )
    with pytest.raises(TemporalAdapterProtocolError, match="workflow"):
        adapter.signal(changed, signal)


def test_adapter_start_input_is_accepted_only_before_agent_run_progresses():
    workflow_input = _input()
    progressed = workflow_input.agent_run.model_dump(mode="json")
    progressed["status"] = AgentRunStatus.PLANNING.value
    progressed["state_version"] = 1
    progressed["run_sha256"] = agent_run_fingerprint(progressed)
    progressed_run = AgentRun(**progressed)
    values = workflow_input.model_dump(mode="json")
    values["agent_run"] = progressed_run.model_dump(mode="json")
    values["input_sha256"] = temporal_contract_fingerprint(
        workflow_input.schema_id,
        values,
        "input_sha256",
    )
    with pytest.raises(ValueError, match="accepted AgentRun"):
        type(workflow_input)(**values)


class _FakeActivityProvider:
    def __init__(self, outcome: TemporalActivityOutcome) -> None:
        self.outcome = outcome
        self.requests: list[dict[str, Any]] = []

    def dispatch_activity(self, *, request: dict[str, Any]) -> TemporalProviderActivityResult:
        self.requests.append(request)
        values = {
            "tenant_id": request["tenant_id"],
            "workflow_id": request["workflow_id"],
            "run_id": request["run_id"],
            "step_id": request["step_id"],
            "tool_call_id": request["tool_call_id"],
            "activity_id": request["activity_id"],
            "attempt_no": request["attempt_no"],
            "request_sha256": request["request_sha256"],
            "outcome": self.outcome,
            "provider_receipt_ref": "temporal://receipt/activity-901",
            "provider_operation_ref": "provider://operation/activity-901",
            "output_artifact_id": (
                "00000000-0000-4000-8000-000000001101"
                if self.outcome is TemporalActivityOutcome.SUCCEEDED
                else None
            ),
            "external_receipt_artifact_id": None,
            "failure_type": (
                "ProviderTimeout" if self.outcome is TemporalActivityOutcome.FAILED else None
            ),
        }
        values["result_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_ACTIVITY_RESULT_SCHEMA, values, "result_sha256"
        )
        return TemporalProviderActivityResult(**values)


def _activity_request():
    workflow_input = _input()
    harness = TemporalTaskGraphWorkflowHarness()
    workflow_id = workflow_input.identity.workflow_id
    step = workflow_input.task_graph.steps[0]
    harness.start(workflow_input)
    snapshot = harness.start_step(workflow_id, step.step_id)
    snapshot = harness.bind_tool_call(
        workflow_id,
        step_id=step.step_id,
        tool_ref="tool:plan:v1",
        capability_ref="capability:data_product.execute:v1",
        subject_context=workflow_input.subject_context,
        side_effect=AgentSideEffect.NONE,
        policy_decision_ref=workflow_input.policy_decision_ref,
        idempotency_key="tool-call:activity-adapter",
    )
    call = snapshot.execution.tool_calls[0]
    harness.dispatch_tool_call(workflow_id, call.tool_call_id)
    return (
        harness,
        workflow_id,
        call,
        harness.build_activity_request(workflow_id, call.tool_call_id),
    )


def test_activity_adapter_dispatches_request_and_returns_evidence():
    harness, workflow_id, call, request = _activity_request()
    provider = _FakeActivityProvider(TemporalActivityOutcome.SUCCEEDED)
    evidence = TemporalActivityAdapter(provider).dispatch(request)

    assert provider.requests[0]["activity_id"] == str(request.activity_id)
    assert provider.requests[0]["request_sha256"] == request.request_sha256
    assert evidence.tool_call_id == call.tool_call_id
    assert evidence.output_artifact_id == UUID("00000000-0000-4000-8000-000000001101")
    projected = harness.record_activity(workflow_id, evidence)
    assert projected.execution.tool_calls[0].status.value == "succeeded"


def test_unknown_activity_evidence_uses_distinct_key_from_later_settlement():
    _harness, _workflow_id, _call, request = _activity_request()
    unknown = TemporalActivityAdapter(
        _FakeActivityProvider(TemporalActivityOutcome.UNKNOWN)
    ).dispatch(request)
    settled = TemporalActivityAdapter(
        _FakeActivityProvider(TemporalActivityOutcome.SUCCEEDED)
    ).dispatch(request)
    assert unknown.idempotency_key.endswith(":unknown")
    assert settled.idempotency_key != unknown.idempotency_key
    assert settled.idempotency_key.endswith(":activity-attempt:1")


def test_workflow_harness_dispatch_activity_connects_adapter_and_receipt():
    harness, workflow_id, call, _request = _activity_request()
    provider = _FakeActivityProvider(TemporalActivityOutcome.SUCCEEDED)
    projected = harness.dispatch_activity(
        workflow_id, call.tool_call_id, TemporalActivityAdapter(provider)
    )
    assert projected.execution.tool_calls[0].status.value == "succeeded"
    assert len(provider.requests) == 1


def test_activity_adapter_rejects_receipt_identity_drift():
    _harness, _workflow_id, _call, request = _activity_request()

    class _WrongActivityProvider(_FakeActivityProvider):
        def dispatch_activity(self, *, request: dict[str, Any]) -> TemporalProviderActivityResult:
            result = super().dispatch_activity(request=request)
            values = result.model_dump(mode="json")
            values["request_sha256"] = "0" * 64
            values["result_sha256"] = temporal_contract_fingerprint(
                TEMPORAL_ACTIVITY_RESULT_SCHEMA, values, "result_sha256"
            )
            return TemporalProviderActivityResult(**values)

    with pytest.raises(TemporalAdapterProtocolError, match="correlation"):
        TemporalActivityAdapter(_WrongActivityProvider(TemporalActivityOutcome.SUCCEEDED)).dispatch(
            request
        )


def test_activity_adapter_sync_entrypoint_rejects_async_provider():
    _harness, _workflow_id, _call, request = _activity_request()

    class _AsyncActivityProvider(_FakeActivityProvider):
        async def dispatch_activity(
            self, *, request: dict[str, Any]
        ) -> TemporalProviderActivityResult:
            return super().dispatch_activity(request=request)

    with pytest.raises(TemporalAdapterError, match="dispatch_async"):
        TemporalActivityAdapter(_AsyncActivityProvider(TemporalActivityOutcome.SUCCEEDED)).dispatch(
            request
        )
    evidence = asyncio.run(
        TemporalActivityAdapter(
            _AsyncActivityProvider(TemporalActivityOutcome.SUCCEEDED)
        ).dispatch_async(request)
    )
    assert evidence.outcome is TemporalActivityOutcome.SUCCEEDED
