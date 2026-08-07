"""Thin PostgreSQL outbox consumer for DolphinScheduler provider commands."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .dolphinscheduler_adapter import (
    DolphinSchedulerAdapter,
    DolphinSchedulerContractError,
    DolphinSchedulerError,
    DolphinSchedulerReconciliationRequired,
)
from .platform_contracts import (
    TERMINAL_RUN_STATUSES,
    PlatformCommand,
    PlatformCommandStatus,
    PlatformCommandType,
)
from .platform_gateway import PlatformGateway, PlatformGatewayError


@dataclass(frozen=True)
class CommandBatchResult:
    claimed: int
    completed: int
    deferred_to_reconcile: int
    retry_pending: int
    failed: int
    command_ids: tuple[UUID, ...]


class DolphinSchedulerCommandConsumer:
    """Deliver commands at least once without owning provider or Run state."""

    def __init__(
        self,
        adapter: DolphinSchedulerAdapter,
        *,
        gateway: PlatformGateway | None = None,
    ):
        self.adapter = adapter
        self.gateway = gateway or adapter.gateway

    @staticmethod
    def _retry_delay(command: PlatformCommand) -> int:
        return min(3600, 30 * (2 ** max(0, command.attempt_count - 1)))

    def _deliver(self, command: PlatformCommand) -> bool:
        if command.actor_subject != self.adapter.profile.workload_subject:
            raise DolphinSchedulerContractError(
                "command actor does not match consumer workload identity"
            )
        if command.command_type == PlatformCommandType.DOLPHINSCHEDULER_DISPATCH:
            self.adapter.dispatch(
                command.tenant_id,
                command.run_id,
                command.execution_plan_artifact_id,
                actor_subject=command.actor_subject,
                attempt_no=command.attempt_count,
            )
            return False
        if command.command_type == PlatformCommandType.DOLPHINSCHEDULER_RECONCILE:
            run = self.gateway.get_run(command.tenant_id, command.run_id)
            if run.status in TERMINAL_RUN_STATUSES:
                return False
            self.adapter.reconcile(
                command.tenant_id,
                command.run_id,
                command.execution_plan_artifact_id,
                actor_subject=command.actor_subject,
                attempt_no=command.attempt_count,
            )
            return False
        if command.command_type == PlatformCommandType.DOLPHINSCHEDULER_CANCEL:
            run = self.gateway.get_run(command.tenant_id, command.run_id)
            if run.status in TERMINAL_RUN_STATUSES:
                return False
            raw_policy_id = command.payload.get("policy_decision_artifact_id")
            try:
                policy_decision_artifact_id = UUID(str(raw_policy_id))
            except (TypeError, ValueError) as exc:
                raise DolphinSchedulerContractError(
                    "cancel command has no valid policy decision artifact"
                ) from exc
            self.adapter.cancel(
                command.tenant_id,
                command.run_id,
                command.execution_plan_artifact_id,
                actor_subject=command.actor_subject,
                policy_decision_artifact_id=policy_decision_artifact_id,
            )
            return True
        raise DolphinSchedulerContractError("unsupported platform command type")

    def run_once(
        self,
        tenant_id: str,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> CommandBatchResult:
        commands = self.gateway.claim_commands(
            tenant_id,
            worker_id,
            actor_subject=self.adapter.profile.workload_subject,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        completed = 0
        deferred = 0
        retry_pending = 0
        failed = 0
        for command in commands:
            try:
                enqueue_reconcile = self._deliver(command)
            except DolphinSchedulerReconciliationRequired:
                if command.command_type == PlatformCommandType.DOLPHINSCHEDULER_DISPATCH:
                    self.gateway.defer_dispatch_to_reconcile(
                        command,
                        worker_id=worker_id,
                    )
                    deferred += 1
                    continue
                result = self.gateway.fail_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                    error="provider reconciliation is still required",
                    retry_delay_seconds=self._retry_delay(command),
                )
            except (DolphinSchedulerError, PlatformGatewayError) as exc:
                result = self.gateway.fail_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_delay_seconds=self._retry_delay(command),
                )
            else:
                if enqueue_reconcile:
                    self.gateway.complete_cancel_and_enqueue_reconcile(
                        command,
                        worker_id=worker_id,
                    )
                    deferred += 1
                else:
                    self.gateway.complete_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                    )
                completed += 1
                continue
            if result.status == PlatformCommandStatus.FAILED:
                failed += 1
            else:
                retry_pending += 1
        return CommandBatchResult(
            claimed=len(commands),
            completed=completed,
            deferred_to_reconcile=deferred,
            retry_pending=retry_pending,
            failed=failed,
            command_ids=tuple(command.command_id for command in commands),
        )
