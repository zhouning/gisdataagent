"""Durable recovery worker for the five governed projection providers.

The worker deliberately keeps provider execution and checkpoint authority as
separate calls.  It is therefore safe to run repeatedly after a process
restart: a durable ``provider_committed`` snapshot only performs observation
and authority retry, while an unknown provider outcome is never replayed
automatically.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from .cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionRepairPlan,
    ProjectionTargetObservation,
)
from .cross_store_projection_recovery import (
    CheckpointAuthority,
    ProjectionRecoveryCoordinator,
    ProjectionRecoveryError,
    ProjectionRecoveryLedger,
    ProjectionRecoverySnapshot,
    ProjectionRecoveryState,
)


class ProjectionProviderFailure(RuntimeError):
    """Provider failure with an explicit statement about commit knowledge."""

    def __init__(self, message: str, *, outcome_known: bool) -> None:
        super().__init__(message)
        self.outcome_known = outcome_known


class ProjectionRecoveryProvider(Protocol):
    def execute(self, plan: ProjectionRepairPlan) -> Any: ...

    def observe(self, plan: ProjectionRepairPlan) -> ProjectionTargetObservation: ...

    def recover_receipt(self, plan: ProjectionRepairPlan) -> Any | None: ...


Compensation = Callable[[ProjectionRepairPlan, ProjectionRecoverySnapshot], Any]


@dataclass(frozen=True)
class RegisteredExecutorProjectionProvider:
    """Adapt any existing PostGIS/RDF/vector/S3/Iceberg executor.

    All five executors expose the same plan-bound ``execute`` and ``observe``
    semantics, with only PostGIS and pgvector accepting structured rows.
    Registries remain the authority for target identity; this adapter never
    accepts a target supplied by the recovery event.
    """

    executor: Any
    registry: Any
    rows: tuple[dict[str, Any], ...] = ()

    def _target(self, plan: ProjectionRepairPlan) -> Any:
        return self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )

    def execute(self, plan: ProjectionRepairPlan) -> Any:
        self._target(plan)
        if plan.target_engine.value in {"postgis", "vector"}:
            return self.executor.execute(plan, rows=self.rows)
        return self.executor.execute(plan)

    def observe(self, plan: ProjectionRepairPlan) -> ProjectionTargetObservation:
        observation = self.executor.observe(self._target(plan))
        if not isinstance(observation, ProjectionTargetObservation):
            raise ProjectionProviderFailure(
                "projection executor returned invalid target observation",
                outcome_known=False,
            )
        return observation

    def recover_receipt(self, plan: ProjectionRepairPlan) -> Any | None:
        self._target(plan)
        recover = getattr(self.executor, "recover_receipt", None)
        return recover(plan) if callable(recover) else None


WorkerAction = Literal[
    "execute_provider",
    "retry_authority",
    "reobserve_target",
    "manual_compensation",
    "await_operator",
    "none",
]


class ProjectionRecoveryWorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    action_taken: WorkerAction
    snapshot: ProjectionRecoverySnapshot
    checkpoint: ProjectionCheckpoint | None = None
    error_code: str | None = None


class ProjectionRecoveryWorker:
    """Run at most one provider mutation or authority retry per invocation."""

    def __init__(
        self,
        plan: ProjectionRepairPlan,
        *,
        checkpointed_by: str,
        provider: ProjectionRecoveryProvider,
        authority: CheckpointAuthority,
        ledger: ProjectionRecoveryLedger | None = None,
        compensation: Compensation | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.plan = plan
        self.provider = provider
        self.authority = authority
        self.compensation = compensation
        self.coordinator = ProjectionRecoveryCoordinator(
            plan,
            checkpointed_by=checkpointed_by,
            ledger=ledger,
            now=now,
        )

    @staticmethod
    def _error_code(error: Exception | str) -> str:
        text = str(error).strip().replace(" ", "_")
        return text[:128] or "unknown_error"

    def _result(
        self,
        action: WorkerAction,
        *,
        checkpoint: ProjectionCheckpoint | None = None,
        error: Exception | str | None = None,
    ) -> ProjectionRecoveryWorkerResult:
        return ProjectionRecoveryWorkerResult(
            action_taken=action,
            snapshot=self.coordinator.snapshot,
            checkpoint=checkpoint,
            error_code=None if error is None else self._error_code(error),
        )

    def _execute_provider(self) -> ProjectionRecoveryWorkerResult | None:
        try:
            receipt = self.provider.execute(self.plan)
        except ProjectionProviderFailure as exc:
            snapshot = self.coordinator.provider_failed(
                exc, outcome_known=exc.outcome_known
            )
            action: WorkerAction = (
                "execute_provider"
                if snapshot.state is ProjectionRecoveryState.PROVIDER_FAILED
                else "reobserve_target"
            )
            return self._result(action, error=exc)
        except Exception as exc:
            snapshot = self.coordinator.provider_failed(exc, outcome_known=False)
            return self._result("reobserve_target", error=exc)
        self.coordinator.provider_committed(receipt)
        return None

    def _observe_and_recover(self) -> ProjectionRecoveryWorkerResult:
        try:
            observation = self.provider.observe(self.plan)
        except Exception as exc:
            snapshot = self.coordinator.authority_failed(exc)
            return self._result("retry_authority", error=exc)
        snapshot, checkpoint = self.coordinator.recover_authority(
            observation, self.authority
        )
        if snapshot.next_action == "manual_compensation":
            return self._compensate_or_wait()
        return self._result("retry_authority", checkpoint=checkpoint)

    def _reobserve_unknown(self) -> ProjectionRecoveryWorkerResult:
        try:
            recover_receipt = getattr(self.provider, "recover_receipt", None)
            receipt = (
                recover_receipt(self.plan) if callable(recover_receipt) else None
            )
            if receipt is not None:
                self.coordinator.provider_receipt_recovered(receipt)
                return self._observe_and_recover()
            observation = self.provider.observe(self.plan)
            self.coordinator.reobserve_unknown_provider(observation)
        except Exception as exc:
            self.coordinator.require_compensation(exc)
            return self._result("await_operator", error=exc)
        return self._compensate_or_wait()

    def _compensate_or_wait(self) -> ProjectionRecoveryWorkerResult:
        if self.compensation is None:
            return self._result("await_operator")
        try:
            receipt = self.compensation(self.plan, self.coordinator.snapshot)
            self.coordinator.provider_committed(receipt)
        except ProjectionProviderFailure as exc:
            self.coordinator.require_compensation(exc)
            return self._result("await_operator", error=exc)
        except Exception as exc:
            self.coordinator.require_compensation(exc)
            return self._result("await_operator", error=exc)
        return self._observe_and_recover()

    def run_once(self) -> ProjectionRecoveryWorkerResult:
        snapshot = self.coordinator.snapshot
        if snapshot.state is ProjectionRecoveryState.AUTHORITY_COMMITTED:
            return self._result("none")
        if snapshot.next_action == "execute_provider":
            result = self._execute_provider()
            if result is not None:
                return result
        snapshot = self.coordinator.snapshot
        if snapshot.next_action == "retry_authority":
            return self._observe_and_recover()
        if snapshot.next_action == "reobserve_target":
            return self._reobserve_unknown()
        if snapshot.next_action == "manual_compensation":
            return self._compensate_or_wait()
        raise ProjectionRecoveryError(
            f"unsupported recovery worker action: {snapshot.next_action}"
        )


__all__ = [
    "ProjectionProviderFailure",
    "ProjectionRecoveryProvider",
    "ProjectionRecoveryWorker",
    "ProjectionRecoveryWorkerResult",
    "RegisteredExecutorProjectionProvider",
]
