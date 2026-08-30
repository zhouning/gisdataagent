"""Real Temporal SDK rehearsal for the provider-neutral AgentOps boundary.

This module is intentionally a separate workflow type. It exercises one typed activity and
history replay without registering the production ``gda.agentops.gis_product`` workflow.
Importing it requires the optional ``agentops-temporal`` dependency.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .agentops_temporal_adapter import (
        TemporalProviderActivityResult,
    )
    from .agentops_temporal_contracts import (
        TemporalActivityOutcome,
        TemporalActivityRequest,
        temporal_contract_fingerprint,
    )
    from .agentops_temporalio_provider import TemporalActivityWorkerHandler

REHEARSAL_WORKFLOW_TYPE = "gda.agentops.rehearsal.v1"
REHEARSAL_ACTIVITY_TYPE = "gda.agentops.rehearsal.activity"
REHEARSAL_OUTPUT_NAMESPACE = NAMESPACE_URL


def _output_artifact_id(request: TemporalActivityRequest) -> UUID:
    return uuid5(
        REHEARSAL_OUTPUT_NAMESPACE,
        f"gda-temporal-rehearsal-output:{request.run_id}:{request.tool_call_id}:{request.attempt_no}",
    )


def _rehearsal_executor(request: TemporalActivityRequest) -> TemporalProviderActivityResult:
    """Return a deterministic receipt; no external system is touched by this rehearsal."""

    values: dict[str, Any] = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "outcome": TemporalActivityOutcome.SUCCEEDED,
        "provider_receipt_ref": (
            f"temporal://gda-agentops-rehearsal/{request.workflow_id}/{request.activity_id}"
        ),
        "provider_operation_ref": f"rehearsal://operation/{request.activity_id}",
        "output_artifact_id": _output_artifact_id(request),
        "external_receipt_artifact_id": None,
        "failure_type": None,
    }
    values["result_sha256"] = temporal_contract_fingerprint(
        TemporalProviderActivityResult.schema_id,
        values,
        "result_sha256",
    )
    return TemporalProviderActivityResult(**values)


_REHEARSAL_HANDLER = TemporalActivityWorkerHandler(_rehearsal_executor)


@activity.defn(name=REHEARSAL_ACTIVITY_TYPE)
async def rehearsal_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one request through the same worker handler used by a real activity."""

    activity.heartbeat({"activity_id": payload["activity_id"]})
    return await _REHEARSAL_HANDLER.handle_async(payload)


@workflow.defn(name=REHEARSAL_WORKFLOW_TYPE)
class RehearsalWorkflow:
    """One explicit activity schedule used only for SDK/server conformance."""

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        schedule = payload["schedule"]
        if schedule["sdk_maximum_attempts"] != 1:
            raise ValueError("rehearsal refuses hidden Temporal activity retries")
        return await workflow.execute_activity(
            REHEARSAL_ACTIVITY_TYPE,
            payload["request"],
            task_queue=schedule["task_queue_ref"],
            activity_id=schedule["activity_id"],
            schedule_to_close_timeout=timedelta(
                seconds=schedule["schedule_to_close_timeout_seconds"]
            ),
            start_to_close_timeout=timedelta(
                seconds=schedule["start_to_close_timeout_seconds"]
            ),
            heartbeat_timeout=timedelta(
                seconds=schedule["heartbeat_timeout_seconds"]
            ),
            retry_policy=RetryPolicy(maximum_attempts=1),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )


__all__ = [
    "REHEARSAL_ACTIVITY_TYPE",
    "REHEARSAL_WORKFLOW_TYPE",
    "RehearsalWorkflow",
    "rehearsal_activity",
]
