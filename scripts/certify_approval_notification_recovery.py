#!/usr/bin/env python3
"""Certify ApprovalCase notification recovery in disposable PostgreSQL 16."""

from __future__ import annotations

import argparse
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
from data_agent.platform_contracts import ApprovalCase

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = tuple(
    REPO_ROOT / "data_agent/migrations" / name
    for name in (
        "092_platform_control_ledger.sql",
        "094_platform_control_gateway.sql",
        "102_source_schema_drift_ledger.sql",
        "103_unified_approval_case_authority.sql",
        "118_approval_case_sla_notification_outbox.sql",
        "119_approval_notification_governed_recovery.sql",
    )
)
RUNTIME_ROLE = "gda_approval_recovery_runtime"
TENANT_A = "approval-cert-a"
TENANT_B = "approval-cert-b"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _start_postgres(image: str) -> tuple[str, int]:
    container = f"gda-approval-recovery-{secrets.token_hex(5)}"
    _docker(
        "run",
        "--rm",
        "--detach",
        "--name",
        container,
        "--publish",
        "127.0.0.1::5432",
        "--env",
        "POSTGRES_HOST_AUTH_METHOD=trust",
        image,
    )
    for _ in range(120):
        ready = _docker("exec", container, "pg_isready", "-U", "postgres", check=False)
        if ready.returncode == 0:
            binding = _docker("port", container, "5432/tcp").stdout.strip()
            return container, int(binding.splitlines()[0].rsplit(":", 1)[1])
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
            engine.dispose()
            time.sleep(0.25)
    raise RuntimeError("PostgreSQL host port did not become ready") from last_error


def _bootstrap(admin_engine) -> None:
    with admin_engine.begin() as connection:
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))
        connection.exec_driver_sql(
            f"CREATE ROLE {RUNTIME_ROLE} LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS"
        )
        connection.exec_driver_sql(f"GRANT gda_control_gateway TO {RUNTIME_ROLE}")


def _case(case_id: str) -> ApprovalCase:
    now = datetime.now(UTC)
    return ApprovalCase(
        tenant_id=TENANT_A,
        approval_case_ref=f"gda://{TENANT_A}/approval_case/{case_id}",
        target_resource_urn=f"gda://{TENANT_A}/dataset/{case_id}",
        target_fingerprint="a" * 64,
        action="data_product.release",
        requester_subject="workload:release-controller",
        request_reason="certify governed notification recovery",
        requested_at=now,
        expires_at=now + timedelta(hours=1),
    )


def _drive_to_dead_letter(authority: ApprovalCaseAuthority, notification_id) -> None:
    for _ in range(10):
        envelopes = authority.claim_notifications(
            TENANT_A,
            "worker:recovery-cert",
            limit=1,
            lease_seconds=30,
        )
        next(
            item for item in envelopes if item.notification.notification_id == notification_id
        )
        failed = authority.fail_notification(
            TENANT_A,
            notification_id,
            worker_id="worker:recovery-cert",
            error="certified receiver outage",
            retry_delay_seconds=0,
        )
    if failed.status.value != "failed" or failed.attempt_count != 10:
        raise AssertionError("notification did not reach the bounded dead-letter state")


def _tenant_visible_recoveries(runtime_engine, tenant_id: str) -> int:
    with runtime_engine.begin() as connection:
        connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )
        return int(
            connection.execute(
                text(
                    "SELECT COUNT(*) "
                    "FROM gda_control.approval_case_notification_recovery_event"
                )
            ).scalar_one()
        )


def _mutation_denied(engine, statement: str, *, set_gateway: bool = False) -> bool:
    try:
        with engine.begin() as connection:
            if set_gateway:
                connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
                connection.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
                    {"tenant_id": TENANT_A},
                )
            connection.execute(text(statement))
    except DBAPIError:
        return True
    return False


