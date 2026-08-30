from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from data_agent.agentops_temporal_adapter import (
    TemporalAdapterError,
    build_temporal_start_request,
)
from data_agent.agentops_temporal_discovery_worker_postgres_rehearsal import (
    AgentOpsTemporalDiscoveryWorkerPostgresRehearsalReport,
    _cycle_from_stdout,
    _RehearsalObserver,
    _report_hash,
)
from data_agent.test_agentops_temporal_checkpoint_authority import (
    _checkpoint,
    _observation,
)


def test_discovery_worker_rehearsal_report_hash_is_self_bound() -> None:
    payload = {
        "schema_id": "gda.agentops-temporal-discovery-worker-postgres-rehearsal.v1",
        "checked_at": datetime.now(UTC),
        "database_scope": "temporary_database_only",
        "process_scope": "two_independent_discovery_worker_processes",
        "migration_ids": ("092", "094", "240", "241", "242"),
        "lease_seconds": 5,
        "worker_a_pid": 123,
        "worker_a_exit_code": -9,
        "worker_b_failure_exit_code": 0,
        "worker_b_recovery_exit_code": 0,
        "heartbeat_observed_renewals": 2,
        "final_attempt_count": 3,
        "reconciliation_count": 1,
        "checks": {"all": True},
        "passed": True,
        "failure_reasons": (),
        "technical_baseline_status": "technical_baseline_unreviewed",
        "decision_status": "assisted_precheck_not_for_production_decision",
    }
    report = AgentOpsTemporalDiscoveryWorkerPostgresRehearsalReport(
        **payload, report_sha256=_report_hash(payload)
    )
    assert report.report_sha256 == _report_hash(report.model_dump(mode="json"))
    with pytest.raises(ValueError, match="hash is invalid"):
        AgentOpsTemporalDiscoveryWorkerPostgresRehearsalReport(
            **payload, report_sha256="0" * 64
        )


def test_rehearsal_observer_exposes_health_and_network_failure_modes() -> None:
    checkpoint = _checkpoint()
    history = _observation()
    request_sha256 = build_temporal_start_request(
        checkpoint.workflow_input
    ).payload_sha256
    observer = _RehearsalObserver(history, request_sha256)
    observed = asyncio.run(
        observer.observe_workflow_input(
            tenant_id=history.tenant_id,
            namespace_ref=history.namespace_ref,
            workflow_id=history.workflow_id,
        )
    )
    assert observed.observed_input_sha256 == request_sha256
    assert asyncio.run(observer.check_health()) is True
    observer.mode = "network-failure"
    with pytest.raises(TemporalAdapterError, match="network outage"):
        asyncio.run(
            observer.observe_workflow_input(
                tenant_id=history.tenant_id,
                namespace_ref=history.namespace_ref,
                workflow_id=history.workflow_id,
            )
        )
    observer.mode = "frontend-outage"
    assert asyncio.run(observer.check_health()) is False


def test_cycle_output_parser_reads_child_contract() -> None:
    assert _cycle_from_stdout(
        'log line\n{"cycle": {"claimed_count": 1, "completed_count": 1}}\n'
    ) == {"claimed_count": 1, "completed_count": 1}
