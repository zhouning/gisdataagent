"""Fail-closed orchestration for one run spanning multiple projection providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cross_store_projection_consistency import ProjectionRepairPlan
from .cross_store_projection_recovery import (
    InMemoryProjectionRecoveryLedger,
    ProjectionRecoveryLedger,
    ProjectionRecoveryState,
)
from .cross_store_projection_recovery_worker import (
    Compensation,
    ProjectionRecoveryProvider,
    ProjectionRecoveryWorker,
    ProjectionRecoveryWorkerResult,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class FederatedProjectionRecoveryError(RuntimeError):
    """A multi-provider recovery run cannot advance without guessing."""


class FederatedProjectionRecoveryState(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPENSATION_REQUIRED = "compensation_required"
    FAILED_CLOSED = "failed_closed"


class FederatedProjectionItemState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AUTHORITY_COMMITTED = "authority_committed"
    RECOVERY_REQUIRED = "recovery_required"
    COMPENSATION_REQUIRED = "compensation_required"
    FAILED_CLOSED = "failed_closed"


FederatedNextAction = Literal["advance", "retry_item", "await_operator", "none"]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def federated_projection_item_fingerprint(**values: Any) -> str:
    values.pop("item_sha256", None)
    return canonical_json_fingerprint(
        {"schema": FederatedProjectionItemSnapshot.schema_id, "data": _json_ready(values)}
    )


def federated_projection_event_fingerprint(**values: Any) -> str:
    values.pop("event_sha256", None)
    return canonical_json_fingerprint(
        {"schema": FederatedProjectionRecoveryEvent.schema_id, "data": _json_ready(values)}
    )


def federated_projection_snapshot_fingerprint(**values: Any) -> str:
    values.pop("snapshot_sha256", None)
    return canonical_json_fingerprint(
        {
            "schema": FederatedProjectionRecoverySnapshot.schema_id,
            "data": _json_ready(values),
        }
    )


class FederatedProjectionItemSnapshot(_FrozenModel):
    """Current state of one sealed plan inside a federated run."""

    schema_id: ClassVar[str] = "gda.federated-projection-recovery-item.v1"
    position: int = Field(ge=0)
    projection_id: NonEmptyText
    target_engine: NonEmptyText
    target_ref: NonEmptyText
    plan_sha256: Sha256
    plan_idempotency_key: Sha256
    state: FederatedProjectionItemState
    worker_state: ProjectionRecoveryState | None = None
    worker_next_action: NonEmptyText | None = None
    provider_attempts: int = Field(ge=0)
    authority_attempts: int = Field(ge=0)
    provider_commit_ref: dict[str, Any] | None = None
    checkpoint_sha256: Sha256 | None = None
    worker_snapshot_sha256: Sha256 | None = None
    last_error_code: NonEmptyText | None = None
    item_sha256: Sha256

    @model_validator(mode="after")
    def _state_contract(self) -> FederatedProjectionItemSnapshot:
        if self.state is FederatedProjectionItemState.PENDING and (
            self.worker_state is not None
            or self.worker_next_action is not None
            or self.provider_attempts
            or self.authority_attempts
            or self.provider_commit_ref is not None
            or self.checkpoint_sha256 is not None
            or self.worker_snapshot_sha256 is not None
            or self.last_error_code is not None
        ):
            raise ValueError("pending federated item contains worker evidence")
        if self.state is FederatedProjectionItemState.RUNNING:
            if self.worker_state is None:
                if any(
                    value is not None
                    for value in (
                        self.worker_next_action,
                        self.provider_commit_ref,
                        self.checkpoint_sha256,
                        self.worker_snapshot_sha256,
                    )
                ):
                    raise ValueError("running federated item has partial worker evidence")
            elif self.worker_snapshot_sha256 is None or self.worker_next_action is None:
                raise ValueError("running federated item lacks worker evidence")
        if self.state is FederatedProjectionItemState.RECOVERY_REQUIRED and (
            self.worker_state is not ProjectionRecoveryState.RECONCILIATION_REQUIRED
            or self.worker_next_action != "reobserve_target"
            or self.worker_snapshot_sha256 is None
        ):
            raise ValueError("recovery-required item lacks re-observation evidence")
        if self.state is FederatedProjectionItemState.AUTHORITY_COMMITTED and (
            self.worker_state is not ProjectionRecoveryState.AUTHORITY_COMMITTED
            or self.checkpoint_sha256 is None
            or self.worker_snapshot_sha256 is None
            or self.provider_commit_ref is None
            or self.worker_next_action != "none"
        ):
            raise ValueError("committed federated item lacks authority evidence")
        if self.state is FederatedProjectionItemState.COMPENSATION_REQUIRED and (
            self.worker_state
            not in {
                ProjectionRecoveryState.RECONCILIATION_REQUIRED,
                ProjectionRecoveryState.COMPENSATION_REQUIRED,
            }
            or self.worker_next_action != "manual_compensation"
            or self.worker_snapshot_sha256 is None
        ):
            raise ValueError("compensation item lacks recovery evidence")
        if self.state is FederatedProjectionItemState.COMPENSATION_REQUIRED and (
            self.worker_next_action != "manual_compensation"
        ):
            raise ValueError("compensation item must await explicit compensation")
        expected = federated_projection_item_fingerprint(
            **self.model_dump(mode="json", exclude={"item_sha256"})
        )
        if self.item_sha256 != expected:
            raise ValueError("federated projection item fingerprint is invalid")
        return self


class FederatedProjectionRecoveryEvent(_FrozenModel):
    """One append-only aggregate transition."""

    schema_id: ClassVar[str] = "gda.federated-projection-recovery-event.v1"
    sequence: int = Field(ge=1)
    event_type: Literal[
        "planned",
        "run_started",
        "item_started",
        "item_progressed",
        "item_committed",
        "item_blocked",
        "run_yielded",
        "run_completed",
        "run_failed_closed",
    ]
    occurred_at: datetime
    detail: dict[str, Any] = Field(default_factory=dict)
    event_sha256: Sha256

    @model_validator(mode="after")
    def _canonical(self) -> FederatedProjectionRecoveryEvent:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("federated recovery event timestamp must be timezone-aware")
        expected = federated_projection_event_fingerprint(
            **self.model_dump(mode="json", exclude={"event_sha256"})
        )
        if self.event_sha256 != expected:
            raise ValueError("federated projection event fingerprint is invalid")
        return self


class FederatedProjectionRecoverySnapshot(_FrozenModel):
    """Aggregate state for an ordered group of provider repair plans."""

    schema_id: ClassVar[str] = "gda.federated-projection-recovery-snapshot.v1"
    run_id: NonEmptyText
    tenant_id: TenantId
    state: FederatedProjectionRecoveryState
    next_action: FederatedNextAction
    current_position: int = Field(ge=0)
    plan_sha256s: tuple[Sha256, ...] = Field(min_length=2, max_length=32)
    items: tuple[FederatedProjectionItemSnapshot, ...] = Field(min_length=2, max_length=32)
    committed_plan_sha256s: tuple[Sha256, ...] = ()
    last_error_code: NonEmptyText | None = None
    events: tuple[FederatedProjectionRecoveryEvent, ...] = ()
    snapshot_sha256: Sha256

    @model_validator(mode="after")
    def _state_contract(self) -> FederatedProjectionRecoverySnapshot:
        if len(set(self.plan_sha256s)) != len(self.plan_sha256s):
            raise ValueError("federated recovery plans must be unique")
        if self.current_position > len(self.items):
            raise ValueError("federated recovery position exceeds the plan count")
        if tuple(item.position for item in self.items) != tuple(range(len(self.items))):
            raise ValueError("federated recovery item positions are not sequential")
        if tuple(item.plan_sha256 for item in self.items) != self.plan_sha256s:
            raise ValueError("federated recovery item identity differs from the plan list")
        if tuple(event.sequence for event in self.events) != tuple(range(1, len(self.events) + 1)):
            raise ValueError("federated recovery event sequence is not contiguous")
        if not self.events:
            raise ValueError("federated recovery snapshot requires an event")
        committed = tuple(
            item.plan_sha256
            for item in self.items
            if item.state is FederatedProjectionItemState.AUTHORITY_COMMITTED
        )
        if committed != self.committed_plan_sha256s:
            raise ValueError("federated recovery committed plan evidence is inconsistent")
        if self.state is FederatedProjectionRecoveryState.COMPLETED and (
            self.current_position != len(self.items)
            or len(committed) != len(self.items)
            or self.next_action != "none"
        ):
            raise ValueError("completed federated recovery lacks all checkpoints")
        if self.state is FederatedProjectionRecoveryState.COMPENSATION_REQUIRED and (
            self.next_action != "await_operator"
            or not any(
                item.state
                in {
                    FederatedProjectionItemState.RECOVERY_REQUIRED,
                    FederatedProjectionItemState.COMPENSATION_REQUIRED,
                }
                for item in self.items
            )
        ):
            raise ValueError("blocked federated recovery lacks an operator item")
        if self.state is FederatedProjectionRecoveryState.FAILED_CLOSED and (
            self.next_action != "await_operator"
            or not any(
                item.state is FederatedProjectionItemState.FAILED_CLOSED for item in self.items
            )
        ):
            raise ValueError("failed federated recovery lacks a failed item")
        if self.state is FederatedProjectionRecoveryState.PLANNED and (
            self.current_position != 0
            or self.next_action != "advance"
            or any(item.state is not FederatedProjectionItemState.PENDING for item in self.items)
        ):
            raise ValueError("planned federated recovery must contain only pending items")
        if self.state is FederatedProjectionRecoveryState.RUNNING and (
            self.next_action not in {"advance", "retry_item"}
            or (
                self.current_position == len(self.items)
                and (self.next_action != "advance" or len(committed) != len(self.items))
            )
        ):
            raise ValueError("running federated recovery has an invalid cursor")
        if self.state in {
            FederatedProjectionRecoveryState.COMPENSATION_REQUIRED,
            FederatedProjectionRecoveryState.FAILED_CLOSED,
        } and self.current_position >= len(self.items):
            raise ValueError("blocked federated recovery cursor exceeds the plan count")
        expected = federated_projection_snapshot_fingerprint(
            **self.model_dump(mode="json", exclude={"snapshot_sha256"})
        )
        if self.snapshot_sha256 != expected:
            raise ValueError("federated recovery snapshot fingerprint is invalid")
        return self


class FederatedProjectionRecoveryLedger(Protocol):
    def current(self, run_id: str) -> FederatedProjectionRecoverySnapshot | None: ...

    def append(
        self, snapshot: FederatedProjectionRecoverySnapshot
    ) -> FederatedProjectionRecoverySnapshot: ...


class InMemoryFederatedProjectionRecoveryLedger:
    """Append-only aggregate ledger for contract tests and local rehearsal."""

    def __init__(self) -> None:
        self._current: dict[str, FederatedProjectionRecoverySnapshot] = {}
        self._history: dict[str, list[FederatedProjectionRecoverySnapshot]] = {}

    def current(self, run_id: str) -> FederatedProjectionRecoverySnapshot | None:
        return self._current.get(run_id)

    def history(self, run_id: str) -> tuple[FederatedProjectionRecoverySnapshot, ...]:
        return tuple(self._history.get(run_id, ()))

    def append(
        self, snapshot: FederatedProjectionRecoverySnapshot
    ) -> FederatedProjectionRecoverySnapshot:
        current = self._current.get(snapshot.run_id)
        if current is not None:
            if current.snapshot_sha256 == snapshot.snapshot_sha256:
                return current
            if (
                snapshot.tenant_id != current.tenant_id
                or snapshot.plan_sha256s != current.plan_sha256s
                or snapshot.events[: len(current.events)] != current.events
                or len(snapshot.events) != len(current.events) + 1
                or snapshot.current_position < current.current_position
            ):
                raise FederatedProjectionRecoveryError(
                    "federated recovery history is not append-only"
                )
            for previous_item, next_item in zip(current.items, snapshot.items, strict=True):
                if (
                    next_item.provider_attempts < previous_item.provider_attempts
                    or next_item.authority_attempts < previous_item.authority_attempts
                ):
                    raise FederatedProjectionRecoveryError(
                        "federated recovery attempt counters cannot decrease"
                    )
                if (
                    previous_item.state is FederatedProjectionItemState.AUTHORITY_COMMITTED
                    and next_item.state is not FederatedProjectionItemState.AUTHORITY_COMMITTED
                ):
                    raise FederatedProjectionRecoveryError(
                        "committed federated item cannot be rolled back"
                    )
        self._current[snapshot.run_id] = snapshot
        self._history.setdefault(snapshot.run_id, []).append(snapshot)
        return snapshot


ProviderResolver = Callable[[ProjectionRepairPlan], ProjectionRecoveryProvider]
AuthorityResolver = Callable[[ProjectionRepairPlan], Any]
PlanLedgerResolver = Callable[[ProjectionRepairPlan], ProjectionRecoveryLedger]
CompensationResolver = Callable[[ProjectionRepairPlan], Compensation | None]


class FederatedProjectionRecoveryCoordinator:
    """Advance ordered provider repairs until complete or human judgment is required."""

    def __init__(
        self,
        run_id: str,
        plans: tuple[ProjectionRepairPlan, ...],
        *,
        checkpointed_by: str,
        provider_resolver: ProviderResolver,
        authority_resolver: AuthorityResolver,
        ledger: FederatedProjectionRecoveryLedger | None = None,
        plan_ledger_resolver: PlanLedgerResolver | None = None,
        compensation_resolver: CompensationResolver | None = None,
        max_provider_attempts: int = 3,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        try:
            plans = tuple(
                ProjectionRepairPlan.model_validate(plan.model_dump(mode="json")) for plan in plans
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise FederatedProjectionRecoveryError(
                "federated recovery requires sealed repair plans"
            ) from exc
        if len(plans) < 2 or len(plans) > 32:
            raise FederatedProjectionRecoveryError(
                "federated recovery requires between 2 and 32 plans"
            )
        if len({plan.plan_sha256 for plan in plans}) != len(plans):
            raise FederatedProjectionRecoveryError(
                "federated recovery plans must have unique fingerprints"
            )
        tenant_ids = {plan.tenant_id for plan in plans}
        if len(tenant_ids) != 1:
            raise FederatedProjectionRecoveryError(
                "federated recovery cannot cross tenant boundaries"
            )
        if any(plan.action == "fail_closed" for plan in plans):
            raise FederatedProjectionRecoveryError(
                "federated recovery accepts executable sealed plans only"
            )
        if not checkpointed_by.startswith(("human:", "workload:", "agent:")):
            raise FederatedProjectionRecoveryError(
                "federated recovery actor must use a typed subject identity"
            )
        if max_provider_attempts < 1 or max_provider_attempts > 10:
            raise FederatedProjectionRecoveryError(
                "provider attempt budget must be between 1 and 10"
            )
        self.run_id = run_id
        self.plans = plans
        self.checkpointed_by = checkpointed_by
        self.provider_resolver = provider_resolver
        self.authority_resolver = authority_resolver
        self.ledger = ledger or InMemoryFederatedProjectionRecoveryLedger()
        self.plan_ledger_resolver = plan_ledger_resolver
        self.compensation_resolver = compensation_resolver
        self.max_provider_attempts = max_provider_attempts
        self._now = now or (lambda: datetime.now(UTC))
        self._local_plan_ledgers: dict[str, ProjectionRecoveryLedger] = {}

        current = self.ledger.current(run_id)
        if current is None:
            items = tuple(self._pending_item(position, plan) for position, plan in enumerate(plans))
            self._append(
                state=FederatedProjectionRecoveryState.PLANNED,
                next_action="advance",
                current_position=0,
                items=items,
                event_type="planned",
                detail={"plan_count": len(plans)},
            )
        else:
            expected = tuple(plan.plan_sha256 for plan in plans)
            if current.tenant_id != next(iter(tenant_ids)) or current.plan_sha256s != expected:
                raise FederatedProjectionRecoveryError(
                    "federated recovery run identity differs from its sealed plans"
                )
            if plan_ledger_resolver is None and any(
                item.worker_snapshot_sha256 is not None for item in current.items
            ):
                raise FederatedProjectionRecoveryError(
                    "resuming a federated run requires durable per-plan recovery ledgers"
                )

    @property
    def snapshot(self) -> FederatedProjectionRecoverySnapshot:
        snapshot = self.ledger.current(self.run_id)
        if snapshot is None:
            raise FederatedProjectionRecoveryError("federated recovery snapshot is missing")
        return snapshot

    def _now_utc(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise FederatedProjectionRecoveryError(
                "federated recovery clock must return an aware timestamp"
            )
        return value.astimezone(UTC)

    @staticmethod
    def _error_code(error: Exception | str | None) -> str | None:
        if error is None:
            return None
        value = str(error).strip().replace(" ", "_")
        return value[:128] or "unknown_error"

    @staticmethod
    def _pending_item(position: int, plan: ProjectionRepairPlan) -> FederatedProjectionItemSnapshot:
        values = {
            "position": position,
            "projection_id": plan.projection_id,
            "target_engine": plan.target_engine.value,
            "target_ref": plan.target_ref,
            "plan_sha256": plan.plan_sha256,
            "plan_idempotency_key": plan.plan_idempotency_key,
            "state": FederatedProjectionItemState.PENDING,
            "worker_state": None,
            "worker_next_action": None,
            "provider_attempts": 0,
            "authority_attempts": 0,
            "provider_commit_ref": None,
            "checkpoint_sha256": None,
            "worker_snapshot_sha256": None,
            "last_error_code": None,
        }
        return FederatedProjectionItemSnapshot(
            **values,
            item_sha256=federated_projection_item_fingerprint(**values),
        )

    @staticmethod
    def _item_from_worker(
        item: FederatedProjectionItemSnapshot,
        result: ProjectionRecoveryWorkerResult,
    ) -> FederatedProjectionItemSnapshot:
        worker = result.snapshot
        if worker.state is ProjectionRecoveryState.AUTHORITY_COMMITTED:
            state = FederatedProjectionItemState.AUTHORITY_COMMITTED
        elif worker.state is ProjectionRecoveryState.COMPENSATION_REQUIRED or (
            worker.state is ProjectionRecoveryState.RECONCILIATION_REQUIRED
            and worker.next_action == "manual_compensation"
        ):
            state = FederatedProjectionItemState.COMPENSATION_REQUIRED
        elif worker.state is ProjectionRecoveryState.RECONCILIATION_REQUIRED:
            state = FederatedProjectionItemState.RECOVERY_REQUIRED
        elif worker.state is ProjectionRecoveryState.FAILED_CLOSED:
            state = FederatedProjectionItemState.FAILED_CLOSED
        else:
            state = FederatedProjectionItemState.RUNNING
        values = {
            "position": item.position,
            "projection_id": item.projection_id,
            "target_engine": item.target_engine,
            "target_ref": item.target_ref,
            "plan_sha256": item.plan_sha256,
            "plan_idempotency_key": item.plan_idempotency_key,
            "state": state,
            "worker_state": worker.state,
            "worker_next_action": worker.next_action,
            "provider_attempts": worker.provider_attempts,
            "authority_attempts": worker.authority_attempts,
            "provider_commit_ref": worker.provider_commit_ref,
            "checkpoint_sha256": worker.checkpoint_sha256,
            "worker_snapshot_sha256": worker.snapshot_sha256,
            "last_error_code": result.error_code or worker.last_error_code,
        }
        return FederatedProjectionItemSnapshot(
            **values,
            item_sha256=federated_projection_item_fingerprint(**values),
        )

    @staticmethod
    def _replace_item(
        items: tuple[FederatedProjectionItemSnapshot, ...],
        replacement: FederatedProjectionItemSnapshot,
    ) -> tuple[FederatedProjectionItemSnapshot, ...]:
        return tuple(
            replacement if item.position == replacement.position else item for item in items
        )

    def _append(
        self,
        *,
        state: FederatedProjectionRecoveryState,
        next_action: FederatedNextAction,
        current_position: int,
        items: tuple[FederatedProjectionItemSnapshot, ...],
        event_type: str,
        detail: dict[str, Any],
        error: Exception | str | None = None,
    ) -> FederatedProjectionRecoverySnapshot:
        previous = self.ledger.current(self.run_id)
        event_values = {
            "sequence": len(previous.events) + 1 if previous else 1,
            "event_type": event_type,
            "occurred_at": self._now_utc(),
            "detail": detail,
        }
        event = FederatedProjectionRecoveryEvent(
            **event_values,
            event_sha256=federated_projection_event_fingerprint(**event_values),
        )
        events = previous.events + (event,) if previous else (event,)
        committed = tuple(
            item.plan_sha256
            for item in items
            if item.state is FederatedProjectionItemState.AUTHORITY_COMMITTED
        )
        values = {
            "run_id": self.run_id,
            "tenant_id": self.plans[0].tenant_id,
            "state": state,
            "next_action": next_action,
            "current_position": current_position,
            "plan_sha256s": tuple(plan.plan_sha256 for plan in self.plans),
            "items": items,
            "committed_plan_sha256s": committed,
            "last_error_code": self._error_code(error)
            if error is not None
            else (previous.last_error_code if previous else None),
            "events": events,
        }
        snapshot = FederatedProjectionRecoverySnapshot(
            **values,
            snapshot_sha256=federated_projection_snapshot_fingerprint(**values),
        )
        return self.ledger.append(snapshot)

    def _plan_ledger(self, plan: ProjectionRepairPlan) -> ProjectionRecoveryLedger:
        if self.plan_ledger_resolver is not None:
            ledger = self.plan_ledger_resolver(plan)
        else:
            ledger = self._local_plan_ledgers.setdefault(
                plan.plan_sha256, InMemoryProjectionRecoveryLedger()
            )
        return ledger

    def _assert_worker_snapshot(
        self,
        item: FederatedProjectionItemSnapshot,
        ledger: ProjectionRecoveryLedger,
    ) -> None:
        if item.worker_snapshot_sha256 is None:
            return
        current = ledger.current(item.plan_sha256)
        if current is None or current.snapshot_sha256 != item.worker_snapshot_sha256:
            raise FederatedProjectionRecoveryError(
                "federated item differs from its per-plan recovery ledger"
            )

    def _worker(
        self,
        plan: ProjectionRepairPlan,
        item: FederatedProjectionItemSnapshot,
    ) -> ProjectionRecoveryWorker:
        plan_ledger = self._plan_ledger(plan)
        self._assert_worker_snapshot(item, plan_ledger)
        compensation = (
            self.compensation_resolver(plan) if self.compensation_resolver is not None else None
        )
        return ProjectionRecoveryWorker(
            plan,
            checkpointed_by=self.checkpointed_by,
            provider=self.provider_resolver(plan),
            authority=self.authority_resolver(plan),
            ledger=plan_ledger,
            compensation=compensation,
            now=self._now,
        )

    def advance(self, *, max_steps_per_item: int = 8) -> FederatedProjectionRecoverySnapshot:
        """Advance until all plans commit, a budget yields, or human input is required."""
        if max_steps_per_item < 1 or max_steps_per_item > 100:
            raise FederatedProjectionRecoveryError(
                "federated recovery step budget must be between 1 and 100"
            )
        snapshot = self.snapshot
        if snapshot.state in {
            FederatedProjectionRecoveryState.COMPLETED,
            FederatedProjectionRecoveryState.COMPENSATION_REQUIRED,
            FederatedProjectionRecoveryState.FAILED_CLOSED,
        }:
            return snapshot
        if snapshot.state is FederatedProjectionRecoveryState.PLANNED:
            snapshot = self._append(
                state=FederatedProjectionRecoveryState.RUNNING,
                next_action="advance",
                current_position=0,
                items=snapshot.items,
                event_type="run_started",
                detail={},
            )

        while snapshot.current_position < len(self.plans):
            position = snapshot.current_position
            plan = self.plans[position]
            item = snapshot.items[position]
            if item.state is FederatedProjectionItemState.PENDING:
                item_values = item.model_dump(mode="json", exclude={"item_sha256"})
                item_values["state"] = FederatedProjectionItemState.RUNNING
                item = FederatedProjectionItemSnapshot(
                    **item_values,
                    item_sha256=federated_projection_item_fingerprint(**item_values),
                )
                items = self._replace_item(snapshot.items, item)
                snapshot = self._append(
                    state=FederatedProjectionRecoveryState.RUNNING,
                    next_action="advance",
                    current_position=position,
                    items=items,
                    event_type="item_started",
                    detail={"position": position, "plan_sha256": plan.plan_sha256},
                )

            try:
                worker = self._worker(plan, item)
            except Exception as exc:
                failed_values = item.model_dump(mode="json", exclude={"item_sha256"})
                failed_values.update(
                    {
                        "state": FederatedProjectionItemState.FAILED_CLOSED,
                        "last_error_code": self._error_code(exc),
                    }
                )
                failed_item = FederatedProjectionItemSnapshot(
                    **failed_values,
                    item_sha256=federated_projection_item_fingerprint(**failed_values),
                )
                return self._append(
                    state=FederatedProjectionRecoveryState.FAILED_CLOSED,
                    next_action="await_operator",
                    current_position=position,
                    items=self._replace_item(snapshot.items, failed_item),
                    event_type="run_failed_closed",
                    detail={"position": position, "phase": "worker_resolution"},
                    error=exc,
                )

            for _ in range(max_steps_per_item):
                try:
                    result = worker.run_once()
                except Exception as exc:
                    failed_values = item.model_dump(mode="json", exclude={"item_sha256"})
                    failed_values.update(
                        {
                            "state": FederatedProjectionItemState.FAILED_CLOSED,
                            "last_error_code": self._error_code(exc),
                        }
                    )
                    failed_item = FederatedProjectionItemSnapshot(
                        **failed_values,
                        item_sha256=federated_projection_item_fingerprint(**failed_values),
                    )
                    return self._append(
                        state=FederatedProjectionRecoveryState.FAILED_CLOSED,
                        next_action="await_operator",
                        current_position=position,
                        items=self._replace_item(snapshot.items, failed_item),
                        event_type="run_failed_closed",
                        detail={"position": position, "phase": "worker_execution"},
                        error=exc,
                    )
                item = self._item_from_worker(item, result)
                items = self._replace_item(snapshot.items, item)
                snapshot = self._append(
                    state=FederatedProjectionRecoveryState.RUNNING,
                    next_action="retry_item",
                    current_position=position,
                    items=items,
                    event_type="item_progressed",
                    detail={
                        "position": position,
                        "worker_state": result.snapshot.state.value,
                        "worker_action": result.action_taken,
                    },
                    error=result.error_code or result.snapshot.last_error_code,
                )
                if item.state is FederatedProjectionItemState.AUTHORITY_COMMITTED:
                    next_position = position + 1
                    snapshot = self._append(
                        state=FederatedProjectionRecoveryState.RUNNING,
                        next_action="advance",
                        current_position=next_position,
                        items=snapshot.items,
                        event_type="item_committed",
                        detail={
                            "position": position,
                            "checkpoint_sha256": item.checkpoint_sha256,
                        },
                    )
                    break
                if (
                    item.state
                    in {
                        FederatedProjectionItemState.RECOVERY_REQUIRED,
                        FederatedProjectionItemState.COMPENSATION_REQUIRED,
                    }
                    and result.action_taken == "await_operator"
                ):
                    return self._append(
                        state=FederatedProjectionRecoveryState.COMPENSATION_REQUIRED,
                        next_action="await_operator",
                        current_position=position,
                        items=snapshot.items,
                        event_type="item_blocked",
                        detail={
                            "position": position,
                            "committed_plan_sha256s": snapshot.committed_plan_sha256s,
                        },
                        error=result.error_code or result.snapshot.last_error_code,
                    )
                if (
                    result.snapshot.state is ProjectionRecoveryState.PROVIDER_FAILED
                    and result.snapshot.provider_attempts >= self.max_provider_attempts
                ):
                    failed_values = item.model_dump(mode="json", exclude={"item_sha256"})
                    failed_values["state"] = FederatedProjectionItemState.FAILED_CLOSED
                    failed_item = FederatedProjectionItemSnapshot(
                        **failed_values,
                        item_sha256=federated_projection_item_fingerprint(**failed_values),
                    )
                    return self._append(
                        state=FederatedProjectionRecoveryState.FAILED_CLOSED,
                        next_action="await_operator",
                        current_position=position,
                        items=self._replace_item(snapshot.items, failed_item),
                        event_type="run_failed_closed",
                        detail={
                            "position": position,
                            "reason": "provider_attempt_budget_exhausted",
                        },
                        error=result.error_code or result.snapshot.last_error_code,
                    )
            else:
                return self._append(
                    state=FederatedProjectionRecoveryState.RUNNING,
                    next_action="retry_item",
                    current_position=position,
                    items=snapshot.items,
                    event_type="run_yielded",
                    detail={"position": position, "step_budget": max_steps_per_item},
                )

        return self._append(
            state=FederatedProjectionRecoveryState.COMPLETED,
            next_action="none",
            current_position=len(self.plans),
            items=snapshot.items,
            event_type="run_completed",
            detail={"committed_plan_count": len(snapshot.committed_plan_sha256s)},
        )


__all__ = [
    "FederatedProjectionItemSnapshot",
    "FederatedProjectionItemState",
    "FederatedProjectionRecoveryCoordinator",
    "FederatedProjectionRecoveryError",
    "FederatedProjectionRecoveryEvent",
    "FederatedProjectionRecoveryLedger",
    "FederatedProjectionRecoverySnapshot",
    "FederatedProjectionRecoveryState",
    "InMemoryFederatedProjectionRecoveryLedger",
    "federated_projection_event_fingerprint",
    "federated_projection_item_fingerprint",
    "federated_projection_snapshot_fingerprint",
]
