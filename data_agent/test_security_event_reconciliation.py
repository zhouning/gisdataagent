from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from data_agent.security_event_ledger import (
    SecurityEvent,
    SecurityEventLedger,
    SecurityEventLedgerConfigurationError,
    SecurityEventLedgerConflictError,
    SecurityOperationReceipt,
)
from data_agent.security_event_reconciliation import reconcile_security_event_outcomes
from data_agent.spatial_anonymization_receipt import SpatialAnonymizationReceipt


def _admission(*, action="data_anonymize"):
    return SecurityEvent(
        tenant_id="tenant-a",
        event_id=uuid4(),
        sequence_no=2,
        attempt_id=uuid4(),
        phase="admitted",
        action=action,
        outcome="admitted",
        actor_subject="human:alice",
        resource_ref="postgis://geo/roads->postgis://public/roads_grid",
        reason="authorized_request",
        details={
            "source_table": "geo.roads",
            "output_table": "public.roads_grid",
            "data_type": "polygon",
            "level": "L3",
        },
        previous_event_sha256="a" * 64,
        event_sha256="b" * 64,
        occurred_at=datetime.now(UTC),
        inserted=False,
    )


def _receipt(admission, **overrides):
    values = {
        "tenant_id": admission.tenant_id,
        "attempt_id": admission.attempt_id,
        "source_schema": "geo",
        "source_table": "roads",
        "output_schema": "public",
        "output_table": "roads_grid",
        "data_type": "polygon",
        "level": "L3",
        "output_row_count": 12,
    }
    values.update(overrides)
    return SpatialAnonymizationReceipt.succeeded(**values)


def _receipt_record(admission, receipt):
    if receipt is None:
        return None
    return SecurityOperationReceipt(
        tenant_id=admission.tenant_id,
        receipt_id=uuid4(),
        attempt_id=admission.attempt_id,
        action=admission.action,
        resource_ref=admission.resource_ref,
        receipt_type=receipt.schema,
        receipt_sha256="c" * 64,
        evidence=receipt.as_dict(),
        recorded_by="workload:spatial-anonymization",
        recorded_at=datetime.now(UTC),
        inserted=False,
    )


def _ledger(admission, receipt=None):
    ledger = MagicMock()
    ledger.list_incomplete_admissions.return_value = [admission]
    ledger.get_operation_receipt.return_value = _receipt_record(admission, receipt)
    ledger.append.return_value = SimpleNamespace(event_id=uuid4())
    return ledger


def _reconcile(admission, *, receipt=None, apply=False, ledger=None):
    event_ledger = ledger or _ledger(admission, receipt)
    if ledger is not None:
        ledger.get_operation_receipt.return_value = _receipt_record(
            admission,
            receipt,
        )
    return reconcile_security_event_outcomes(
        "tenant-a",
        older_than=datetime.now(UTC),
        apply=apply,
        ledger=event_ledger,
    )


def test_preview_marks_exact_receipt_ready_without_appending():
    admission = _admission()
    ledger = _ledger(admission)

    results = _reconcile(
        admission,
        receipt=_receipt(admission),
        ledger=ledger,
    )

    assert results[0].status == "ready"
    assert results[0].reason == "matching_output_receipt_found"
    ledger.append.assert_not_called()


def test_apply_appends_success_outcome_from_exact_receipt():
    admission = _admission()
    ledger = _ledger(admission)

    results = _reconcile(
        admission,
        receipt=_receipt(admission),
        apply=True,
        ledger=ledger,
    )

    assert results[0].status == "reconciled"
    parameters = ledger.append.call_args.kwargs
    assert parameters["attempt_id"] == admission.attempt_id
    assert parameters["phase"] == "outcome"
    assert parameters["outcome"] == "success"
    assert parameters["details"]["reconciled"] is True


@pytest.mark.parametrize(
    ("receipt_factory", "reason"),
    [
        (lambda admission: None, "output_receipt_missing"),
        (
            lambda admission: _receipt(admission, tenant_id="tenant-b"),
            "output_receipt_mismatch",
        ),
        (
            lambda admission: _receipt(admission, output_table="other_grid"),
            "output_receipt_mismatch",
        ),
    ],
)
def test_missing_or_mismatched_receipt_requires_manual_review(
    receipt_factory, reason
):
    admission = _admission()
    ledger = _ledger(admission)

    results = _reconcile(
        admission,
        receipt=receipt_factory(admission),
        apply=True,
        ledger=ledger,
    )

    assert results[0].status == "manual_review"
    assert results[0].reason == reason
    ledger.append.assert_not_called()


def test_read_only_verification_never_gets_an_invented_outcome():
    admission = _admission(action="anonymization_verify")
    ledger = _ledger(admission)

    results = reconcile_security_event_outcomes(
        "tenant-a",
        older_than=datetime.now(UTC),
        apply=True,
        ledger=ledger,
    )

    assert results[0].status == "manual_review"
    assert results[0].reason == "action_has_no_durable_completion_receipt"
    ledger.get_operation_receipt.assert_not_called()
    ledger.append.assert_not_called()


def test_concurrent_outcome_is_reported_as_already_resolved():
    admission = _admission()
    ledger = _ledger(admission)
    existing = SimpleNamespace(phase="outcome", event_id=uuid4())
    ledger.append.side_effect = SecurityEventLedgerConflictError("race")
    ledger.list_events.return_value = [existing]

    results = _reconcile(
        admission,
        receipt=_receipt(admission),
        apply=True,
        ledger=ledger,
    )

    assert results[0].status == "already_resolved"
    assert results[0].outcome_event_id == existing.event_id


def test_reconciliation_requires_postgresql():
    engine = MagicMock()
    engine.dialect.name = "duckdb"

    with pytest.raises(
        SecurityEventLedgerConfigurationError,
        match="PostgreSQL",
    ):
        reconcile_security_event_outcomes(
            "tenant-a",
            older_than=datetime.now(UTC),
            ledger=SecurityEventLedger(engine),
            engine=engine,
        )
