"""Deterministic worker entrypoint for governed spatial anonymization Runs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid5

from .audit_logger import ACTION_DATA_ANONYMIZE
from .platform_contracts import RunStatus
from .platform_gateway import PlatformGateway
from .security_event_ledger import (
    SecurityEventLedger,
    SecurityOperationReceipt,
)
from .security_event_reconciliation import reconcile_security_event_outcomes
from .spatial_anonymization_receipt import (
    SpatialAnonymizationReceipt,
    SpatialAnonymizationReceiptError,
)
from .spatial_anonymization_run import (
    SPATIAL_ANONYMIZATION_SEMANTIC_TYPE,
    SpatialAnonymizationRequest,
    parse_spatial_anonymization_version,
)

_EXECUTABLE_RUN_STATUSES = frozenset(
    {RunStatus.DISPATCHING, RunStatus.RUNNING, RunStatus.RECONCILING}
)


class SpatialAnonymizationWorkerError(RuntimeError):
    code = "spatial_anonymization_worker_error"


class SpatialAnonymizationWorkerContractError(SpatialAnonymizationWorkerError):
    code = "spatial_anonymization_worker_contract_error"


class SpatialAnonymizationWorkerExecutionError(SpatialAnonymizationWorkerError):
    code = "spatial_anonymization_worker_execution_error"


@dataclass(frozen=True)
class SpatialAnonymizationWorkerResult:
    tenant_id: str
    run_id: UUID
    attempt_id: UUID
    request_version_id: UUID
    status: str
    output_table: str
    output_row_count: int | None
    receipt_sha256: str | None
    outcome_event_id: UUID | None
    recovered_from_receipt: bool

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for field in ("run_id", "attempt_id", "request_version_id", "outcome_event_id"):
            if payload[field] is not None:
                payload[field] = str(payload[field])
        return payload


def spatial_anonymization_attempt_id(run_id: UUID) -> UUID:
    """Return one stable security attempt identity for all retries of a Run."""
    return uuid5(run_id, "spatial-anonymization:security-attempt:v1")


def _resource_ref(request: SpatialAnonymizationRequest) -> str:
    return (
        f"postgis://{request.source_schema}/{request.source_table}"
        f"->postgis://{request.output_schema}/{request.output_table}"
    )


def _validate_receipt(
    receipt_record: SecurityOperationReceipt,
    request: SpatialAnonymizationRequest,
    attempt_id: UUID,
) -> SpatialAnonymizationReceipt:
    try:
        receipt = SpatialAnonymizationReceipt.parse(
            json.dumps(receipt_record.evidence, ensure_ascii=True)
        )
    except SpatialAnonymizationReceiptError as exc:
        raise SpatialAnonymizationWorkerContractError(
            "stored spatial anonymization receipt is invalid"
        ) from exc
    if (
        receipt_record.action != ACTION_DATA_ANONYMIZE
        or receipt_record.resource_ref != _resource_ref(request)
        or receipt.tenant_id != request.tenant_id
        or receipt.attempt_id != attempt_id
        or receipt.source_schema != request.source_schema
        or receipt.source_table != request.source_table
        or receipt.output_schema != request.output_schema
        or receipt.output_table != request.output_table
        or receipt.data_type != request.data_type
        or receipt.level != request.level
        or receipt.status != "success"
    ):
        raise SpatialAnonymizationWorkerContractError(
            "stored receipt does not match the immutable Run request"
        )
    return receipt


class SpatialAnonymizationWorker:
    def __init__(
        self,
        *,
        gateway: PlatformGateway | None = None,
        ledger: SecurityEventLedger | None = None,
        polygon_operation: Callable[..., dict[str, Any]] | None = None,
        point_operation: Callable[..., dict[str, Any]] | None = None,
        reconcile: Callable[..., list[Any]] = reconcile_security_event_outcomes,
    ):
        self.gateway = gateway or PlatformGateway()
        self.ledger = ledger or SecurityEventLedger()
        self._polygon_operation = polygon_operation
        self._point_operation = point_operation
        self._reconcile = reconcile

    def _load_request(self, tenant_id: str, run_id: UUID):
        run = self.gateway.get_run(tenant_id, run_id)
        if run.orchestration_class.value != "dataops":
            raise SpatialAnonymizationWorkerContractError(
                "spatial anonymization requires a dataops Run"
            )
        if run.status not in _EXECUTABLE_RUN_STATUSES:
            raise SpatialAnonymizationWorkerContractError(
                f"Run in {run.status.value} cannot execute spatial anonymization"
            )
        bindings = [
            binding
            for binding in run.input_bindings
            if binding.binding_name == "anonymization_request"
        ]
        if (
            len(bindings) != 1
            or bindings[0].semantic_type != SPATIAL_ANONYMIZATION_SEMANTIC_TYPE
        ):
            raise SpatialAnonymizationWorkerContractError(
                "Run must bind exactly one spatial anonymization request"
            )
        version = self.gateway.get_resource_version(
            tenant_id,
            bindings[0].resource_version_id,
        )
        try:
            request = parse_spatial_anonymization_version(version)
        except ValueError as exc:
            raise SpatialAnonymizationWorkerContractError(
                "Run spatial anonymization request is invalid"
            ) from exc
        actor_subject = (
            f"{run.subject_context.subject_type.value}:"
            f"{run.subject_context.subject_id}"
        )
        if (
            request.tenant_id != run.tenant_id
            or request.requester_subject != run.subject_context.delegated_by
            or run.subject_context.subject_type.value != "workload"
        ):
            raise SpatialAnonymizationWorkerContractError(
                "Run identity does not match the spatial anonymization request"
            )
        return run, version, request, actor_subject

    def _existing_outcome(self, tenant_id: str, attempt_id: UUID):
        return next(
            (
                event
                for event in self.ledger.list_events(
                    tenant_id,
                    attempt_id=attempt_id,
                    limit=10,
                )
                if event.phase == "outcome"
            ),
            None,
        )

    def _recover_receipt(
        self,
        *,
        tenant_id: str,
        run_id: UUID,
        request_version_id: UUID,
        request: SpatialAnonymizationRequest,
        attempt_id: UUID,
        actor_subject: str,
        receipt_record: SecurityOperationReceipt,
    ) -> SpatialAnonymizationWorkerResult:
        receipt = _validate_receipt(receipt_record, request, attempt_id)
        existing = self._existing_outcome(tenant_id, attempt_id)
        if existing is not None:
            if existing.outcome != "success":
                raise SpatialAnonymizationWorkerContractError(
                    "successful receipt conflicts with a failure outcome"
                )
            outcome_event_id = existing.event_id
            status = "already_completed"
        else:
            reconciled = self._reconcile(
                tenant_id,
                older_than=datetime.now(UTC) + timedelta(minutes=1),
                attempt_id=attempt_id,
                limit=1,
                apply=True,
                actor_subject=actor_subject,
                ledger=self.ledger,
            )
            if len(reconciled) != 1 or reconciled[0].status not in {
                "reconciled",
                "already_resolved",
            }:
                raise SpatialAnonymizationWorkerContractError(
                    "receipt recovery could not produce a matching security outcome"
                )
            outcome_event_id = reconciled[0].outcome_event_id
            status = reconciled[0].status
        return SpatialAnonymizationWorkerResult(
            tenant_id=tenant_id,
            run_id=run_id,
            attempt_id=attempt_id,
            request_version_id=request_version_id,
            status=status,
            output_table=f"{request.output_schema}.{request.output_table}",
            output_row_count=receipt.output_row_count,
            receipt_sha256=receipt_record.receipt_sha256,
            outcome_event_id=outcome_event_id,
            recovered_from_receipt=True,
        )

    def _operation(self, request: SpatialAnonymizationRequest):
        if request.data_type == "point":
            if self._point_operation is not None:
                return self._point_operation
            from .grid_anonymize import poi_grid_aggregate_pg

            return poi_grid_aggregate_pg
        if self._polygon_operation is not None:
            return self._polygon_operation
        from .grid_anonymize import grid_anonymize_pg

        return grid_anonymize_pg

    @staticmethod
    def _operation_kwargs(
        request: SpatialAnonymizationRequest,
        attempt_id: UUID,
    ) -> dict[str, Any]:
        common = {
            "source_table": request.source_table,
            "output_table": request.output_table,
            "source_schema": request.source_schema,
            "output_schema": request.output_schema,
            "level": request.level,
            "k_anonymity": request.k_anonymity,
            "register_lineage": request.register_lineage,
            "security_tenant_id": request.tenant_id,
            "security_attempt_id": str(attempt_id),
        }
        if request.data_type == "point":
            return {
                **common,
                "category_column": request.category_column,
                "top_k_categories": request.top_k_categories,
            }
        return {
            **common,
            "keep_attrs": list(request.keep_attrs),
            "agg_strategy": request.agg_strategy,
            "dp_epsilon": request.dp_epsilon,
            "dp_numeric_fields": list(request.dp_numeric_fields),
            "random_offset": request.random_offset,
            "random_seed": request.random_seed,
        }

    def execute(
        self,
        tenant_id: str,
        run_id: UUID,
    ) -> SpatialAnonymizationWorkerResult:
        run, version, request, actor_subject = self._load_request(tenant_id, run_id)
        attempt_id = spatial_anonymization_attempt_id(run.run_id)
        with self.ledger.attempt_lock(tenant_id, attempt_id) as acquired:
            if not acquired:
                raise SpatialAnonymizationWorkerExecutionError(
                    "another worker is executing this Run attempt"
                )
            return self._execute_locked(
                tenant_id=tenant_id,
                run=run,
                version=version,
                request=request,
                actor_subject=actor_subject,
                attempt_id=attempt_id,
            )

    def _execute_locked(
        self,
        *,
        tenant_id: str,
        run: Any,
        version: Any,
        request: SpatialAnonymizationRequest,
        actor_subject: str,
        attempt_id: UUID,
    ) -> SpatialAnonymizationWorkerResult:
        resource_ref = _resource_ref(request)
        receipt_record = self.ledger.get_operation_receipt(tenant_id, attempt_id)
        if receipt_record is not None:
            return self._recover_receipt(
                tenant_id=tenant_id,
                run_id=run.run_id,
                request_version_id=version.resource_version_id,
                request=request,
                attempt_id=attempt_id,
                actor_subject=actor_subject,
                receipt_record=receipt_record,
            )

        outcome = self._existing_outcome(tenant_id, attempt_id)
        if outcome is not None:
            raise SpatialAnonymizationWorkerContractError(
                "Run attempt already has an outcome without a matching receipt"
            )
        admission = self.ledger.append(
            tenant_id=tenant_id,
            attempt_id=attempt_id,
            phase="admitted",
            action=ACTION_DATA_ANONYMIZE,
            outcome="admitted",
            actor_subject=actor_subject,
            resource_ref=resource_ref,
            reason="governed_spatial_anonymization_worker_started",
            details={
                "run_id": str(run.run_id),
                "request_version_id": str(version.resource_version_id),
                "source_asset_ref": request.source_asset_ref,
                "source_table": f"{request.source_schema}.{request.source_table}",
                "output_table": f"{request.output_schema}.{request.output_table}",
                "data_type": request.data_type,
                "level": request.level,
                "k_anonymity": request.k_anonymity,
            },
        )
        operation = self._operation(request)
        try:
            result = operation(**self._operation_kwargs(request, attempt_id))
        except Exception as exc:
            failure = self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                phase="outcome",
                action=ACTION_DATA_ANONYMIZE,
                outcome="failure",
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                reason="spatial_anonymization_worker_raised_exception",
                details={
                    "run_id": str(run.run_id),
                    "admission_event_id": str(admission.event_id),
                    "error_type": type(exc).__name__,
                },
            )
            raise SpatialAnonymizationWorkerExecutionError(
                f"spatial anonymization failed; outcome={failure.event_id}"
            ) from exc
        if not isinstance(result, dict) or result.get("status") != "ok":
            failure = self.ledger.append(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                phase="outcome",
                action=ACTION_DATA_ANONYMIZE,
                outcome="failure",
                actor_subject=actor_subject,
                resource_ref=resource_ref,
                reason="spatial_anonymization_worker_returned_failure",
                details={
                    "run_id": str(run.run_id),
                    "admission_event_id": str(admission.event_id),
                    "result_status": (
                        result.get("status", "unknown")
                        if isinstance(result, dict)
                        else "invalid"
                    ),
                },
            )
            raise SpatialAnonymizationWorkerExecutionError(
                f"spatial anonymization failed; outcome={failure.event_id}"
            )

        receipt_record = self.ledger.get_operation_receipt(tenant_id, attempt_id)
        if receipt_record is None:
            raise SpatialAnonymizationWorkerContractError(
                "successful operation did not commit its security receipt"
            )
        receipt = _validate_receipt(receipt_record, request, attempt_id)
        outcome_event = self.ledger.append(
            tenant_id=tenant_id,
            attempt_id=attempt_id,
            phase="outcome",
            action=ACTION_DATA_ANONYMIZE,
            outcome="success",
            actor_subject=actor_subject,
            resource_ref=resource_ref,
            reason="governed_spatial_anonymization_worker_succeeded",
            details={
                "run_id": str(run.run_id),
                "admission_event_id": str(admission.event_id),
                "request_version_id": str(version.resource_version_id),
                "receipt_sha256": receipt_record.receipt_sha256,
                "output_row_count": receipt.output_row_count,
            },
        )
        return SpatialAnonymizationWorkerResult(
            tenant_id=tenant_id,
            run_id=run.run_id,
            attempt_id=attempt_id,
            request_version_id=version.resource_version_id,
            status="completed",
            output_table=f"{request.output_schema}.{request.output_table}",
            output_row_count=receipt.output_row_count,
            receipt_sha256=receipt_record.receipt_sha256,
            outcome_event_id=outcome_event.event_id,
            recovered_from_receipt=False,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute one governed spatial anonymization PlatformRun"
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--run-id", required=True, type=UUID)
    args = parser.parse_args(argv)
    try:
        result = SpatialAnonymizationWorker().execute(args.tenant_id, args.run_id)
    except SpatialAnonymizationWorkerError as exc:
        print(
            json.dumps(
                {"status": "error", "code": exc.code, "message": str(exc)},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
