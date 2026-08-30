"""Provider adapter contracts for the AgentOps Temporal integration.

This module intentionally does not import temporalio. The real SDK client is
an adapter implementation behind TemporalProviderClient. The contract keeps
GDA identity, policy and evidence authoritative while allowing the provider
to own workflow history and retry execution.
"""

from __future__ import annotations

from collections.abc import Awaitable
from enum import StrEnum
from inspect import isawaitable
from typing import Any, ClassVar, Protocol, TypeVar
from uuid import UUID

from pydantic import model_validator

from .agentops_contracts import AgentSideEffect
from .agentops_temporal_contracts import (
    TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA,
    TemporalActivityEvidence,
    TemporalActivityOutcome,
    TemporalActivityRequest,
    TemporalSignal,
    TemporalWorkflowIdentity,
    TemporalWorkflowInput,
    derive_temporal_activity_id,
    temporal_contract_fingerprint,
)
from .platform_contracts import FrozenContract, NonEmptyText, Sha256, TenantId

TEMPORAL_START_REQUEST_SCHEMA = "gda.temporal_start_request.v1"
TEMPORAL_START_RESULT_SCHEMA = "gda.temporal_start_result.v1"
TEMPORAL_START_RECONCILIATION_SCHEMA = "gda.temporal_start_reconciliation.v1"
TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA = "gda.temporal_workflow_input_observation.v1"
TEMPORAL_SIGNAL_RESULT_SCHEMA = "gda.temporal_signal_result.v1"
TEMPORAL_CANCELLATION_RESULT_SCHEMA = "gda.temporal_cancellation_result.v1"
TEMPORAL_ACTIVITY_RESULT_SCHEMA = "gda.temporal_activity_result.v1"


class TemporalAdapterError(RuntimeError):
    """Base error for provider adapter contract failures."""


class TemporalAdapterProtocolError(TemporalAdapterError):
    """Provider returned a result that cannot be trusted by the control plane."""


class TemporalProviderStartStatus(StrEnum):
    STARTED = "started"
    ALREADY_EXISTS = "already_exists"
    UNKNOWN = "unknown"


class TemporalStartReconciliationVerdict(StrEnum):
    """Control-plane verdict for a provider start observation."""

    STARTED = "started"
    ALREADY_EXISTS_MATCHED = "already_exists_matched"
    UNKNOWN_PENDING = "unknown_pending"


class TemporalProviderSignalStatus(StrEnum):
    ACCEPTED = "accepted"
    ALREADY_APPLIED = "already_applied"
    UNKNOWN = "unknown"


class TemporalProviderCancellationStatus(StrEnum):
    """Receipt for a Temporal workflow cancellation request."""

    ACCEPTED = "accepted"
    UNKNOWN = "unknown"


class TemporalWorkflowStartRequest(FrozenContract):
    """Canonical wire payload for one idempotent workflow start."""

    schema_id: ClassVar[str] = TEMPORAL_START_REQUEST_SCHEMA
    tenant_id: TenantId
    namespace_ref: NonEmptyText
    workflow_id: NonEmptyText
    workflow_type: NonEmptyText
    task_queue_ref: NonEmptyText
    policy_decision_ref: NonEmptyText
    payload: dict[str, Any]
    payload_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_request(self) -> TemporalWorkflowStartRequest:
        identity = self.payload.get("identity")
        if not isinstance(identity, dict):
            raise ValueError("Temporal start payload must contain identity")
        namespace = identity.get("namespace")
        task_queue = identity.get("task_queue")
        if not isinstance(namespace, dict) or not isinstance(task_queue, dict):
            raise ValueError("Temporal start payload identity lacks namespace or task queue")
        if (
            identity.get("workflow_id") != self.workflow_id
            or namespace.get("namespace_ref") != self.namespace_ref
            or identity.get("workflow_type") != self.workflow_type
            or task_queue.get("queue_ref") != self.task_queue_ref
        ):
            raise ValueError("Temporal start payload identity differs from request")
        if self.payload.get("policy_decision_ref") != self.policy_decision_ref:
            raise ValueError("Temporal start payload policy ref differs from request")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "payload_sha256"
        )
        if self.payload_sha256 != expected:
            raise ValueError("payload_sha256 does not match Temporal start payload")
        return self


