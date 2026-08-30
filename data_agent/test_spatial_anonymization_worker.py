from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from data_agent.platform_contracts import RunStatus
from data_agent.security_event_ledger import SecurityOperationReceipt
from data_agent.spatial_anonymization_receipt import SpatialAnonymizationReceipt
from data_agent.spatial_anonymization_run import (
    SpatialAnonymizationRequest,
    SpatialAnonymizationRunSpec,
    build_spatial_anonymization_submission,
)
from data_agent.spatial_anonymization_worker import (
    SpatialAnonymizationWorker,
    SpatialAnonymizationWorkerContractError,
    SpatialAnonymizationWorkerExecutionError,
    spatial_anonymization_attempt_id,
)

TENANT = "tenant-a"
DEFINITION_ID = UUID("50000000-0000-4000-8000-000000000020")
PLAN_ID = UUID("50000000-0000-4000-8000-000000000030")
ADMITTED_AT = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)


def _submission():
    request = SpatialAnonymizationRequest(
        tenant_id=TENANT,
        client_request_id="worker-spatial-mask-001",
        requester_subject="human:data-governance-operator",
        source_asset_ref="agent_data_assets:17",
        source_schema="geo",
        source_table="restricted_parcels",
        output_schema="public",
        output_table="restricted_parcels_l3",
        data_type="polygon",
        level="L3",
        k_anonymity=5,
        keep_attrs=("tbmj", "dlmc"),
        agg_strategy="area_weighted",
        dp_epsilon=1.0,
        dp_numeric_fields=("tbmj",),
    )
    spec = SpatialAnonymizationRunSpec(
        request=request,
        definition_version_id=DEFINITION_ID,
        execution_plan_artifact_id=PLAN_ID,
        workload_subject_id="spatial-anonymization-worker",
        purpose="produce a governed anonymized spatial output",
        policy_version_ref="gda://tenant-a/policy/spatial-anonymization:v1",
        policy_evaluator_subject="workload:policy-evaluator",
    )
    return build_spatial_anonymization_submission(spec, admitted_at=ADMITTED_AT)


class _Ledger:
    def __init__(self):
        self.events = []
        self.receipt = None
        self.lock_acquired = True

    @contextmanager
    def attempt_lock(self, tenant_id, attempt_id):
        yield self.lock_acquired

    def get_operation_receipt(self, tenant_id, attempt_id):
        return self.receipt

    def list_events(self, tenant_id, *, attempt_id=None, limit=100):
        return [event for event in self.events if event.attempt_id == attempt_id][:limit]

    def append(self, **values):
        event = SimpleNamespace(
            event_id=uuid4(),
            inserted=True,
            **values,
        )
        self.events.append(event)
        return event


def _gateway(submission, *, status=RunStatus.DISPATCHING):
    gateway = MagicMock()
    run = submission.run.model_copy(update={"status": status, "state_version": 1})
    gateway.get_run.return_value = run
    gateway.get_resource_version.return_value = submission.request_version
    return gateway


def _receipt(submission, attempt_id, *, output_row_count=12):
    operation_request = submission.request_version.authority_version_ref["request"]
    evidence = SpatialAnonymizationReceipt.succeeded(
        tenant_id=TENANT,
        attempt_id=attempt_id,
        source_schema=operation_request["source_schema"],
        source_table=operation_request["source_table"],
        output_schema=operation_request["output_schema"],
        output_table=operation_request["output_table"],
        data_type=operation_request["data_type"],
        level=operation_request["level"],
        output_row_count=output_row_count,
    )
    return SecurityOperationReceipt(
        tenant_id=TENANT,
        receipt_id=uuid4(),
        attempt_id=attempt_id,
        action="data_anonymize",
        resource_ref=(
            "postgis://geo/restricted_parcels"
            "->postgis://public/restricted_parcels_l3"
        ),
        receipt_type=evidence.schema,
        receipt_sha256="a" * 64,
        evidence=evidence.as_dict(),
        recorded_by="workload:spatial-anonymization",
        recorded_at=ADMITTED_AT,
        inserted=True,
    )


