#!/usr/bin/env python3
"""Certify ApprovalCase SLA escalation in disposable PostgreSQL 16."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseConflictError,
    ApprovalCaseValidationError,
)
from data_agent.approval_case_batch import (
    ApprovalCaseBatchEscalationItem,
    ApprovalCaseBatchEscalationRequest,
    execute_approval_case_batch_escalation,
)
from data_agent.platform_contracts import ApprovalCase

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "docs/reports/agentops_approval_sla_escalation_2026-08-30.json"
MIGRATIONS = tuple(
    ROOT / "data_agent/migrations" / name
    for name in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "118_approval_case_sla_notification_outbox.sql",
        "119_approval_notification_governed_recovery.sql",
        "120_approval_case_assignment_authority.sql",
        "121_approval_principal_directory.sql",
        "249_agentops_approval_sla_escalation.sql",
        "250_agentops_approval_sla_escalation_outbox_stage_key.sql",
    )
)
RUNTIME_ROLE = "gda_approval_sla_runtime"
TENANT_A = "approval-sla-a"
TENANT_B = "approval-sla-b"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def _start_postgres(image: str) -> tuple[str, int]:
    container = f"gda-approval-sla-{secrets.token_hex(5)}"
    _docker(
        "run", "--rm", "--detach", "--name", container, "--publish", "127.0.0.1::5432",
        "--env", "POSTGRES_HOST_AUTH_METHOD=trust", image,
    )
    for _ in range(120):
        if _docker("exec", container, "pg_isready", "-U", "postgres", check=False).returncode == 0:
            binding = _docker("port", container, "5432/tcp").stdout.strip()
            return container, int(binding.rsplit(":", 1)[1])
        time.sleep(0.25)
    raise RuntimeError("disposable PostgreSQL did not become ready")


def _wait_for_connection(engine) -> None:
    last_error = None
    for _ in range(120):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except DBAPIError as error:
            last_error = error
            time.sleep(0.25)
    raise RuntimeError("PostgreSQL host port did not become ready") from last_error


def _bootstrap(engine) -> None:
    with engine.begin() as connection:
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))
        connection.exec_driver_sql(
            f"CREATE ROLE {RUNTIME_ROLE} LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS"
        )
        connection.exec_driver_sql(f"GRANT gda_control_gateway TO {RUNTIME_ROLE}")


def _case(case_id: str, tenant: str = TENANT_A) -> ApprovalCase:
    now = datetime.now(UTC)
    requested_at = now - timedelta(minutes=5)
    return ApprovalCase(
        tenant_id=tenant,
        approval_case_ref=f"gda://{tenant}/approval_case/{case_id}",
        target_resource_urn=f"gda://{tenant}/dataset/{case_id}",
        target_fingerprint="a" * 64,
        action="data_product.release",
        requester_subject="workload:release-controller",
        request_reason="certify SLA escalation",
        requested_at=requested_at,
        expires_at=now + timedelta(minutes=30),
    )


def _visible_count(engine, tenant: str, table: str) -> int:
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": tenant},
        )
        return int(
            connection.execute(text(f"SELECT COUNT(*) FROM gda_control.{table}")).scalar_one()
        )


def _visible_escalations(engine, tenant: str, approval_case_ref: str) -> list[dict[str, object]]:
    with engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": tenant},
        )
        rows = connection.execute(
            text(
                """
                SELECT escalation_stage, status, materialized_at, suppressed_at
                FROM gda_control.approval_case_sla_escalation
                WHERE tenant_id = :tenant_id AND approval_case_ref = :approval_case_ref
                ORDER BY escalation_stage
                """
            ),
            {"tenant_id": tenant, "approval_case_ref": approval_case_ref},
        ).mappings().all()
        return [dict(row) for row in rows]


def _certify(engine, admin_engine) -> dict[str, object]:
    authority = ApprovalCaseAuthority(engine)
    case = _case("release-1")
    authority.create(case, owner_ref="team:data-platform")
    authority.upsert_principal(
        tenant_id=TENANT_A,
        principal_subject="human:data-steward",
        expected_directory_version=0,
        principal_type="human",
        display_name="Data Steward",
        status="active",
        approval_eligible=True,
        availability_status="available",
        valid_from=datetime.now(UTC) - timedelta(minutes=1),
        valid_until=None,
        actor_subject="human:platform-admin",
        reason="register certification approver",
    )
    due = datetime.now(UTC) - timedelta(seconds=2)
    first = authority.schedule_sla_escalation(
        tenant_id=TENANT_A, approval_case_ref=case.approval_case_ref,
        expected_state_version=0, escalation_stage=1, due_at=due,
        target_team_subject="team:data-governance", on_call_ref="oncall:data-governance",
        actor_subject="workload:sla-policy-controller", reason="stage one reminder",
    )
    replay = authority.schedule_sla_escalation(
        tenant_id=TENANT_A, approval_case_ref=case.approval_case_ref,
        expected_state_version=0, escalation_stage=1, due_at=due,
        target_team_subject="team:data-governance", on_call_ref="oncall:data-governance",
        actor_subject="workload:sla-policy-controller", reason="stage one reminder",
    )
    if replay.escalation_id != first.escalation_id:
        raise AssertionError("escalation replay created a duplicate identity")
    second = authority.schedule_sla_escalation(
        tenant_id=TENANT_A, approval_case_ref=case.approval_case_ref,
        expected_state_version=0, escalation_stage=2,
        due_at=datetime.now(UTC) - timedelta(seconds=1),
        target_team_subject="team:data-governance", on_call_ref="oncall:data-governance",
        actor_subject="workload:sla-policy-controller", reason="stage two on-call escalation",
    )
    materialized = authority.materialize_sla_escalations(TENANT_A, limit=10)
    materialized_stages = sorted(
        notification.notification.escalation_stage for notification in materialized
    )
    if materialized_stages != [1, 2]:
        raise AssertionError("both due escalation stages did not materialize exactly once")
    replay_materialized = authority.materialize_sla_escalations(TENANT_A, limit=10)
    if replay_materialized:
        raise AssertionError("materialization replay created a duplicate notification")
    authority.decide(
        tenant_id=TENANT_A, approval_case_ref=case.approval_case_ref,
        expected_state_version=0, verdict="approved", actor_subject="human:data-steward",
        reason="decision before second escalation",
    )
    notifications = authority.notifications(TENANT_A, case.approval_case_ref)
    escalation_statuses = [
        n.status.value
        for n in notifications
        if n.notification_kind.value == "escalated"
    ]
    escalation_stages = sorted(
        n.escalation_stage
        for n in notifications
        if n.notification_kind.value == "escalated"
    )
    escalation_projections = _visible_escalations(
        engine, TENANT_A, case.approval_case_ref
    )
    stale_version_rejected = False
    try:
        authority.schedule_sla_escalation(
            tenant_id=TENANT_A, approval_case_ref=case.approval_case_ref,
            expected_state_version=0, escalation_stage=2, due_at=second.due_at,
            target_team_subject="team:data-governance", on_call_ref="oncall:data-governance",
            actor_subject="workload:sla-policy-controller", reason="stale version",
        )
    except (ApprovalCaseConflictError, ApprovalCaseValidationError):
        stale_version_rejected = True

    batch_cases = (_case("batch-ok-1"), _case("batch-ok-2"))
    for batch_case in batch_cases:
        authority.create(batch_case, owner_ref="team:data-platform")
    batch_request = ApprovalCaseBatchEscalationRequest(
        tenant_id=TENANT_A,
        actor_subject="workload:sla-policy-controller",
        items=(
            ApprovalCaseBatchEscalationItem(
                approval_case_ref=batch_cases[0].approval_case_ref,
                expected_state_version=0,
                escalation_stage=1,
                due_at=datetime.now(UTC) - timedelta(seconds=1),
                target_team_subject="team:data-governance",
                on_call_ref="oncall:data-governance",
                reason="batch stage one reminder",
            ),
            ApprovalCaseBatchEscalationItem(
                approval_case_ref=batch_cases[1].approval_case_ref,
                expected_state_version=0,
                escalation_stage=2,
                due_at=datetime.now(UTC) - timedelta(seconds=1),
                target_team_subject="team:data-governance",
                on_call_ref="oncall:data-governance",
                reason="batch stage two on-call escalation",
            ),
            ApprovalCaseBatchEscalationItem(
                approval_case_ref=f"gda://{TENANT_A}/approval_case/batch-missing",
                expected_state_version=0,
                escalation_stage=1,
                due_at=datetime.now(UTC) - timedelta(seconds=1),
                target_team_subject="team:data-governance",
                on_call_ref="oncall:data-governance",
                reason="missing case must be reported independently",
            ),
        ),
    )
    batch_response = execute_approval_case_batch_escalation(
        batch_request, authority=authority
    )
    batch_outcomes = [result.outcome for result in batch_response.results]
    batch_materialized = authority.materialize_sla_escalations(TENANT_A, limit=10)
    batch_materialized_refs = sorted(
        envelope.approval_case.approval_case_ref
        for envelope in batch_materialized
        if envelope.approval_case.approval_case_ref in {
            batch_case.approval_case_ref for batch_case in batch_cases
        }
    )
    tenant_b_isolated = _visible_count(engine, TENANT_B, "approval_case_sla_escalation") == 0
    with admin_engine.connect() as connection:
        privileges = connection.execute(
            text(
                "SELECT has_table_privilege('gda_control_gateway', "
                "'gda_control.approval_case_sla_escalation', 'SELECT'), "
                "has_table_privilege('gda_control_gateway', "
                "'gda_control.approval_case_sla_escalation', 'INSERT'), "
                "has_function_privilege('gda_control_gateway', "
                "'gda_control.schedule_approval_case_sla_escalation("
                "text,text,integer,integer,timestamptz,text,text,text,text,text)', "
                "'EXECUTE')"
            )
        ).one()
    checks = {
        "schedule_idempotent": replay.escalation_id == first.escalation_id,
        "due_materialized_once": materialized_stages == [1, 2] and not replay_materialized,
        "terminal_decision_suppresses_future_escalation": (
            escalation_stages == [1, 2]
            and escalation_statuses == ["suppressed", "suppressed"]
        ),
        "terminal_decision_suppresses_escalation_projections": (
            [row["escalation_stage"] for row in escalation_projections] == [1, 2]
            and [row["status"] for row in escalation_projections] == ["suppressed", "suppressed"]
            and all(
                row["materialized_at"] is not None and row["suppressed_at"] is not None
                for row in escalation_projections
            )
        ),
        "stale_state_version_rejected": stale_version_rejected,
        "tenant_isolation": tenant_b_isolated,
        "gateway_select_only": bool(privileges[0]) and not bool(privileges[1]),
        "gateway_schedule_function_granted": bool(privileges[2]),
        "case_verdict_remains_approved": authority.get(
            TENANT_A, case.approval_case_ref
        ).status.value
        == "approved",
        "batch_per_case_outcomes": batch_outcomes == ["scheduled", "scheduled", "not_found"],
        "batch_successes_materialized": batch_materialized_refs == sorted(
            batch_case.approval_case_ref for batch_case in batch_cases
        ),
    }
    return {
        "schema": "gda.agentops_approval_sla_escalation_certification.v3",
        "status": "verified" if all(checks.values()) else "failed",
        "checks": checks,
        "materialized_notification_count": len(materialized),
        "materialized_escalation_stages": materialized_stages,
        "escalation_stages_after_decision": escalation_stages,
        "escalation_projections_after_decision": [
            {
                "escalation_stage": row["escalation_stage"],
                "status": row["status"],
                "materialized": row["materialized_at"] is not None,
                "suppressed": row["suppressed_at"] is not None,
            }
            for row in escalation_projections
        ],
        "batch_outcomes": batch_outcomes,
        "batch_materialized_case_refs": batch_materialized_refs,
        "escalation_statuses_after_decision": escalation_statuses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="postgres:16")
    parser.add_argument("--output", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    container = None
    admin_engine = None
    runtime_engine = None
    try:
        container, port = _start_postgres(args.image)
        admin_engine = create_engine(f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres")
        _wait_for_connection(admin_engine)
        _bootstrap(admin_engine)
        runtime_engine = create_engine(f"postgresql+psycopg2://{RUNTIME_ROLE}@127.0.0.1:{port}/postgres")
        _wait_for_connection(runtime_engine)
        report = _certify(runtime_engine, admin_engine)
        rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
        report["report_sha256"] = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        Path(args.output).write_text(
            json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report["status"] == "verified" else 1
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        if admin_engine is not None:
            admin_engine.dispose()
        if container is not None:
            _docker("rm", "--force", container, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