class TemporalProviderStartResult(FrozenContract):
    """Provider receipt for a workflow start attempt."""

    schema_id: ClassVar[str] = TEMPORAL_START_RESULT_SCHEMA
    tenant_id: TenantId
    namespace_ref: NonEmptyText
    workflow_id: NonEmptyText
    status: TemporalProviderStartStatus
    provider_run_id: NonEmptyText | None = None
    provider_receipt_ref: NonEmptyText | None = None
    result_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_result(self) -> TemporalProviderStartResult:
        if self.status in {
            TemporalProviderStartStatus.STARTED,
            TemporalProviderStartStatus.ALREADY_EXISTS,
        } and (self.provider_run_id is None or self.provider_receipt_ref is None):
            raise ValueError("successful Temporal start requires provider run and receipt")
        if self.status is TemporalProviderStartStatus.UNKNOWN and self.provider_receipt_ref is None:
            raise ValueError("unknown Temporal start requires a provider receipt reference")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "result_sha256"
        )
        if self.result_sha256 != expected:
            raise ValueError("result_sha256 does not match Temporal start result")
        return self


class TemporalStartReconciliation(FrozenContract):
    """Immutable evidence for reconciling a Temporal workflow start attempt."""

    schema_id: ClassVar[str] = TEMPORAL_START_RECONCILIATION_SCHEMA
    tenant_id: TenantId
    namespace_ref: NonEmptyText
    workflow_id: NonEmptyText
    provider_status: TemporalProviderStartStatus
    verdict: TemporalStartReconciliationVerdict
    provider_run_id: NonEmptyText | None = None
    provider_receipt_ref: NonEmptyText
    request_sha256: Sha256
    observed_input_sha256: Sha256 | None = None
    reconciliation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_reconciliation(self) -> TemporalStartReconciliation:
        if self.provider_status is TemporalProviderStartStatus.STARTED:
            if self.verdict is not TemporalStartReconciliationVerdict.STARTED:
                raise ValueError("started result requires started reconciliation verdict")
            if self.provider_run_id is None:
                raise ValueError("started reconciliation requires provider run id")
        elif self.provider_status is TemporalProviderStartStatus.ALREADY_EXISTS:
            if self.verdict is not TemporalStartReconciliationVerdict.ALREADY_EXISTS_MATCHED:
                raise ValueError("already_exists result requires matched reconciliation verdict")
            if self.provider_run_id is None or self.observed_input_sha256 is None:
                raise ValueError("already_exists reconciliation requires run and input evidence")
        elif self.provider_status is TemporalProviderStartStatus.UNKNOWN:
            if self.verdict is TemporalStartReconciliationVerdict.UNKNOWN_PENDING:
                if self.provider_run_id is not None:
                    raise ValueError(
                        "unknown pending reconciliation cannot claim a provider run id"
                    )
            elif self.verdict is TemporalStartReconciliationVerdict.ALREADY_EXISTS_MATCHED:
                if self.provider_run_id is None or self.observed_input_sha256 is None:
                    raise ValueError(
                        "unknown matched reconciliation requires run and input evidence"
                    )
            else:
                raise ValueError(
                    "unknown result requires pending or matched reconciliation verdict"
                )
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "reconciliation_sha256"
        )
        if self.reconciliation_sha256 != expected:
            raise ValueError("reconciliation_sha256 does not match Temporal start observation")
        return self


class TemporalProviderWorkflowInputObservation(FrozenContract):
    """Provider observation of the immutable input for an existing workflow run."""

    schema_id: ClassVar[str] = TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA
    tenant_id: TenantId
    namespace_ref: NonEmptyText
    workflow_id: NonEmptyText
    provider_run_id: NonEmptyText
    provider_receipt_ref: NonEmptyText
    observed_input_sha256: Sha256
    observation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_observation(self) -> TemporalProviderWorkflowInputObservation:
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "observation_sha256"
        )
        if self.observation_sha256 != expected:
            raise ValueError("observation_sha256 does not match workflow input observation")
        return self


class TemporalProviderSignalResult(FrozenContract):
    """Provider receipt for an idempotent workflow signal attempt."""

    schema_id: ClassVar[str] = TEMPORAL_SIGNAL_RESULT_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    signal_id: NonEmptyText
    status: TemporalProviderSignalStatus
    provider_receipt_ref: NonEmptyText | None = None
    result_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_result(self) -> TemporalProviderSignalResult:
        if self.provider_receipt_ref is None:
            raise ValueError("Temporal signal result requires a provider receipt reference")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "result_sha256"
        )
        if self.result_sha256 != expected:
            raise ValueError("result_sha256 does not match Temporal signal result")
        return self


