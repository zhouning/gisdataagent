"""Deployment-owned, fail-closed projection recovery compensation strategies.

Only the original sealed repair plan may be re-applied. The strategy selector
cannot supply targets, rows, credentials, endpoints, or executable code.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import model_validator

from .cross_store_projection_consistency import ProjectionRepairPlan
from .cross_store_projection_recovery import (
    ProjectionRecoveryLedger,
    ProjectionRecoverySnapshot,
    ProjectionRecoveryState,
)
from .cross_store_projection_recovery_worker import (
    Compensation,
    ProjectionProviderFailure,
    ProjectionRecoveryProvider,
)
from .platform_contracts import (
    FrozenContract,
    ResourceURNText,
    Sha256,
    canonical_json_fingerprint,
    parse_resource_urn,
)

_ATTEMPT_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://gis-data-agent.local/projection-recovery-compensation-attempt/v1",
)


class ProjectionRecoveryCompensationError(RuntimeError):
    """Compensation was disabled or its sealed authority evidence drifted."""

    code = "projection_recovery_compensation_error"


class ProjectionRecoveryCompensationIndeterminateError(ProjectionProviderFailure):
    """The provider may have committed and automatic replay must stop."""

    code = "compensation_execution_outcome_is_indeterminate"


class ProjectionRecoveryCompensationEvidenceWriteError(ProjectionProviderFailure):
    """Terminal provider evidence could not be durably recorded."""

    code = "compensation_terminal_evidence_write_failed"


class ProjectionRecoveryCompensationStrategy(StrEnum):
    DISABLED = "disabled"
    APPROVED_REAPPLY_SEALED_PLAN = "approved_reapply_sealed_plan"


class ProjectionRecoveryCompensationConfig(FrozenContract):
    schema_id: Literal["gda.projection-recovery-compensation-config.v1"] = (
        "gda.projection-recovery-compensation-config.v1"
    )
    strategy: ProjectionRecoveryCompensationStrategy = (
        ProjectionRecoveryCompensationStrategy.DISABLED
    )

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> ProjectionRecoveryCompensationConfig:
        values = os.environ if environment is None else environment
        return cls(
            strategy=values.get(
                "GDA_PROJECTION_RECOVERY_COMPENSATION_STRATEGY",
                ProjectionRecoveryCompensationStrategy.DISABLED.value,
            ).strip()
        )


CompensationExecutionOutcome = Literal[
    "started",
    "indeterminate",
    "succeeded",
    "failed_known",
    "failed_unknown",
]
CompensationReconciliationVerdict = Literal[
    "provider_committed",
    "provider_not_committed",
]


class ProjectionRecoveryCompensationAttempt(FrozenContract):
    schema_id: Literal["gda.projection-recovery-compensation-attempt.v1"] = (
        "gda.projection-recovery-compensation-attempt.v1"
    )
    compensation_attempt_id: UUID
    outcome: CompensationExecutionOutcome
    provider_commit_ref: dict[str, Any] | None = None
    receipt_sha256: Sha256 | None = None
    error_code: str | None = None

    @model_validator(mode="after")
    def _outcome_contract(self) -> ProjectionRecoveryCompensationAttempt:
        if self.outcome == "succeeded":
            if self.provider_commit_ref is None or self.receipt_sha256 is None:
                raise ValueError("successful compensation lacks provider receipt evidence")
            if self.error_code is not None:
                raise ValueError("successful compensation contains an error")
        elif self.outcome in {"failed_known", "failed_unknown"}:
            if not self.error_code or self.provider_commit_ref is not None:
                raise ValueError("failed compensation evidence is incomplete")
            if self.receipt_sha256 is not None:
                raise ValueError("failed compensation contains a provider receipt")
        elif any(
            value is not None
            for value in (
                self.provider_commit_ref,
                self.receipt_sha256,
                self.error_code,
            )
        ):
            raise ValueError("non-terminal compensation contains terminal evidence")
        return self


class ProjectionRecoveryCompensationReceipt(FrozenContract):
    schema_id: Literal["gda.projection-recovery-compensation-receipt.v1"] = (
        "gda.projection-recovery-compensation-receipt.v1"
    )
    plan_sha256: Sha256
    idempotency_key: Sha256
    provider_commit_ref: dict[str, Any]
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def _receipt_contract(self) -> ProjectionRecoveryCompensationReceipt:
        expected = compensation_receipt_fingerprint(
            plan_sha256=self.plan_sha256,
            idempotency_key=self.idempotency_key,
            provider_commit_ref=self.provider_commit_ref,
        )
        if self.receipt_sha256 != expected:
            raise ValueError("compensation receipt fingerprint is invalid")
        if (
            self.provider_commit_ref.get("plan_sha256") != self.plan_sha256
            or self.provider_commit_ref.get("idempotency_key")
            != self.idempotency_key
        ):
            raise ValueError("compensation provider commit evidence is not plan-bound")
        return self


class ProjectionRecoveryCompensationReconciliation(FrozenContract):
    """One human-authorized ruling for a started-only provider attempt."""

    schema_id: Literal[
        "gda.projection-recovery-compensation-reconciliation.v1"
    ] = "gda.projection-recovery-compensation-reconciliation.v1"
    tenant_id: str
    reconciliation_event_id: UUID
    compensation_attempt_id: UUID
    job_id: UUID
    original_approval_case_ref: ResourceURNText
    reconciliation_approval_case_ref: ResourceURNText
    target_fingerprint: Sha256
    resume_snapshot_sha256: Sha256
    plan_sha256: Sha256
    plan_idempotency_key: Sha256
    strategy: Literal["approved_reapply_sealed_plan"]
    verdict: CompensationReconciliationVerdict
    observed_by: str
    observation_ref: str
    observation_sha256: Sha256
    reason: str
    provider_commit_ref: dict[str, Any] | None = None
    receipt_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _reconciliation_contract(
        self,
    ) -> ProjectionRecoveryCompensationReconciliation:
        for approval_ref in (
            self.original_approval_case_ref,
            self.reconciliation_approval_case_ref,
        ):
            identity = parse_resource_urn(approval_ref)
            if (
                identity["tenant_id"] != self.tenant_id
                or identity["resource_kind"] != "approval_case"
            ):
                raise ValueError("reconciliation approval identity differs")
        expected_target = compensation_reconciliation_target_fingerprint(
            tenant_id=self.tenant_id,
            job_id=self.job_id,
            compensation_attempt_id=self.compensation_attempt_id,
            resume_snapshot_sha256=self.resume_snapshot_sha256,
            plan_sha256=self.plan_sha256,
            plan_idempotency_key=self.plan_idempotency_key,
            strategy=self.strategy,
        )
        if self.target_fingerprint != expected_target:
            raise ValueError("reconciliation target fingerprint is invalid")
        if self.verdict == "provider_committed":
            if self.provider_commit_ref is None or self.receipt_sha256 is None:
                raise ValueError("committed reconciliation lacks provider receipt")
            if (
                self.provider_commit_ref.get("plan_sha256") != self.plan_sha256
                or self.provider_commit_ref.get("idempotency_key")
                != self.plan_idempotency_key
            ):
                raise ValueError("committed reconciliation receipt is not plan-bound")
            expected_receipt = compensation_receipt_fingerprint(
                plan_sha256=self.plan_sha256,
                idempotency_key=self.plan_idempotency_key,
                provider_commit_ref=self.provider_commit_ref,
            )
            if self.receipt_sha256 != expected_receipt:
                raise ValueError("reconciled provider receipt fingerprint is invalid")
        elif any(
            value is not None
            for value in (self.provider_commit_ref, self.receipt_sha256)
        ):
            raise ValueError("not-committed reconciliation contains a receipt")
        if not self.observed_by.startswith("human:"):
            raise ValueError("reconciliation evidence must name a human observer")
        if not self.observation_ref.strip() or not self.reason.strip():
            raise ValueError("reconciliation evidence requires reference and reason")
        return self


class ProjectionRecoveryCompensationAuthority(Protocol):
    def begin_compensation_execution(
        self,
        job: Any,
        snapshot: ProjectionRecoverySnapshot,
        *,
        strategy: str,
        compensation_attempt_id: UUID,
    ) -> ProjectionRecoveryCompensationAttempt: ...

    def finish_compensation_execution(
        self,
        job: Any,
        *,
        compensation_attempt_id: UUID,
        outcome: Literal["succeeded", "failed_known", "failed_unknown"],
        provider_commit_ref: dict[str, Any] | None = None,
        receipt_sha256: str | None = None,
        error_code: str | None = None,
    ) -> ProjectionRecoveryCompensationAttempt: ...

    def reconcile_compensation_execution(
        self,
        *,
        tenant_id: str,
        job_id: UUID,
        original_approval_case_ref: str,
        reconciliation_approval_case_ref: str,
        compensation_attempt_id: UUID,
        target_fingerprint: str,
        verdict: CompensationReconciliationVerdict,
        observed_by: str,
        observation_ref: str,
        observation_sha256: str,
        reason: str,
        provider_commit_ref: dict[str, Any] | None = None,
        receipt_sha256: str | None = None,
    ) -> ProjectionRecoveryCompensationReconciliation: ...


def projection_recovery_compensation_attempt_id(job: Any) -> UUID:
    return uuid5(
        _ATTEMPT_NAMESPACE,
        ":".join(
            (
                str(job.tenant_id),
                str(job.job_id),
                str(job.resume_approval_case_ref),
                str(job.resume_snapshot_sha256),
                str(job.plan_sha256),
            )
        ),
    )


def compensation_receipt_fingerprint(
    *,
    plan_sha256: str,
    idempotency_key: str,
    provider_commit_ref: dict[str, Any],
) -> str:
    return canonical_json_fingerprint(
        {
            "schema": "gda.projection-recovery-compensation-receipt.v1",
            "plan_sha256": plan_sha256,
            "idempotency_key": idempotency_key,
            "provider_commit_ref": provider_commit_ref,
        }
    )


def compensation_reconciliation_target_fingerprint(
    *,
    tenant_id: str,
    job_id: UUID | str,
    compensation_attempt_id: UUID | str,
    resume_snapshot_sha256: str,
    plan_sha256: str,
    plan_idempotency_key: str,
    strategy: str = ProjectionRecoveryCompensationStrategy.APPROVED_REAPPLY_SEALED_PLAN.value,
) -> str:
    """Fingerprint used to bind a reconciliation ApprovalCase to one attempt."""

    payload = "\x1f".join(
        (
            "gda.projection-recovery-compensation-reconciliation-target.v1",
            str(tenant_id),
            str(job_id),
            str(compensation_attempt_id),
            resume_snapshot_sha256,
            plan_sha256,
            plan_idempotency_key,
            strategy,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assert_original_plan(job: Any, plan: ProjectionRepairPlan) -> None:
    sealed = getattr(job, "plan", None)
    if not isinstance(sealed, ProjectionRepairPlan) or plan != sealed:
        raise ProjectionRecoveryCompensationError(
            "compensation_plan_differs_from_sealed_job_plan"
        )
    if plan.action in {"fail_closed", "noop"}:
        raise ProjectionRecoveryCompensationError(
            "compensation_requires_executable_sealed_plan"
        )
    if (
        getattr(job, "plan_sha256", None) != plan.plan_sha256
        or getattr(job, "plan_idempotency_key", None)
        != plan.plan_idempotency_key
        or getattr(job, "tenant_id", None) != plan.tenant_id
        or getattr(job, "projection_id", None) != plan.projection_id
        or getattr(job, "target_engine", None) != plan.target_engine.value
        or getattr(job, "target_ref", None) != plan.target_ref
    ):
        raise ProjectionRecoveryCompensationError(
            "compensation_job_identity_differs_from_sealed_plan"
        )


def _assert_waiting_snapshot(
    job: Any,
    snapshot: ProjectionRecoverySnapshot,
    ledger: ProjectionRecoveryLedger,
) -> None:
    resume_snapshot_sha256 = getattr(job, "resume_snapshot_sha256", None)
    if (
        not resume_snapshot_sha256
        or getattr(job, "resume_approval_case_ref", None) is None
        or getattr(job, "resume_reason", None) is None
        or getattr(job, "resumed_by", None) is None
        or getattr(job, "resumed_at", None) is None
    ):
        raise ProjectionRecoveryCompensationError(
            "compensation_requires_complete_resume_approval_evidence"
        )
    if (
        snapshot.snapshot_sha256 != resume_snapshot_sha256
        or snapshot.plan_sha256 != job.plan_sha256
        or snapshot.plan_idempotency_key != job.plan_idempotency_key
        or snapshot.tenant_id != job.tenant_id
        or snapshot.projection_id != job.projection_id
        or snapshot.target_engine.value != job.target_engine
        or snapshot.target_ref != job.target_ref
        or snapshot.state
        not in {
            ProjectionRecoveryState.RECONCILIATION_REQUIRED,
            ProjectionRecoveryState.COMPENSATION_REQUIRED,
        }
        or snapshot.next_action != "manual_compensation"
    ):
        raise ProjectionRecoveryCompensationError(
            "compensation_snapshot_differs_from_approved_waiting_snapshot"
        )
    durable = ledger.current(job.plan_sha256)
    if durable is None or durable.snapshot_sha256 != snapshot.snapshot_sha256:
        raise ProjectionRecoveryCompensationError(
            "compensation_durable_recovery_snapshot_drifted"
        )


def _sealed_receipt(
    receipt: Any,
    plan: ProjectionRepairPlan,
) -> ProjectionRecoveryCompensationReceipt:
    commit_ref = getattr(receipt, "provider_commit_ref", None)
    if (
        getattr(receipt, "plan_sha256", None) != plan.plan_sha256
        or getattr(receipt, "idempotency_key", None) != plan.plan_idempotency_key
        or not isinstance(commit_ref, dict)
        or commit_ref.get("plan_sha256") != plan.plan_sha256
        or commit_ref.get("idempotency_key") != plan.plan_idempotency_key
    ):
        raise ProjectionProviderFailure(
            "compensation_provider_receipt_is_not_plan_bound",
            outcome_known=False,
        )
    receipt_sha256 = compensation_receipt_fingerprint(
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=commit_ref,
    )
    return ProjectionRecoveryCompensationReceipt(
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=commit_ref,
        receipt_sha256=receipt_sha256,
    )


def _receipt_from_attempt(
    attempt: ProjectionRecoveryCompensationAttempt,
    plan: ProjectionRepairPlan,
) -> ProjectionRecoveryCompensationReceipt:
    if (
        attempt.outcome != "succeeded"
        or attempt.provider_commit_ref is None
        or attempt.receipt_sha256 is None
    ):
        raise ProjectionRecoveryCompensationError(
            "compensation_attempt_does_not_contain_a_successful_receipt"
        )
    return ProjectionRecoveryCompensationReceipt(
        plan_sha256=plan.plan_sha256,
        idempotency_key=plan.plan_idempotency_key,
        provider_commit_ref=attempt.provider_commit_ref,
        receipt_sha256=attempt.receipt_sha256,
    )


def _error_code(error: Exception) -> str:
    value = str(getattr(error, "code", "") or str(error)).strip()
    return value.replace(" ", "_")[:128] or "compensation_provider_error"


class ApprovedReapplySealedPlanCompensation:
    """Re-apply one job's original plan after exact durable authorization checks."""

    def __init__(
        self,
        *,
        job: Any,
        provider: ProjectionRecoveryProvider,
        ledger: ProjectionRecoveryLedger,
        authority: ProjectionRecoveryCompensationAuthority,
    ) -> None:
        self._job = job
        self._provider = provider
        self._ledger = ledger
        self._authority = authority

    def __call__(
        self,
        plan: ProjectionRepairPlan,
        snapshot: ProjectionRecoverySnapshot,
    ) -> Any:
        _assert_original_plan(self._job, plan)
        _assert_waiting_snapshot(self._job, snapshot, self._ledger)
        attempt_id = projection_recovery_compensation_attempt_id(self._job)
        attempt = self._authority.begin_compensation_execution(
            self._job,
            snapshot,
            strategy=ProjectionRecoveryCompensationStrategy.APPROVED_REAPPLY_SEALED_PLAN.value,
            compensation_attempt_id=attempt_id,
        )
        if attempt.outcome == "succeeded":
            return _receipt_from_attempt(attempt, self._job.plan)
        if attempt.outcome == "indeterminate":
            raise ProjectionRecoveryCompensationIndeterminateError(
                "compensation_execution_outcome_is_indeterminate",
                outcome_known=False,
            )
        if attempt.outcome in {"failed_known", "failed_unknown"}:
            raise ProjectionProviderFailure(
                "compensation_execution_already_failed",
                outcome_known=attempt.outcome == "failed_known",
            )
        if attempt.outcome != "started":
            raise ProjectionRecoveryCompensationError(
                "compensation_execution_authority_returned_invalid_state"
            )
        try:
            receipt = _sealed_receipt(
                self._provider.execute(self._job.plan),
                self._job.plan,
            )
        except Exception as exc:
            outcome: Literal["failed_known", "failed_unknown"] = (
                "failed_known"
                if isinstance(exc, ProjectionProviderFailure) and exc.outcome_known
                else "failed_unknown"
            )
            try:
                self._authority.finish_compensation_execution(
                    self._job,
                    compensation_attempt_id=attempt_id,
                    outcome=outcome,
                    error_code=_error_code(exc),
                )
            except Exception as authority_error:
                raise ProjectionRecoveryCompensationEvidenceWriteError(
                    "compensation_terminal_evidence_write_failed",
                    outcome_known=False,
                ) from authority_error
            raise
        terminal = self._authority.finish_compensation_execution(
            self._job,
            compensation_attempt_id=attempt_id,
            outcome="succeeded",
            provider_commit_ref=receipt.provider_commit_ref,
            receipt_sha256=receipt.receipt_sha256,
        )
        return _receipt_from_attempt(terminal, self._job.plan)


