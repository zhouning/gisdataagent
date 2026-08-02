#!/usr/bin/env python3
"""Certify the source schema drift ledger in an isolated PostgreSQL database."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import dotenv_values
from psycopg2 import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from data_agent.approval_case_authority import (
    ApprovalCaseAuthority,
    ApprovalCaseConflictError,
    ApprovalCaseNotFoundError,
    ApprovalCaseValidationError,
)
from data_agent.connectors.database import _connection_url
from data_agent.platform_contracts import ApprovalCase, ApprovalCaseStatus, build_resource_urn
from data_agent.platform_gateway import PlatformGateway
from data_agent.source_connector_governance import (
    DiscoveredResource,
    DiscoverySnapshot,
    ProfileField,
    detect_schema_drift,
)
from data_agent.source_schema_drift_ledger import (
    SchemaDriftStatus,
    SourceSchemaDriftConflictError,
    SourceSchemaDriftLedger,
    SourceSchemaDriftNotFoundError,
    SourceSchemaDriftValidationError,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = REPO_ROOT / ".tmp/source-connector-certification/drift-ledger-report.json"
MIGRATIONS = (
    REPO_ROOT / "data_agent/migrations/092_platform_control_ledger.sql",
    REPO_ROOT / "data_agent/migrations/094_platform_control_gateway.sql",
    REPO_ROOT / "data_agent/migrations/102_source_schema_drift_ledger.sql",
    REPO_ROOT / "data_agent/migrations/103_unified_approval_case_authority.sql",
)


def _settings() -> dict[str, str]:
    values = {
        key: str(value)
        for key, value in dotenv_values(REPO_ROOT / ".env").items()
        if value is not None
    }
    return {**values, **os.environ}


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class _PostgresDatabaseSandbox:
    """Own one random database and remove only that exact database."""

    def __init__(self, admin_url: str) -> None:
        self.database = f"gda_drift_cert_{secrets.token_hex(5)}"
        parsed = make_url(admin_url)
        self.database_url = parsed.set(database=self.database).render_as_string(hide_password=False)
        maintenance_url = parsed.set(database="postgres").render_as_string(hide_password=False)
        self._maintenance = psycopg2.connect(maintenance_url)
        self._maintenance.autocommit = True
        self._created = False
        self.engine = None

    def setup(self) -> None:
        with self._maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)",
                ("gda_control_gateway",),
            )
            if not cursor.fetchone()[0]:
                raise RuntimeError("gda_control_gateway role must preexist")
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)",
                (self.database,),
            )
            if cursor.fetchone()[0]:
                raise RuntimeError("random certification database already exists")
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database)))
            self._created = True

        self.engine = create_engine(self.database_url, pool_size=1, max_overflow=0)
        with self.engine.begin() as connection:
            for migration in MIGRATIONS:
                connection.execute(text(migration.read_text(encoding="utf-8")))

    def cleanup(self) -> dict[str, bool]:
        if self.engine is not None:
            self.engine.dispose()
        with self._maintenance.cursor() as cursor:
            if self._created:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (self.database,),
                )
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(self.database)))
            cursor.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)",
                (self.database,),
            )
            database_removed = bool(cursor.fetchone()[0])
        self._maintenance.close()
        return {"database_removed": database_removed}


def _drift_events():
    initial = DiscoverySnapshot(
        provider="PostgreSQL",
        provider_version="16.14",
        resources=(
            DiscoveredResource(
                name="certification.source_asset",
                resource_type="table",
                fields=(
                    ProfileField(name="id", data_type="INTEGER", nullable=False),
                    ProfileField(name="name", data_type="TEXT", nullable=False),
                ),
            ),
        ),
    )
    additive = initial.model_copy(
        update={
            "resources": (
                initial.resources[0].model_copy(
                    update={
                        "fields": initial.resources[0].fields
                        + (
                            ProfileField(
                                name="observed_at",
                                data_type="TIMESTAMP",
                                nullable=True,
                            ),
                        )
                    }
                ),
            )
        }
    )
    breaking = additive.model_copy(
        update={
            "resources": (
                additive.resources[0].model_copy(
                    update={
                        "fields": (
                            ProfileField(name="id", data_type="BIGINT", nullable=False),
                            *additive.resources[0].fields[1:],
                        )
                    }
                ),
            )
        }
    )
    additive_event = detect_schema_drift("drift-ledger-certification", initial, additive)
    breaking_event = detect_schema_drift("drift-ledger-certification", additive, breaking)
    if additive_event is None or breaking_event is None:
        raise RuntimeError("certification drift fixtures did not produce events")
    rejected_event = breaking_event.model_copy(
        update={"source_id": "drift-ledger-rejection-certification"}
    )
    return additive_event, breaking_event, rejected_event


def _direct_update_denied(engine, tenant_id: str, drift_event_id: str) -> bool:
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": tenant_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE gda_control.source_schema_drift
                    SET status = 'reconciled', state_version = state_version + 1
                    WHERE tenant_id = :tenant_id
                      AND drift_event_id = :drift_event_id
                    """
                ),
                {"tenant_id": tenant_id, "drift_event_id": drift_event_id},
            )
    except DBAPIError as exc:
        return _sqlstate(exc) in {"42501", "55000"}
    return False