class TemporalProviderCancellationResult(FrozenContract):
    """Provider receipt for a workflow cancellation API call."""

    schema_id: ClassVar[str] = TEMPORAL_CANCELLATION_RESULT_SCHEMA
    tenant_id: TenantId
    namespace_ref: NonEmptyText
    workflow_id: NonEmptyText
    status: TemporalProviderCancellationStatus
    reason: NonEmptyText
    provider_receipt_ref: NonEmptyText
    result_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_result(self) -> TemporalProviderCancellationResult:
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "result_sha256"
        )
        if self.result_sha256 != expected:
            raise ValueError("result_sha256 does not match Temporal cancellation result")
        return self


class TemporalProviderActivityResult(FrozenContract):
    """Provider receipt for one typed activity dispatch attempt."""

    schema_id: ClassVar[str] = TEMPORAL_ACTIVITY_RESULT_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    run_id: UUID
    step_id: UUID
    tool_call_id: UUID
    activity_id: UUID
    attempt_no: int
    request_sha256: Sha256
    outcome: TemporalActivityOutcome
    provider_receipt_ref: NonEmptyText
    provider_operation_ref: NonEmptyText | None = None
    output_artifact_id: UUID | None = None
    external_receipt_artifact_id: UUID | None = None
    failure_type: NonEmptyText | None = None
    result_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_result(self) -> TemporalProviderActivityResult:
        if self.attempt_no < 1:
            raise ValueError("activity result attempt_no must be positive")
        if self.activity_id != derive_temporal_activity_id(
            run_id=self.run_id,
            tool_call_id=self.tool_call_id,
            attempt_no=self.attempt_no,
        ):
            raise ValueError("activity result identity does not match ToolCall attempt")
        if self.outcome is TemporalActivityOutcome.SUCCEEDED and self.output_artifact_id is None:
            raise ValueError("successful activity result requires an output artifact")
        if self.outcome is TemporalActivityOutcome.UNKNOWN and self.provider_operation_ref is None:
            raise ValueError("unknown activity result requires provider operation ref")
        if self.outcome is TemporalActivityOutcome.FAILED and self.failure_type is None:
            raise ValueError("failed activity result requires a failure type")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "result_sha256"
        )
        if self.result_sha256 != expected:
            raise ValueError("result_sha256 does not match activity result")
        return self


class TemporalProviderClient(Protocol):
    """Minimal surface implemented by a pinned Temporal SDK client."""

    def start_workflow(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        workflow_type: str,
        task_queue_ref: str,
        payload: dict[str, Any],
        retry_policy: dict[str, Any],
    ) -> TemporalProviderStartResult: ...

    def signal_workflow(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        signal: dict[str, Any],
    ) -> TemporalProviderSignalResult: ...

    def cancel_workflow(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        reason: str,
    ) -> TemporalProviderCancellationResult: ...


class TemporalAsyncProviderClient(Protocol):
    """Async surface used by the Temporal Python SDK adapter."""

    def start_workflow(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        workflow_type: str,
        task_queue_ref: str,
        payload: dict[str, Any],
        retry_policy: dict[str, Any],
    ) -> Awaitable[TemporalProviderStartResult]: ...

    def signal_workflow(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        signal: dict[str, Any],
    ) -> Awaitable[TemporalProviderSignalResult]: ...

    def cancel_workflow(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        reason: str,
    ) -> Awaitable[TemporalProviderCancellationResult]: ...

    def observe_workflow_input(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        provider_run_id: str | None,
    ) -> Awaitable[TemporalProviderWorkflowInputObservation]: ...


class TemporalActivityProviderClient(Protocol):
    """Minimal provider surface for a typed activity dispatch boundary."""

    def dispatch_activity(self, *, request: dict[str, Any]) -> TemporalProviderActivityResult: ...


class TemporalAsyncActivityProviderClient(Protocol):
    """Async provider surface for a Temporal activity worker/bridge."""

    def dispatch_activity(
        self, *, request: dict[str, Any]
    ) -> Awaitable[TemporalProviderActivityResult]: ...


