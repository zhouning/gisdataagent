"""Optional Temporal Python SDK bridge for the AgentOps provider contract.

The module deliberately imports no Temporal SDK symbols at import time. This keeps the
core AgentOps contracts usable in lite mode while making the SDK dependency explicit at
the provider boundary. The bridge owns translation to Temporal client calls; GDA-owned
identity, policy and receipt validation remains in ``agentops_temporal_adapter``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from inspect import isawaitable
from typing import Any, Protocol
from uuid import UUID

from .agentops_temporal_adapter import (
    TEMPORAL_SIGNAL_RESULT_SCHEMA,
    TEMPORAL_START_REQUEST_SCHEMA,
    TEMPORAL_START_RESULT_SCHEMA,
    TemporalActivityAdapter,
    TemporalAdapterError,
    TemporalAsyncProviderClient,
    TemporalProviderActivityResult,
    TemporalProviderCancellationResult,
    TemporalProviderCancellationStatus,
    TemporalProviderSignalResult,
    TemporalProviderSignalStatus,
    TemporalProviderStartResult,
    TemporalProviderStartStatus,
    TemporalProviderWorkflowInputObservation,
    TemporalWorkflowStartRequest,
)
from .agentops_temporal_contracts import (
    TemporalActivityRequest,
    TemporalActivitySchedulePlan,
    TemporalWorkflowInput,
    temporal_contract_fingerprint,
)
from .agentops_temporal_reconciliation import (
    TemporalProviderActivityHistoryObservation,
    TemporalProviderActivityHistoryStatus,
    TemporalProviderWorkflowHistoryObservation,
    TemporalProviderWorkflowHistoryStatus,
)

TEMPORAL_SIGNAL_NAME = "gda_agentops_signal"
TEMPORAL_WORKFLOW_INPUT_ENVELOPE_SCHEMAS = frozenset(
    {
        "gda.temporal_checkpoint_reconciliation_rehearsal.v1",
        "gda.agentops.flink_cancellation_probe.v1",
    }
)

TemporalActivityExecutor = Callable[
    [TemporalActivityRequest],
    TemporalProviderActivityResult | Awaitable[TemporalProviderActivityResult],
]


@dataclass(frozen=True)
class TemporalioActivityCall:
    """Typed positional input and keyword options for ``workflow.execute_activity``."""

    activity_type: str
    argument: dict[str, Any]
    activity_id: str
    task_queue: str
    schedule_to_close_timeout: timedelta
    start_to_close_timeout: timedelta
    heartbeat_timeout: timedelta
    retry_policy: Any
    cancellation_type: Any

    def options(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "task_queue": self.task_queue,
            "schedule_to_close_timeout": self.schedule_to_close_timeout,
            "start_to_close_timeout": self.start_to_close_timeout,
            "heartbeat_timeout": self.heartbeat_timeout,
            "retry_policy": self.retry_policy,
            "cancellation_type": self.cancellation_type,
        }


class TemporalioActivityScheduleMapper:
    """Translate a validated schedule plan to exact Temporal SDK call arguments."""

    @classmethod
    def map(
        cls,
        plan: TemporalActivitySchedulePlan,
        *,
        retry_policy_class: Callable[..., Any] | None = None,
        cancellation_type_class: Any | None = None,
    ) -> TemporalioActivityCall:
        if plan.sdk_maximum_attempts != 1:
            raise TemporalAdapterError(
                "Temporal activity SDK retry must use exactly one attempt"
            )
        if retry_policy_class is None or cancellation_type_class is None:
            sdk_retry_policy, sdk_cancellation_type = cls._load_sdk_types()
            retry_policy_class = retry_policy_class or sdk_retry_policy
            cancellation_type_class = (
                cancellation_type_class or sdk_cancellation_type
            )
        try:
            retry_policy = retry_policy_class(
                maximum_attempts=plan.sdk_maximum_attempts
            )
            cancellation_type = getattr(
                cancellation_type_class,
                plan.cancellation_type.name,
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise TemporalAdapterError(
                "Temporal activity schedule option mapping failed"
            ) from exc
        return TemporalioActivityCall(
            activity_type=plan.activity_type,
            argument=plan.request.model_dump(mode="json"),
            activity_id=str(plan.activity_id),
            task_queue=plan.task_queue_ref,
            schedule_to_close_timeout=timedelta(
                seconds=plan.schedule_to_close_timeout_seconds
            ),
            start_to_close_timeout=timedelta(
                seconds=plan.start_to_close_timeout_seconds
            ),
            heartbeat_timeout=timedelta(seconds=plan.heartbeat_timeout_seconds),
            retry_policy=retry_policy,
            cancellation_type=cancellation_type,
        )

    @staticmethod
    def _load_sdk_types() -> tuple[Callable[..., Any], Any]:
        try:
            from temporalio.common import RetryPolicy
            from temporalio.workflow import ActivityCancellationType
        except ImportError as exc:
            raise TemporalAdapterError(
                "Temporal activity scheduling requires optional dependency temporalio"
            ) from exc
        return RetryPolicy, ActivityCancellationType


class TemporalioWorkflowHandle(Protocol):
    """Small subset of ``temporalio.client.WorkflowHandle`` used by the bridge."""

    id: str
    run_id: str | None

    def signal(self, signal: str, arg: dict[str, Any]) -> Awaitable[Any]: ...

    def cancel(self, *, reason: str = "") -> Awaitable[Any]: ...

    def fetch_history(self) -> Awaitable[Any]: ...


class TemporalioClientLike(Protocol):
    """Duck-typed subset of ``temporalio.client.Client`` for conformance tests."""

    def start_workflow(
        self,
        workflow: str,
        arg: dict[str, Any],
        *,
        id: str,
        task_queue: str,
        retry_policy: Any,
    ) -> Awaitable[TemporalioWorkflowHandle]: ...

    def get_workflow_handle(
        self, workflow_id: str, *, run_id: str | None = None
    ) -> TemporalioWorkflowHandle: ...


class TemporalioProviderClient(TemporalAsyncProviderClient):
    """Translate the GDA async provider contract to a connected Temporal client.

    The supplied client must already be connected to the namespace represented by
    ``namespace_ref``. Namespace changes require constructing a new provider instance;
    callers cannot redirect a request to another tenant at runtime.
    """

    def __init__(
        self,
        client: TemporalioClientLike,
        *,
        namespace_ref: str,
        receipt_prefix: str = "temporal://gda-agentops",
    ) -> None:
        if not namespace_ref.strip():
            raise ValueError("namespace_ref must not be empty")
        if not receipt_prefix.strip():
            raise ValueError("receipt_prefix must not be empty")
        self._client = client
        self._namespace_ref = namespace_ref
        self._receipt_prefix = receipt_prefix.rstrip("/")

    async def check_health(self) -> bool:
        """Check the connected Temporal frontend without creating workflow state."""

        service_client = getattr(self._client, "service_client", None)
        checker = getattr(service_client, "check_health", None)
        if not callable(checker):
            raise TemporalAdapterError("Temporal client does not expose health check")
        return bool(await checker(timeout=timedelta(seconds=5)))

    async def start_workflow(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        workflow_type: str,
        task_queue_ref: str,
        payload: dict[str, Any],
        retry_policy: dict[str, Any],
    ) -> TemporalProviderStartResult:
        self._check_namespace(namespace_ref)
        receipt_ref = self._receipt_ref("start", workflow_id, payload)
        try:
            handle = await self._client.start_workflow(
                workflow_type,
                payload,
                id=workflow_id,
                task_queue=task_queue_ref,
                retry_policy=self._build_retry_policy(retry_policy),
            )
        except TemporalAdapterError:
            raise
        except Exception as exc:  # provider outcome may be unknown after transport failure
            if exc.__class__.__name__ == "WorkflowAlreadyStartedError":
                run_id = self._run_id_from_exception(exc)
                if run_id:
                    return self._start_result(
                        tenant_id=tenant_id,
                        namespace_ref=namespace_ref,
                        workflow_id=workflow_id,
                        status=TemporalProviderStartStatus.ALREADY_EXISTS,
                        provider_run_id=run_id,
                        provider_receipt_ref=receipt_ref,
                    )
            return self._start_result(
                tenant_id=tenant_id,
                namespace_ref=namespace_ref,
                workflow_id=workflow_id,
                status=TemporalProviderStartStatus.UNKNOWN,
                provider_receipt_ref=receipt_ref,
            )

        run_id = getattr(handle, "run_id", None)
        if not isinstance(run_id, str) or not run_id:
            return self._start_result(
                tenant_id=tenant_id,
                namespace_ref=namespace_ref,
                workflow_id=workflow_id,
                status=TemporalProviderStartStatus.UNKNOWN,
                provider_receipt_ref=receipt_ref,
            )
        return self._start_result(
            tenant_id=tenant_id,
            namespace_ref=namespace_ref,
            workflow_id=workflow_id,
            status=TemporalProviderStartStatus.STARTED,
            provider_run_id=run_id,
            provider_receipt_ref=receipt_ref,
        )

    async def signal_workflow(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        signal: dict[str, Any],
    ) -> TemporalProviderSignalResult:
        self._check_namespace(namespace_ref)
        signal_id = signal.get("signal_id")
        if not isinstance(signal_id, str) or not signal_id:
            raise TemporalAdapterError("Temporal signal requires a non-empty signal_id")
        receipt_ref = self._receipt_ref("signal", workflow_id, signal)
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.signal(TEMPORAL_SIGNAL_NAME, signal)
        except Exception:
            return self._signal_result(
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                signal_id=signal_id,
                status=TemporalProviderSignalStatus.UNKNOWN,
                provider_receipt_ref=receipt_ref,
            )
        return self._signal_result(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            signal_id=signal_id,
            status=TemporalProviderSignalStatus.ACCEPTED,
            provider_receipt_ref=receipt_ref,
        )

    async def cancel_workflow(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        reason: str,
    ) -> TemporalProviderCancellationResult:
        self._check_namespace(namespace_ref)
        normalized_reason = str(reason or "").strip() or "GDA cancellation requested"
        receipt_ref = self._receipt_ref(
            "cancel", workflow_id, {"reason": normalized_reason}
        )
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            await handle.cancel(reason=normalized_reason)
        except Exception:
            return self._cancellation_result(
                tenant_id=tenant_id,
                namespace_ref=namespace_ref,
                workflow_id=workflow_id,
                status=TemporalProviderCancellationStatus.UNKNOWN,
                reason=normalized_reason,
                provider_receipt_ref=receipt_ref,
            )
        return self._cancellation_result(
            tenant_id=tenant_id,
            namespace_ref=namespace_ref,
            workflow_id=workflow_id,
            status=TemporalProviderCancellationStatus.ACCEPTED,
            reason=normalized_reason,
            provider_receipt_ref=receipt_ref,
        )

    async def observe_workflow_input(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        provider_run_id: str | None,
    ) -> TemporalProviderWorkflowInputObservation:
        """Read and hash the first workflow input from provider history.

        This is deliberately an observation-only call. It never starts, signals or retries a
        workflow. A missing/undecodable start event is an adapter error so the caller can keep an
        ``unknown`` submission pending.
        """

        self._check_namespace(namespace_ref)
        try:
            handle = self._client.get_workflow_handle(
                workflow_id, run_id=provider_run_id
            )
            history = await handle.fetch_history()
        except Exception as exc:
            raise TemporalAdapterError(
                "Temporal workflow input observation failed"
            ) from exc
        events = getattr(history, "events", None)
        if not events:
            raise TemporalAdapterError("Temporal workflow history has no start event")
        attributes = getattr(events[0], "workflow_execution_started_event_attributes", None)
        if attributes is None or not attributes.input.payloads:
            raise TemporalAdapterError(
                "Temporal workflow history start event has no input payload"
            )
        try:
            converter = getattr(self._client, "data_converter", None)
            if converter is None:
                from temporalio.converter import default

                converter = default()
            decoded = converter.decode(list(attributes.input.payloads))
            if isawaitable(decoded):
                decoded = await decoded
        except Exception as exc:
            raise TemporalAdapterError(
                "Temporal workflow input payload could not be decoded"
            ) from exc
        if len(decoded) != 1 or not isinstance(decoded[0], dict):
            raise TemporalAdapterError(
                "Temporal workflow start must contain exactly one object payload"
            )
        payload = decoded[0]
        # The checkpoint rehearsal uses a thin execution envelope so the workflow can
        # receive provider-specific schedule fixtures alongside the canonical GDA input.
        # Production starts continue to send the canonical input object directly.
        if isinstance(payload, dict) and isinstance(payload.get("workflow_input"), dict):
            if payload.get("schema") not in TEMPORAL_WORKFLOW_INPUT_ENVELOPE_SCHEMAS:
                raise TemporalAdapterError(
                    "Temporal workflow input envelope has an unknown schema"
                )
            try:
                workflow_input = TemporalWorkflowInput.model_validate(
                    payload["workflow_input"]
                )
            except (TypeError, ValueError) as exc:
                raise TemporalAdapterError(
                    "Temporal workflow input envelope contains invalid canonical input"
                ) from exc
            if payload.get("workflow_input_sha256") != workflow_input.input_sha256:
                raise TemporalAdapterError(
                    "Temporal workflow input envelope fingerprint differs from canonical input"
                )
            payload = payload["workflow_input"]
        identity = payload.get("identity")
        if not isinstance(identity, dict):
            raise TemporalAdapterError("Temporal workflow input lacks identity")
        namespace = identity.get("namespace")
        task_queue = identity.get("task_queue")
        if not isinstance(namespace, dict) or not isinstance(task_queue, dict):
            raise TemporalAdapterError(
                "Temporal workflow input identity lacks namespace or task queue"
            )
        workflow_type = identity.get("workflow_type")
        policy_decision_ref = payload.get("policy_decision_ref")
        values = {
            "tenant_id": tenant_id,
            "namespace_ref": namespace_ref,
            "workflow_id": workflow_id,
            "workflow_type": workflow_type,
            "task_queue_ref": task_queue.get("queue_ref"),
            "policy_decision_ref": policy_decision_ref,
            "payload": payload,
        }
        try:
            values["payload_sha256"] = temporal_contract_fingerprint(
                TEMPORAL_START_REQUEST_SCHEMA, values, "payload_sha256"
            )
            request = TemporalWorkflowStartRequest(**values)
        except (TypeError, ValueError) as exc:
            raise TemporalAdapterError(
                "Temporal workflow input does not satisfy canonical start contract"
            ) from exc
        observed_run_id = (
            provider_run_id
            or getattr(history, "run_id", None)
            or getattr(handle, "run_id", None)
            or getattr(attributes, "original_execution_run_id", None)
        )
        if not isinstance(observed_run_id, str) or not observed_run_id:
            raise TemporalAdapterError("Temporal workflow input observation lacks run id")
        if provider_run_id is not None and observed_run_id != provider_run_id:
            raise TemporalAdapterError(
                "Temporal workflow input observation run id differs from request"
            )
        receipt_ref = self._receipt_ref(
            "observe-input",
            workflow_id,
            {"provider_run_id": observed_run_id, "payload_sha256": request.payload_sha256},
        )
        observation_values = {
            "tenant_id": tenant_id,
            "namespace_ref": namespace_ref,
            "workflow_id": workflow_id,
            "provider_run_id": observed_run_id,
            "provider_receipt_ref": receipt_ref,
            "observed_input_sha256": request.payload_sha256,
        }
        observation_values["observation_sha256"] = temporal_contract_fingerprint(
            TemporalProviderWorkflowInputObservation.schema_id,
            observation_values,
            "observation_sha256",
        )
        return TemporalProviderWorkflowInputObservation(**observation_values)

    async def observe_workflow_history(
        self,
        *,
        tenant_id: str,
        namespace_ref: str,
        workflow_id: str,
        provider_run_id: str | None,
    ) -> TemporalProviderWorkflowHistoryObservation:
        """Decode activity schedules and terminal outcomes from one Temporal history.

        This is observation-only. It never signals, retries or mutates the workflow. The
        returned activity observations are later compared with a GDA checkpoint by the
        provider-neutral reconciliation contract.
        """

        self._check_namespace(namespace_ref)
        try:
            handle = self._client.get_workflow_handle(
                workflow_id, run_id=provider_run_id
            )
            history = await handle.fetch_history()
            input_observation = await self.observe_workflow_input(
                tenant_id=tenant_id,
                namespace_ref=namespace_ref,
                workflow_id=workflow_id,
                provider_run_id=provider_run_id,
            )
            from temporalio.api.enums.v1 import EventType, TimeoutType

            events = list(getattr(history, "events", ()) or ())
            if not events:
                raise TemporalAdapterError("Temporal workflow history has no events")
            scheduled: dict[int, dict[str, Any]] = {}
            started: dict[int, int] = {}
            terminal: dict[int, dict[str, Any]] = {}
            for event in events:
                event_type = EventType.Name(event.event_type)
                event_id = int(event.event_id)
                if event_type == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED":
                    attributes = event.activity_task_scheduled_event_attributes
                    payloads = list(attributes.input.payloads)
                    decoded = await self._decode_payloads(payloads)
                    if len(decoded) != 1 or not isinstance(decoded[0], dict):
                        raise TemporalAdapterError(
                            "Temporal activity schedule must contain one object payload"
                        )
                    request = TemporalActivityRequest.model_validate(decoded[0])
                    activity_id = UUID(str(attributes.activity_id))
                    if request.activity_id != activity_id:
                        raise TemporalAdapterError(
                            "Temporal activity schedule id differs from request"
                        )
                    scheduled[event_id] = {
                        "activity_id": activity_id,
                        "request": request,
                        "request_sha256": request.request_sha256,
                        "scheduled_event_id": event_id,
                    }
                elif event_type == "EVENT_TYPE_ACTIVITY_TASK_STARTED":
                    attributes = event.activity_task_started_event_attributes
                    scheduled_event_id = int(attributes.scheduled_event_id)
                    if scheduled_event_id in started:
                        raise TemporalAdapterError(
                            "Temporal history contains multiple activity starts for one schedule"
                        )
                    if int(getattr(attributes, "attempt", 0) or 0) not in {0, 1}:
                        raise TemporalAdapterError(
                            "Temporal history activity attempt exceeds the explicit retry boundary"
                        )
                    started[scheduled_event_id] = event_id
                elif event_type == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":
                    attributes = event.activity_task_completed_event_attributes
                    scheduled_event_id = int(attributes.scheduled_event_id)
                    if scheduled_event_id in terminal:
                        raise TemporalAdapterError(
                            "Temporal history contains multiple terminal events for one schedule"
                        )
                    decoded = await self._decode_payloads(
                        list(attributes.result.payloads)
                    )
                    if len(decoded) != 1 or not isinstance(decoded[0], dict):
                        raise TemporalAdapterError(
                            "Temporal activity completion must contain one object result"
                        )
                    result = TemporalProviderActivityResult.model_validate(decoded[0])
                    terminal[scheduled_event_id] = {
                        "status": TemporalProviderActivityHistoryStatus.SUCCEEDED,
                        "terminal_event_id": event_id,
                        "provider_result": result,
                    }
                elif event_type == "EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT":
                    attributes = event.activity_task_timed_out_event_attributes
                    scheduled_event_id = int(attributes.scheduled_event_id)
                    if scheduled_event_id in terminal:
                        raise TemporalAdapterError(
                            "Temporal history contains multiple terminal events for one schedule"
                        )
                    timeout_info = attributes.failure.timeout_failure_info
                    terminal[scheduled_event_id] = {
                        "status": TemporalProviderActivityHistoryStatus.TIMED_OUT,
                        "terminal_event_id": event_id,
                        "timeout_type": TimeoutType.Name(timeout_info.timeout_type),
                    }
                elif event_type == "EVENT_TYPE_ACTIVITY_TASK_FAILED":
                    attributes = event.activity_task_failed_event_attributes
                    scheduled_event_id = int(attributes.scheduled_event_id)
                    if scheduled_event_id in terminal:
                        raise TemporalAdapterError(
                            "Temporal history contains multiple terminal events for one schedule"
                        )
                    message = getattr(attributes.failure, "message", "activity failed")
                    terminal[scheduled_event_id] = {
                        "status": TemporalProviderActivityHistoryStatus.FAILED,
                        "terminal_event_id": event_id,
                        "failure_type": f"TemporalActivityFailed:{message}",
                    }
                elif event_type == "EVENT_TYPE_ACTIVITY_TASK_CANCELED":
                    attributes = event.activity_task_canceled_event_attributes
                    scheduled_event_id = int(attributes.scheduled_event_id)
                    if scheduled_event_id in terminal:
                        raise TemporalAdapterError(
                            "Temporal history contains multiple terminal events for one schedule"
                        )
                    terminal[scheduled_event_id] = {
                        "status": TemporalProviderActivityHistoryStatus.CANCELLED,
                        "terminal_event_id": event_id,
                        "failure_type": "TemporalActivityCancelled",
                    }
            scheduled_ids = set(scheduled)
            if set(started) - scheduled_ids or set(terminal) - scheduled_ids:
                raise TemporalAdapterError(
                    "Temporal history contains activity events without a schedule"
                )
            activities: list[TemporalProviderActivityHistoryObservation] = []
            for scheduled_event_id, values in sorted(scheduled.items()):
                request = values["request"]
                terminal_values = terminal.get(scheduled_event_id, {})
                status = terminal_values.get(
                    "status",
                    TemporalProviderActivityHistoryStatus.STARTED
                    if scheduled_event_id in started
                    else TemporalProviderActivityHistoryStatus.SCHEDULED,
                )
                observation_values = {
                    "tenant_id": tenant_id,
                    "workflow_id": workflow_id,
                    "activity_id": values["activity_id"],
                    "attempt_no": request.attempt_no,
                    "request": request,
                    "request_sha256": values["request_sha256"],
                    "status": status,
                    "scheduled_event_id": scheduled_event_id,
                    "started_event_id": started.get(scheduled_event_id),
                    "terminal_event_id": terminal_values.get("terminal_event_id"),
                    "timeout_type": terminal_values.get("timeout_type"),
                    "failure_type": terminal_values.get("failure_type"),
                    "provider_result": terminal_values.get("provider_result"),
                }
                observation_values["observation_sha256"] = temporal_contract_fingerprint(
                    TemporalProviderActivityHistoryObservation.schema_id,
                    observation_values,
                    "observation_sha256",
                )
                activities.append(
                    TemporalProviderActivityHistoryObservation(**observation_values)
                )
            last_event_type = EventType.Name(events[-1].event_type)
            workflow_status = {
                "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED": (
                    TemporalProviderWorkflowHistoryStatus.COMPLETED
                ),
                "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED": (
                    TemporalProviderWorkflowHistoryStatus.FAILED
                ),
                "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED": (
                    TemporalProviderWorkflowHistoryStatus.CANCELLED
                ),
                "EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED": (
                    TemporalProviderWorkflowHistoryStatus.TERMINATED
                ),
                "EVENT_TYPE_WORKFLOW_EXECUTION_TIMED_OUT": (
                    TemporalProviderWorkflowHistoryStatus.TIMED_OUT
                ),
            }.get(last_event_type, TemporalProviderWorkflowHistoryStatus.RUNNING)
            history_json = history.to_json()
            observed_run_id = input_observation.provider_run_id
            observation_values = {
                "tenant_id": tenant_id,
                "namespace_ref": namespace_ref,
                "workflow_id": workflow_id,
                "provider_run_id": observed_run_id,
                "observed_input_sha256": input_observation.observed_input_sha256,
                "status": workflow_status,
                "history_event_count": len(events),
                "history_sha256": hashlib.sha256(
                    history_json.encode("utf-8")
                ).hexdigest(),
                "activities": tuple(activities),
            }
            observation_values["observation_sha256"] = temporal_contract_fingerprint(
                TemporalProviderWorkflowHistoryObservation.schema_id,
                observation_values,
                "observation_sha256",
            )
            return TemporalProviderWorkflowHistoryObservation(**observation_values)
        except TemporalAdapterError:
            raise
        except Exception as exc:
            raise TemporalAdapterError(
                "Temporal workflow activity history observation failed"
            ) from exc

    async def _decode_payloads(self, payloads: list[Any]) -> list[Any]:
        converter = getattr(self._client, "data_converter", None)
        if converter is None:
            from temporalio.converter import default

            converter = default()
        decoded = converter.decode(payloads)
        if isawaitable(decoded):
            decoded = await decoded
        return list(decoded)

    def _check_namespace(self, namespace_ref: str) -> None:
        if namespace_ref != self._namespace_ref:
            raise TemporalAdapterError(
                "Temporal client namespace differs from the provider binding"
            )

    def _receipt_ref(
        self, operation: str, workflow_id: str, payload: dict[str, Any]
    ) -> str:
        digest = temporal_contract_fingerprint(
            "gda.temporal_provider_attempt.v1",
            {"operation": operation, "workflow_id": workflow_id, "payload": payload},
            "_unused",
        )[:24]
        return f"{self._receipt_prefix}/{operation}/{workflow_id}/{digest}"

    @staticmethod
    def _run_id_from_exception(exc: Exception) -> str | None:
        run_id = getattr(exc, "run_id", None)
        return run_id if isinstance(run_id, str) and run_id else None

    @staticmethod
    def _build_retry_policy(values: dict[str, Any]) -> Any:
        try:
            from temporalio.common import RetryPolicy
        except ImportError as exc:
            raise TemporalAdapterError(
                "Temporal SDK provider requires optional dependency temporalio"
            ) from exc
        try:
            return RetryPolicy(
                initial_interval=timedelta(
                    seconds=float(values["initial_interval_seconds"])
                ),
                backoff_coefficient=float(values["backoff_coefficient"]),
                maximum_interval=timedelta(seconds=float(values["max_interval_seconds"])),
                maximum_attempts=int(values["max_attempts"]),
                non_retryable_error_types=list(values.get("non_retryable_error_types", [])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TemporalAdapterError("invalid Temporal retry policy payload") from exc

    @staticmethod
    def _start_result(**values: Any) -> TemporalProviderStartResult:
        values.setdefault("provider_run_id", None)
        values.setdefault("provider_receipt_ref", None)
        values["result_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_START_RESULT_SCHEMA, values, "result_sha256"
        )
        return TemporalProviderStartResult(**values)

    @staticmethod
    def _signal_result(**values: Any) -> TemporalProviderSignalResult:
        values["result_sha256"] = temporal_contract_fingerprint(
            TEMPORAL_SIGNAL_RESULT_SCHEMA, values, "result_sha256"
        )
        return TemporalProviderSignalResult(**values)

    @staticmethod
    def _cancellation_result(**values: Any) -> TemporalProviderCancellationResult:
        values["result_sha256"] = temporal_contract_fingerprint(
            "gda.temporal_cancellation_result.v1", values, "result_sha256"
        )
        return TemporalProviderCancellationResult(**values)


class TemporalActivityWorkerHandler:
    """Provider-neutral worker boundary for a Temporal activity definition.

    A real ``@activity.defn`` function can pass its serialized argument to this handler. The
    handler owns request parsing and receipt correlation; the domain executor owns the actual
    tool/action and must return a typed provider result.
    """

    def __init__(self, executor: TemporalActivityExecutor) -> None:
        self._executor = executor

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = self._parse_request(payload)
        result = self._executor(request)
        if isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise TemporalAdapterError(
                "async activity executor requires handle_async; refusing to block the event loop"
            )
        self._validate_result(request, result)
        return result.model_dump(mode="json")

    async def handle_async(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = self._parse_request(payload)
        result = self._executor(request)
        if isawaitable(result):
            result = await result
        self._validate_result(request, result)
        return result.model_dump(mode="json")

    @staticmethod
    def _parse_request(payload: dict[str, Any]) -> TemporalActivityRequest:
        try:
            return TemporalActivityRequest.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise TemporalAdapterError("invalid Temporal activity request payload") from exc

    @staticmethod
    def _validate_result(
        request: TemporalActivityRequest,
        result: TemporalProviderActivityResult,
    ) -> None:
        if not isinstance(result, TemporalProviderActivityResult):
            raise TemporalAdapterError(
                "activity executor must return TemporalProviderActivityResult"
            )
        try:
            TemporalActivityAdapter.evidence_from_result(request, result)
        except (TypeError, ValueError, TemporalAdapterError) as exc:
            raise TemporalAdapterError(
                "activity executor result failed request correlation"
            ) from exc


__all__ = [
    "TEMPORAL_SIGNAL_NAME",
    "TEMPORAL_WORKFLOW_INPUT_ENVELOPE_SCHEMAS",
    "TemporalActivityExecutor",
    "TemporalioActivityCall",
    "TemporalioActivityScheduleMapper",
    "TemporalActivityWorkerHandler",
    "TemporalioClientLike",
    "TemporalioProviderClient",
    "TemporalioWorkflowHandle",
]