def _approval_direct_update_denied(
    engine,
    tenant_id: str,
    approval_case_ref: str,
) -> bool:
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql('SET LOCAL ROLE "gda_control_gateway"')
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": tenant_id},
            )
            connection.execute(
                text(
                    """
                    UPDATE gda_control.approval_case
                    SET status = 'approved', state_version = state_version + 1
                    WHERE tenant_id = :tenant_id
                      AND approval_case_ref = :approval_case_ref
                    """
                ),
                {"tenant_id": tenant_id, "approval_case_ref": approval_case_ref},
            )
    except DBAPIError as exc:
        return _sqlstate(exc) in {"42501", "55000"}
    return False


def _privileges(engine) -> dict[str, bool]:
    with engine.connect() as connection:
        values = connection.execute(
            text(
                """
                SELECT
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.source_schema_drift', 'SELECT,INSERT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.source_schema_drift', 'UPDATE'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.source_schema_drift_lifecycle_event', 'INSERT'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.transition_source_schema_drift(text,text,integer,text,text,text,text,jsonb)',
                        'EXECUTE'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case', 'SELECT,INSERT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case', 'UPDATE'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.approval_case_event', 'INSERT'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.transition_approval_case(text,text,integer,text,text,text,jsonb)',
                        'EXECUTE'
                    )
                """
            )
        ).one()
        connection.rollback()
    return {
        "base_select_insert": bool(values[0]),
        "base_update_denied": not bool(values[1]),
        "lifecycle_insert_denied": not bool(values[2]),
        "transition_execute": bool(values[3]),
        "approval_base_select_insert": bool(values[4]),
        "approval_base_update_denied": not bool(values[5]),
        "approval_event_insert_denied": not bool(values[6]),
        "approval_transition_execute": bool(values[7]),
    }


def _approval_case(
    *,
    tenant_id: str,
    case_id: str,
    drift_event_id: str,
    requested_at: datetime,
    target_event_id: str | None = None,
) -> ApprovalCase:
    target_id = target_event_id or drift_event_id
    return ApprovalCase(
        tenant_id=tenant_id,
        approval_case_ref=build_resource_urn(tenant_id, "approval_case", case_id),
        target_resource_urn=build_resource_urn(tenant_id, "schema_drift", target_id),
        target_fingerprint=target_id,
        action="source_schema_drift.reconcile",
        requester_subject="workload:connector-certification",
        request_reason="breaking schema drift requires a human verdict",
        request_context={"drift_event_id": drift_event_id},
        requested_at=requested_at,
        expires_at=requested_at + timedelta(hours=1),
    )


