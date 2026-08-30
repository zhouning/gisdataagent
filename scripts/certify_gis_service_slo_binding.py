#!/usr/bin/env python3
"""Certify migration 223 against a disposable PostgreSQL database.

The certification deliberately exercises the database authorities instead of
only validating Python contracts: exact activation binding, replay, drift,
immutability, and forced tenant isolation.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

TENANT_A = "slo-gis-a"
TENANT_B = "slo-gis-b"
SERVICE_A = f"gda://{TENANT_A}/gis_service/district-features"
SERVICE_OTHER = f"gda://{TENANT_A}/gis_service/other-features"
SERVICE_B = f"gda://{TENANT_B}/gis_service/district-features"
SLO_REF = f"gda://{TENANT_A}/slo_definition/district-features-availability"
SLO_V1 = f"{SLO_REF}.v1"
SLO_V2 = f"{SLO_REF}.v2"
APPROVAL_V1 = f"gda://{TENANT_A}/approval_case/district-slo-v1"
APPROVAL_V2 = f"gda://{TENANT_A}/approval_case/district-slo-v2"
ACTOR = "workload:gis-slo-controller"
APPROVER = "human:gis-service-owner"
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


def _resource(
    connection: Any,
    *,
    tenant: str,
    urn: str,
    kind: str,
    authority_system: str = "gda",
    authority_locator: str | None = None,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO gda_control.resource (
                tenant_id, resource_urn, resource_kind, authority_system,
                authority_locator, owner_ref, governance_ref, technical_refs
            ) VALUES (
                :tenant, :urn, :kind, :authority_system, :locator,
                'team:geo-platform', '{}'::jsonb, '[]'::jsonb
            ) ON CONFLICT DO NOTHING
            """
        ),
        {
            "tenant": tenant,
            "urn": urn,
            "kind": kind,
            "authority_system": authority_system,
            "locator": authority_locator or urn,
        },
    )


def _seed_services(engine: Engine) -> None:
    with engine.begin() as connection:
        for tenant, service_urn in (
            (TENANT_A, SERVICE_A),
            (TENANT_A, SERVICE_OTHER),
            (TENANT_B, SERVICE_B),
        ):
            connection.execute(
                text("SELECT set_config('app.current_tenant', :tenant, true)"),
                {"tenant": tenant},
            )
            _resource(connection, tenant=tenant, urn=service_urn, kind="gis_service")
            connection.execute(
                text("SELECT set_config('gda.gis_service_record_allowed', '1', true)")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO gda_control.gis_service (
                        tenant_id, service_urn, created_at, updated_at
                    ) VALUES (:tenant, :service_urn, :now, :now)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"tenant": tenant, "service_urn": service_urn, "now": NOW},
            )


def _register_approver(engine: Engine) -> None:
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        connection.execute(
            text(
                """
                SELECT * FROM gda_control.upsert_approval_principal(
                    :tenant, :subject, 0, 'GIS service owner', 'active', true,
                    'available', :valid_from, :valid_until,
                    'human:platform-admin', 'register SLO certification approver'
                )
                """
            ),
            {
                "tenant": TENANT_A,
                "subject": APPROVER,
                "valid_from": NOW - timedelta(hours=1),
                "valid_until": NOW + timedelta(hours=4),
            },
        ).first()
        transaction.commit()
    except Exception:
        transaction.rollback()
        raise
    finally:
        connection.close()


def _indicator() -> dict[str, Any]:
    return {
        "kind": "event_success_ratio",
        "metric_name": "gda_gis_service_requests_total",
        "good_outcomes": ["success"],
        "bad_outcomes": ["error"],
        "match_labels": {"service": "district-features"},
    }


def _burn_policy() -> list[dict[str, Any]]:
    return [
        {
            "name": "fast",
            "short_window_seconds": 300,
            "long_window_seconds": 3600,
            "burn_rate_milli": 14400,
            "minimum_events": 20,
            "for_seconds": 120,
            "severity": "critical",
        }
    ]


