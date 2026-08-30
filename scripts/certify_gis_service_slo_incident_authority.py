#!/usr/bin/env python3
"""Certify the atomic GIS ServiceSLO alert to DataIncident authority.

This is a disposable PostgreSQL certification for migration 225.  It keeps the
generic SLO authority, GIS ServiceSLO binding and shared DataIncident tables as
the only state owners, and checks that the gateway locks the exact activation
before inserting the incident.
"""

from __future__ import annotations

import argparse
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from rehearse_approval_alertmanager_delivery import (
    _docker,
    _ensure_image,
    _start_postgres,
    _wait_for_connection,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.migration_runner import discover_migrations
from data_agent.platform_contracts import ApprovalCase, IncidentSeverity
from data_agent.platform_gateway import (
    GatewayForbiddenError,
    GatewayValidationError,
    PlatformGateway,
)
from data_agent.slo_authority import (
    SLOBurnRateWindow,
    SLODefinitionAuthority,
    SLODefinitionDraft,
    SLOEventRatioIndicator,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = tuple(discover_migrations())
TENANT_A = "gis-incident-a"
TENANT_B = "gis-incident-b"
SERVICE_A = f"gda://{TENANT_A}/gis_service/district-features"
SERVICE_B = f"gda://{TENANT_B}/gis_service/district-features"
SLO_REF = f"gda://{TENANT_A}/slo_definition/district-features-availability"
SLO_VERSION = f"{SLO_REF}.v1"
APPROVAL_REF = f"gda://{TENANT_A}/approval_case/district-slo-v1"
APPROVER = "human:gis-service-owner"
CONTROLLER = "workload:gis-slo-controller"
DETECTOR = "workload:slo-alert-ingestor"
RUNTIME_ROLE = "gda_gis_incident_runtime"
NOW = datetime.now(UTC).replace(microsecond=0)


def _gateway_connection(engine: Engine, tenant: str):
    connection = engine.connect()
    transaction = connection.begin()
    connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
    connection.execute(
        text("SELECT set_config('app.current_tenant', :tenant, true)"),
        {"tenant": tenant},
    )
    return connection, transaction


def _bootstrap(admin_engine: Engine) -> str:
    with admin_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE ROLE agent_user LOGIN NOSUPERUSER NOBYPASSRLS"
        )
        for migration in MIGRATIONS:
            connection.execute(text(migration.path.read_text(encoding="utf-8")))
        connection.exec_driver_sql(
            f"CREATE ROLE {RUNTIME_ROLE} LOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS"
        )
        connection.exec_driver_sql(f"GRANT gda_control_gateway TO {RUNTIME_ROLE}")
        return str(connection.execute(text("SHOW server_version")).scalar_one())


def _seed_services(engine: Engine) -> None:
    with engine.begin() as connection:
        for tenant, service in ((TENANT_A, SERVICE_A), (TENANT_B, SERVICE_B)):
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.resource (
                        tenant_id, resource_urn, resource_kind, authority_system,
                        authority_locator, owner_ref, governance_ref, technical_refs
                    ) VALUES (
                        :tenant, :service, 'gis_service', 'gda', :service,
                        'team:geo-platform', '{}'::jsonb, '[]'::jsonb
                    ) ON CONFLICT DO NOTHING
                    """
                ),
                {"tenant": tenant, "service": service},
            )
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": tenant},
            )
            connection.execute(
                text("SELECT set_config('gda.gis_service_record_allowed', '1', true)")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.gis_service (
                        tenant_id, service_urn, created_at, updated_at
                    ) VALUES (:tenant, :service, :now, :now)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"tenant": tenant, "service": service, "now": NOW},
            )


def _draft() -> SLODefinitionDraft:
    return SLODefinitionDraft(
        tenant_id=TENANT_A,
        slo_definition_ref=SLO_REF,
        slo_version_ref=SLO_VERSION,
        version=1,
        service_resource_urn=SERVICE_A,
        indicator=SLOEventRatioIndicator(
            metric_name="gda_gis_service_requests_total",
            good_outcomes=("success",),
            bad_outcomes=("error",),
            match_labels={"service": "district-features"},
        ),
        objective_basis_points=9900,
        objective_window_seconds=86400,
        owner_subject="team:geo-platform",
        oncall_ref="oncall:geo-platform",
        burn_rate_windows=(
            SLOBurnRateWindow(
                name="fast",
                short_window_seconds=300,
                long_window_seconds=3600,
                burn_rate_milli=14400,
                minimum_events=20,
                for_seconds=120,
                severity="critical",
            ),
        ),
        created_by=CONTROLLER,
        creation_reason="certify GIS ServiceSLO incident authority",
        created_at=NOW,
    )


def _register_approver(authority: ApprovalCaseAuthority) -> None:
    authority.upsert_principal(
        tenant_id=TENANT_A,
        principal_subject=APPROVER,
        expected_directory_version=0,
        principal_type="human",
        display_name="GIS service owner",
        status="active",
        approval_eligible=True,
        availability_status="available",
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(hours=2),
        actor_subject="human:platform-admin",
        reason="register GIS incident certification approver",
    )


def _approve(authority: ApprovalCaseAuthority, fingerprint: str) -> ApprovalCase:
    case = ApprovalCase(
        tenant_id=TENANT_A,
        approval_case_ref=APPROVAL_REF,
        target_resource_urn=SLO_VERSION,
        target_fingerprint=fingerprint,
        action="slo_definition.activate",
        requester_subject=CONTROLLER,
        request_reason="approve exact GIS ServiceSLO activation",
        requested_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    authority.create(case, owner_ref="team:geo-platform")
    return authority.decide(
        tenant_id=TENANT_A,
        approval_case_ref=APPROVAL_REF,
        expected_state_version=0,
        verdict="approved",
        actor_subject=APPROVER,
        reason="approve exact GIS ServiceSLO incident certification",
    )


def _bind(engine: Engine, fingerprint: str, activation_version: int) -> UUID:
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        binding_id = uuid4()
        value = connection.execute(
            text(
                """
                SELECT gda_control.bind_gis_service_slo(
                    :tenant, CAST(:binding_id AS uuid), :service, :definition,
                    :version, :fingerprint, :approval, :activation, :bound_by,
                    :reason, :bound_at
                )
                """
            ),
            {
                "tenant": TENANT_A,
                "binding_id": str(binding_id),
                "service": SERVICE_A,
                "definition": SLO_REF,
                "version": SLO_VERSION,
                "fingerprint": fingerprint,
                "approval": APPROVAL_REF,
                "activation": activation_version,
                "bound_by": "human:gis-service-owner",
                "reason": "bind exact GIS ServiceSLO incident certification",
                "bound_at": NOW,
            },
        ).scalar_one()
        transaction.commit()
        return UUID(str(value))
    except Exception:
        transaction.rollback()
        raise
    finally:
        connection.close()


def _expect_rejected(callback) -> str:
    try:
        callback()
    except GatewayValidationError as exc:
        return exc.code
    except DBAPIError as exc:
        original = getattr(exc, "orig", None)
        return str(
            getattr(original, "sqlstate", None)
            or getattr(original, "pgcode", None)
            or "db-error"
        )
    raise AssertionError("operation unexpectedly succeeded")


def _activation_lock_sqlstate(
    engine: Engine,
    *,
    fingerprint: str,
    activation_version: int,
) -> str:
    lock_connection, lock_transaction = _gateway_connection(engine, TENANT_A)
    try:
        lock_connection.execute(
            text(
                """
                SELECT gda_control.assert_gis_service_slo_incident_authority(
                    :tenant, :service, :definition, :version,
                    :fingerprint, :approval, :activation
                )
                """
            ),
            {
                "tenant": TENANT_A,
                "service": SERVICE_A,
                "definition": SLO_REF,
                "version": SLO_VERSION,
                "fingerprint": fingerprint,
                "approval": APPROVAL_REF,
                "activation": activation_version,
            },
        )
        return _expect_rejected(
            lambda: _attempt_activation_update(engine)
        )
    finally:
        lock_transaction.rollback()
        lock_connection.close()


def _attempt_activation_update(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '250ms'"))
        connection.execute(
            text("SELECT set_config('gda.slo_activation_allowed', '1', true)")
        )
        connection.execute(
            text(
                """
                UPDATE gda_control.slo_definition_activation
                SET activation_reason = activation_reason
                WHERE tenant_id = :tenant AND slo_definition_ref = :definition
                """
            ),
            {"tenant": TENANT_A, "definition": SLO_REF},
        )


def _incident_rows(engine: Engine, incident_id: UUID) -> dict[str, Any]:
    with engine.connect() as connection:
        incident = connection.execute(
            text(
                """
                SELECT run_id, subject_resource_urn, status, state_version
                FROM gda_control.data_incident
                WHERE tenant_id = :tenant AND incident_id = :incident
                """
            ),
            {"tenant": TENANT_A, "incident": incident_id},
        ).mappings().one()
        events = tuple(
            connection.execute(
                text(
                    """
                    SELECT sequence_no
                    FROM gda_control.data_incident_event
                    WHERE tenant_id = :tenant AND incident_id = :incident
                    ORDER BY sequence_no
                    """
                ),
                {"tenant": TENANT_A, "incident": incident_id},
            ).scalars()
        )
        notifications = tuple(
            connection.execute(
                text(
                    """
                    SELECT incident_sequence_no, status, provider_receipt,
                           receipt_sha256, terminal_worker_id
                    FROM gda_control.data_incident_notification_outbox
                    WHERE tenant_id = :tenant AND incident_id = :incident
                    ORDER BY incident_sequence_no
                    """
                ),
                {"tenant": TENANT_A, "incident": incident_id},
            ).mappings()
        )
    return {**dict(incident), "events": events, "notifications": notifications}


def _security_contract(engine: Engine) -> dict[str, bool]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege('gda_control_gateway',
                        'gda_control.gis_service_slo_binding', 'INSERT'),
                    has_table_privilege('gda_control_gateway',
                        'gda_control.gis_service_slo_binding', 'UPDATE'),
                    has_table_privilege('gda_control_gateway',
                        'gda_control.gis_service_slo_binding', 'DELETE'),
                    has_function_privilege('gda_control_gateway',
                        'gda_control.assert_gis_service_slo_incident_authority('
                        'text,text,text,text,text,text,integer)', 'EXECUTE'),
                    has_table_privilege('gda_control_gateway',
                        'gda_control.data_incident', 'INSERT')
                """
            )
        ).one()
    return {
        "binding_insert": bool(row[0]),
        "binding_update": bool(row[1]),
        "binding_delete": bool(row[2]),
        "authority_execute": bool(row[3]),
        "incident_insert": bool(row[4]),
    }