def _privileges(admin_engine) -> dict[str, bool]:
    with admin_engine.connect() as connection:
        values = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case_notification_recovery_event',
                        'SELECT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case_notification_recovery_event',
                        'INSERT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case_notification_outbox',
                        'UPDATE'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.retry_approval_case_notification('
                        'text,text,uuid,integer,text,text)',
                        'EXECUTE'
                    )
                """
            )
        ).one()
    return {
        "recovery_event_select": bool(values[0]),
        "recovery_event_insert": bool(values[1]),
        "outbox_update": bool(values[2]),
        "retry_function_execute": bool(values[3]),
    }


def _certify(admin_engine, runtime_engine) -> dict[str, object]:
    authority = ApprovalCaseAuthority(runtime_engine)
    approval_case = _case("release-1")
    authority.create(approval_case, owner_ref="team:data-platform")
    requested = next(
        item
        for item in authority.notifications(TENANT_A, approval_case.approval_case_ref)
        if item.notification_kind.value == "requested"
    )
    _drive_to_dead_letter(authority, requested.notification_id)

    for recovery_no in range(1, 11):
        recovered = authority.retry_notification(
            tenant_id=TENANT_A,
            approval_case_ref=approval_case.approval_case_ref,
            notification_id=requested.notification_id,
            expected_attempt_count=10,
            actor_subject="human:platform-admin",
            reason=f"certified receiver repair {recovery_no}",
        )
        if recovered.recovery_count != recovery_no or recovered.attempt_count != 0:
            raise AssertionError("manual recovery projection is inconsistent")
        _drive_to_dead_letter(authority, requested.notification_id)

    recovery_limit_enforced = False
    try:
        authority.retry_notification(
            tenant_id=TENANT_A,
            approval_case_ref=approval_case.approval_case_ref,
            notification_id=requested.notification_id,
            expected_attempt_count=10,
            actor_subject="human:platform-admin",
            reason="must exceed recovery limit",
        )
    except ApprovalCaseValidationError:
        recovery_limit_enforced = True

    attempt_cas_enforced = False
    try:
        authority.retry_notification(
            tenant_id=TENANT_A,
            approval_case_ref=approval_case.approval_case_ref,
            notification_id=requested.notification_id,
            expected_attempt_count=9,
            actor_subject="human:platform-admin",
            reason="must fail stale CAS",
        )
    except (ApprovalCaseConflictError, ApprovalCaseValidationError):
        attempt_cas_enforced = True

    recovery_events = authority.notification_recoveries(
        TENANT_A,
        approval_case.approval_case_ref,
    )

    terminal_case = _case("terminal-expiry")
    authority.create(terminal_case, owner_ref="team:data-platform")
    expiry = next(
        item
        for item in authority.notifications(TENANT_A, terminal_case.approval_case_ref)
        if item.notification_kind.value == "expired"
    )
    with admin_engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE gda_control.approval_case_notification_outbox
                SET status = 'failed', attempt_count = max_attempts,
                    last_error = 'certified expiry outage',
                    completed_at = clock_timestamp()
                WHERE tenant_id = :tenant_id AND notification_id = :notification_id
                """
            ),
            {"tenant_id": TENANT_A, "notification_id": expiry.notification_id},
        )
    authority.decide(
        tenant_id=TENANT_A,
        approval_case_ref=terminal_case.approval_case_ref,
        expected_state_version=0,
        verdict="approved",
        actor_subject="human:data-steward",
        reason="certify stale expiry protection",
    )
    stale_expiry_rejected = False
    try:
        authority.retry_notification(
            tenant_id=TENANT_A,
            approval_case_ref=terminal_case.approval_case_ref,
            notification_id=expiry.notification_id,
            expected_attempt_count=10,
            actor_subject="human:platform-admin",
            reason="must not replay terminal expiry",
        )
    except ApprovalCaseValidationError:
        stale_expiry_rejected = True

    privileges = _privileges(admin_engine)
    checks = {
        "ten_recoveries_recorded": len(recovery_events) == 10,
        "recovery_sequence_contiguous": [event.recovery_no for event in recovery_events]
        == list(range(1, 11)),
        "recovery_limit_enforced": recovery_limit_enforced,
        "attempt_cas_enforced": attempt_cas_enforced,
        "stale_expiry_rejected": stale_expiry_rejected,
        "tenant_a_visible_recoveries": _tenant_visible_recoveries(
            runtime_engine, TENANT_A
        )
        == 10,
        "tenant_b_isolated": _tenant_visible_recoveries(runtime_engine, TENANT_B) == 0,
        "gateway_direct_mutation_denied": _mutation_denied(
            runtime_engine,
            "UPDATE gda_control.approval_case_notification_recovery_event "
            "SET reason = 'forged'",
            set_gateway=True,
        ),
        "owner_audit_mutation_denied": _mutation_denied(
            admin_engine,
            "UPDATE gda_control.approval_case_notification_recovery_event "
            "SET reason = 'forged'",
        ),
        "gateway_select_only": privileges
        == {
            "recovery_event_select": True,
            "recovery_event_insert": False,
            "outbox_update": False,
            "retry_function_execute": True,
        },
    }
    return {
        "schema": "gda.approval_notification_recovery_certification.v1",
        "status": "verified" if all(checks.values()) else "failed",
        "checks": checks,
        "privileges": privileges,
        "recovery_event_count": len(recovery_events),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="postgres:16")
    args = parser.parse_args()
    container = None
    admin_engine = None
    runtime_engine = None
    try:
        container, port = _start_postgres(args.image)
        admin_engine = create_engine(
            f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres"
        )
        _wait_for_connection(admin_engine)
        _bootstrap(admin_engine)
        runtime_engine = create_engine(
            f"postgresql+psycopg2://{RUNTIME_ROLE}@127.0.0.1:{port}/postgres"
        )
        _wait_for_connection(runtime_engine)
        report = _certify(admin_engine, runtime_engine)
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
