from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
import yaml
from pydantic import ValidationError

from data_agent.gis_service_slo_reconciliation import (
    GIS_SERVICE_SLO_RECONCILIATION_WORKLOAD,
    GISServiceSLOReconciliationStatus,
    GISServiceSLOReconciliationTask,
)
from data_agent.gis_service_slo_reconciliation_worker import (
    GISServiceSLOReconciliationWorker,
    GISServiceSLOReconciliationWorkerConfig,
    GISServiceSLOReconciliationWorkerConfigurationError,
)
from data_agent.platform_gateway import PlatformGateway

TENANT = "planning"
ROOT = Path(__file__).resolve().parents[1]
TASK_ID = UUID("10000000-0000-4000-8000-000000000224")
BINDING_ID = UUID("20000000-0000-4000-8000-000000000223")
NOW = datetime(2026, 8, 22, 8, 0, tzinfo=UTC)


def _task(
    *,
    task_id: UUID = TASK_ID,
    status: GISServiceSLOReconciliationStatus = (
        GISServiceSLOReconciliationStatus.IN_FLIGHT
    ),
) -> GISServiceSLOReconciliationTask:
    terminal = status in {
        GISServiceSLOReconciliationStatus.DONE,
        GISServiceSLOReconciliationStatus.FAILED,
        GISServiceSLOReconciliationStatus.SUPERSEDED,
    }
    return GISServiceSLOReconciliationTask(
        tenant_id=TENANT,
        task_id=task_id,
        service_urn=f"gda://{TENANT}/gis_service/district-features",
        slo_definition_ref=(
            f"gda://{TENANT}/slo_definition/district-features-availability"
        ),
        active_version_ref=(
            f"gda://{TENANT}/slo_definition/district-features-availability.v1"
        ),
        definition_fingerprint="a" * 64,
        approval_case_ref=f"gda://{TENANT}/approval_case/district-slo-v1",
        activation_version=1,
        status=status,
        attempt_count=1,
        max_attempts=5,
        available_at=NOW,
        claimed_by=(
            "worker:gis-slo-reconciliation:test"
            if status is GISServiceSLOReconciliationStatus.IN_FLIGHT
            else None
        ),
        claimed_until=(
            NOW + timedelta(minutes=1)
            if status is GISServiceSLOReconciliationStatus.IN_FLIGHT
            else None
        ),
        binding_id=(
            BINDING_ID if status is GISServiceSLOReconciliationStatus.DONE else None
        ),
        last_error=(
            "activation superseded"
            if status
            in {
                GISServiceSLOReconciliationStatus.FAILED,
                GISServiceSLOReconciliationStatus.SUPERSEDED,
            }
            else None
        ),
        created_at=NOW,
        completed_at=NOW if terminal else None,
    )


def _gateway_transaction(row_or_rows):
    result = MagicMock()
    mappings = result.mappings.return_value
    if isinstance(row_or_rows, list):
        mappings.all.return_value = row_or_rows
    else:
        mappings.one.return_value = row_or_rows
    connection = MagicMock()
    connection.execute.return_value = result
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    transaction.__exit__.return_value = False
    return transaction, connection


def test_task_contract_rejects_inconsistent_terminal_evidence():
    payload = _task(status=GISServiceSLOReconciliationStatus.DONE).model_dump()
    payload["binding_id"] = None

    with pytest.raises(ValidationError, match="binding evidence"):
        GISServiceSLOReconciliationTask.model_validate(payload)


def test_worker_config_rejects_unsafe_lease():
    with pytest.raises(
        GISServiceSLOReconciliationWorkerConfigurationError,
        match="lease must be between",
    ):
        GISServiceSLOReconciliationWorkerConfig(
            tenant_id=TENANT,
            worker_id="worker:gis-slo-reconciliation:test",
            lease_seconds=4,
        ).validate()