def build_temporal_start_request(
    workflow_input: TemporalWorkflowInput,
) -> TemporalWorkflowStartRequest:
    """Build the only payload a provider client is allowed to submit."""

    payload = workflow_input.model_dump(mode="json")
    values = {
        "tenant_id": workflow_input.tenant_id,
        "namespace_ref": workflow_input.identity.namespace.namespace_ref,
        "workflow_id": workflow_input.identity.workflow_id,
        "workflow_type": workflow_input.identity.workflow_type,
        "task_queue_ref": workflow_input.identity.task_queue.queue_ref,
        "policy_decision_ref": workflow_input.policy_decision_ref,
        "payload": payload,
    }
    values["payload_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_START_REQUEST_SCHEMA, values, "payload_sha256"
    )
    return TemporalWorkflowStartRequest(**values)


_ProviderResult = TypeVar("_ProviderResult")


async def _resolve_provider_result(
    value: _ProviderResult | Awaitable[_ProviderResult],
) -> _ProviderResult:
    """Resolve sync fakes and async SDK calls without creating an event loop."""

    if isawaitable(value):
        return await value
    return value


class TemporalWorkflowAdapter:
    """GDA-owned validation around a provider-specific Temporal client."""

    def __init__(self, client: TemporalProviderClient | TemporalAsyncProviderClient):
        self._client = client

    def start(self, workflow_input: TemporalWorkflowInput) -> TemporalProviderStartResult:
        request = build_temporal_start_request(workflow_input)
        result = self._start_provider(request, workflow_input)
        self._validate_start_result(request, result)
        return result

    async def start_async(
        self, workflow_input: TemporalWorkflowInput
    ) -> TemporalProviderStartResult:
        """Start through an async Temporal SDK client using the same contract checks."""

        request = build_temporal_start_request(workflow_input)
        result = await _resolve_provider_result(
            self._client.start_workflow(
                tenant_id=request.tenant_id,
                namespace_ref=request.namespace_ref,
                workflow_id=request.workflow_id,
                workflow_type=request.workflow_type,
                task_queue_ref=request.task_queue_ref,
                payload=request.payload,
                retry_policy=workflow_input.retry_policy.model_dump(mode="json"),
            )
        )
        self._validate_start_result(request, result)
        return result

    def reconcile_start(
        self,
        workflow_input: TemporalWorkflowInput,
        result: TemporalProviderStartResult,
        *,
        observed_input_sha256: str | None = None,
        observed_provider_run_id: str | None = None,
    ) -> TemporalStartReconciliation:
        """Reconcile provider state against the immutable workflow input.

        ``unknown`` remains pending and is never retried here. ``already_exists``
        is accepted only when provider-observed input matches this request.
        """

        request = build_temporal_start_request(workflow_input)
        self._validate_start_result(request, result)
        if observed_input_sha256 is not None and observed_input_sha256 != request.payload_sha256:
            raise TemporalAdapterProtocolError(
                "Temporal existing workflow input fingerprint differs from request"
            )
        if (
            result.provider_run_id is not None
            and observed_provider_run_id is not None
            and result.provider_run_id != observed_provider_run_id
        ):
            raise TemporalAdapterProtocolError(
                "Temporal observed provider run differs from start receipt"
            )
        if result.status is TemporalProviderStartStatus.ALREADY_EXISTS:
            if observed_input_sha256 is None:
                raise TemporalAdapterProtocolError(
                    "Temporal already_exists requires observed workflow input fingerprint"
                )
            verdict = TemporalStartReconciliationVerdict.ALREADY_EXISTS_MATCHED
        elif result.status is TemporalProviderStartStatus.UNKNOWN:
            if observed_provider_run_id is not None:
                if observed_input_sha256 is None:
                    raise TemporalAdapterProtocolError(
                        "matched Temporal observation requires input fingerprint"
                    )
                verdict = TemporalStartReconciliationVerdict.ALREADY_EXISTS_MATCHED
            else:
                verdict = TemporalStartReconciliationVerdict.UNKNOWN_PENDING
        else:
            verdict = TemporalStartReconciliationVerdict.STARTED
        effective_provider_run_id = observed_provider_run_id or result.provider_run_id
        values = {
            "tenant_id": request.tenant_id,
            "namespace_ref": request.namespace_ref,
            "workflow_id": request.workflow_id,
            "provider_status": result.status,
            "verdict": verdict,
            "provider_run_id": effective_provider_run_id,
            "provider_receipt_ref": result.provider_receipt_ref,
            "request_sha256": request.payload_sha256,
            "observed_input_sha256": observed_input_sha256,
        }
        values["reconciliation_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_START_RECONCILIATION_SCHEMA,
            values,
            "reconciliation_sha256",
        )
        return TemporalStartReconciliation(**values)

    async def reconcile_start_async(
        self,
        workflow_input: TemporalWorkflowInput,
        result: TemporalProviderStartResult,
    ) -> TemporalStartReconciliation:
        """Read provider history for an uncertain/duplicate start before settling it.

        A provider that cannot expose the existing run input leaves ``unknown`` pending;
        it is never retried or promoted by this helper.
        """

        if result.status is TemporalProviderStartStatus.STARTED:
            return self.reconcile_start(workflow_input, result)
        observer = getattr(self._client, "observe_workflow_input", None)
        if not callable(observer):
            return self.reconcile_start(workflow_input, result)
        provider_run_id = result.provider_run_id
        if provider_run_id is None and result.status is TemporalProviderStartStatus.ALREADY_EXISTS:
            raise TemporalAdapterProtocolError(
                "already_exists reconciliation requires provider run id"
            )
        try:
            observation = await _resolve_provider_result(
                observer(
                    tenant_id=workflow_input.tenant_id,
                    namespace_ref=workflow_input.identity.namespace.namespace_ref,
                    workflow_id=workflow_input.identity.workflow_id,
                    provider_run_id=provider_run_id,
                )
            )
        except TemporalAdapterError:
            if result.status is TemporalProviderStartStatus.UNKNOWN:
                return self.reconcile_start(workflow_input, result)
            raise
        if not isinstance(observation, TemporalProviderWorkflowInputObservation):
            raise TemporalAdapterProtocolError(
                "Temporal workflow input observer returned an invalid observation"
            )
        if (
            observation.tenant_id != workflow_input.tenant_id
            or observation.namespace_ref != workflow_input.identity.namespace.namespace_ref
            or observation.workflow_id != workflow_input.identity.workflow_id
            or (provider_run_id is not None and observation.provider_run_id != provider_run_id)
        ):
            raise TemporalAdapterProtocolError(
                "Temporal workflow input observation correlation differs"
            )
        return self.reconcile_start(
            workflow_input,
            result,
            observed_input_sha256=observation.observed_input_sha256,
            observed_provider_run_id=observation.provider_run_id,
        )

    def start_and_register(
        self,
        workflow_input: TemporalWorkflowInput,
        *,
        target_authority: Any,
        registered_by: str,
    ) -> Any:
        """Start a workflow and durably register its receipt for discovery.

        The registration happens even when the provider result is ``unknown``;
        that result remains pending until a reconciler observes the provider's
        immutable start input.  This method intentionally does not retry a
        provider start.
        """

        request = build_temporal_start_request(workflow_input)
        result = self.start(workflow_input)
        reconciliation = self.reconcile_start(workflow_input, result)
        return target_authority.register_start_target(
            request,
            result,
            reconciliation,
            registered_by=registered_by,
        )

    async def start_and_register_async(
        self,
        workflow_input: TemporalWorkflowInput,
        *,
        target_authority: Any,
        registered_by: str,
    ) -> Any:
        """Async start plus durable start-target registration boundary."""

        request = build_temporal_start_request(workflow_input)
        result = await self.start_async(workflow_input)
        reconciliation = await self.reconcile_start_async(workflow_input, result)
        return await _resolve_provider_result(
            target_authority.register_start_target(
                request,
                result,
                reconciliation,
                registered_by=registered_by,
            )
        )

    def signal(
        self, identity: TemporalWorkflowIdentity, signal: TemporalSignal
    ) -> TemporalProviderSignalResult:
        result = self._signal_provider(identity, signal)
        self._validate_signal_result(identity, signal, result)
        return result

    async def signal_async(
        self, identity: TemporalWorkflowIdentity, signal: TemporalSignal
    ) -> TemporalProviderSignalResult:
        """Send a signal through an async Temporal SDK client."""

        if signal.tenant_id != identity.tenant_id:
            raise TemporalAdapterProtocolError("signal tenant differs from workflow identity")
        if signal.workflow_id != identity.workflow_id:
            raise TemporalAdapterProtocolError("signal workflow differs from identity")
        result = await _resolve_provider_result(
            self._client.signal_workflow(
                tenant_id=identity.tenant_id,
                namespace_ref=identity.namespace.namespace_ref,
                workflow_id=identity.workflow_id,
                signal=signal.model_dump(mode="json"),
            )
        )
        self._validate_signal_result(identity, signal, result)
        return result

    def cancel(
        self, identity: TemporalWorkflowIdentity, *, reason: str = ""
    ) -> TemporalProviderCancellationResult:
        normalized_reason = reason.strip() or "GDA cancellation requested"
        result = self._client.cancel_workflow(
            tenant_id=identity.tenant_id,
            namespace_ref=identity.namespace.namespace_ref,
            workflow_id=identity.workflow_id,
            reason=normalized_reason,
        )
        if isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise TemporalAdapterError(
                "async Temporal provider requires cancel_async; refusing to block the event loop"
            )
        self._validate_cancellation_result(identity, result)
        return result

    async def cancel_async(
        self, identity: TemporalWorkflowIdentity, *, reason: str = ""
    ) -> TemporalProviderCancellationResult:
        normalized_reason = reason.strip() or "GDA cancellation requested"
        result = await _resolve_provider_result(
            self._client.cancel_workflow(
                tenant_id=identity.tenant_id,
                namespace_ref=identity.namespace.namespace_ref,
                workflow_id=identity.workflow_id,
                reason=normalized_reason,
            )
        )
        self._validate_cancellation_result(identity, result)
        return result

    def _start_provider(
        self, request: TemporalWorkflowStartRequest, workflow_input: TemporalWorkflowInput
    ) -> TemporalProviderStartResult:
        result = self._client.start_workflow(
            tenant_id=request.tenant_id,
            namespace_ref=request.namespace_ref,
            workflow_id=request.workflow_id,
            workflow_type=request.workflow_type,
            task_queue_ref=request.task_queue_ref,
            payload=request.payload,
            retry_policy=workflow_input.retry_policy.model_dump(mode="json"),
        )
        if isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise TemporalAdapterError(
                "async Temporal provider requires start_async; refusing to block the event loop"
            )
        return result

    def _signal_provider(
        self, identity: TemporalWorkflowIdentity, signal: TemporalSignal
    ) -> TemporalProviderSignalResult:
        if signal.tenant_id != identity.tenant_id:
            raise TemporalAdapterProtocolError("signal tenant differs from workflow identity")
        if signal.workflow_id != identity.workflow_id:
            raise TemporalAdapterProtocolError("signal workflow differs from identity")
        result = self._client.signal_workflow(
            tenant_id=identity.tenant_id,
            namespace_ref=identity.namespace.namespace_ref,
            workflow_id=identity.workflow_id,
            signal=signal.model_dump(mode="json"),
        )
        if isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise TemporalAdapterError(
                "async Temporal provider requires signal_async; refusing to block the event loop"
            )
        return result

    @staticmethod
    def _validate_cancellation_result(
        identity: TemporalWorkflowIdentity,
        result: TemporalProviderCancellationResult,
    ) -> None:
        if (
            result.tenant_id != identity.tenant_id
            or result.namespace_ref != identity.namespace.namespace_ref
            or result.workflow_id != identity.workflow_id
        ):
            raise TemporalAdapterProtocolError(
                "Temporal cancellation receipt correlation differs"
            )

    @staticmethod
    def _validate_signal_result(
        identity: TemporalWorkflowIdentity,
        signal: TemporalSignal,
        result: TemporalProviderSignalResult,
    ) -> None:
        if (
            result.tenant_id != identity.tenant_id
            or result.workflow_id != identity.workflow_id
            or result.signal_id != str(signal.signal_id)
        ):
            raise TemporalAdapterProtocolError("Temporal signal receipt correlation differs")

    @staticmethod
    def _validate_start_result(
        request: TemporalWorkflowStartRequest,
        result: TemporalProviderStartResult,
    ) -> None:
        if (
            result.tenant_id != request.tenant_id
            or result.namespace_ref != request.namespace_ref
            or result.workflow_id != request.workflow_id
        ):
            raise TemporalAdapterProtocolError(
                "Temporal start receipt correlation differs from request"
            )