def certify(*, postgres_image: str) -> dict[str, Any]:
    _ensure_image(postgres_image)
    container = f"gda-gis-incident-{secrets.token_hex(5)}"
    admin_engine = None
    runtime_engine = None
    try:
        port = _start_postgres(container, postgres_image)
        admin_engine = create_engine(
            f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres"
        )
        _wait_for_connection(admin_engine)
        postgres_version = _bootstrap(admin_engine)
        _seed_services(admin_engine)
        runtime_engine = create_engine(
            f"postgresql+psycopg2://{RUNTIME_ROLE}@127.0.0.1:{port}/postgres"
        )
        _wait_for_connection(runtime_engine)

        slo = SLODefinitionAuthority(runtime_engine)
        approvals = ApprovalCaseAuthority(runtime_engine)
        gateway = PlatformGateway(runtime_engine)
        _register_approver(approvals)
        definition = slo.stage(_draft())
        approval = _approve(approvals, definition.definition_fingerprint)
        activation_version = slo.activate(
            tenant_id=TENANT_A,
            slo_version_ref=SLO_VERSION,
            definition_fingerprint=definition.definition_fingerprint,
            approval_case_ref=approval.approval_case_ref,
            expected_activation_version=0,
            actor_subject=CONTROLLER,
            reason="activate exact GIS ServiceSLO incident certification",
        ).activation_version
        binding_id = _bind(admin_engine, definition.definition_fingerprint, activation_version)
        incident_id = uuid4()
        details = {
            "schema": "gda.gis_service_slo_incident.v1",
            "slo_definition_ref": SLO_REF,
            "active_version_ref": SLO_VERSION,
            "definition_fingerprint": definition.definition_fingerprint,
            "approval_case_ref": approval.approval_case_ref,
            "activation_version": activation_version,
            "binding_id": str(binding_id),
        }
        opened = gateway.open_gis_service_slo_incident(
            tenant_id=TENANT_A,
            service_urn=SERVICE_A,
            slo_definition_ref=SLO_REF,
            active_version_ref=SLO_VERSION,
            definition_fingerprint=definition.definition_fingerprint,
            approval_case_ref=approval.approval_case_ref,
            activation_version=activation_version,
            incident_id=incident_id,
            dedupe_key="gis-slo-district-features-v1-fast",
            incident_type="slo_error_budget_burn",
            severity=IncidentSeverity.CRITICAL,
            summary="GIS ServiceSLO error budget burn",
            details=details,
            detected_by=DETECTOR,
        )
        replay = gateway.open_gis_service_slo_incident(
            tenant_id=TENANT_A,
            service_urn=SERVICE_A,
            slo_definition_ref=SLO_REF,
            active_version_ref=SLO_VERSION,
            definition_fingerprint=definition.definition_fingerprint,
            approval_case_ref=approval.approval_case_ref,
            activation_version=activation_version,
            incident_id=incident_id,
            dedupe_key="gis-slo-district-features-v1-fast",
            incident_type="slo_error_budget_burn",
            severity=IncidentSeverity.CRITICAL,
            summary="GIS ServiceSLO error budget burn",
            details=details,
            detected_by=DETECTOR,
        )
        claimed_notifications = gateway.claim_incident_notifications(
            TENANT_A, "worker:gis-incident-cert", limit=10, lease_seconds=5
        )
        receipt = {
            "schema": "gda.alertmanager_provider_receipt.v1",
            "provider": "alertmanager",
            "accepted": True,
            "http_status": 202,
            "destination_ref": "alertmanager:default",
            "accepted_at": NOW.isoformat().replace("+00:00", "Z"),
        }
        invalid_receipt = _expect_rejected(
            lambda: gateway.complete_incident_notification(
                TENANT_A,
                claimed_notifications[0].notification.notification_id,
                worker_id="worker:gis-incident-cert",
                provider_receipt={
                    "schema": "gda.alertmanager_provider_receipt.v1",
                    "provider": "alertmanager",
                    "accepted": True,
                    "http_status": 503,
                    "destination_ref": "alertmanager:default",
                    "accepted_at": NOW.isoformat().replace("+00:00", "Z"),
                },
            )
        )
        completed_notification = gateway.complete_incident_notification(
            TENANT_A,
            claimed_notifications[0].notification.notification_id,
            worker_id="worker:gis-incident-cert",
            provider_receipt=receipt,
        )
        state = _incident_rows(admin_engine, incident_id)
        activation_lock_sqlstate = _activation_lock_sqlstate(
            admin_engine,
            fingerprint=definition.definition_fingerprint,
            activation_version=activation_version,
        )
        stale_fingerprint = _expect_rejected(
            lambda: gateway.open_gis_service_slo_incident(
                tenant_id=TENANT_A,
                service_urn=SERVICE_A,
                slo_definition_ref=SLO_REF,
                active_version_ref=SLO_VERSION,
                definition_fingerprint="f" * 64,
                approval_case_ref=approval.approval_case_ref,
                activation_version=activation_version,
                incident_id=uuid4(),
                dedupe_key="gis-slo-stale-fingerprint",
                incident_type="slo_error_budget_burn",
                severity=IncidentSeverity.CRITICAL,
                summary="must reject stale fingerprint",
                details=details,
                detected_by=DETECTOR,
            )
        )
        missing_binding = _expect_rejected(
            lambda: gateway.open_gis_service_slo_incident(
                tenant_id=TENANT_A,
                service_urn=SERVICE_A,
                slo_definition_ref=SLO_REF,
                active_version_ref=SLO_VERSION,
                definition_fingerprint=definition.definition_fingerprint,
                approval_case_ref=approval.approval_case_ref,
                activation_version=activation_version + 1,
                incident_id=uuid4(),
                dedupe_key="gis-slo-missing-binding",
                incident_type="slo_error_budget_burn",
                severity=IncidentSeverity.CRITICAL,
                summary="must reject missing exact binding",
                details=details,
                detected_by=DETECTOR,
            )
        )
        cross_tenant = False
        try:
            gateway.open_gis_service_slo_incident(
                tenant_id=TENANT_B,
                service_urn=SERVICE_A,
                slo_definition_ref=SLO_REF,
                active_version_ref=SLO_VERSION,
                definition_fingerprint=definition.definition_fingerprint,
                approval_case_ref=approval.approval_case_ref,
                activation_version=activation_version,
                incident_id=uuid4(),
                dedupe_key="gis-slo-cross-tenant",
                incident_type="slo_error_budget_burn",
                severity=IncidentSeverity.CRITICAL,
                summary="must reject cross tenant",
                details=details,
                detected_by=DETECTOR,
            )
        except GatewayForbiddenError:
            cross_tenant = True

        checks = {
            "postgres_major_16": postgres_version.startswith("16."),
            "incident_created": opened.created,
            "replay_idempotent": not replay.created and replay.value == opened.value,
            "resource_subject_without_run": (
                state["run_id"] is None and state["subject_resource_urn"] == SERVICE_A
            ),
            "shared_event_and_notification_outbox": (
                state["events"] == (0,)
                and len(state["notifications"]) == 1
                and state["notifications"][0]["status"] == "done"
            ),
            "provider_receipt_and_hash_recorded": (
                completed_notification.status.value == "done"
                and completed_notification.provider_receipt == receipt
                and completed_notification.receipt_sha256 is not None
                and len(completed_notification.receipt_sha256) == 64
                and state["notifications"][0]["receipt_sha256"]
                == completed_notification.receipt_sha256
            ),
            "invalid_provider_receipt_rejected": (
                invalid_receipt == GatewayValidationError.code
            ),
            "stale_fingerprint_rejected": (
                stale_fingerprint == GatewayValidationError.code
            ),
            "missing_exact_binding_rejected": (
                missing_binding == GatewayValidationError.code
            ),
            "cross_tenant_rejected": cross_tenant,
            "activation_update_blocked_while_incident_authority_locked": (
                activation_lock_sqlstate == "55P03"
            ),
            "gateway_has_no_binding_table_write": _security_contract(admin_engine)[
                "binding_insert"
            ] is False,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise AssertionError(f"GIS ServiceSLO incident certification failed: {failed}")
        return {
            "schema": "gda.gis_service_slo_incident_authority_certification.v1",
            "status": "verified",
            "postgres_version": postgres_version,
            "migration_count": len(MIGRATIONS),
            "incident_id": str(incident_id),
            "checks": checks,
            "security_contract": _security_contract(admin_engine),
        }
    finally:
        if runtime_engine is not None:
            runtime_engine.dispose()
        if admin_engine is not None:
            admin_engine.dispose()
        _docker("rm", "--force", container, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-image", default="gis-postgis-pgvector:16-3.4")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = certify(postgres_image=args.postgres_image)
    rendered = json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
