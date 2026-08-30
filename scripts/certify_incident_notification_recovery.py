#!/usr/bin/env python3
"""Certify governed DataIncident notification dead-letter recovery on PostgreSQL 16."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.migration_runner import discover_migrations
from data_agent.platform_contracts import IncidentSeverity, data_incident_fingerprint
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayForbiddenError,
    GatewayValidationError,
    PlatformGateway,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_NAMES = (
    "092_platform_control_ledger.sql",
    "094_platform_control_gateway.sql",
    "098_platform_data_incident.sql",
    "099_platform_incident_notification_outbox.sql",
    "123_resource_bound_data_incident.sql",
    "226_incident_notification_provider_receipt.sql",
    "227_incident_notification_receipt_strict_authority.sql",
    "228_incident_notification_governed_recovery.sql",
)
MIGRATIONS = tuple(
    migration for migration in discover_migrations() if migration.filename in MIGRATION_NAMES
)
RUNTIME_ROLE = "gda_incident_recovery_runtime"
TENANT_A = "incident-recovery-a"
TENANT_B = "incident-recovery-b"


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def _start_postgres(image: str) -> tuple[str, int]:
    container = f"gda-incident-recovery-{secrets.token_hex(5)}"
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
        if _docker("exec", container, "pg_isready", "-U", "postgres", check=False).returncode == 0:
            binding = _docker("port", container, "5432/tcp").stdout.strip()
            return container, int(binding.splitlines()[0].rsplit(":", 1)[1])
        time.sleep(0.25)
    raise RuntimeError("disposable PostgreSQL did not become ready")


def _wait(engine) -> None:
    last = None
    for _ in range(120):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except DBAPIError as exc:
            last = exc
            time.sleep(0.25)
    raise RuntimeError("PostgreSQL port did not become ready") from last


def _bootstrap(engine) -> str:
    with engine.begin() as connection:
        for migration in MIGRATIONS:
            connection.execute(text(migration.path.read_text(encoding="utf-8")))
        connection.exec_driver_sql(
            f"CREATE ROLE {RUNTIME_ROLE} LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS"
        )
        connection.exec_driver_sql(f"GRANT gda_control_gateway TO {RUNTIME_ROLE}")
        return str(connection.execute(text("SHOW server_version")).scalar_one())


def _seed_incident(engine, tenant: str, *, suffix: str = "primary"):
    incident_id = uuid4()
    resource_urn = f"gda://{tenant}/dataset/recovery-cert-{suffix}"
    now = datetime.now(UTC)
    details = {}
    incident_sha256 = data_incident_fingerprint(
        tenant_id=tenant,
        run_id=None,
        dedupe_key=f"recovery-cert-{suffix}",
        incident_type="notification_delivery",
        severity=IncidentSeverity.HIGH,
        summary="recovery certification",
        trigger_observation_id=None,
        details=details,
        detected_by="workload:certifier",
        opened_at=now,
        subject_resource_urn=resource_urn,
    )
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"), {"tenant": tenant}
        )
        connection.execute(text("SELECT set_config('gda.data_incident_record_allowed', '1', true)"))
        connection.execute(
            text(
                """
                INSERT INTO gda_control.resource(
                    tenant_id, resource_urn, resource_kind, authority_system,
                    authority_locator, owner_ref, governance_ref, technical_refs
                ) VALUES (:tenant, :urn, 'dataset', 'gda', :urn,
                    'team:data-platform', '{}'::jsonb, '[]'::jsonb)
                ON CONFLICT DO NOTHING
                """
            ),
            {"tenant": tenant, "urn": resource_urn},
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.data_incident(
                    tenant_id, incident_id, run_id, subject_resource_urn,
                    dedupe_key, incident_type, severity, summary,
                    trigger_observation_id, details, incident_sha256,
                    detected_by, status, state_version, opened_at, updated_at
                ) VALUES (:tenant, :incident, NULL, :urn, :dedupe_key,
                    'notification_delivery', 'high', 'recovery certification', NULL,
                    CAST(:details AS jsonb), :incident_sha256, 'workload:certifier',
                    'open', 0, :now, :now)
                """
            ),
            {
                "tenant": tenant,
                "incident": incident_id,
                "urn": resource_urn,
                "now": now,
                "details": json.dumps(details),
                "incident_sha256": incident_sha256,
                "dedupe_key": f"recovery-cert-{suffix}",
            },
        )
        connection.execute(text("SELECT set_config('gda.data_incident_record_allowed', '0', true)"))
    return incident_id