class TemporalActivityAdapter:
    """Validate provider activity receipts and convert them to GDA evidence."""

    def __init__(
        self,
        client: TemporalActivityProviderClient | TemporalAsyncActivityProviderClient,
    ) -> None:
        self._client = client

    def dispatch(self, request: TemporalActivityRequest) -> TemporalActivityEvidence:
        result = self._dispatch_provider(request)
        return self._evidence_from_result(request, result)

    async def dispatch_async(self, request: TemporalActivityRequest) -> TemporalActivityEvidence:
        result = await _resolve_provider_result(
            self._client.dispatch_activity(request=request.model_dump(mode="json"))
        )
        return self._evidence_from_result(request, result)

    def _dispatch_provider(
        self, request: TemporalActivityRequest
    ) -> TemporalProviderActivityResult:
        result = self._client.dispatch_activity(request=request.model_dump(mode="json"))
        if isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise TemporalAdapterError(
                "async Temporal activity provider requires dispatch_async; "
                "refusing to block the event loop"
            )
        return result

    @staticmethod
    def evidence_from_result(
        request: TemporalActivityRequest, result: TemporalProviderActivityResult
    ) -> TemporalActivityEvidence:
        if (
            result.tenant_id != request.tenant_id
            or result.workflow_id != request.workflow_id
            or result.run_id != request.run_id
            or result.step_id != request.step_id
            or result.tool_call_id != request.tool_call_id
            or result.activity_id != request.activity_id
            or result.attempt_no != request.attempt_no
            or result.request_sha256 != request.request_sha256
        ):
            raise TemporalAdapterProtocolError(
                "Temporal activity receipt correlation differs from request"
            )
        if (
            request.side_effect is AgentSideEffect.NONE
            and result.external_receipt_artifact_id is not None
        ):
            raise TemporalAdapterProtocolError(
                "read-only activity receipt cannot carry an external receipt"
            )
        if (
            result.outcome is TemporalActivityOutcome.SUCCEEDED
            and request.side_effect is AgentSideEffect.EXTERNAL_WRITE
            and result.external_receipt_artifact_id is None
        ):
            raise TemporalAdapterProtocolError(
                "external-write activity receipt requires an external receipt artifact"
            )
        # Unknown is an observation, not a terminal settlement. Give it a distinct
        # evidence identity so a later receipt for the same activity attempt can be
        # appended as an immutable reconciliation settlement without key reuse.
        evidence_suffix = ":unknown" if result.outcome is TemporalActivityOutcome.UNKNOWN else ""
        values = {
            "tenant_id": result.tenant_id,
            "workflow_id": result.workflow_id,
            "run_id": result.run_id,
            "activity_id": result.activity_id,
            "tool_call_id": result.tool_call_id,
            "idempotency_key": (
                f"{request.idempotency_key}:activity-attempt:{request.attempt_no}{evidence_suffix}"
            ),
            "side_effect": request.side_effect,
            "outcome": result.outcome,
            "policy_decision_ref": request.policy_decision_ref,
            "output_artifact_id": result.output_artifact_id,
            "external_receipt_artifact_id": result.external_receipt_artifact_id,
            "provider_operation_ref": result.provider_operation_ref or result.provider_receipt_ref,
            "failure_type": result.failure_type,
        }
        values["evidence_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA, values, "evidence_sha256"
        )
        return TemporalActivityEvidence(**values)

    _evidence_from_result = evidence_from_result


