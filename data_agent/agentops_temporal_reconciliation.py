"""Reconcile Temporal provider history with the GDA AgentOps checkpoint projection.

Temporal owns durable workflow history. GDA owns AgentRun, TaskStep, ToolCall, Artifact,
policy and checkpoint evidence. This module compares the two authorities without allowing
either side to silently overwrite the other.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from pydantic import Field, model_validator

from .agentops_contracts import AgentRunStatus
from .agentops_provider_identity import derive_specialist_provider_receipt_ref
from .agentops_specialist_providers import (
    SpecialistActivityReconciliation,
    SpecialistArtifactStore,
    SpecialistOperationAuthority,
    SpecialistProviderCancellationAdapter,
    SpecialistProviderCancellationStatus,
    SpecialistProviderError,
    SpecialistReconciliationVerdict,
    reconcile_unknown_specialist_activity,
)
from .agentops_temporal_adapter import (
    TemporalActivityAdapter,
    TemporalProviderActivityResult,
    build_temporal_start_request,
)
from .agentops_temporal_contracts import (
    TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA,
    TemporalActivityEvidence,
    TemporalActivityOutcome,
    TemporalActivityRequest,
    temporal_contract_fingerprint,
)
from .agentops_temporal_workflow import TemporalTaskGraphWorkflowCheckpoint
from .platform_contracts import FrozenContract, NonEmptyText, Sha256, TenantId

TEMPORAL_ACTIVITY_HISTORY_OBSERVATION_SCHEMA = (
    "gda.temporal_activity_history_observation.v1"
)
TEMPORAL_WORKFLOW_HISTORY_OBSERVATION_SCHEMA = (
    "gda.temporal_workflow_history_observation.v1"
)
TEMPORAL_CHECKPOINT_RECONCILIATION_SCHEMA = (
    "gda.temporal_checkpoint_reconciliation.v1"
)
TEMPORAL_SPECIALIST_HISTORY_RECONCILIATION_SCHEMA = (
    "gda.temporal_specialist_history_reconciliation.v1"
)


class TemporalHistoryReconciliationError(ValueError):
    """Raised when provider history and GDA checkpoint evidence diverge."""


class TemporalProviderActivityHistoryStatus(StrEnum):
    SCHEDULED = "scheduled"
    STARTED = "started"
    TIMED_OUT = "timed_out"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"


class TemporalProviderWorkflowHistoryStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TERMINATED = "terminated"
    TIMED_OUT = "timed_out"


class TemporalCheckpointReconciliationVerdict(StrEnum):
    MATCHED = "matched"
    CHECKPOINT_BEHIND = "checkpoint_behind"
    PROVIDER_BEHIND = "provider_behind"


class TemporalSpecialistHistoryReconciliation(FrozenContract):
    """Join one Temporal terminal observation to the specialist receipt verdict."""

    schema_id: ClassVar[str] = TEMPORAL_SPECIALIST_HISTORY_RECONCILIATION_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    activity_id: UUID
    attempt_no: int = Field(ge=1)
    request_sha256: Sha256
    temporal_status: TemporalProviderActivityHistoryStatus
    provider_operation_ref: NonEmptyText
    provider_receipt_ref: NonEmptyText
    specialist_verdict: SpecialistReconciliationVerdict
    resulting_outcome: TemporalActivityOutcome
    output_artifact_id: UUID | None = None
    failure_type: NonEmptyText | None = None
    specialist_reconciliation_sha256: Sha256
    reconciliation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_join(self) -> TemporalSpecialistHistoryReconciliation:
        if self.temporal_status is TemporalProviderActivityHistoryStatus.SUCCEEDED:
            raise ValueError(
                "specialist history reconciliation requires a non-success Temporal observation"
            )
        if self.specialist_verdict is SpecialistReconciliationVerdict.MATCHED_SUCCEEDED:
            if self.resulting_outcome is not TemporalActivityOutcome.SUCCEEDED:
                raise ValueError("matched specialist receipt must produce succeeded outcome")
            if self.output_artifact_id is None or self.failure_type is not None:
                raise ValueError("matched specialist receipt requires output Artifact only")
        elif self.specialist_verdict is SpecialistReconciliationVerdict.DEFINITIVE_FAILED:
            if self.resulting_outcome is not TemporalActivityOutcome.FAILED:
                raise ValueError("definitive specialist failure must produce failed outcome")
            if self.failure_type is None or self.output_artifact_id is not None:
                raise ValueError("definitive specialist failure requires failure type only")
        elif self.specialist_verdict is SpecialistReconciliationVerdict.UNKNOWN_PENDING:
            if self.resulting_outcome is not TemporalActivityOutcome.UNKNOWN:
                raise ValueError("pending specialist reconciliation must remain unknown")
            if self.output_artifact_id is not None or self.failure_type is not None:
                raise ValueError("pending specialist reconciliation cannot claim terminal evidence")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "reconciliation_sha256"
        )
        if self.reconciliation_sha256 != expected:
            raise ValueError("Temporal specialist history reconciliation hash is invalid")
        return self


class TemporalProviderActivityHistoryObservation(FrozenContract):
    """One activity attempt decoded from immutable Temporal history."""

    schema_id: ClassVar[str] = TEMPORAL_ACTIVITY_HISTORY_OBSERVATION_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    activity_id: UUID
    attempt_no: int = Field(ge=1)
    request: TemporalActivityRequest
    request_sha256: Sha256
    status: TemporalProviderActivityHistoryStatus
    scheduled_event_id: int = Field(ge=1)
    started_event_id: int | None = Field(default=None, ge=1)
    terminal_event_id: int | None = Field(default=None, ge=1)
    timeout_type: NonEmptyText | None = None
    failure_type: NonEmptyText | None = None
    provider_result: TemporalProviderActivityResult | None = None
    observation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_observation(
        self,
    ) -> TemporalProviderActivityHistoryObservation:
        request = self.request
        if (
            request.tenant_id != self.tenant_id
            or request.workflow_id != self.workflow_id
            or request.activity_id != self.activity_id
            or request.attempt_no != self.attempt_no
            or request.request_sha256 != self.request_sha256
        ):
            raise ValueError("activity history request correlation differs")
        if self.started_event_id is not None and (
            self.started_event_id <= self.scheduled_event_id
        ):
            raise ValueError("activity start event must follow schedule event")
        if self.terminal_event_id is not None and (
            self.terminal_event_id
            <= (self.started_event_id or self.scheduled_event_id)
        ):
            raise ValueError("activity terminal event must follow start or schedule")
        if self.status is TemporalProviderActivityHistoryStatus.SCHEDULED:
            if self.started_event_id is not None or self.terminal_event_id is not None:
                raise ValueError("scheduled activity cannot carry later event ids")
        elif self.status is TemporalProviderActivityHistoryStatus.STARTED:
            if self.started_event_id is None or self.terminal_event_id is not None:
                raise ValueError("started activity requires only a start event id")
        else:
            if self.terminal_event_id is None:
                raise ValueError("terminal activity observation requires terminal event id")
        if self.status is TemporalProviderActivityHistoryStatus.TIMED_OUT:
            if self.timeout_type is None or self.provider_result is not None:
                raise ValueError("timed-out activity requires timeout type without result")
        elif self.timeout_type is not None:
            raise ValueError("only timed-out activity can carry timeout type")
        if self.status in {
            TemporalProviderActivityHistoryStatus.FAILED,
            TemporalProviderActivityHistoryStatus.CANCELLED,
        }:
            if self.failure_type is None or self.provider_result is not None:
                raise ValueError("failed/cancelled activity requires failure type")
        elif self.failure_type is not None:
            raise ValueError("only failed/cancelled activity can carry failure type")
        if self.status is TemporalProviderActivityHistoryStatus.SUCCEEDED:
            result = self.provider_result
            if result is None or result.outcome is not TemporalActivityOutcome.SUCCEEDED:
                raise ValueError("successful activity history requires successful result")
            if (
                result.tenant_id != self.tenant_id
                or result.workflow_id != self.workflow_id
                or result.activity_id != self.activity_id
                or result.attempt_no != self.attempt_no
                or result.request_sha256 != self.request_sha256
            ):
                raise ValueError("activity history provider result correlation differs")
        elif self.provider_result is not None:
            raise ValueError("only successful activity history can carry provider result")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "observation_sha256"
        )
        if self.observation_sha256 != expected:
            raise ValueError("activity history observation_sha256 does not match content")
        return self


class TemporalProviderWorkflowHistoryObservation(FrozenContract):
    """Hash-bound provider observation for one workflow execution history."""

    schema_id: ClassVar[str] = TEMPORAL_WORKFLOW_HISTORY_OBSERVATION_SCHEMA
    tenant_id: TenantId
    namespace_ref: NonEmptyText
    workflow_id: NonEmptyText
    provider_run_id: NonEmptyText
    observed_input_sha256: Sha256
    status: TemporalProviderWorkflowHistoryStatus
    history_event_count: int = Field(ge=1)
    history_sha256: Sha256
    activities: tuple[TemporalProviderActivityHistoryObservation, ...] = ()
    observation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_observation(
        self,
    ) -> TemporalProviderWorkflowHistoryObservation:
        if tuple(item.scheduled_event_id for item in self.activities) != tuple(
            sorted(item.scheduled_event_id for item in self.activities)
        ):
            raise ValueError("workflow history activities must follow schedule order")
        activity_ids = tuple(item.activity_id for item in self.activities)
        if len(activity_ids) != len(set(activity_ids)):
            raise ValueError("workflow history activity ids must be unique")
        attempts = tuple(
            (item.request.tool_call_id, item.attempt_no) for item in self.activities
        )
        if len(attempts) != len(set(attempts)):
            raise ValueError("workflow history ToolCall attempts must be unique")
        if any(
            item.tenant_id != self.tenant_id
            or item.workflow_id != self.workflow_id
            or item.scheduled_event_id > self.history_event_count
            or (item.terminal_event_id or 0) > self.history_event_count
            for item in self.activities
        ):
            raise ValueError("workflow history activity correlation differs")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "observation_sha256"
        )
        if self.observation_sha256 != expected:
            raise ValueError("workflow history observation_sha256 does not match content")
        return self


def reconcile_specialist_activity_history(
    observation: TemporalProviderActivityHistoryObservation,
    *,
    artifact_store: SpecialistArtifactStore,
    operation_authority: SpecialistOperationAuthority | None = None,
    cancellation_adapter: SpecialistProviderCancellationAdapter | None = None,
) -> tuple[
    TemporalSpecialistHistoryReconciliation,
    SpecialistActivityReconciliation,
    TemporalProviderActivityResult,
]:
    """Reconcile a Temporal timeout/cancel/failure against a provider receipt.

    Temporal terminal history only says that the activity response was not accepted;
    it does not prove that a provider-side operation failed.  The derived UNKNOWN
    result below is an identity envelope for reconciliation, not success evidence.
    """

    if observation.status is TemporalProviderActivityHistoryStatus.SUCCEEDED:
        raise TemporalHistoryReconciliationError(
            "specialist history reconciliation requires a non-success Temporal observation"
        )
    request = observation.request
    spec = request.provider_spec
    if spec is None:
        raise TemporalHistoryReconciliationError(
            "specialist history reconciliation requires a provider binding"
        )
    operation_ref = f"{spec.operation_ref}://{observation.activity_id}"
    receipt_ref = derive_specialist_provider_receipt_ref(request)
    result_values = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "step_id": request.step_id,
        "tool_call_id": request.tool_call_id,
        "activity_id": request.activity_id,
        "attempt_no": request.attempt_no,
        "request_sha256": request.request_sha256,
        "outcome": TemporalActivityOutcome.UNKNOWN,
        "provider_receipt_ref": receipt_ref,
        "provider_operation_ref": operation_ref,
        "output_artifact_id": None,
        "external_receipt_artifact_id": None,
        "failure_type": None,
    }
    result_values["result_sha256"] = temporal_contract_fingerprint(
        TemporalProviderActivityResult.schema_id, result_values, "result_sha256"
    )
    unknown_result = TemporalProviderActivityResult(**result_values)
    if operation_authority is not None and cancellation_adapter is not None:
        # Temporal cancellation only proves that Temporal stopped accepting the
        # activity result.  A managed reconciliation pass may ask the provider
        # for its own terminal state, but only for an already cancellation-
        # requested receipt.  This keeps ordinary unknown/timeout operations
        # from acquiring an implicit provider cancellation side effect.
        current = operation_authority.observe(operation_ref)
        if (
            current is not None
            and current.status.value == "unknown"
            and current.cancellation_requested
        ):
            try:
                provider_observation = cancellation_adapter.observe_cancellation(
                    request,
                    operation_ref=operation_ref,
                    provider_receipt_ref=receipt_ref,
                )
            except Exception:
                provider_observation = None
            if (
                provider_observation is not None
                and provider_observation.status
                is SpecialistProviderCancellationStatus.CONFIRMED
            ):
                try:
                    operation_authority.cancel(
                        operation_ref,
                        provider_observation.failure_type
                        or "ProviderCancellationConfirmed",
                    )
                except SpecialistProviderError:
                    # A concurrent terminal transition remains authoritative.
                    pass
            elif (
                provider_observation is not None
                and provider_observation.uncertainty_type is not None
                and provider_observation.uncertainty_type != current.uncertainty_type
            ):
                try:
                    operation_authority.request_cancellation(
                        operation_ref,
                        uncertainty_type=provider_observation.uncertainty_type,
                    )
                except SpecialistProviderError:
                    pass
    try:
        specialist_reconciliation, settled = reconcile_unknown_specialist_activity(
            request,
            unknown_result,
            artifact_store=artifact_store,
            operation_authority=operation_authority,
        )
    except SpecialistProviderError as exc:
        raise TemporalHistoryReconciliationError(
            "specialist provider receipt reconciliation failed"
        ) from exc
    values: dict[str, object] = {
        "tenant_id": observation.tenant_id,
        "workflow_id": observation.workflow_id,
        "activity_id": observation.activity_id,
        "attempt_no": observation.attempt_no,
        "request_sha256": observation.request_sha256,
        "temporal_status": observation.status,
        "provider_operation_ref": operation_ref,
        "provider_receipt_ref": receipt_ref,
        "specialist_verdict": specialist_reconciliation.verdict,
        "resulting_outcome": settled.outcome,
        "output_artifact_id": settled.output_artifact_id,
        "failure_type": settled.failure_type,
        "specialist_reconciliation_sha256": specialist_reconciliation.reconciliation_sha256,
    }
    values["reconciliation_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_SPECIALIST_HISTORY_RECONCILIATION_SCHEMA,
        values,
        "reconciliation_sha256",
    )
    return (
        TemporalSpecialistHistoryReconciliation(**values),
        specialist_reconciliation,
        settled,
    )


class TemporalCheckpointReconciliation(FrozenContract):
    """Immutable verdict comparing provider history with one GDA checkpoint."""

    schema_id: ClassVar[str] = TEMPORAL_CHECKPOINT_RECONCILIATION_SCHEMA
    tenant_id: TenantId
    workflow_id: NonEmptyText
    provider_run_id: NonEmptyText
    verdict: TemporalCheckpointReconciliationVerdict
    checkpoint_sha256: Sha256
    execution_state_sha256: Sha256
    history_sha256: Sha256
    checkpoint_run_status: AgentRunStatus
    provider_workflow_status: TemporalProviderWorkflowHistoryStatus
    checkpoint_missing_run_status: bool = False
    provider_missing_run_status: bool = False
    matched_activity_ids: tuple[UUID, ...] = ()
    checkpoint_missing_activity_ids: tuple[UUID, ...] = ()
    provider_missing_activity_ids: tuple[UUID, ...] = ()
    checkpoint_missing_evidence_ids: tuple[UUID, ...] = ()
    reconciliation_sha256: Sha256

    @model_validator(mode="after")
    def _consistent_reconciliation(self) -> TemporalCheckpointReconciliation:
        groups = (
            self.matched_activity_ids,
            self.checkpoint_missing_activity_ids,
            self.provider_missing_activity_ids,
            self.checkpoint_missing_evidence_ids,
        )
        if self.checkpoint_missing_run_status and self.provider_missing_run_status:
            raise ValueError("reconciliation cannot have run status missing on both sides")
        if any(len(group) != len(set(group)) for group in groups):
            raise ValueError("reconciliation activity id groups must be unique")
        if self.verdict is TemporalCheckpointReconciliationVerdict.MATCHED:
            if (
                any(groups[1:])
                or self.checkpoint_missing_run_status
                or self.provider_missing_run_status
            ):
                raise ValueError("matched reconciliation cannot have missing evidence")
        elif self.verdict is TemporalCheckpointReconciliationVerdict.CHECKPOINT_BEHIND:
            if not (
                self.checkpoint_missing_activity_ids
                or self.checkpoint_missing_evidence_ids
                or self.checkpoint_missing_run_status
            ) or self.provider_missing_activity_ids or self.provider_missing_run_status:
                raise ValueError("checkpoint-behind verdict has inconsistent missing ids")
        elif self.verdict is TemporalCheckpointReconciliationVerdict.PROVIDER_BEHIND:
            if not (
                self.provider_missing_activity_ids or self.provider_missing_run_status
            ) or self.checkpoint_missing_activity_ids or self.checkpoint_missing_run_status:
                raise ValueError("provider-behind verdict has inconsistent missing ids")
            if self.checkpoint_missing_evidence_ids:
                raise ValueError("provider-behind checkpoint cannot lack provider evidence")
        expected = temporal_contract_fingerprint(
            self.schema_id, self.model_dump(mode="json"), "reconciliation_sha256"
        )
        if self.reconciliation_sha256 != expected:
            raise ValueError("reconciliation_sha256 does not match checkpoint comparison")
        return self


def activity_evidence_from_history(
    observation: TemporalProviderActivityHistoryObservation,
) -> TemporalActivityEvidence:
    """Convert one definitive provider terminal event to GDA activity evidence."""

    request = observation.request
    if observation.status is TemporalProviderActivityHistoryStatus.SUCCEEDED:
        assert observation.provider_result is not None
        return TemporalActivityAdapter.evidence_from_result(
            request, observation.provider_result
        )
    if observation.status not in {
        TemporalProviderActivityHistoryStatus.TIMED_OUT,
        TemporalProviderActivityHistoryStatus.FAILED,
        TemporalProviderActivityHistoryStatus.CANCELLED,
    }:
        raise TemporalHistoryReconciliationError(
            "non-terminal activity history cannot produce GDA evidence"
        )
    if request.provider_spec is not None:
        raise TemporalHistoryReconciliationError(
            "provider-bound Temporal failure requires specialist receipt reconciliation"
        )
    failure_type = (
        f"TemporalTimeout:{observation.timeout_type}"
        if observation.status is TemporalProviderActivityHistoryStatus.TIMED_OUT
        else observation.failure_type
    )
    values = {
        "tenant_id": request.tenant_id,
        "workflow_id": request.workflow_id,
        "run_id": request.run_id,
        "activity_id": request.activity_id,
        "tool_call_id": request.tool_call_id,
        "idempotency_key": (
            f"{request.idempotency_key}:activity-attempt:{request.attempt_no}"
        ),
        "side_effect": request.side_effect,
        "outcome": TemporalActivityOutcome.FAILED,
        "policy_decision_ref": request.policy_decision_ref,
        "output_artifact_id": None,
        "external_receipt_artifact_id": None,
        "provider_operation_ref": None,
        "failure_type": failure_type,
    }
    values["evidence_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_ACTIVITY_EVIDENCE_SCHEMA, values, "evidence_sha256"
    )
    return TemporalActivityEvidence(**values)


def reconcile_temporal_checkpoint(
    checkpoint: TemporalTaskGraphWorkflowCheckpoint,
    observation: TemporalProviderWorkflowHistoryObservation,
    *,
    specialist_evidence: Mapping[UUID, TemporalActivityEvidence] | None = None,
) -> TemporalCheckpointReconciliation:
    """Compare provider history with a checkpoint without mutating either authority.

    ``specialist_evidence`` is supplied by the receipt reconciler for provider-bound
    terminal activities.  It is intentionally separate from the checkpoint projection:
    a receipt can prove what the provider did, but it cannot silently manufacture a
    missing GDA activity evidence row.
    """

    workflow_id = checkpoint.workflow_input.identity.workflow_id
    if (
        checkpoint.workflow_input.tenant_id != observation.tenant_id
        or workflow_id != observation.workflow_id
    ):
        raise TemporalHistoryReconciliationError(
            "Temporal history identity differs from GDA checkpoint"
        )
    expected_input_sha256 = build_temporal_start_request(
        checkpoint.workflow_input
    ).payload_sha256
    if observation.observed_input_sha256 != expected_input_sha256:
        raise TemporalHistoryReconciliationError(
            "Temporal history start input differs from GDA checkpoint"
        )
    checkpoint_schedules = {
        schedule.activity_id: schedule for schedule in checkpoint.activity_schedules
    }
    provider_activities = {
        activity.activity_id: activity for activity in observation.activities
    }
    checkpoint_only = tuple(
        activity_id
        for activity_id in checkpoint_schedules
        if activity_id not in provider_activities
    )
    provider_only = tuple(
        activity_id
        for activity_id in provider_activities
        if activity_id not in checkpoint_schedules
    )
    if checkpoint_only and provider_only:
        raise TemporalHistoryReconciliationError(
            "Temporal history and GDA checkpoint contain divergent activity identities"
        )

    evidence_by_activity = {
        evidence.activity_id: evidence for evidence in checkpoint.activity_evidence
    }
    matched: list[UUID] = []
    missing_evidence: list[UUID] = []
    for activity_id in checkpoint_schedules.keys() & provider_activities.keys():
        schedule = checkpoint_schedules[activity_id]
        activity = provider_activities[activity_id]
        if (
            schedule.attempt_no != activity.attempt_no
            or schedule.request_sha256 != activity.request_sha256
            or schedule.request != activity.request
        ):
            raise TemporalHistoryReconciliationError(
                "Temporal activity request differs from GDA schedule"
            )
        if activity.status in {
            TemporalProviderActivityHistoryStatus.SCHEDULED,
            TemporalProviderActivityHistoryStatus.STARTED,
        }:
            if activity_id in evidence_by_activity:
                raise TemporalHistoryReconciliationError(
                    "GDA checkpoint has terminal evidence for non-terminal provider activity"
                )
            matched.append(activity_id)
            continue
        if activity.request.provider_spec is not None and activity.status in {
            TemporalProviderActivityHistoryStatus.TIMED_OUT,
            TemporalProviderActivityHistoryStatus.FAILED,
            TemporalProviderActivityHistoryStatus.CANCELLED,
        }:
            expected_evidence = (
                specialist_evidence.get(activity_id)
                if specialist_evidence is not None
                else None
            )
            if expected_evidence is None:
                missing_evidence.append(activity_id)
                continue
        else:
            expected_evidence = activity_evidence_from_history(activity)
        checkpoint_evidence = evidence_by_activity.get(activity_id)
        if checkpoint_evidence is None:
            missing_evidence.append(activity_id)
            continue
        if checkpoint_evidence != expected_evidence:
            raise TemporalHistoryReconciliationError(
                "Temporal terminal activity evidence differs from GDA checkpoint"
            )
        matched.append(activity_id)

    orphan_evidence = set(evidence_by_activity) - set(checkpoint_schedules)
    if orphan_evidence:
        raise TemporalHistoryReconciliationError(
            "GDA checkpoint has activity evidence without a persisted schedule"
        )
    terminal_target = {
        TemporalProviderWorkflowHistoryStatus.COMPLETED: AgentRunStatus.SUCCEEDED,
        TemporalProviderWorkflowHistoryStatus.FAILED: AgentRunStatus.FAILED,
        TemporalProviderWorkflowHistoryStatus.TIMED_OUT: AgentRunStatus.FAILED,
        TemporalProviderWorkflowHistoryStatus.CANCELLED: AgentRunStatus.CANCELLED,
        TemporalProviderWorkflowHistoryStatus.TERMINATED: AgentRunStatus.CANCELLED,
    }.get(observation.status)
    terminal_run_statuses = {
        AgentRunStatus.SUCCEEDED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
    }
    checkpoint_missing_run_status = False
    provider_missing_run_status = False
    if terminal_target is None:
        provider_missing_run_status = checkpoint.run.status in terminal_run_statuses
    elif checkpoint.run.status is terminal_target:
        pass
    elif checkpoint.run.status in terminal_run_statuses:
        raise TemporalHistoryReconciliationError(
            "Temporal workflow terminal status differs from GDA AgentRun"
        )
    else:
        checkpoint_missing_run_status = True

    checkpoint_lag = bool(
        provider_only or missing_evidence or checkpoint_missing_run_status
    )
    provider_lag = bool(checkpoint_only or provider_missing_run_status)
    if checkpoint_lag and provider_lag:
        raise TemporalHistoryReconciliationError(
            "Temporal history and GDA checkpoint are behind in conflicting directions"
        )
    if checkpoint_lag:
        verdict = TemporalCheckpointReconciliationVerdict.CHECKPOINT_BEHIND
    elif provider_lag:
        verdict = TemporalCheckpointReconciliationVerdict.PROVIDER_BEHIND
    else:
        verdict = TemporalCheckpointReconciliationVerdict.MATCHED
    values = {
        "tenant_id": observation.tenant_id,
        "workflow_id": workflow_id,
        "provider_run_id": observation.provider_run_id,
        "verdict": verdict,
        "checkpoint_sha256": checkpoint.checkpoint_sha256,
        "execution_state_sha256": checkpoint.execution.state_sha256,
        "history_sha256": observation.history_sha256,
        "checkpoint_run_status": checkpoint.run.status,
        "provider_workflow_status": observation.status,
        "checkpoint_missing_run_status": checkpoint_missing_run_status,
        "provider_missing_run_status": provider_missing_run_status,
        "matched_activity_ids": tuple(sorted(matched, key=str)),
        "checkpoint_missing_activity_ids": tuple(sorted(provider_only, key=str)),
        "provider_missing_activity_ids": tuple(sorted(checkpoint_only, key=str)),
        "checkpoint_missing_evidence_ids": tuple(sorted(missing_evidence, key=str)),
    }
    values["reconciliation_sha256"] = temporal_contract_fingerprint(
        TEMPORAL_CHECKPOINT_RECONCILIATION_SCHEMA,
        values,
        "reconciliation_sha256",
    )
    return TemporalCheckpointReconciliation(**values)


__all__ = [
    "TEMPORAL_ACTIVITY_HISTORY_OBSERVATION_SCHEMA",
    "TEMPORAL_CHECKPOINT_RECONCILIATION_SCHEMA",
    "TEMPORAL_SPECIALIST_HISTORY_RECONCILIATION_SCHEMA",
    "TEMPORAL_WORKFLOW_HISTORY_OBSERVATION_SCHEMA",
    "TemporalCheckpointReconciliation",
    "TemporalCheckpointReconciliationVerdict",
    "TemporalHistoryReconciliationError",
    "TemporalProviderActivityHistoryObservation",
    "TemporalProviderActivityHistoryStatus",
    "TemporalProviderWorkflowHistoryObservation",
    "TemporalProviderWorkflowHistoryStatus",
    "TemporalSpecialistHistoryReconciliation",
    "activity_evidence_from_history",
    "reconcile_specialist_activity_history",
    "reconcile_temporal_checkpoint",
]
