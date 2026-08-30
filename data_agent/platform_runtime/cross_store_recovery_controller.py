"""Fail-closed controller contract for one admitted cross-store recovery run.

This module owns recovery coordination state, not provider commits.  A future
durable repository can implement the same append/current/history protocol.  The
controller never marks a run complete without the exact durable binding that
was admitted for every covered tenant.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from ..platform_contracts import canonical_json_fingerprint
from .cross_store_recovery_admission import CrossStoreRecoveryAdmission


class CrossStoreRecoveryControllerError(RuntimeError):
    """A recovery state transition or evidence check was rejected."""


class CrossStoreRecoveryRunState(StrEnum):
    PLANNED = "planned"
    ADMITTED = "admitted"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    COMPLETED = "completed"
    FAILED_CLOSED = "failed_closed"


RecoveryNextAction = Literal[
    "await_admission",
    "reconcile_stores",
    "complete",
    "await_operator",
    "none",
]


def _json_ready(value: Any) -> Any:
    if hasattr(value, "as_dict") and callable(value.as_dict):
        return _json_ready(value.as_dict())
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def recovery_controller_event_fingerprint(**values: Any) -> str:
    return canonical_json_fingerprint(
        {"schema": "gda.cross_store_recovery_controller_event.v1", "data": _json_ready(values)}
    )


def recovery_controller_snapshot_fingerprint(**values: Any) -> str:
    values = dict(values)
    values.pop("snapshot_sha256", None)
    return canonical_json_fingerprint(
        {
            "schema": "gda.cross_store_recovery_controller_snapshot.v1",
            "data": _json_ready(values),
        }
    )


@dataclass(frozen=True)
class CrossStoreRecoveryControllerEvent:
    sequence: int
    event_type: Literal[
        "planned",
        "admitted",
        "reconciliation_required",
        "reconciled",
        "completed",
        "failed_closed",
    ]
    occurred_at: datetime
    detail: dict[str, Any]
    event_sha256: str

    def validate(self) -> None:
        if self.sequence < 1:
            raise CrossStoreRecoveryControllerError("controller event sequence must be positive")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise CrossStoreRecoveryControllerError(
                "controller event timestamp must be timezone-aware"
            )
        expected = recovery_controller_event_fingerprint(
            sequence=self.sequence,
            event_type=self.event_type,
            occurred_at=self.occurred_at,
            detail=self.detail,
        )
        if self.event_sha256 != expected:
            raise CrossStoreRecoveryControllerError("controller event fingerprint is invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "detail": self.detail,
            "event_sha256": self.event_sha256,
        }


@dataclass(frozen=True)
class CrossStoreRecoveryControllerSnapshot:
    run_id: str
    state: CrossStoreRecoveryRunState
    next_action: RecoveryNextAction
    tenant_ids: tuple[str, ...]
    binding_sha256: str | None
    events: tuple[CrossStoreRecoveryControllerEvent, ...]
    snapshot_sha256: str

    def validate(self) -> None:
        if not self.run_id.strip():
            raise CrossStoreRecoveryControllerError("controller run_id is required")
        if tuple(sorted(set(self.tenant_ids))) != self.tenant_ids:
            raise CrossStoreRecoveryControllerError(
                "controller tenant ids must be sorted and unique"
            )
        if tuple(event.sequence for event in self.events) != tuple(range(1, len(self.events) + 1)):
            raise CrossStoreRecoveryControllerError("controller event sequence is not contiguous")
        for event in self.events:
            event.validate()
        if not self.events:
            raise CrossStoreRecoveryControllerError("controller snapshot requires an event")
        if self.state is CrossStoreRecoveryRunState.PLANNED and (
            self.tenant_ids
            or self.binding_sha256 is not None
            or self.next_action != "await_admission"
        ):
            raise CrossStoreRecoveryControllerError(
                "planned controller snapshot has admission evidence"
            )
        if self.state is CrossStoreRecoveryRunState.ADMITTED and (
            self.binding_sha256 is None or self.next_action != "complete"
        ):
            raise CrossStoreRecoveryControllerError(
                "admitted controller snapshot lacks binding evidence"
            )
        if self.state is CrossStoreRecoveryRunState.RECONCILIATION_REQUIRED and (
            self.binding_sha256 is None or self.next_action != "reconcile_stores"
        ):
            raise CrossStoreRecoveryControllerError(
                "reconciliation snapshot lacks binding evidence"
            )
        if self.state is CrossStoreRecoveryRunState.COMPLETED and (
            self.binding_sha256 is None or self.next_action != "none"
        ):
            raise CrossStoreRecoveryControllerError(
                "completed controller snapshot lacks terminal evidence"
            )
        if (
            self.state is CrossStoreRecoveryRunState.FAILED_CLOSED
            and self.next_action != "await_operator"
        ):
            raise CrossStoreRecoveryControllerError(
                "failed-closed controller snapshot lacks operator action"
            )
        expected = recovery_controller_snapshot_fingerprint(
            run_id=self.run_id,
            state=self.state,
            next_action=self.next_action,
            tenant_ids=self.tenant_ids,
            binding_sha256=self.binding_sha256,
            events=self.events,
        )
        if self.snapshot_sha256 != expected:
            raise CrossStoreRecoveryControllerError("controller snapshot fingerprint is invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "next_action": self.next_action,
            "tenant_ids": list(self.tenant_ids),
            "binding_sha256": self.binding_sha256,
            "events": [event.as_dict() for event in self.events],
            "snapshot_sha256": self.snapshot_sha256,
        }


class CrossStoreRecoveryControllerLedger(Protocol):
    def current(self, run_id: str) -> CrossStoreRecoveryControllerSnapshot | None: ...

    def append(
        self, snapshot: CrossStoreRecoveryControllerSnapshot
    ) -> CrossStoreRecoveryControllerSnapshot: ...

    def history(self, run_id: str) -> tuple[CrossStoreRecoveryControllerSnapshot, ...]: ...


class InMemoryCrossStoreRecoveryControllerLedger:
    """Contract ledger for tests and local rehearsal only."""

    def __init__(self) -> None:
        self._current: dict[str, CrossStoreRecoveryControllerSnapshot] = {}
        self._history: dict[str, list[CrossStoreRecoveryControllerSnapshot]] = {}

    def current(self, run_id: str) -> CrossStoreRecoveryControllerSnapshot | None:
        return self._current.get(run_id)

    def history(self, run_id: str) -> tuple[CrossStoreRecoveryControllerSnapshot, ...]:
        return tuple(self._history.get(run_id, ()))

    def append(self, snapshot: CrossStoreRecoveryControllerSnapshot):
        snapshot.validate()
        current = self._current.get(snapshot.run_id)
        if current is not None:
            if current.snapshot_sha256 == snapshot.snapshot_sha256:
                return current
            if snapshot.events[: len(current.events)] != current.events:
                raise CrossStoreRecoveryControllerError("controller history is not append-only")
        self._current[snapshot.run_id] = snapshot
        self._history.setdefault(snapshot.run_id, []).append(snapshot)
        return snapshot


def _binding_evidence(admission: CrossStoreRecoveryAdmission) -> tuple[str, tuple[str, ...]]:
    binding = admission.binding
    if tuple(admission.persisted_tenant_ids) != binding.tenant_ids:
        raise CrossStoreRecoveryControllerError("admission did not persist every binding tenant")
    binding.validate()
    return binding.binding_sha256, binding.tenant_ids


class CrossStoreRecoveryController:
    """Drive deterministic recovery coordination around one admission."""

    def __init__(
        self,
        run_id: str,
        *,
        ledger: CrossStoreRecoveryControllerLedger | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(run_id, str) or not run_id.strip():
            raise CrossStoreRecoveryControllerError("controller run_id is required")
        self.run_id = run_id.strip()
        self.ledger = ledger or InMemoryCrossStoreRecoveryControllerLedger()
        self._now = now or (lambda: datetime.now(UTC))
        if self.ledger.current(self.run_id) is None:
            self._append(
                state=CrossStoreRecoveryRunState.PLANNED,
                next_action="await_admission",
                tenant_ids=(),
                binding_sha256=None,
                event_type="planned",
                detail={},
            )

    @property
    def snapshot(self) -> CrossStoreRecoveryControllerSnapshot:
        snapshot = self.ledger.current(self.run_id)
        if snapshot is None:
            raise CrossStoreRecoveryControllerError("controller snapshot is missing")
        return snapshot

    def _append(
        self,
        *,
        state: CrossStoreRecoveryRunState,
        next_action: RecoveryNextAction,
        tenant_ids: tuple[str, ...],
        binding_sha256: str | None,
        event_type: Any,
        detail: dict[str, Any],
    ) -> CrossStoreRecoveryControllerSnapshot:
        current = self.ledger.current(self.run_id)
        sequence = len(current.events) + 1 if current else 1
        occurred_at = self._now()
        event_values = {
            "sequence": sequence,
            "event_type": event_type,
            "occurred_at": occurred_at,
            "detail": detail,
        }
        event = CrossStoreRecoveryControllerEvent(
            **event_values,
            event_sha256=recovery_controller_event_fingerprint(**event_values),
        )
        events = (*current.events, event) if current else (event,)
        values = {
            "run_id": self.run_id,
            "state": state,
            "next_action": next_action,
            "tenant_ids": tuple(sorted(tenant_ids)),
            "binding_sha256": binding_sha256,
            "events": events,
        }
        snapshot = CrossStoreRecoveryControllerSnapshot(
            **values,
            snapshot_sha256=recovery_controller_snapshot_fingerprint(**values),
        )
        return self.ledger.append(snapshot)

    def admit(self, admission: CrossStoreRecoveryAdmission) -> CrossStoreRecoveryControllerSnapshot:
        binding_sha256, tenant_ids = _binding_evidence(admission)
        current = self.snapshot
        if current.state is CrossStoreRecoveryRunState.ADMITTED:
            if current.binding_sha256 == binding_sha256:
                return current
            raise CrossStoreRecoveryControllerError("controller admission evidence differs")
        if current.state is not CrossStoreRecoveryRunState.PLANNED:
            raise CrossStoreRecoveryControllerError("controller cannot admit from current state")
        return self._append(
            state=CrossStoreRecoveryRunState.ADMITTED,
            next_action="complete",
            tenant_ids=tenant_ids,
            binding_sha256=binding_sha256,
            event_type="admitted",
            detail={"binding_sha256": binding_sha256},
        )

    def require_reconciliation(self, reason: str) -> CrossStoreRecoveryControllerSnapshot:
        if not isinstance(reason, str) or not reason.strip():
            raise CrossStoreRecoveryControllerError("reconciliation reason is required")
        current = self.snapshot
        if current.state is CrossStoreRecoveryRunState.RECONCILIATION_REQUIRED:
            return current
        if current.state is not CrossStoreRecoveryRunState.ADMITTED:
            raise CrossStoreRecoveryControllerError(
                "controller cannot require reconciliation from current state"
            )
        return self._append(
            state=CrossStoreRecoveryRunState.RECONCILIATION_REQUIRED,
            next_action="reconcile_stores",
            tenant_ids=current.tenant_ids,
            binding_sha256=current.binding_sha256,
            event_type="reconciliation_required",
            detail={"reason": reason.strip()},
        )

    def reconcile(
        self, admission: CrossStoreRecoveryAdmission
    ) -> CrossStoreRecoveryControllerSnapshot:
        binding_sha256, tenant_ids = _binding_evidence(admission)
        current = self.snapshot
        if current.state is not CrossStoreRecoveryRunState.RECONCILIATION_REQUIRED:
            raise CrossStoreRecoveryControllerError("controller is not awaiting reconciliation")
        if current.binding_sha256 != binding_sha256 or current.tenant_ids != tenant_ids:
            raise CrossStoreRecoveryControllerError("reconciliation binding evidence differs")
        return self._append(
            state=CrossStoreRecoveryRunState.ADMITTED,
            next_action="complete",
            tenant_ids=tenant_ids,
            binding_sha256=binding_sha256,
            event_type="reconciled",
            detail={"binding_sha256": binding_sha256},
        )

    def complete(
        self, admission: CrossStoreRecoveryAdmission
    ) -> CrossStoreRecoveryControllerSnapshot:
        binding_sha256, tenant_ids = _binding_evidence(admission)
        current = self.snapshot
        if current.state is CrossStoreRecoveryRunState.COMPLETED:
            if current.binding_sha256 == binding_sha256:
                return current
            raise CrossStoreRecoveryControllerError("completed controller evidence differs")
        if current.state is not CrossStoreRecoveryRunState.ADMITTED:
            raise CrossStoreRecoveryControllerError("controller cannot complete from current state")
        if current.binding_sha256 != binding_sha256 or current.tenant_ids != tenant_ids:
            raise CrossStoreRecoveryControllerError("completion binding evidence differs")
        return self._append(
            state=CrossStoreRecoveryRunState.COMPLETED,
            next_action="none",
            tenant_ids=tenant_ids,
            binding_sha256=binding_sha256,
            event_type="completed",
            detail={"binding_sha256": binding_sha256},
        )

    def fail_closed(self, reason: str) -> CrossStoreRecoveryControllerSnapshot:
        if not isinstance(reason, str) or not reason.strip():
            raise CrossStoreRecoveryControllerError("failed-closed reason is required")
        current = self.snapshot
        if current.state is CrossStoreRecoveryRunState.FAILED_CLOSED:
            return current
        if current.state is CrossStoreRecoveryRunState.COMPLETED:
            raise CrossStoreRecoveryControllerError("completed controller cannot be failed closed")
        return self._append(
            state=CrossStoreRecoveryRunState.FAILED_CLOSED,
            next_action="await_operator",
            tenant_ids=current.tenant_ids,
            binding_sha256=current.binding_sha256,
            event_type="failed_closed",
            detail={"reason": reason.strip()},
        )


__all__ = [
    "CrossStoreRecoveryController",
    "CrossStoreRecoveryControllerError",
    "CrossStoreRecoveryControllerEvent",
    "CrossStoreRecoveryControllerLedger",
    "CrossStoreRecoveryControllerSnapshot",
    "CrossStoreRecoveryRunState",
    "InMemoryCrossStoreRecoveryControllerLedger",
    "recovery_controller_event_fingerprint",
    "recovery_controller_snapshot_fingerprint",
]