class ProjectionRecoveryCompensationResolver:
    """Resolve the single deployment-approved bounded strategy, or no strategy."""

    def __init__(
        self,
        *,
        config: ProjectionRecoveryCompensationConfig,
        authority: ProjectionRecoveryCompensationAuthority,
    ) -> None:
        self.config = config
        self.authority = authority

    @classmethod
    def from_environment(
        cls,
        *,
        authority: ProjectionRecoveryCompensationAuthority,
        environment: Mapping[str, str] | None = None,
    ) -> ProjectionRecoveryCompensationResolver:
        return cls(
            config=ProjectionRecoveryCompensationConfig.from_environment(environment),
            authority=authority,
        )

    def __call__(
        self,
        job: Any,
        provider: ProjectionRecoveryProvider,
        ledger: ProjectionRecoveryLedger,
    ) -> Compensation | None:
        if self.config.strategy is ProjectionRecoveryCompensationStrategy.DISABLED:
            return None
        if (
            self.config.strategy
            is ProjectionRecoveryCompensationStrategy.APPROVED_REAPPLY_SEALED_PLAN
        ):
            return ApprovedReapplySealedPlanCompensation(
                job=job,
                provider=provider,
                ledger=ledger,
                authority=self.authority,
            )
        raise ProjectionRecoveryCompensationError(
            "unsupported_projection_recovery_compensation_strategy"
        )


__all__ = [
    "ApprovedReapplySealedPlanCompensation",
    "ProjectionRecoveryCompensationConfig",
    "ProjectionRecoveryCompensationError",
    "ProjectionRecoveryCompensationEvidenceWriteError",
    "ProjectionRecoveryCompensationIndeterminateError",
    "ProjectionRecoveryCompensationAttempt",
    "ProjectionRecoveryCompensationReceipt",
    "ProjectionRecoveryCompensationReconciliation",
    "ProjectionRecoveryCompensationResolver",
    "ProjectionRecoveryCompensationStrategy",
    "compensation_receipt_fingerprint",
    "compensation_reconciliation_target_fingerprint",
    "projection_recovery_compensation_attempt_id",
]
