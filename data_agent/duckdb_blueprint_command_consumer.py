"""Recoverable outbox delivery for governed DuckDB Blueprint executions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .duckdb_blueprint_provider import (
    DUCKDB_BLUEPRINT_WORKLOAD,
    DuckDBBlueprintExecutionRequest,
    DuckDBBlueprintProvider,
)
from .platform_contracts import (
    TERMINAL_RUN_STATUSES,
    PlatformCommand,
    PlatformCommandStatus,
    PlatformCommandType,
    RunStatus,
)
from .platform_gateway import PlatformGateway, PlatformGatewayError


class DuckDBBlueprintCommandContractError(RuntimeError):
    """A claimed command is not an exact DuckDB Blueprint execution binding."""


@dataclass(frozen=True)
class DuckDBBlueprintCommandBatchResult:
    claimed: int
    completed: int
    execution_succeeded: int
    execution_failed: int
    terminal_reconciled: int
    retry_pending: int
    failed: int
    command_ids: tuple[UUID, ...]


class DuckDBBlueprintCommandConsumer:
    """Consume shared outbox commands without becoming Run authority."""

    def __init__(
        self,
        *,
        gateway: PlatformGateway,
        provider: DuckDBBlueprintProvider | None = None,
        retry_delay_seconds: int = 30,
    ):
        if not 0 <= retry_delay_seconds <= 86_400:
            raise ValueError("retry_delay_seconds must be between 0 and 86400")
        self.gateway = gateway
        self.provider = provider or DuckDBBlueprintProvider()
        self.retry_delay_seconds = retry_delay_seconds

    @staticmethod
    def _validate_command(command: PlatformCommand) -> None:
        if command.actor_subject != DUCKDB_BLUEPRINT_WORKLOAD:
            raise DuckDBBlueprintCommandContractError(
                "DuckDB Blueprint command actor does not match the provider workload"
            )
        if command.command_type is PlatformCommandType.BLUEPRINT_PROVIDER_EXECUTE:
            expected_schema = "gda.data_product_blueprint_duckdb_execute_command.v1"
        elif command.command_type is PlatformCommandType.BLUEPRINT_PROVIDER_RETRY:
            expected_schema = "gda.data_product_blueprint_provider_retry_command.v1"
        else:
            raise DuckDBBlueprintCommandContractError(
                "DuckDB Blueprint worker received an unsupported command type"
            )
        payload = command.payload
        if (
            payload.get("schema") != expected_schema
            or payload.get("run_id") != str(command.run_id)
            or payload.get("execution_plan_artifact_id")
            != str(command.execution_plan_artifact_id)
        ):
            raise DuckDBBlueprintCommandContractError(
                "DuckDB Blueprint command does not bind its Run and execution plan"
            )

    def _fail_delivery(
        self,
        command: PlatformCommand,
        *,
        worker_id: str,
        error: str,
        retry_delay_seconds: int,
    ) -> PlatformCommand:
        return self.gateway.fail_command(
            command.tenant_id,
            command.command_id,
            worker_id=worker_id,
            error=error,
            retry_delay_seconds=retry_delay_seconds,
        )

    def run_once(
        self,
        tenant_id: str,
        *,
        worker_id: str,
        limit: int = 1,
        lease_seconds: int = 900,
    ) -> DuckDBBlueprintCommandBatchResult:
        commands = self.gateway.claim_commands(
            tenant_id,
            worker_id,
            actor_subject=DUCKDB_BLUEPRINT_WORKLOAD,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        completed = 0
        execution_succeeded = 0
        execution_failed = 0
        terminal_reconciled = 0
        retry_pending = 0
        failed = 0

        for command in commands:
            try:
                self._validate_command(command)
                run = self.gateway.get_run(command.tenant_id, command.run_id)
                if run.status in TERMINAL_RUN_STATUSES:
                    self.gateway.complete_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                    )
                    completed += 1
                    terminal_reconciled += 1
                    execution_failed += int(run.status is not RunStatus.SUCCEEDED)
                    continue

                try:
                    self.gateway.execute_blueprint_duckdb_test_run(
                        command.tenant_id,
                        DuckDBBlueprintExecutionRequest(run_id=command.run_id),
                        actor_subject=DUCKDB_BLUEPRINT_WORKLOAD,
                        provider=self.provider,
                    )
                except PlatformGatewayError:
                    current = self.gateway.get_run(
                        command.tenant_id,
                        command.run_id,
                    )
                    if current.status not in TERMINAL_RUN_STATUSES:
                        raise
                    self.gateway.complete_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                    )
                    completed += 1
                    terminal_reconciled += 1
                    execution_failed += int(
                        current.status is not RunStatus.SUCCEEDED
                    )
                    continue

                self.gateway.complete_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                )
                completed += 1
                execution_succeeded += 1
            except DuckDBBlueprintCommandContractError:
                delivery = self._fail_delivery(
                    command,
                    worker_id=worker_id,
                    error="DuckDB Blueprint command contract rejected",
                    retry_delay_seconds=0,
                )
                if delivery.status is PlatformCommandStatus.FAILED:
                    failed += 1
                else:
                    retry_pending += 1
            except PlatformGatewayError:
                delivery = self._fail_delivery(
                    command,
                    worker_id=worker_id,
                    error="DuckDB Blueprint control-plane delivery failed",
                    retry_delay_seconds=self.retry_delay_seconds,
                )
                if delivery.status is PlatformCommandStatus.FAILED:
                    failed += 1
                else:
                    retry_pending += 1

        return DuckDBBlueprintCommandBatchResult(
            claimed=len(commands),
            completed=completed,
            execution_succeeded=execution_succeeded,
            execution_failed=execution_failed,
            terminal_reconciled=terminal_reconciled,
            retry_pending=retry_pending,
            failed=failed,
            command_ids=tuple(command.command_id for command in commands),
        )
