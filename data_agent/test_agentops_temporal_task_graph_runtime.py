from __future__ import annotations

import asyncio

import pytest
from temporalio import exceptions as temporal_exceptions

from data_agent import agentops_temporal_task_graph_runtime as runtime
from data_agent.agentops_specialist_providers import build_gwm_provider_spec
from data_agent.agentops_temporal_contracts import TemporalActivityOutcome
from data_agent.test_agentops_temporal_adapter import _activity_request


@pytest.mark.parametrize(
    "error",
    (
        temporal_exceptions.TimeoutError(
            "activity timed out",
            type=temporal_exceptions.TimeoutType.START_TO_CLOSE,
            last_heartbeat_details=[],
        ),
        temporal_exceptions.CancelledError("activity cancelled"),
        RuntimeError("activity response was lost"),
    ),
)
def test_provider_bound_temporal_failure_stays_unknown_for_receipt_reconciliation(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    harness, workflow_id, call, _request = _activity_request()
    spec = build_gwm_provider_spec()
    schedule = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.specialist.activity",
        schedule_to_close_timeout_seconds=60,
        start_to_close_timeout_seconds=30,
        heartbeat_timeout_seconds=10,
        provider_spec=spec,
    ).activity_schedules[0]

    async def _raise_activity_error(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(runtime.workflow, "execute_activity", _raise_activity_error)

    result = asyncio.run(runtime._execute_schedule(schedule))

    assert result.outcome is TemporalActivityOutcome.UNKNOWN
    assert result.failure_type is None
    assert result.provider_operation_ref == f"{spec.operation_ref}://{schedule.activity_id}"
    assert result.provider_receipt_ref == (
        f"provider://specialist/{schedule.activity_id}/{schedule.attempt_no}"
    )


def test_unbound_temporal_failure_remains_definitive_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness, workflow_id, call, _request = _activity_request()
    schedule = harness.schedule_activity(
        workflow_id,
        call.tool_call_id,
        activity_type="gda.agentops.activity",
        schedule_to_close_timeout_seconds=60,
        start_to_close_timeout_seconds=30,
        heartbeat_timeout_seconds=10,
    ).activity_schedules[0]

    async def _raise_activity_error(*_args, **_kwargs):
        raise RuntimeError("activity failed before provider dispatch")

    monkeypatch.setattr(runtime.workflow, "execute_activity", _raise_activity_error)

    result = asyncio.run(runtime._execute_schedule(schedule))

    assert result.outcome is TemporalActivityOutcome.FAILED
    assert result.failure_type == "RuntimeError"
    assert result.provider_operation_ref is None
    assert result.provider_receipt_ref.startswith("temporal://history/")


def test_specialist_activity_heartbeats_for_the_full_execution_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _harness, _workflow_id, _call, request = _activity_request()
    heartbeats: list[dict[str, object]] = []
    finished = asyncio.Event()

    async def _long_running_executor(_request):
        await finished.wait()
        raise AssertionError("long-running test executor should remain active")

    monkeypatch.setattr(runtime.activity, "heartbeat", heartbeats.append)
    activity_definition = runtime.build_specialist_activity_definition(
        _long_running_executor
    )

    async def _run() -> None:
        task = asyncio.create_task(activity_definition(request.model_dump(mode="json")))
        await asyncio.sleep(1.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_run())

    assert len(heartbeats) >= 2
    assert all(item["activity_id"] == str(request.activity_id) for item in heartbeats)
