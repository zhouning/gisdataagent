from __future__ import annotations

import asyncio
import builtins
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from temporalio.api.common.v1 import Payloads
from temporalio.api.enums.v1 import EventType
from temporalio.api.history.v1 import (
    ActivityTaskCompletedEventAttributes,
    ActivityTaskScheduledEventAttributes,
    ActivityTaskStartedEventAttributes,
    HistoryEvent,
    WorkflowExecutionCompletedEventAttributes,
    WorkflowExecutionStartedEventAttributes,
)
from temporalio.client import WorkflowHistory
from temporalio.converter import default

from data_agent.agentops_temporal_adapter import (
    TEMPORAL_ACTIVITY_RESULT_SCHEMA,
    TemporalAdapterError,
    TemporalProviderActivityResult,
    TemporalProviderStartResult,
    TemporalProviderStartStatus,
    TemporalStartReconciliationVerdict,
    TemporalWorkflowAdapter,
    build_temporal_start_request,
)
from data_agent.agentops_temporal_contracts import (
    TemporalActivityCancellationType,
    TemporalActivityOutcome,
    TemporalSignalKind,
    temporal_contract_fingerprint,
)
from data_agent.agentops_temporalio_provider import (
    TEMPORAL_SIGNAL_NAME,
    TemporalActivityWorkerHandler,
    TemporalioActivityScheduleMapper,
    TemporalioProviderClient,
)
from data_agent.test_agentops_contracts import _signal
from data_agent.test_agentops_temporal_adapter import _activity_request, _input


class _FakeHandle:
    def __init__(self, run_id: str = "run-901") -> None:
        self.id = "workflow-901"
        self.run_id = run_id
        self.signals: list[tuple[str, dict[str, Any]]] = []
        self.cancellations: list[str] = []
        self.cancel_error: Exception | None = None
        self.history: Any = SimpleNamespace(events=[])

    async def signal(self, name: str, payload: dict[str, Any]) -> None:
        self.signals.append((name, payload))

    async def cancel(self, *, reason: str = "") -> None:
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancellations.append(reason)

    async def fetch_history(self) -> Any:
        return self.history


class _FakeTemporalioClient:
    def __init__(self) -> None:
        self.handle = _FakeHandle()
        self.start_calls: list[dict[str, Any]] = []
        self.start_error: Exception | None = None
        self.signal_error: Exception | None = None
        self.service_client = _FakeServiceClient()

    async def start_workflow(
        self,
        workflow: str,
        arg: dict[str, Any],
        *,
        id: str,
        task_queue: str,
        retry_policy: Any,
    ) -> _FakeHandle:
        self.start_calls.append(
            {
                "workflow": workflow,
                "arg": arg,
                "id": id,
                "task_queue": task_queue,
                "retry_policy": retry_policy,
            }
        )
        if self.start_error is not None:
            raise self.start_error
        return self.handle

    def get_workflow_handle(
        self, workflow_id: str, *, run_id: str | None = None
    ) -> _FakeHandle:
        assert workflow_id == self.handle.id or workflow_id.startswith("gda-agent-")
        if run_id is not None:
            self.handle.run_id = run_id
        return self.handle


class WorkflowAlreadyStartedError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__("workflow already started")
        self.run_id = run_id


class _FakeServiceClient:
    def __init__(self) -> None:
        self.health_checks: list[dict[str, Any]] = []

    async def check_health(self, **kwargs: Any) -> bool:
        self.health_checks.append(kwargs)
        return True


def _provider(client: _FakeTemporalioClient, workflow_input: Any) -> TemporalioProviderClient:
    return TemporalioProviderClient(
        client,
        namespace_ref=workflow_input.identity.namespace.namespace_ref,
    )


def test_temporalio_bridge_exposes_frontend_health() -> None:
    workflow_input = _input()
    client = _FakeTemporalioClient()

    assert asyncio.run(_provider(client, workflow_input).check_health()) is True
    assert client.service_client.health_checks[0]["timeout"].total_seconds() == 5