def _certify(engine) -> dict[str, Any]:
    tenant_a = "drift-cert-a"
    tenant_b = "drift-cert-b"
    definition_fingerprint = "f" * 64
    detected_at = datetime.now(UTC)
    ledger = SourceSchemaDriftLedger(engine)
    approval_authority = ApprovalCaseAuthority(engine)
    additive_event, breaking_event, rejected_event = _drift_events()

    additive_first = ledger.record(
        tenant_id=tenant_a,
        source_definition_fingerprint=definition_fingerprint,
        event=additive_event,
        detected_by="workload:connector-certification",
        detected_at=detected_at,
    )
    additive_replay = ledger.record(
        tenant_id=tenant_a,
        source_definition_fingerprint=definition_fingerprint,
        event=additive_event,
        detected_by="workload:connector-certification",
        detected_at=detected_at,
    )
    additive_reconciled = ledger.transition(
        tenant_id=tenant_a,
        drift_event_id=additive_event.event_id,
        expected_state_version=0,
        to_status=SchemaDriftStatus.RECONCILED,
        actor_subject="workload:schema-reconciler",
        reason="non-breaking drift observed and reconciled",
        details={"schema": "gda.schema_drift_reconciliation.v1"},
    )
    stale_cas_failed = False
    try:
        ledger.transition(
            tenant_id=tenant_a,
            drift_event_id=additive_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.RECONCILED,
            actor_subject="workload:schema-reconciler",
            reason="stale replay",
        )
    except SourceSchemaDriftConflictError:
        stale_cas_failed = True

    breaking_first = ledger.record(
        tenant_id=tenant_a,
        source_definition_fingerprint=definition_fingerprint,
        event=breaking_event,
        detected_by="workload:connector-certification",
        detected_at=detected_at,
    )
    rejected_first = ledger.record(
        tenant_id=tenant_a,
        source_definition_fingerprint=definition_fingerprint,
        event=rejected_event,
        detected_by="workload:connector-certification",
        detected_at=detected_at,
    )
    approval_bypass_failed = False
    try:
        ledger.transition(
            tenant_id=tenant_a,
            drift_event_id=breaking_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.RECONCILED,
            actor_subject="workload:schema-reconciler",
            reason="must not bypass approval",
        )
    except SourceSchemaDriftValidationError:
        approval_bypass_failed = True

    missing_approval_ref_failed = False
    try:
        ledger.transition(
            tenant_id=tenant_a,
            drift_event_id=breaking_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.APPROVED,
            actor_subject="human:data-steward",
            reason="missing external approval reference",
        )
    except SourceSchemaDriftValidationError:
        missing_approval_ref_failed = True

    unregistered_approval_ref_failed = False
    try:
        ledger.transition(
            tenant_id=tenant_a,
            drift_event_id=breaking_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.APPROVED,
            actor_subject="human:data-steward",
            reason="must not trust an unregistered case reference",
            approval_case_ref=build_resource_urn(
                tenant_a,
                "approval_case",
                "unregistered-drift-certification",
            ),
        )
    except SourceSchemaDriftValidationError:
        unregistered_approval_ref_failed = True

    wrong_target_case = _approval_case(
        tenant_id=tenant_a,
        case_id="wrong-target-drift-certification",
        drift_event_id=breaking_event.event_id,
        target_event_id="d" * 64,
        requested_at=detected_at,
    )
    approval_authority.create(wrong_target_case, owner_ref="team:data-platform")
    wrong_target_reason = "approved for a different immutable target"
    approval_authority.decide(
        tenant_id=tenant_a,
        approval_case_ref=wrong_target_case.approval_case_ref,
        expected_state_version=0,
        verdict=ApprovalCaseStatus.APPROVED,
        actor_subject="human:data-steward",
        reason=wrong_target_reason,
    )
    wrong_target_failed = False
    try:
        ledger.transition(
            tenant_id=tenant_a,
            drift_event_id=breaking_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.APPROVED,
            actor_subject="human:data-steward",
            reason=wrong_target_reason,
            approval_case_ref=wrong_target_case.approval_case_ref,
        )
    except SourceSchemaDriftValidationError:
        wrong_target_failed = True

    rejected_case = _approval_case(
        tenant_id=tenant_a,
        case_id="rejected-drift-certification",
        drift_event_id=breaking_event.event_id,
        requested_at=detected_at,
    )
    approval_authority.create(rejected_case, owner_ref="team:data-platform")
    rejected_reason = "schema compatibility plan is insufficient"
    approval_authority.decide(
        tenant_id=tenant_a,
        approval_case_ref=rejected_case.approval_case_ref,
        expected_state_version=0,
        verdict=ApprovalCaseStatus.REJECTED,
        actor_subject="human:data-steward",
        reason=rejected_reason,
    )
    wrong_verdict_failed = False
    try:
        ledger.transition(
            tenant_id=tenant_a,
            drift_event_id=breaking_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.APPROVED,
            actor_subject="human:data-steward",
            reason=rejected_reason,
            approval_case_ref=rejected_case.approval_case_ref,
        )
    except SourceSchemaDriftValidationError:
        wrong_verdict_failed = True

    rejected_drift_case = _approval_case(
        tenant_id=tenant_a,
        case_id="consumed-rejection-drift-certification",
        drift_event_id=rejected_event.event_id,
        requested_at=detected_at,
    )
    approval_authority.create(rejected_drift_case, owner_ref="team:data-platform")
    consumed_rejection_reason = "breaking migration plan was rejected"
    approval_authority.decide(
        tenant_id=tenant_a,
        approval_case_ref=rejected_drift_case.approval_case_ref,
        expected_state_version=0,
        verdict=ApprovalCaseStatus.REJECTED,
        actor_subject="human:data-steward",
        reason=consumed_rejection_reason,
    )
    rejected_drift = ledger.transition(
        tenant_id=tenant_a,
        drift_event_id=rejected_event.event_id,
        expected_state_version=0,
        to_status=SchemaDriftStatus.REJECTED,
        actor_subject="human:data-steward",
        reason=consumed_rejection_reason,
        approval_case_ref=rejected_drift_case.approval_case_ref,
    )

    expired_case = _approval_case(
        tenant_id=tenant_a,
        case_id="expired-drift-certification",
        drift_event_id=breaking_event.event_id,
        requested_at=detected_at - timedelta(hours=2),
    )
    approval_authority.create(expired_case, owner_ref="team:data-platform")
    expired_case_failed = False
    try:
        approval_authority.decide(
            tenant_id=tenant_a,
            approval_case_ref=expired_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:data-steward",
            reason="expired case must not authorize a verdict",
        )
    except ApprovalCaseValidationError:
        expired_case_failed = True

    approval_case = _approval_case(
        tenant_id=tenant_a,
        case_id="approved-drift-certification",
        drift_event_id=breaking_event.event_id,
        requested_at=detected_at,
    )
    case_first = approval_authority.create(
        approval_case,
        owner_ref="team:data-platform",
    )
    case_replay = approval_authority.create(
        approval_case,
        owner_ref="team:data-platform",
    )
    pending_case_failed = False
    approval_reason = "external ApprovalCase approved the migration"
    try:
        ledger.transition(
            tenant_id=tenant_a,
            drift_event_id=breaking_event.event_id,
            expected_state_version=0,
            to_status=SchemaDriftStatus.APPROVED,
            actor_subject="human:data-steward",
            reason=approval_reason,
            approval_case_ref=approval_case.approval_case_ref,
        )
    except SourceSchemaDriftValidationError:
        pending_case_failed = True

    requester_approval_failed = False
    try:
        approval_authority.decide(
            tenant_id=tenant_a,
            approval_case_ref=approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject=approval_case.requester_subject,
            reason="requester must not approve its own case",
        )
    except ApprovalCaseValidationError:
        requester_approval_failed = True

    approved_case = approval_authority.decide(
        tenant_id=tenant_a,
        approval_case_ref=approval_case.approval_case_ref,
        expected_state_version=0,
        verdict=ApprovalCaseStatus.APPROVED,
        actor_subject="human:data-steward",
        reason=approval_reason,
        details={"schema": "gda.approval_case_decision.v1"},
    )
    decided_case_replay = approval_authority.create(
        approval_case,
        owner_ref="team:data-platform",
    )
    stale_case_cas_failed = False
    try:
        approval_authority.decide(
            tenant_id=tenant_a,
            approval_case_ref=approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.REJECTED,
            actor_subject="human:data-steward",
            reason="stale approval replay",
        )
    except ApprovalCaseConflictError:
        stale_case_cas_failed = True

    approval_case_ref = approval_case.approval_case_ref
    breaking_approved = ledger.transition(
        tenant_id=tenant_a,
        drift_event_id=breaking_event.event_id,
        expected_state_version=0,
        to_status=SchemaDriftStatus.APPROVED,
        actor_subject="human:data-steward",
        reason=approval_reason,
        approval_case_ref=approval_case_ref,
        details={"schema": "gda.external_approval_binding.v1"},
    )
    breaking_reconciled = ledger.transition(
        tenant_id=tenant_a,
        drift_event_id=breaking_event.event_id,
        expected_state_version=1,
        to_status=SchemaDriftStatus.RECONCILED,
        actor_subject="workload:schema-reconciler",
        reason="approved drift reconciled",
        details={"schema": "gda.schema_drift_reconciliation.v1"},
    )

    additive_lifecycle = ledger.lifecycle(tenant_a, additive_event.event_id)
    breaking_lifecycle = ledger.lifecycle(tenant_a, breaking_event.event_id)
    approval_events = approval_authority.events(tenant_a, approval_case_ref)
    approval_resource = PlatformGateway(engine).get_resource(tenant_a, approval_case_ref)
    tenant_isolated = False
    try:
        ledger.get(tenant_b, additive_event.event_id)
    except SourceSchemaDriftNotFoundError:
        tenant_isolated = True
    approval_tenant_isolated = False
    try:
        approval_authority.get(tenant_b, approval_case_ref)
    except ApprovalCaseNotFoundError:
        approval_tenant_isolated = True
    tenant_b_write = ledger.record(
        tenant_id=tenant_b,
        source_definition_fingerprint=definition_fingerprint,
        event=additive_event,
        detected_by="workload:connector-certification",
        detected_at=detected_at,
    )
    privilege_checks = _privileges(engine)

    checks = {
        "additive_recorded_observed": (
            additive_first.created
            and additive_first.drift.status is SchemaDriftStatus.OBSERVED
            and additive_first.drift.state_version == 0
        ),
        "duplicate_record_idempotent": (
            not additive_replay.created
            and additive_replay.drift.drift_event_id == additive_event.event_id
        ),
        "additive_reconciled": (
            additive_reconciled.status is SchemaDriftStatus.RECONCILED
            and additive_reconciled.state_version == 1
            and [entry.to_status for entry in additive_lifecycle]
            == [SchemaDriftStatus.OBSERVED, SchemaDriftStatus.RECONCILED]
        ),
        "stale_cas_failed": stale_cas_failed,
        "breaking_requires_approval": (
            breaking_first.created
            and breaking_first.drift.status is SchemaDriftStatus.APPROVAL_REQUIRED
            and approval_bypass_failed
            and missing_approval_ref_failed
            and unregistered_approval_ref_failed
            and wrong_target_failed
            and wrong_verdict_failed
            and pending_case_failed
        ),
        "approval_case_authority_bound": (
            case_first.created
            and not case_replay.created
            and approved_case.status is ApprovalCaseStatus.APPROVED
            and approved_case.state_version == 1
            and not decided_case_replay.created
            and decided_case_replay.approval_case == approved_case
            and requester_approval_failed
            and expired_case_failed
            and stale_case_cas_failed
            and [event.to_status for event in approval_events]
            == [ApprovalCaseStatus.PENDING, ApprovalCaseStatus.APPROVED]
            and approval_resource.resource_kind == "approval_case"
            and approval_resource.authority_system == "gda_control"
            and approval_resource.governance_ref["target_fingerprint"]
            == breaking_event.event_id
        ),
        "rejected_case_consumed": (
            rejected_first.created
            and rejected_drift.status is SchemaDriftStatus.REJECTED
            and rejected_drift.state_version == 1
        ),
        "breaking_approval_bound": (
            breaking_approved.status is SchemaDriftStatus.APPROVED
            and breaking_reconciled.status is SchemaDriftStatus.RECONCILED
            and breaking_reconciled.state_version == 2
            and [entry.to_status for entry in breaking_lifecycle]
            == [
                SchemaDriftStatus.APPROVAL_REQUIRED,
                SchemaDriftStatus.APPROVED,
                SchemaDriftStatus.RECONCILED,
            ]
            and breaking_lifecycle[1].approval_case_ref == approval_case_ref
        ),
        "direct_update_denied": (
            _direct_update_denied(engine, tenant_a, additive_event.event_id)
            and _approval_direct_update_denied(engine, tenant_a, approval_case_ref)
        ),
        "tenant_isolation_enforced": (
            tenant_isolated and approval_tenant_isolated and tenant_b_write.created
        ),
        "gateway_least_privilege": all(privilege_checks.values()),
    }
    return {
        "schema": "gda.source_schema_drift_ledger.acceptance.v1",
        "generated_at": detected_at.isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "migrations": [migration.name for migration in MIGRATIONS],
        "gateway_privileges": privilege_checks,
        "approval_case": {
            "approval_case_ref": approval_case_ref,
            "target_resource_urn": approved_case.target_resource_urn,
            "target_fingerprint": approved_case.target_fingerprint,
            "action": approved_case.action,
            "created": case_first.created,
            "replay_created": case_replay.created,
            "decided_replay_created": decided_case_replay.created,
            "status": approved_case.status.value,
            "state_version": approved_case.state_version,
            "resource": approval_resource.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in approval_events],
            "rejected_case_ref": rejected_drift_case.approval_case_ref,
            "rejected_drift_event_id": rejected_event.event_id,
            "rejected_drift_status": rejected_drift.status.value,
        },
        "additive": {
            "event_id": additive_event.event_id,
            "created": additive_first.created,
            "replay_created": additive_replay.created,
            "final_status": additive_reconciled.status.value,
            "state_version": additive_reconciled.state_version,
            "lifecycle": [entry.model_dump(mode="json") for entry in additive_lifecycle],
        },
        "breaking": {
            "event_id": breaking_event.event_id,
            "initial_status": breaking_first.drift.status.value,
            "final_status": breaking_reconciled.status.value,
            "state_version": breaking_reconciled.state_version,
            "approval_case_ref": approval_case_ref,
            "lifecycle": [entry.model_dump(mode="json") for entry in breaking_lifecycle],
        },
        "not_claimed": [
            "ApprovalCase Inbox API, delegation, notification, or SLA timeout automation",
            "PlatformRun, publication, and sensitive-operation ApprovalCase consumers",
            "automatic provider schema migration",
            "object-storage or STAC schema drift detection",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--postgres-url",
        default="postgresql://127.0.0.1:5433/gis_agent",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    settings = _settings()
    admin_auth = {
        "type": "basic",
        "username": settings.get("POSTGRES_USER", "postgres"),
        "password": settings.get(
            "POSTGRES_ADMIN_PASSWORD",
            settings.get("POSTGRES_PASSWORD", "postgres"),
        ),
    }
    sandbox = _PostgresDatabaseSandbox(_connection_url(args.postgres_url, admin_auth))
    report: dict[str, Any] | None = None
    cleanup: dict[str, bool] = {}
    try:
        sandbox.setup()
        if sandbox.engine is None:
            raise RuntimeError("certification database engine was not created")
        report = _certify(sandbox.engine)
        report["sandbox"] = {"database": sandbox.database, "persistent": False}
    finally:
        cleanup = sandbox.cleanup()
    if report is None:
        raise RuntimeError("schema drift ledger certification did not produce a report")
    report["cleanup"] = cleanup
    if not all(cleanup.values()):
        report["status"] = "failed"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.report),
                "checks": report["checks"],
                "cleanup": cleanup,
            },
            sort_keys=True,
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
