"""Bind the durable projection recovery job to the cross-store controller.

The projection recovery ledger records provider/checkpoint state.  The
cross-store controller records the broader recovery run and its admitted
control/object binding.  This adapter keeps those responsibilities separate
while making the provider boundary fail closed when controller evidence is
missing or stale.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .cross_store_projection_recovery import (
    ProjectionRecoverySnapshot,
    ProjectionRecoveryState,
)
from .platform_runtime.cross_store_recovery_admission import CrossStoreRecoveryAdmission
from .platform_runtime.cross_store_recovery_controller import (
    CrossStoreRecoveryController,
    CrossStoreRecoveryControllerError,
    CrossStoreRecoveryControllerSnapshot,
    CrossStoreRecoveryRunState,
)


class ProjectionRecoveryControllerBindingError(RuntimeError):
    """Controller evidence cannot authorize the projection recovery action."""

    code = "projection_recovery_controller_binding_error"


class ProjectionRecoveryControllerBinding(Protocol):
    controller: CrossStoreRecoveryController
    admission: CrossStoreRecoveryAdmission


@dataclass(frozen=True)
class StaticProjectionRecoveryControllerBinding:
    """A job-bound controller and its already-validated admission evidence."""

    controller: CrossStoreRecoveryController
    admission: CrossStoreRecoveryAdmission


ControllerBindingResolver = Callable[[Any], ProjectionRecoveryControllerBinding]


class ProjectionRecoveryControllerGuard:
    """Apply controller admission and settlement around one worker action."""

    def __init__(
        self,
        binding: ProjectionRecoveryControllerBinding,
        *,
        tenant_id: str | None = None,
    ):
        self.binding = binding
        self.controller = binding.controller
        self.admission = binding.admission
        if tenant_id is not None and tenant_id not in self.admission.binding.tenant_ids:
            raise ProjectionRecoveryControllerBindingError(
                "projection recovery tenant is outside the admitted controller binding"
            )

    @property
    def snapshot(self) -> CrossStoreRecoveryControllerSnapshot:
        return self.controller.snapshot

    def admit_before_execution(self, recovery_snapshot: ProjectionRecoverySnapshot | None) -> None:
        current = self.controller.snapshot
        if current.state is CrossStoreRecoveryRunState.PLANNED:
            try:
                current = self.controller.admit(self.admission)
            except CrossStoreRecoveryControllerError as exc:
                self._fail_closed(f"admission_rejected:{exc}")
                raise ProjectionRecoveryControllerBindingError(
                    "cross-store recovery controller admission was rejected"
                ) from exc
        if current.state is CrossStoreRecoveryRunState.FAILED_CLOSED:
            raise ProjectionRecoveryControllerBindingError(
                "cross-store recovery controller is failed closed"
            )
        if current.state is CrossStoreRecoveryRunState.COMPLETED:
            if (
                recovery_snapshot is None
                or recovery_snapshot.state
                is not ProjectionRecoveryState.AUTHORITY_COMMITTED
            ):
                raise ProjectionRecoveryControllerBindingError(
                    "completed controller has no matching projection recovery evidence"
                )
            return
        if current.state is CrossStoreRecoveryRunState.RECONCILIATION_REQUIRED and (
            recovery_snapshot is None
            or recovery_snapshot.next_action == "execute_provider"
        ):
            raise ProjectionRecoveryControllerBindingError(
                "controller reconciliation is required before provider execution"
            )

    def settle(self, recovery_snapshot: ProjectionRecoverySnapshot) -> None:
        if recovery_snapshot.state is ProjectionRecoveryState.AUTHORITY_COMMITTED:
            current = self.controller.snapshot
            try:
                if current.state is CrossStoreRecoveryRunState.RECONCILIATION_REQUIRED:
                    self.controller.reconcile(self.admission)
                self.controller.complete(self.admission)
            except CrossStoreRecoveryControllerError as exc:
                self._fail_closed(f"completion_rejected:{exc}")
                raise ProjectionRecoveryControllerBindingError(
                    "cross-store recovery controller completion was rejected"
                ) from exc
            return
        if recovery_snapshot.state in {
            ProjectionRecoveryState.RECONCILIATION_REQUIRED,
            ProjectionRecoveryState.COMPENSATION_REQUIRED,
        }:
            current = self.controller.snapshot
            if current.state is CrossStoreRecoveryRunState.ADMITTED:
                try:
                    self.controller.require_reconciliation(
                        recovery_snapshot.last_error_code or recovery_snapshot.next_action
                    )
                except CrossStoreRecoveryControllerError as exc:
                    self._fail_closed(f"reconciliation_rejected:{exc}")
                    raise ProjectionRecoveryControllerBindingError(
                        "cross-store recovery controller could not require reconciliation"
                    ) from exc
            return
        if recovery_snapshot.state is ProjectionRecoveryState.FAILED_CLOSED:
            self._fail_closed(
                recovery_snapshot.last_error_code
                or "projection_recovery_failed_closed"
            )

    def fail_closed(self, reason: str) -> None:
        self._fail_closed(reason)

    def _fail_closed(self, reason: str) -> None:
        current = self.controller.snapshot
        if current.state in {
            CrossStoreRecoveryRunState.COMPLETED,
            CrossStoreRecoveryRunState.FAILED_CLOSED,
        }:
            return
        try:
            self.controller.fail_closed(reason)
        except CrossStoreRecoveryControllerError as exc:
            raise ProjectionRecoveryControllerBindingError(
                "cross-store recovery controller could not fail closed"
            ) from exc


__all__ = [
    "ControllerBindingResolver",
    "ProjectionRecoveryControllerBinding",
    "ProjectionRecoveryControllerBindingError",
    "ProjectionRecoveryControllerGuard",
    "StaticProjectionRecoveryControllerBinding",
]