def _dead_letter(gateway: PlatformGateway, tenant: str, incident_id):
    notification = gateway.list_incident_notifications(tenant, incident_id)[0]
    for _ in range(10):
        claimed = gateway.claim_incident_notifications(
            tenant, "worker:recovery-cert", limit=1, lease_seconds=30
        )
        envelope = next(
            item
            for item in claimed
            if item.notification.notification_id == notification.notification_id
        )
        notification = gateway.fail_incident_notification(
            tenant,
            envelope.notification.notification_id,
            worker_id="worker:recovery-cert",
            error="receiver outage",
            retry_delay_seconds=0,
        )
    return notification


def _mutation_denied(
    engine, sql: str, *, gateway_role: bool = False, tenant: str = TENANT_A
) -> bool:
    try:
        with engine.begin() as connection:
            if gateway_role:
                connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"), {"tenant": tenant}
            )
            connection.execute(text(sql))
    except DBAPIError:
        return True
    return False


def certify(image: str) -> dict[str, object]:
    container = admin_engine = runtime_engine = None
    try:
        container, port = _start_postgres(image)
        admin_engine = create_engine(f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres")
        _wait(admin_engine)
        version = _bootstrap(admin_engine)
        runtime_engine = create_engine(
            f"postgresql+psycopg2://{RUNTIME_ROLE}@127.0.0.1:{port}/postgres"
        )
        _wait(runtime_engine)
        gateway = PlatformGateway(runtime_engine)
        incident_id = _seed_incident(admin_engine, TENANT_A)
        tenant_b_incident_id = _seed_incident(admin_engine, TENANT_B)
        failed = _dead_letter(gateway, TENANT_A, incident_id)
        recovery_events = []
        pending_rejected = False
        for recovery_no in range(1, 11):
            failed = gateway.recover_incident_notification(
                TENANT_A,
                incident_id,
                failed.notification_id,
                expected_attempt_count=failed.attempt_count,
                expected_receipt_sha256=failed.receipt_sha256 or "",
                actor_subject="human:platform-admin",
                reason=f"receiver repair {recovery_no}",
            )
            recovery_events = gateway.incident_notification_recoveries(
                TENANT_A, incident_id, failed.notification_id
            )
            if (
                failed.status.value != "pending"
                or failed.attempt_count != 0
                or failed.receipt_sha256 is not None
            ):
                raise AssertionError("recovery projection did not return to pending")
            if recovery_no == 1:
                pending_notification_id = failed.notification_id
                pending_rejected = _expect(
                    lambda notification_id=pending_notification_id: (
                        gateway.recover_incident_notification(
                            TENANT_A,
                            incident_id,
                            notification_id,
                            expected_attempt_count=1,
                            expected_receipt_sha256="a" * 64,
                            actor_subject="human:platform-admin",
                            reason="pending notification must not recover",
                        )
                    ),
                    GatewayConflictError,
                )
            failed = _dead_letter(gateway, TENANT_A, incident_id)
        done_incident_id = _seed_incident(admin_engine, TENANT_A, suffix="done")
        done_notification = gateway.claim_incident_notifications(
            TENANT_A, "worker:recovery-cert", limit=1, lease_seconds=30
        )[0].notification
        done_notification = gateway.complete_incident_notification(
            TENANT_A,
            done_notification.notification_id,
            worker_id="worker:recovery-cert",
            provider_receipt={
                "schema": "gda.alertmanager_provider_receipt.v1",
                "provider": "alertmanager",
                "accepted": True,
                "http_status": 202,
                "destination_ref": done_notification.destination_ref,
                "accepted_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
        )
        checks = {
            "postgres_16": version.startswith("16."),
            "ten_recoveries": len(recovery_events) == 10,
            "recovery_sequence": [event.recovery_no for event in recovery_events]
            == list(range(1, 11)),
            "recovery_limit": _expect(
                lambda: gateway.recover_incident_notification(
                    TENANT_A,
                    incident_id,
                    failed.notification_id,
                    expected_attempt_count=failed.attempt_count,
                    expected_receipt_sha256=failed.receipt_sha256 or "",
                    actor_subject="human:platform-admin",
                    reason="must be rejected",
                ),
                GatewayValidationError,
            ),
            "stale_attempt_cas": _expect(
                lambda: gateway.recover_incident_notification(
                    TENANT_A,
                    incident_id,
                    failed.notification_id,
                    expected_attempt_count=9,
                    expected_receipt_sha256=failed.receipt_sha256 or "",
                    actor_subject="human:platform-admin",
                    reason="stale CAS",
                ),
                (GatewayConflictError, GatewayValidationError),
            ),
            "stale_receipt_cas": _expect(
                lambda: gateway.recover_incident_notification(
                    TENANT_A,
                    incident_id,
                    failed.notification_id,
                    expected_attempt_count=failed.attempt_count,
                    expected_receipt_sha256="b" * 64,
                    actor_subject="human:platform-admin",
                    reason="stale receipt evidence",
                ),
                GatewayConflictError,
            ),
            "pending_rejected": pending_rejected,
            "done_rejected": _expect(
                lambda: gateway.recover_incident_notification(
                    TENANT_A,
                    done_incident_id,
                    done_notification.notification_id,
                    expected_attempt_count=done_notification.attempt_count,
                    expected_receipt_sha256=done_notification.receipt_sha256 or "",
                    actor_subject="human:platform-admin",
                    reason="done notification must not recover",
                ),
                GatewayConflictError,
            ),
            "non_human_rejected": _expect(
                lambda: gateway.recover_incident_notification(
                    TENANT_A,
                    incident_id,
                    failed.notification_id,
                    expected_attempt_count=failed.attempt_count,
                    expected_receipt_sha256=failed.receipt_sha256 or "",
                    actor_subject="workload:auto-retry",
                    reason="non human",
                ),
                GatewayForbiddenError,
            ),
            "tenant_isolated": len(
                gateway.incident_notification_recoveries(
                    TENANT_B,
                    tenant_b_incident_id,
                    failed.notification_id,
                )
            )
            == 0,
            "event_direct_insert_denied": _mutation_denied(
                runtime_engine,
                "INSERT INTO gda_control.data_incident_notification_recovery_event "
                "(tenant_id) VALUES ('incident-recovery-a')",
                gateway_role=True,
            ),
            "event_direct_update_denied": _mutation_denied(
                runtime_engine,
                "UPDATE gda_control.data_incident_notification_recovery_event "
                "SET reason = 'forged'",
                gateway_role=True,
            ),
            "event_owner_update_denied": _mutation_denied(
                admin_engine,
                "UPDATE gda_control.data_incident_notification_recovery_event "
                "SET reason = 'forged'",
            ),
            "event_direct_delete_denied": _mutation_denied(
                admin_engine,
                "DELETE FROM gda_control.data_incident_notification_recovery_event",
            ),
            "event_owner_insert_guarded": _mutation_denied(
                admin_engine,
                """
                INSERT INTO gda_control.data_incident_notification_recovery_event(
                    tenant_id, recovery_event_id, notification_id, incident_id,
                    incident_event_id, recovery_no, actor_subject, reason,
                    previous_status, previous_attempt_count, previous_max_attempts,
                    previous_last_error, previous_provider_receipt,
                    previous_receipt_sha256, previous_terminal_worker_id,
                    previous_completed_at, occurred_at
                )
                SELECT tenant_id, gen_random_uuid(), notification_id, incident_id,
                       incident_event_id, recovery_no, actor_subject, 'forged',
                       previous_status, previous_attempt_count, previous_max_attempts,
                       previous_last_error, previous_provider_receipt,
                       previous_receipt_sha256, previous_terminal_worker_id,
                       previous_completed_at, clock_timestamp()
                  FROM gda_control.data_incident_notification_recovery_event
                 LIMIT 1
                """,
            ),
            "outbox_direct_update_denied": _mutation_denied(
                runtime_engine,
                "UPDATE gda_control.data_incident_notification_outbox SET status = 'pending'",
                gateway_role=True,
            ),
        }
        with admin_engine.connect() as connection:
            privilege = connection.execute(
                text(
                    """
                SELECT has_table_privilege('gda_control_gateway',
                    'gda_control.data_incident_notification_recovery_event', 'SELECT'),
                       has_table_privilege('gda_control_gateway',
                    'gda_control.data_incident_notification_recovery_event', 'INSERT'),
                       has_table_privilege('gda_control_gateway',
                    'gda_control.data_incident_notification_outbox', 'UPDATE'),
                       has_function_privilege('gda_control_gateway',
                    'gda_control.recover_data_incident_notification('
                    'text,uuid,uuid,integer,text,text,text)', 'EXECUTE')
                """
                )
            ).one()
        checks["gateway_least_privilege"] = tuple(bool(value) for value in privilege) == (
            True,
            False,
            False,
            True,
        )
        return {
            "schema": "gda.incident_notification_recovery_certification.v1",
            "status": "verified" if all(checks.values()) else "failed",
            "postgres_version": version,
            "recovery_event_count": len(recovery_events),
            "checks": checks,
        }
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        if admin_engine is not None:
            admin_engine.dispose()
        if container is not None:
            _docker("rm", "--force", container, check=False)


def _expect(call, errors) -> bool:
    try:
        call()
    except errors:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="postgres:16")
    args = parser.parse_args()
    report = certify(args.image)
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
