from __future__ import annotations

import asyncio

import httpx
import pytest

from data_agent.agentops_flink_provider import (
    FLINK_ICEBERG_OPERATION,
    FLINK_JOB_RECEIPT_PREFIX,
    FLINK_PROVIDER_REF,
    FlinkProviderCancellationAdapter,
)
from data_agent.agentops_provider_identity import derive_specialist_provider_receipt_ref
from data_agent.agentops_specialist_providers import (
    BoundSpecialistExecutor,
    FilesystemSpecialistArtifactStore,
    InMemorySpecialistCancellationAdapter,
    InMemorySpecialistOperationAuthority,
    SpecialistOperationStatus,
    SpecialistProviderCancellationStatus,
    SpecialistProviderError,
    SpecialistUncertaintyType,
    TemporalProviderCancellationProbeExecutor,
)
from data_agent.agentops_temporal_contracts import (
    TemporalActivityRequest,
    TemporalProviderExecutionSpec,
    temporal_contract_fingerprint,
)
from data_agent.test_agentops_temporal_adapter import _activity_request

JOB_ID = "0123456789abcdef0123456789abcdef"


def _request(*, job_id: str = JOB_ID, provider_ref: str = FLINK_PROVIDER_REF):
    _harness, _workflow_id, _call, request = _activity_request()
    spec_values = {
        "provider_ref": provider_ref,
        "operation_ref": FLINK_ICEBERG_OPERATION,
        "parameters": {"job_id": job_id},
        "input_artifact_ids": (),
        "output_media_type": "application/json",
    }
    spec_values["spec_sha256"] = temporal_contract_fingerprint(
        TemporalProviderExecutionSpec.schema_id, spec_values, "spec_sha256"
    )
    spec = TemporalProviderExecutionSpec(**spec_values)
    values = request.model_dump(mode="python")
    values["provider_spec"] = spec
    values["request_sha256"] = temporal_contract_fingerprint(
        TemporalActivityRequest.schema_id, values, "request_sha256"
    )
    return TemporalActivityRequest(**values)


def test_flink_cancel_upgrades_patch_acceptance_only_after_canceled_state():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "PATCH":
            return httpx.Response(202, request=request)
        return httpx.Response(200, json={"jid": JOB_ID, "state": "CANCELING"}, request=request)

    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    receipt_ref = f"{FLINK_JOB_RECEIPT_PREFIX}{JOB_ID}"
    with FlinkProviderCancellationAdapter(
        "http://flink.example.test", transport=httpx.MockTransport(handler)
    ) as adapter:
        observation = adapter.request_cancellation(
            request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
        )

    assert observation.status is SpecialistProviderCancellationStatus.ACCEPTED
    assert [item.method for item in calls] == ["GET", "PATCH", "GET"]
    assert str(calls[1].url) == f"http://flink.example.test/jobs/{JOB_ID}?mode=cancel"
    assert observation.request_sha256 == request.request_sha256
    assert observation.uncertainty_type is SpecialistUncertaintyType.PROVIDER_CANCELLATION_ACCEPTED


def test_flink_cancel_permission_denial_is_unknown_with_actionable_reason():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "PATCH":
            return httpx.Response(403, json={"errors": ["forbidden"]}, request=request)
        return httpx.Response(200, json={"jid": JOB_ID, "state": "RUNNING"}, request=request)

    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    receipt_ref = f"{FLINK_JOB_RECEIPT_PREFIX}{JOB_ID}"
    with FlinkProviderCancellationAdapter(
        "http://flink.example.test", transport=httpx.MockTransport(handler)
    ) as adapter:
        observation = adapter.request_cancellation(
            request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
        )

    assert observation.status is SpecialistProviderCancellationStatus.UNKNOWN
    assert observation.failure_type is None
    assert (
        observation.uncertainty_type
        is SpecialistUncertaintyType.FLINK_CANCELLATION_PERMISSION_DENIED
    )
    assert [item.method for item in calls] == ["GET", "PATCH"]