def test_temporalio_bridge_maps_start_and_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    workflow_input = _input()
    client = _FakeTemporalioClient()
    monkeypatch.setattr(
        TemporalioProviderClient,
        "_build_retry_policy",
        staticmethod(lambda values: {"mapped": values["max_attempts"]}),
    )
    provider = _provider(client, workflow_input)
    adapter = TemporalWorkflowAdapter(provider)

    started = asyncio.run(adapter.start_async(workflow_input))
    signal = _signal(
        workflow_input,
        kind=TemporalSignalKind.CANCEL,
        expected_state_version=0,
    )
    signaled = asyncio.run(adapter.signal_async(workflow_input.identity, signal))

    assert started.status is TemporalProviderStartStatus.STARTED
    assert started.provider_run_id == "run-901"
    assert client.start_calls[0]["workflow"] == workflow_input.identity.workflow_type
    assert client.start_calls[0]["id"] == workflow_input.identity.workflow_id
    assert client.start_calls[0]["retry_policy"] == {"mapped": 3}
    assert signaled.signal_id == str(signal.signal_id)
    assert client.handle.signals[0] == (
        TEMPORAL_SIGNAL_NAME,
        signal.model_dump(mode="json"),
    )


def test_temporalio_bridge_maps_workflow_cancellation_api() -> None:
    workflow_input = _input()
    client = _FakeTemporalioClient()
    provider = _provider(client, workflow_input)
    adapter = TemporalWorkflowAdapter(provider)

    cancelled = asyncio.run(
        adapter.cancel_async(workflow_input.identity, reason="operator requested stop")
    )

    assert cancelled.status.value == "accepted"
    assert cancelled.namespace_ref == workflow_input.identity.namespace.namespace_ref
    assert cancelled.workflow_id == workflow_input.identity.workflow_id
    assert cancelled.reason == "operator requested stop"
    assert client.handle.cancellations == ["operator requested stop"]


def test_temporalio_bridge_keeps_cancel_rpc_failure_unknown() -> None:
    workflow_input = _input()
    client = _FakeTemporalioClient()
    client.handle.cancel_error = RuntimeError("frontend unavailable")

    result = asyncio.run(
        _provider(client, workflow_input).cancel_workflow(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=workflow_input.identity.namespace.namespace_ref,
            workflow_id=workflow_input.identity.workflow_id,
            reason="operator requested stop",
        )
    )

    assert result.status.value == "unknown"
    assert result.provider_receipt_ref.startswith("temporal://gda-agentops/cancel/")


def test_temporalio_bridge_returns_unknown_without_retry_on_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_input = _input()
    client = _FakeTemporalioClient()
    client.start_error = RuntimeError("transport failed after submit")
    monkeypatch.setattr(
        TemporalioProviderClient,
        "_build_retry_policy",
        staticmethod(lambda values: object()),
    )

    result = asyncio.run(
        _provider(client, workflow_input).start_workflow(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=workflow_input.identity.namespace.namespace_ref,
            workflow_id=workflow_input.identity.workflow_id,
            workflow_type=workflow_input.identity.workflow_type,
            task_queue_ref=workflow_input.identity.task_queue.queue_ref,
            payload=workflow_input.model_dump(mode="json"),
            retry_policy=workflow_input.retry_policy.model_dump(mode="json"),
        )
    )

    assert result.status is TemporalProviderStartStatus.UNKNOWN
    assert len(client.start_calls) == 1
    assert result.provider_receipt_ref is not None


def test_temporalio_bridge_maps_already_started_with_provider_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_input = _input()
    client = _FakeTemporalioClient()
    client.start_error = WorkflowAlreadyStartedError("run-existing")
    monkeypatch.setattr(
        TemporalioProviderClient,
        "_build_retry_policy",
        staticmethod(lambda values: object()),
    )

    result = asyncio.run(
        _provider(client, workflow_input).start_workflow(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=workflow_input.identity.namespace.namespace_ref,
            workflow_id=workflow_input.identity.workflow_id,
            workflow_type=workflow_input.identity.workflow_type,
            task_queue_ref=workflow_input.identity.task_queue.queue_ref,
            payload=workflow_input.model_dump(mode="json"),
            retry_policy=workflow_input.retry_policy.model_dump(mode="json"),
        )
    )

    assert result.status is TemporalProviderStartStatus.ALREADY_EXISTS
    assert result.provider_run_id == "run-existing"


