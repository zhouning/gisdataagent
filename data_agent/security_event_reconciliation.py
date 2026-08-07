"""Fail-closed reconciliation for admitted security events without outcomes."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from .audit_logger import ACTION_DATA_ANONYMIZE
from .security_event_ledger import (
    SecurityEvent,
    SecurityEventLedger,
    SecurityEventLedgerConflictError,
)
from .spatial_anonymization_receipt import (
    SpatialAnonymizationReceipt,
    SpatialAnonymizationReceiptError,
)

_IDENTIFIER_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)
ReconciliationStatus = Literal[
    "ready",
    "reconciled",
    "manual_review",
    "already_resolved",
]


class SecurityEventReconciliationError(RuntimeError):
    code = "security_event_reconciliation_error"


class SecurityEventReconciliationUnavailableError(SecurityEventReconciliationError):
    code = "security_event_reconciliation_unavailable"


@dataclass(frozen=True)
class SecurityEventReconciliationResult:
    tenant_id: str
    attempt_id: UUID
    admission_event_id: UUID
    action: str
    status: ReconciliationStatus
    reason: str
    resource_ref: str
    receipt_sha256: str | None = None
    outcome_event_id: UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for field in ("attempt_id", "admission_event_id", "outcome_event_id"):
            if payload[field] is not None:
                payload[field] = str(payload[field])
        return payload


def _table_reference(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    parts = value.split(".")
    if len(parts) != 2 or any(
        not part
        or len(part.encode("utf-8")) > 63
        or not _IDENTIFIER_RE.fullmatch(part)
        for part in parts
    ):
        return None
    return parts[0], parts[1]


def _receipt_matches_admission(
    receipt: SpatialAnonymizationReceipt,
    admission: SecurityEvent,
) -> bool:
    details = admission.details
    source = _table_reference(details.get("source_table"))
    output = _table_reference(details.get("output_table"))
    if source is None or output is None:
        return False
    expected_resource = (
        f"postgis://{source[0]}/{source[1]}"
        f"->postgis://{output[0]}/{output[1]}"
    )
    return (
        receipt.tenant_id == admission.tenant_id
        and receipt.attempt_id == admission.attempt_id
        and receipt.action == admission.action
        and receipt.source_schema == source[0]
        and receipt.source_table == source[1]
        and receipt.output_schema == output[0]
        and receipt.output_table == output[1]
        and receipt.data_type == details.get("data_type")
        and receipt.level == details.get("level")
        and admission.resource_ref == expected_resource
        and receipt.status == "success"
    )


def _manual_result(
    admission: SecurityEvent,
    reason: str,
) -> SecurityEventReconciliationResult:
    return SecurityEventReconciliationResult(
        tenant_id=admission.tenant_id,
        attempt_id=admission.attempt_id,
        admission_event_id=admission.event_id,
        action=admission.action,
        status="manual_review",
        reason=reason,
        resource_ref=admission.resource_ref,
    )


def _read_receipt(event_ledger: SecurityEventLedger, admission: SecurityEvent):
    receipt_record = event_ledger.get_operation_receipt(
        admission.tenant_id,
        admission.attempt_id,
    )
    if receipt_record is None:
        return None, None, "output_receipt_missing"
    if (
        receipt_record.action != admission.action
        or receipt_record.resource_ref != admission.resource_ref
        or receipt_record.receipt_type
        != "gda.spatial_anonymization_receipt.v1"
    ):
        return None, receipt_record, "output_receipt_mismatch"
    try:
        receipt = SpatialAnonymizationReceipt.parse(
            json.dumps(receipt_record.evidence, ensure_ascii=True)
        )
    except SpatialAnonymizationReceiptError:
        return None, receipt_record, "output_receipt_invalid"
    if not _receipt_matches_admission(receipt, admission):
        return None, receipt_record, "output_receipt_mismatch"
    return receipt, receipt_record, None


def _existing_outcome(
    ledger: SecurityEventLedger,
    tenant_id: str,
    attempt_id: UUID,
) -> SecurityEvent | None:
    return next(
        (
            event
            for event in ledger.list_events(
                tenant_id,
                attempt_id=attempt_id,
                limit=10,
            )
            if event.phase == "outcome"
        ),
        None,
    )


def reconcile_security_event_outcomes(
    tenant_id: str,
    *,
    older_than: datetime,
    attempt_id: UUID | None = None,
    limit: int = 100,
    apply: bool = False,
    actor_subject: str = "workload:security-event-reconciler",
    ledger: SecurityEventLedger | None = None,
    engine=None,
) -> list[SecurityEventReconciliationResult]:
    event_ledger = ledger or SecurityEventLedger(engine)
    admissions = event_ledger.list_incomplete_admissions(
        tenant_id,
        older_than=older_than,
        attempt_id=attempt_id,
        limit=limit,
    )
    results: list[SecurityEventReconciliationResult] = []
    for admission in admissions:
        if admission.action != ACTION_DATA_ANONYMIZE:
            results.append(
                _manual_result(admission, "action_has_no_durable_completion_receipt")
            )
            continue
        receipt, receipt_record, manual_reason = _read_receipt(
            event_ledger,
            admission,
        )
        if receipt is None:
            results.append(_manual_result(admission, manual_reason or "receipt_unknown"))
            continue
        if not apply:
            results.append(
                SecurityEventReconciliationResult(
                    tenant_id=tenant_id,
                    attempt_id=admission.attempt_id,
                    admission_event_id=admission.event_id,
                    action=admission.action,
                    status="ready",
                    reason="matching_output_receipt_found",
                    resource_ref=admission.resource_ref,
                    receipt_sha256=receipt_record.receipt_sha256,
                )
            )
            continue
        try:
            outcome = event_ledger.append(
                tenant_id=tenant_id,
                attempt_id=admission.attempt_id,
                phase="outcome",
                action=admission.action,
                outcome="success",
                actor_subject=actor_subject,
                resource_ref=admission.resource_ref,
                reason="anonymization_reconciled_from_output_receipt",
                details={
                    "reconciled": True,
                    "admission_event_id": str(admission.event_id),
                    "receipt_sha256": receipt_record.receipt_sha256,
                    "output_row_count": receipt.output_row_count,
                },
            )
        except SecurityEventLedgerConflictError:
            existing = _existing_outcome(
                event_ledger,
                tenant_id,
                admission.attempt_id,
            )
            if existing is None:
                raise
            results.append(
                SecurityEventReconciliationResult(
                    tenant_id=tenant_id,
                    attempt_id=admission.attempt_id,
                    admission_event_id=admission.event_id,
                    action=admission.action,
                    status="already_resolved",
                    reason="outcome_was_recorded_concurrently",
                    resource_ref=admission.resource_ref,
                    receipt_sha256=receipt_record.receipt_sha256,
                    outcome_event_id=existing.event_id,
                )
            )
            continue
        results.append(
            SecurityEventReconciliationResult(
                tenant_id=tenant_id,
                attempt_id=admission.attempt_id,
                admission_event_id=admission.event_id,
                action=admission.action,
                status="reconciled",
                reason="outcome_appended_from_matching_output_receipt",
                resource_ref=admission.resource_ref,
                receipt_sha256=receipt_record.receipt_sha256,
                outcome_event_id=outcome.event_id,
            )
        )
    return results