def test_flink_cancel_not_found_and_invalid_response_are_distinguished():
    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    receipt_ref = f"{FLINK_JOB_RECEIPT_PREFIX}{JOB_ID}"

    for response, expected in (
        (
            httpx.Response(404, request=httpx.Request("GET", "http://flink.example.test")),
            SpecialistUncertaintyType.FLINK_JOB_NOT_FOUND,
        ),
        (
            httpx.Response(200, content=b"not-json", request=httpx.Request("GET", "http://flink.example.test")),
            SpecialistUncertaintyType.FLINK_RESPONSE_INVALID,
        ),
    ):
        def handler(_request: httpx.Request, response: httpx.Response = response) -> httpx.Response:
            return response

        with FlinkProviderCancellationAdapter(
            "http://flink.example.test", transport=httpx.MockTransport(handler)
        ) as adapter:
            observation = adapter.observe_cancellation(
                request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
            )
        assert observation.status is SpecialistProviderCancellationStatus.UNKNOWN
        assert observation.uncertainty_type is expected


def test_flink_cancel_confirms_only_from_provider_canceled_state():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"jid": JOB_ID, "state": "CANCELED"},
            request=request,
        )

    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    receipt_ref = f"{FLINK_JOB_RECEIPT_PREFIX}{JOB_ID}"
    with FlinkProviderCancellationAdapter(
        "http://flink.example.test", transport=httpx.MockTransport(handler)
    ) as adapter:
        observation = adapter.request_cancellation(
            request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
        )

    assert observation.status is SpecialistProviderCancellationStatus.CONFIRMED
    assert observation.failure_type == "FlinkJobCancelled"
    assert [item.method for item in calls] == ["GET"]


def test_flink_cancel_transport_failure_is_unknown_and_does_not_claim_success():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("flink unavailable", request=request)

    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    receipt_ref = f"{FLINK_JOB_RECEIPT_PREFIX}{JOB_ID}"
    with FlinkProviderCancellationAdapter(
        "http://flink.example.test", transport=httpx.MockTransport(handler)
    ) as adapter:
        observation = adapter.request_cancellation(
            request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
        )

    assert observation.status is SpecialistProviderCancellationStatus.UNKNOWN
    assert observation.failure_type is None


def test_flink_cancel_rejects_job_and_receipt_identity_drift():
    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    adapter = FlinkProviderCancellationAdapter(
        "http://flink.example.test", transport=httpx.MockTransport(lambda req: httpx.Response(200))
    )
    try:
        with pytest.raises(SpecialistProviderError, match="bound to a different job"):
            adapter.observe_cancellation(
                request,
                operation_ref=operation_ref,
                provider_receipt_ref=f"{FLINK_JOB_RECEIPT_PREFIX}{'f' * 32}",
            )
    finally:
        adapter.close()


def test_flink_cancel_rejects_non_flink_provider_binding():
    request = _request(provider_ref="provider:gwm.local")
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    receipt_ref = f"{FLINK_JOB_RECEIPT_PREFIX}{JOB_ID}"
    adapter = FlinkProviderCancellationAdapter("http://flink.example.test")
    try:
        with pytest.raises(SpecialistProviderError, match="provider binding differs"):
            adapter.request_cancellation(
                request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
            )
    finally:
        adapter.close()


def test_provider_receipt_identity_is_job_bound_only_for_flink():
    flink_request = _request()
    assert derive_specialist_provider_receipt_ref(flink_request) == (
        f"{FLINK_JOB_RECEIPT_PREFIX}{JOB_ID}"
    )

    _harness, _workflow_id, _call, generic_request = _activity_request()
    assert derive_specialist_provider_receipt_ref(generic_request) == (
        f"provider://specialist/{generic_request.activity_id}/{generic_request.attempt_no}"
    )