def test_temporalio_bridge_observes_existing_input_for_unknown_start(
    monkeypatch: pytest.MonkeyPatch,
):
    workflow_input = _input()
    client = _FakeTemporalioClient()
    payloads = asyncio.run(default().encode([workflow_input.model_dump(mode="json")]))
    started = SimpleNamespace(
        input=SimpleNamespace(payloads=payloads),
        original_execution_run_id="run-observed",
    )
    client.handle.history = SimpleNamespace(
        events=[SimpleNamespace(workflow_execution_started_event_attributes=started)],
        run_id="run-observed",
    )
    provider = _provider(client, workflow_input)
    monkeypatch.setattr(
        TemporalioProviderClient,
        "_build_retry_policy",
        staticmethod(lambda values: object()),
    )
    result = asyncio.run(
        provider.start_workflow(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=workflow_input.identity.namespace.namespace_ref,
            workflow_id=workflow_input.identity.workflow_id,
            workflow_type=workflow_input.identity.workflow_type,
            task_queue_ref=workflow_input.identity.task_queue.queue_ref,
            payload=workflow_input.model_dump(mode="json"),
            retry_policy=workflow_input.retry_policy.model_dump(mode="json"),
        )
    )
    assert result.status is TemporalProviderStartStatus.STARTED
    unknown_values = result.model_dump(mode="json")
    unknown_values["status"] = TemporalProviderStartStatus.UNKNOWN.value
    unknown_values["provider_run_id"] = None
    unknown_values["result_sha256"] = temporal_contract_fingerprint(
        "gda.temporal_start_result.v1", unknown_values, "result_sha256"
    )
    unknown = TemporalProviderStartResult(**unknown_values)
    reconciliation = asyncio.run(
        TemporalWorkflowAdapter(provider).reconcile_start_async(
            workflow_input, unknown
        )
    )
    assert reconciliation.verdict is TemporalStartReconciliationVerdict.ALREADY_EXISTS_MATCHED
    assert reconciliation.provider_run_id == "run-observed"
    assert reconciliation.observed_input_sha256 == build_temporal_start_request(
        workflow_input
    ).payload_sha256


def test_temporalio_bridge_observes_canonical_input_inside_rehearsal_envelope():
    workflow_input = _input()
    client = _FakeTemporalioClient()
    envelope = {
        "schema": "gda.temporal_checkpoint_reconciliation_rehearsal.v1",
        "workflow_input": workflow_input.model_dump(mode="json"),
        "workflow_input_sha256": workflow_input.input_sha256,
        "schedule": {"fixture": True},
    }
    payloads = asyncio.run(default().encode([envelope]))
    started = SimpleNamespace(
        input=SimpleNamespace(payloads=payloads),
        original_execution_run_id="run-envelope-901",
    )
    client.handle.history = SimpleNamespace(
        events=[SimpleNamespace(workflow_execution_started_event_attributes=started)],
        run_id="run-envelope-901",
    )

    observation = asyncio.run(
        _provider(client, workflow_input).observe_workflow_input(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=workflow_input.identity.namespace.namespace_ref,
            workflow_id=workflow_input.identity.workflow_id,
            provider_run_id="run-envelope-901",
        )
    )

    assert observation.observed_input_sha256 == build_temporal_start_request(
        workflow_input
    ).payload_sha256