def _stage(engine: Engine, *, version: int, version_ref: str) -> str:
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        fingerprint = connection.execute(
            text(
                """
                SELECT gda_control.stage_slo_definition_version(
                    :tenant, :definition_ref, :version_ref, :version,
                    :service_urn, CAST(:indicator AS jsonb), 9900, 86400,
                    'team:geo-platform', 'oncall:geo-platform',
                    CAST(:burn_policy AS jsonb), :created_by, :reason, :created_at
                )
                """
            ),
            {
                "tenant": TENANT_A,
                "definition_ref": SLO_REF,
                "version_ref": version_ref,
                "version": version,
                "service_urn": SERVICE_A,
                "indicator": json.dumps(_indicator(), sort_keys=True),
                "burn_policy": json.dumps(_burn_policy(), sort_keys=True),
                "created_by": ACTOR,
                "reason": "certify exact GIS ServiceSLO activation binding",
                "created_at": NOW,
            },
        ).scalar_one()
        transaction.commit()
        return str(fingerprint)
    except Exception:
        transaction.rollback()
        raise
    finally:
        connection.close()


def _create_approval(engine: Engine, approval_ref: str, version_ref: str, fingerprint: str) -> None:
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        _resource(
            connection,
            tenant=TENANT_A,
            urn=approval_ref,
            kind="approval_case",
            authority_system="gda_control",
            authority_locator=approval_ref,
        )
        connection.execute(
            text(
                """
                INSERT INTO gda_control.approval_case (
                    tenant_id, approval_case_ref, target_resource_urn,
                    target_fingerprint, action, requester_subject,
                    request_reason, request_context, status, state_version,
                    requested_at, expires_at, updated_at
                ) VALUES (
                    :tenant, :approval_ref, :version_ref, :fingerprint,
                    'slo_definition.activate', :requester,
                    'approve the exact GIS service objective', '{}'::jsonb,
                    'pending', 0, :requested_at, :expires_at, :requested_at
                ) ON CONFLICT DO NOTHING
                """
            ),
            {
                "tenant": TENANT_A,
                "approval_ref": approval_ref,
                "version_ref": version_ref,
                "fingerprint": fingerprint,
                "requester": ACTOR,
                "requested_at": NOW,
                "expires_at": NOW + timedelta(hours=4),
            },
        )
        connection.execute(
            text(
                """
                SELECT gda_control.transition_approval_case(
                    :tenant, :approval_ref, 0, 'approved', :approver,
                    'approved for GIS ServiceSLO certification', '{}'::jsonb
                )
                """
            ),
            {"tenant": TENANT_A, "approval_ref": approval_ref, "approver": APPROVER},
        )
        transaction.commit()
    except Exception:
        transaction.rollback()
        raise
    finally:
        connection.close()


def _activate(
    engine: Engine,
    version_ref: str,
    fingerprint: str,
    approval_ref: str,
    expected: int,
) -> int:
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        value = connection.execute(
            text(
                """
                SELECT gda_control.activate_slo_definition_version(
                    :tenant, :version_ref, :fingerprint, :approval_ref,
                    :expected, :actor, 'activate exact GIS ServiceSLO objective'
                )
                """
            ),
            {
                "tenant": TENANT_A,
                "version_ref": version_ref,
                "fingerprint": fingerprint,
                "approval_ref": approval_ref,
                "expected": expected,
                "actor": ACTOR,
            },
        ).scalar_one()
        transaction.commit()
        return int(value)
    except Exception:
        transaction.rollback()
        raise
    finally:
        connection.close()