def test_bound_executor_sends_flink_job_receipt_on_temporal_cancellation(tmp_path):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "PATCH":
            return httpx.Response(202, request=request)
        return httpx.Response(
            200,
            json={"jid": JOB_ID, "state": "CANCELED"},
            request=request,
        )

    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    receipt_ref = f"{FLINK_JOB_RECEIPT_PREFIX}{JOB_ID}"
    authority = InMemorySpecialistOperationAuthority()
    authority.submit(
        request,
        provider_ref=FLINK_PROVIDER_REF,
        operation_ref=operation_ref,
        provider_receipt_ref=receipt_ref,
    )
    with FlinkProviderCancellationAdapter(
        "http://flink.example.test", transport=httpx.MockTransport(handler)
    ) as adapter:
        executor = BoundSpecialistExecutor(
            FilesystemSpecialistArtifactStore(tmp_path / "artifacts"),
            operation_authority=authority,
            cancellation_adapter=adapter,
        )

        def _bounded_block(_request):
            import time

            time.sleep(0.2)

        executor._execute = _bounded_block

        async def _cancel_activity():
            task = asyncio.create_task(executor(request))
            await asyncio.sleep(0.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(_cancel_activity())

    terminal = authority.observe(operation_ref)
    assert terminal is not None
    assert terminal.status is SpecialistOperationStatus.CANCELLED
    assert [item.method for item in calls] == ["GET"]
    assert str(calls[0].url) == f"http://flink.example.test/jobs/{JOB_ID}"


def test_temporal_cancellation_probe_keeps_accepted_provider_cancel_unknown():
    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    receipt_ref = f"{FLINK_JOB_RECEIPT_PREFIX}{JOB_ID}"
    authority = InMemorySpecialistOperationAuthority()
    adapter = InMemorySpecialistCancellationAdapter(confirm_on_request=False)
    submitted = asyncio.Event()

    async def cancel_probe():
        executor = TemporalProviderCancellationProbeExecutor(
            authority,
            adapter,
            hold_seconds=30,
            cancellation_timeout_seconds=0.1,
            on_submitted=lambda *_args: submitted.set(),
        )
        task = asyncio.create_task(executor(request))
        await asyncio.wait_for(submitted.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_probe())
    observed = authority.observe(operation_ref)
    assert observed is not None
    assert observed.provider_receipt_ref == receipt_ref
    assert observed.status is SpecialistOperationStatus.UNKNOWN
    assert observed.cancellation_requested is True
    assert (
        observed.uncertainty_type
        is SpecialistUncertaintyType.PROVIDER_CANCELLATION_OBSERVATION_TIMEOUT
    )
    assert adapter.observe_cancellation(
        request, operation_ref=operation_ref, provider_receipt_ref=receipt_ref
    ).status is SpecialistProviderCancellationStatus.ACCEPTED


def test_temporal_cancellation_probe_confirms_only_after_provider_terminal_state():
    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    authority = InMemorySpecialistOperationAuthority()
    adapter = InMemorySpecialistCancellationAdapter(confirm_on_request=True)
    submitted = asyncio.Event()

    async def cancel_probe():
        executor = TemporalProviderCancellationProbeExecutor(
            authority,
            adapter,
            hold_seconds=30,
            cancellation_timeout_seconds=0.1,
            on_submitted=lambda *_args: submitted.set(),
        )
        task = asyncio.create_task(executor(request))
        await asyncio.wait_for(submitted.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_probe())
    observed = authority.observe(operation_ref)
    assert observed is not None
    assert observed.status is SpecialistOperationStatus.CANCELLED
    assert observed.failure_type == "ProviderCancellationConfirmed"


def test_temporal_cancellation_probe_observes_accepted_cancel_to_confirmation():
    request = _request()
    operation_ref = f"{FLINK_ICEBERG_OPERATION}://{request.activity_id}"
    authority = InMemorySpecialistOperationAuthority()

    class EventuallyConfirmedAdapter(InMemorySpecialistCancellationAdapter):
        def __init__(self) -> None:
            super().__init__(confirm_on_request=False)
            self.observations = 0

        def observe_cancellation(self, *args, **kwargs):
            self.observations += 1
            if self.observations >= 2:
                return self.confirm(*args, **kwargs)
            return super().observe_cancellation(*args, **kwargs)

    adapter = EventuallyConfirmedAdapter()
    submitted = asyncio.Event()

    async def cancel_probe():
        executor = TemporalProviderCancellationProbeExecutor(
            authority,
            adapter,
            hold_seconds=30,
            cancellation_timeout_seconds=1,
            cancellation_poll_seconds=0.01,
            on_submitted=lambda *_args: submitted.set(),
        )
        task = asyncio.create_task(executor(request))
        await asyncio.wait_for(submitted.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_probe())

    observed = authority.observe(operation_ref)
    assert observed is not None
    assert observed.status is SpecialistOperationStatus.CANCELLED
    assert adapter.observations >= 2