def test_temporalio_bridge_observes_canonical_input_inside_flink_cancellation_envelope():
    workflow_input = _input()
    client = _FakeTemporalioClient()
    envelope = {
        "schema": "gda.agentops.flink_cancellation_probe.v1",
        "workflow_input": workflow_input.model_dump(mode="json"),
        "workflow_input_sha256": workflow_input.input_sha256,
        "schedule": {"activity_id": "probe"},
    }
    payloads = asyncio.run(default().encode([envelope]))
    started = SimpleNamespace(
        input=SimpleNamespace(payloads=payloads),
        original_execution_run_id="run-flink-envelope-901",
    )
    client.handle.history = SimpleNamespace(
        events=[SimpleNamespace(workflow_execution_started_event_attributes=started)],
        run_id="run-flink-envelope-901",
    )

    observation = asyncio.run(
        _provider(client, workflow_input).observe_workflow_input(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=workflow_input.identity.namespace.namespace_ref,
            workflow_id=workflow_input.identity.workflow_id,
            provider_run_id="run-flink-envelope-901",
        )
    )

    assert observation.observed_input_sha256 == build_temporal_start_request(
        workflow_input
    ).payload_sha256


def test_temporalio_bridge_decodes_activity_history_into_typed_observation():
    workflow_input = _input()
    _harness, _workflow_id, _call, request = _activity_request()
    result = _activity_result(request)
    converter = default()
    start_payloads = asyncio.run(
        converter.encode([workflow_input.model_dump(mode="json")])
    )
    request_payloads = asyncio.run(converter.encode([request.model_dump(mode="json")]))
    result_payloads = asyncio.run(converter.encode([result.model_dump(mode="json")]))
    events = [
        HistoryEvent(
            event_id=1,
            event_type=EventType.Value("EVENT_TYPE_WORKFLOW_EXECUTION_STARTED"),
            workflow_execution_started_event_attributes=WorkflowExecutionStartedEventAttributes(
                input=Payloads(payloads=start_payloads),
                original_execution_run_id="run-history-901",
            ),
        ),
        HistoryEvent(
            event_id=2,
            event_type=EventType.Value("EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"),
            activity_task_scheduled_event_attributes=ActivityTaskScheduledEventAttributes(
                activity_id=str(request.activity_id),
                input=Payloads(payloads=request_payloads),
            ),
        ),
        HistoryEvent(
            event_id=3,
            event_type=EventType.Value("EVENT_TYPE_ACTIVITY_TASK_STARTED"),
            activity_task_started_event_attributes=ActivityTaskStartedEventAttributes(
                scheduled_event_id=2,
                attempt=request.attempt_no,
            ),
        ),
        HistoryEvent(
            event_id=4,
            event_type=EventType.Value("EVENT_TYPE_ACTIVITY_TASK_COMPLETED"),
            activity_task_completed_event_attributes=ActivityTaskCompletedEventAttributes(
                scheduled_event_id=2,
                started_event_id=3,
                result=Payloads(payloads=result_payloads),
            ),
        ),
        HistoryEvent(
            event_id=5,
            event_type=EventType.Value("EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"),
            workflow_execution_completed_event_attributes=WorkflowExecutionCompletedEventAttributes(),
        ),
    ]
    client = _FakeTemporalioClient()
    client.data_converter = converter
    client.handle.history = WorkflowHistory(workflow_input.identity.workflow_id, events)
    observation = asyncio.run(
        _provider(client, workflow_input).observe_workflow_history(
            tenant_id=workflow_input.tenant_id,
            namespace_ref=workflow_input.identity.namespace.namespace_ref,
            workflow_id=workflow_input.identity.workflow_id,
            provider_run_id="run-history-901",
        )
    )

    assert observation.provider_run_id == "run-history-901"
    assert observation.status.value == "completed"
    assert observation.history_event_count == 5
    assert observation.activities[0].activity_id == request.activity_id
    assert observation.activities[0].status.value == "succeeded"
    assert observation.activities[0].provider_result == result
    assert observation.activities[0].started_event_id == 3
    assert observation.activities[0].terminal_event_id == 4