__all__ = [
    "TEMPORAL_SIGNAL_RESULT_SCHEMA",
    "TEMPORAL_CANCELLATION_RESULT_SCHEMA",
    "TEMPORAL_START_REQUEST_SCHEMA",
    "TEMPORAL_START_RESULT_SCHEMA",
    "TEMPORAL_START_RECONCILIATION_SCHEMA",
    "TEMPORAL_WORKFLOW_INPUT_OBSERVATION_SCHEMA",
    "TEMPORAL_ACTIVITY_RESULT_SCHEMA",
    "TemporalAdapterError",
    "TemporalAdapterProtocolError",
    "TemporalAsyncProviderClient",
    "TemporalActivityAdapter",
    "TemporalActivityProviderClient",
    "TemporalAsyncActivityProviderClient",
    "TemporalProviderActivityResult",
    "TemporalProviderClient",
    "TemporalProviderSignalResult",
    "TemporalProviderSignalStatus",
    "TemporalProviderCancellationResult",
    "TemporalProviderCancellationStatus",
    "TemporalProviderStartResult",
    "TemporalProviderStartStatus",
    "TemporalProviderWorkflowInputObservation",
    "TemporalStartReconciliation",
    "TemporalStartReconciliationVerdict",
    "TemporalWorkflowAdapter",
    "TemporalWorkflowStartRequest",
    "build_temporal_start_request",
]