def test_worker_settles_done_superseded_retry_and_failed_tasks():
    gateway = MagicMock(spec=PlatformGateway)
    task_ids = [UUID(int=offset) for offset in range(1, 5)]
    claimed = [_task(task_id=task_id) for task_id in task_ids]
    gateway.claim_gis_service_slo_reconciliations.return_value = tuple(claimed)
    gateway.complete_gis_service_slo_reconciliation.side_effect = [
        _task(task_id=task_ids[0], status=GISServiceSLOReconciliationStatus.DONE),
        _task(
            task_id=task_ids[1],
            status=GISServiceSLOReconciliationStatus.SUPERSEDED,
        ),
        RuntimeError("transient database outage"),
        RuntimeError("permanent evidence conflict"),
    ]
    gateway.fail_gis_service_slo_reconciliation.side_effect = [
        _task(task_id=task_ids[2], status=GISServiceSLOReconciliationStatus.PENDING),
        _task(task_id=task_ids[3], status=GISServiceSLOReconciliationStatus.FAILED),
    ]
    config = GISServiceSLOReconciliationWorkerConfig(
        tenant_id=TENANT,
        worker_id="worker:gis-slo-reconciliation:test",
        batch_size=4,
        retry_delay_seconds=7,
    )

    cycle = GISServiceSLOReconciliationWorker(config, gateway=gateway).run_once()

    assert cycle.claimed == 4
    assert cycle.completed == 1
    assert cycle.superseded == 1
    assert cycle.retrying == 1
    assert cycle.failed == 1
    gateway.claim_gis_service_slo_reconciliations.assert_called_once_with(
        TENANT,
        config.worker_id,
        actor_subject=GIS_SERVICE_SLO_RECONCILIATION_WORKLOAD,
        limit=4,
        lease_seconds=60,
    )
    assert gateway.fail_gis_service_slo_reconciliation.call_count == 2
    assert gateway.complete_gis_service_slo_reconciliation.call_args_list[0].kwargs == {
        "worker_id": config.worker_id,
    }
    assert "RuntimeError: transient database outage" == (
        gateway.fail_gis_service_slo_reconciliation.call_args_list[0].kwargs["error"]
    )


@pytest.mark.parametrize(
    "compose_name", ["docker-compose.yml", "docker-compose.gemma4-demo.yml"]
)
def test_compose_worker_is_explicit_optional_profile(compose_name: str):
    compose = yaml.safe_load((ROOT / compose_name).read_text(encoding="utf-8"))
    worker = compose["services"]["gis-service-slo-reconciliation-worker"]

    assert worker["profiles"] == ["gis-slo"]
    assert worker["command"] == [
        "python",
        "-m",
        "data_agent.gis_service_slo_reconciliation_worker",
    ]
    assert "GDA_GIS_SLO_RECONCILIATION_TENANT_ID" in worker["environment"]


def test_gateway_claim_calls_lease_authority_with_exact_parameters():
    row = _task().model_dump(mode="python")
    transaction, connection = _gateway_transaction([row])
    gateway = PlatformGateway()

    with patch.object(gateway, "_transaction", return_value=transaction):
        tasks = gateway.claim_gis_service_slo_reconciliations(
            TENANT,
            "worker:gis-slo-reconciliation:test",
            actor_subject=GIS_SERVICE_SLO_RECONCILIATION_WORKLOAD,
            limit=3,
            lease_seconds=45,
        )

    assert tasks == (_task(),)
    sql = str(connection.execute.call_args.args[0])
    assert "claim_gis_service_slo_reconciliations" in sql
    assert connection.execute.call_args.args[1] == {
        "tenant_id": TENANT,
        "actor_subject": GIS_SERVICE_SLO_RECONCILIATION_WORKLOAD,
        "worker_id": "worker:gis-slo-reconciliation:test",
        "limit": 3,
        "lease_seconds": 45,
    }


@pytest.mark.parametrize(
    ("method_name", "expected_function", "extra_kwargs"),
    [
        (
            "complete_gis_service_slo_reconciliation",
            "complete_gis_service_slo_reconciliation",
            {"bound_at": NOW},
        ),
        (
            "fail_gis_service_slo_reconciliation",
            "fail_gis_service_slo_reconciliation",
            {"error": "provider unavailable", "retry_delay_seconds": 9},
        ),
    ],
)
def test_gateway_settlement_calls_database_authority(
    method_name: str,
    expected_function: str,
    extra_kwargs: dict,
):
    status = (
        GISServiceSLOReconciliationStatus.DONE
        if method_name.startswith("complete")
        else GISServiceSLOReconciliationStatus.PENDING
    )
    transaction, connection = _gateway_transaction(
        _task(status=status).model_dump(mode="python")
    )
    gateway = PlatformGateway()

    with patch.object(gateway, "_transaction", return_value=transaction):
        result = getattr(gateway, method_name)(
            TENANT,
            TASK_ID,
            worker_id="worker:gis-slo-reconciliation:test",
            **extra_kwargs,
        )

    assert result.status is status
    assert expected_function in str(connection.execute.call_args.args[0])
    assert connection.execute.call_args.args[1]["task_id"] == str(TASK_ID)