def _bind(
    engine: Engine,
    *,
    binding_id: UUID,
    service_urn: str = SERVICE_A,
    version_ref: str = SLO_V1,
    fingerprint: str,
    approval_ref: str = APPROVAL_V1,
    activation_version: int = 1,
) -> UUID:
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        value = connection.execute(
            text(
                """
                SELECT gda_control.bind_gis_service_slo(
                    :tenant, CAST(:binding_id AS uuid), :service_urn,
                    :definition_ref, :version_ref, :fingerprint,
                    :approval_ref, :activation_version, :bound_by,
                    'bind the exact approved GIS service objective', :bound_at
                )
                """
            ),
            {
                "tenant": TENANT_A,
                "binding_id": str(binding_id),
                "service_urn": service_urn,
                "definition_ref": SLO_REF,
                "version_ref": version_ref,
                "fingerprint": fingerprint,
                "approval_ref": approval_ref,
                "activation_version": activation_version,
                "bound_by": "human:gis-service-owner",
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
    except DBAPIError as exc:
        original = getattr(exc, "orig", None)
        return str(
            getattr(original, "sqlstate", None)
            or getattr(original, "pgcode", None)
            or "db-error"
        )
    raise AssertionError("operation unexpectedly succeeded")


def _active_count(engine: Engine, tenant: str, service_urn: str) -> int:
    connection, transaction = _gateway_connection(engine, tenant)
    try:
        value = connection.execute(
            text(
                """
                SELECT count(*)
                FROM gda_control.gis_service_slo_binding b
                JOIN gda_control.slo_definition_activation a
                  ON a.tenant_id = b.tenant_id
                 AND a.slo_definition_ref = b.slo_definition_ref
                 AND a.active_version_ref = b.active_version_ref
                 AND a.active_fingerprint = b.definition_fingerprint
                 AND a.approval_case_ref = b.approval_case_ref
                 AND a.activation_version = b.activation_version
                WHERE b.tenant_id = :tenant AND b.service_urn = :service_urn
                """
            ),
            {"tenant": tenant, "service_urn": service_urn},
        ).scalar_one()
        transaction.commit()
        return int(value)
    finally:
        connection.close()


def _security_contract(engine: Engine) -> dict[str, bool]:
    with engine.connect() as connection:
        values = connection.execute(
            text(
                """
                SELECT
                    c.relrowsecurity,
                    c.relforcerowsecurity,
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.gis_service_slo_binding', 'SELECT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.gis_service_slo_binding', 'INSERT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.gis_service_slo_binding', 'UPDATE'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.gis_service_slo_binding', 'DELETE'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.bind_gis_service_slo('
                        'text,uuid,text,text,text,text,text,integer,text,text,'
                        'timestamp with time zone)',
                        'EXECUTE'
                    )
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'gda_control'
                  AND c.relname = 'gis_service_slo_binding'
                """
            )
        ).one()
    return {
        "rls_enabled": bool(values[0]),
        "rls_forced": bool(values[1]),
        "gateway_select": bool(values[2]),
        "gateway_insert": bool(values[3]),
        "gateway_update": bool(values[4]),
        "gateway_delete": bool(values[5]),
        "gateway_bind_execute": bool(values[6]),
    }


def certify(engine: Engine) -> dict[str, Any]:
    _seed_services(engine)
    _register_approver(engine)
    fingerprint_v1 = _stage(engine, version=1, version_ref=SLO_V1)
    _create_approval(engine, APPROVAL_V1, SLO_V1, fingerprint_v1)
    activation_v1 = _activate(engine, SLO_V1, fingerprint_v1, APPROVAL_V1, 0)

    binding_id = uuid4()
    first = _bind(engine, binding_id=binding_id, fingerprint=fingerprint_v1)
    replay = _bind(engine, binding_id=binding_id, fingerprint=fingerprint_v1)

    mismatch_sqlstate = _expect_rejected(
        lambda: _bind(
            engine,
            binding_id=uuid4(),
            service_urn=SERVICE_OTHER,
            fingerprint=fingerprint_v1,
        )
    )
    stale_fingerprint_sqlstate = _expect_rejected(
        lambda: _bind(engine, binding_id=uuid4(), fingerprint="f" * 64)
    )
    stale_approval_sqlstate = _expect_rejected(
        lambda: _bind(
            engine,
            binding_id=uuid4(),
            fingerprint=fingerprint_v1,
            approval_ref=APPROVAL_V2,
        )
    )
    stale_version_sqlstate = _expect_rejected(
        lambda: _bind(
            engine,
            binding_id=uuid4(),
            fingerprint=fingerprint_v1,
            activation_version=2,
        )
    )

    direct_insert_sqlstate = _expect_rejected(
        lambda: _direct_insert(engine, binding_id=uuid4())
    )
    direct_update_sqlstate = _expect_rejected(lambda: _direct_update(engine, binding_id))
    direct_delete_sqlstate = _expect_rejected(lambda: _direct_delete(engine, binding_id))
    owner_update_trigger_sqlstate = _expect_rejected(
        lambda: _owner_update(engine, binding_id)
    )
    owner_delete_trigger_sqlstate = _expect_rejected(
        lambda: _owner_delete(engine, binding_id)
    )

    cross_tenant_rows = _visible_rows(engine, TENANT_B)
    security_contract = _security_contract(engine)
    active_before = _active_count(engine, TENANT_A, SERVICE_A)

    fingerprint_v2 = _stage(engine, version=2, version_ref=SLO_V2)
    _create_approval(engine, APPROVAL_V2, SLO_V2, fingerprint_v2)
    activation_v2 = _activate(engine, SLO_V2, fingerprint_v2, APPROVAL_V2, activation_v1)
    active_after = _active_count(engine, TENANT_A, SERVICE_A)
    binding_v2 = _bind(
        engine,
        binding_id=uuid4(),
        version_ref=SLO_V2,
        fingerprint=fingerprint_v2,
        approval_ref=APPROVAL_V2,
        activation_version=activation_v2,
    )
    active_after_rebind = _active_count(engine, TENANT_A, SERVICE_A)

    return {
        "schema": "gda.gis_service_slo_binding_certification.v1",
        "database": str(engine.url.database),
        "tenant_a": TENANT_A,
        "tenant_b": TENANT_B,
        "binding_id": str(first),
        "binding_v2_id": str(binding_v2),
        "replay_binding_id": str(replay),
        "replay_same_identity": first == replay,
        "fingerprint_v1": fingerprint_v1,
        "fingerprint_v2": fingerprint_v2,
        "activation_v1": activation_v1,
        "activation_v2": activation_v2,
        "active_count_before_activation_change": active_before,
        "active_count_after_activation_change": active_after,
        "active_count_after_v2_rebind": active_after_rebind,
        "cross_tenant_visible_rows": cross_tenant_rows,
        "security_contract": security_contract,
        "mismatch_sqlstate": mismatch_sqlstate,
        "stale_fingerprint_sqlstate": stale_fingerprint_sqlstate,
        "stale_approval_sqlstate": stale_approval_sqlstate,
        "stale_activation_version_sqlstate": stale_version_sqlstate,
        "direct_insert_sqlstate": direct_insert_sqlstate,
        "direct_update_sqlstate": direct_update_sqlstate,
        "direct_delete_sqlstate": direct_delete_sqlstate,
        "owner_update_trigger_sqlstate": owner_update_trigger_sqlstate,
        "owner_delete_trigger_sqlstate": owner_delete_trigger_sqlstate,
    }


def _direct_insert(engine: Engine, *, binding_id: UUID) -> None:
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        connection.execute(
            text(
                """
                INSERT INTO gda_control.gis_service_slo_binding (
                    tenant_id, binding_id, service_urn, slo_definition_ref,
                    active_version_ref, definition_fingerprint, approval_case_ref,
                    activation_version, bound_by, binding_reason, bound_at
                ) VALUES (
                    :tenant, :binding_id, :service, :definition, :version,
                    :fingerprint, :approval, 1, 'human:test', 'direct write', :now
                )
                """
            ),
            {
                "tenant": TENANT_A,
                "binding_id": str(binding_id),
                "service": SERVICE_A,
                "definition": SLO_REF,
                "version": SLO_V1,
                "fingerprint": "0" * 64,
                "approval": APPROVAL_V1,
                "now": NOW,
            },
        )
        transaction.commit()
    finally:
        connection.close()


def _direct_update(engine: Engine, binding_id: UUID) -> None:
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        connection.execute(
            text(
                "UPDATE gda_control.gis_service_slo_binding "
                "SET binding_reason = 'mutated' WHERE binding_id = :id"
            ),
            {"id": str(binding_id)},
        )
        transaction.commit()
    finally:
        connection.close()


def _direct_delete(engine: Engine, binding_id: UUID) -> None:
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        connection.execute(
            text("DELETE FROM gda_control.gis_service_slo_binding WHERE binding_id = :id"),
            {"id": str(binding_id)},
        )
        transaction.commit()
    finally:
        connection.close()


def _owner_update(engine: Engine, binding_id: UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": TENANT_A},
        )
        connection.execute(
            text(
                "UPDATE gda_control.gis_service_slo_binding "
                "SET binding_reason = 'owner mutation' WHERE binding_id = :id"
            ),
            {"id": str(binding_id)},
        )


def _owner_delete(engine: Engine, binding_id: UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant, true)"),
            {"tenant": TENANT_A},
        )
        connection.execute(
            text(
                "DELETE FROM gda_control.gis_service_slo_binding "
                "WHERE binding_id = :id"
            ),
            {"id": str(binding_id)},
        )


def _visible_rows(engine: Engine, tenant: str) -> int:
    connection, transaction = _gateway_connection(engine, tenant)
    try:
        value = connection.execute(
            text("SELECT count(*) FROM gda_control.gis_service_slo_binding")
        ).scalar_one()
        transaction.commit()
        return int(value)
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "GDA_CERT_DATABASE_URL",
            "postgresql+psycopg2://postgres:postgres@127.0.0.1:5433/gda_223_cert",
        ),
    )
    args = parser.parse_args()
    engine = create_engine(args.database_url)
    print(json.dumps(certify(engine), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