def test_temporalio_bridge_surfaces_missing_sdk_and_rejects_namespace_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_input = _input()
    client = _FakeTemporalioClient()
    provider = _provider(client, workflow_input)
    original_import = builtins.__import__

    def _missing_temporal_common(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "temporalio.common":
            raise ImportError("simulated missing temporalio common SDK")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _missing_temporal_common)

    with pytest.raises(TemporalAdapterError, match="optional dependency temporalio"):
        asyncio.run(
            provider.start_workflow(
                tenant_id=workflow_input.tenant_id,
                namespace_ref=workflow_input.identity.namespace.namespace_ref,
                workflow_id=workflow_input.identity.workflow_id,
                workflow_type=workflow_input.identity.workflow_type,
                task_queue_ref=workflow_input.identity.task_queue.queue_ref,
                payload=workflow_input.model_dump(mode="json"),
                retry_policy=workflow_input.retry_policy.model_dump(mode="json"),
            )
        )

    with pytest.raises(TemporalAdapterError, match="namespace"):
        asyncio.run(
            provider.start_workflow(
                tenant_id=workflow_input.tenant_id,
                namespace_ref="other-namespace",
                workflow_id=workflow_input.identity.workflow_id,
                workflow_type=workflow_input.identity.workflow_type,
                task_queue_ref=workflow_input.identity.task_queue.queue_ref,
                payload=workflow_input.model_dump(mode="json"),
                retry_policy=workflow_input.retry_policy.model_dump(mode="json"),
            )
        )


def _activity_result(request: Any) -> TemporalProviderActivityResult:
    values = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "outcome": TemporalActivityOutcome.SUCCEEDED,
        "provider_receipt_ref": "temporal://receipt/worker-901",
        "provider_operation_ref": "provider://operation/worker-901",
        "output_artifact_id": UUID("00000000-0000-4000-8000-000000001101"),
        "external_receipt_artifact_id": None,
        "failure_type": None,
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_RESULT_SCHEMA, values, "result_sha256"
    )
    return TemporalProviderActivityResult(**values)


def test_activity_worker_handler_validates_and_serializes_executor_result():
    _harness, _workflow_id, _call, request = _activity_request()
    seen: list[Any] = []

    def executor(received: Any) -> TemporalProviderActivityResult:
        seen.append(received)
        return _activity_result(received)

    payload = TemporalActivityWorkerHandler(executor).handle(
        request.model_dump(mode="json")
    )
    assert seen[0] == request
    assert payload["activity_id"] == str(request.activity_id)
    assert payload["request_sha256"] == request.request_sha256


def test_activity_worker_handler_async_and_fail_closed_boundaries():
    _harness, _workflow_id, _call, request = _activity_request()

    async def executor(received: Any) -> TemporalProviderActivityResult:
        return _activity_result(received)

    handler = TemporalActivityWorkerHandler(executor)
    with pytest.raises(TemporalAdapterError, match="handle_async"):
        handler.handle(request.model_dump(mode="json"))
    payload = asyncio.run(handler.handle_async(request.model_dump(mode="json")))
    assert payload["outcome"] == TemporalActivityOutcome.SUCCEEDED.value

    with pytest.raises(TemporalAdapterError, match="invalid"):
        handler.handle({"tenant_id": request.tenant_id})


def test_activity_schedule_mapper_forces_one_sdk_attempt_and_maps_options():
    harness, workflow_id, call, _request = _activity_request()
    snapshot = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.activity",
        schedule_to_close_timeout_seconds=600,
        start_to_close_timeout_seconds=300,
        heartbeat_timeout_seconds=30,
        cancellation_type=TemporalActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
    )
    plan = snapshot.activity_schedules[0]

    class _RetryPolicy:
        def __init__(self, **values: Any) -> None:
            self.values = values

    class _Cancellation:
        WAIT_CANCELLATION_COMPLETED = "wait-cancellation-completed"

    mapped = TemporalioActivityScheduleMapper.map(
        plan,
        retry_policy_class=_RetryPolicy,
        cancellation_type_class=_Cancellation,
    )
    assert mapped.activity_type == "gda.agentops.activity"
    assert mapped.argument["activity_id"] == str(plan.activity_id)
    assert mapped.retry_policy.values == {"maximum_attempts": 1}
    assert mapped.cancellation_type == "wait-cancellation-completed"
    assert mapped.options()["task_queue"] == plan.task_queue_ref