def test_worker_executes_from_immutable_binding_and_records_security_outcome():
    submission = _submission()
    ledger = _Ledger()
    attempt_id = spatial_anonymization_attempt_id(submission.run.run_id)

    def operation(**kwargs):
        ledger.receipt = _receipt(submission, attempt_id)
        return {
            "status": "ok",
            "output_table": "public.restricted_parcels_l3",
            "output_row_count": 12,
            "security_receipt_sha256": "a" * 64,
        }

    polygon_operation = MagicMock(side_effect=operation)
    worker = SpatialAnonymizationWorker(
        gateway=_gateway(submission),
        ledger=ledger,
        polygon_operation=polygon_operation,
    )

    result = worker.execute(TENANT, submission.run.run_id)

    assert result.status == "completed"
    assert result.attempt_id == attempt_id
    assert result.output_row_count == 12
    assert result.recovered_from_receipt is False
    assert [event.phase for event in ledger.events] == ["admitted", "outcome"]
    kwargs = polygon_operation.call_args.kwargs
    assert kwargs["source_schema"] == "geo"
    assert kwargs["output_schema"] == "public"
    assert kwargs["keep_attrs"] == ["dlmc", "tbmj"]
    assert kwargs["security_attempt_id"] == str(attempt_id)


def test_worker_recovers_existing_receipt_without_repeating_anonymization():
    submission = _submission()
    ledger = _Ledger()
    attempt_id = spatial_anonymization_attempt_id(submission.run.run_id)
    ledger.receipt = _receipt(submission, attempt_id)
    reconciled_event_id = uuid4()
    reconcile = MagicMock(
        return_value=[
            SimpleNamespace(status="reconciled", outcome_event_id=reconciled_event_id)
        ]
    )
    operation = MagicMock()
    worker = SpatialAnonymizationWorker(
        gateway=_gateway(submission),
        ledger=ledger,
        polygon_operation=operation,
        reconcile=reconcile,
    )

    result = worker.execute(TENANT, submission.run.run_id)

    assert result.status == "reconciled"
    assert result.outcome_event_id == reconciled_event_id
    assert result.recovered_from_receipt is True
    operation.assert_not_called()
    reconcile.assert_called_once()


def test_worker_records_failure_outcome_and_does_not_claim_success():
    submission = _submission()
    ledger = _Ledger()
    worker = SpatialAnonymizationWorker(
        gateway=_gateway(submission),
        ledger=ledger,
        polygon_operation=MagicMock(return_value={"status": "error"}),
    )

    with pytest.raises(SpatialAnonymizationWorkerExecutionError):
        worker.execute(TENANT, submission.run.run_id)

    assert [event.phase for event in ledger.events] == ["admitted", "outcome"]
    assert ledger.events[-1].outcome == "failure"


def test_worker_rejects_accepted_run_before_writing_security_admission():
    submission = _submission()
    ledger = _Ledger()
    worker = SpatialAnonymizationWorker(
        gateway=_gateway(submission, status=RunStatus.ACCEPTED),
        ledger=ledger,
        polygon_operation=MagicMock(),
    )

    with pytest.raises(SpatialAnonymizationWorkerContractError, match="accepted"):
        worker.execute(TENANT, submission.run.run_id)

    assert ledger.events == []


def test_worker_rejects_overlapping_execution_before_running_operation():
    submission = _submission()
    ledger = _Ledger()
    ledger.lock_acquired = False
    operation = MagicMock()
    worker = SpatialAnonymizationWorker(
        gateway=_gateway(submission),
        ledger=ledger,
        polygon_operation=operation,
    )

    with pytest.raises(SpatialAnonymizationWorkerExecutionError, match="another worker"):
        worker.execute(TENANT, submission.run.run_id)

    operation.assert_not_called()
    assert ledger.events == []
