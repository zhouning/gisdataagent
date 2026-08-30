#!/usr/bin/env python3
"""Certify migration 224 against PostgreSQL 16.

The certification exercises the production boundary: generic SLO activation
creates one durable projection task, a leased worker rechecks exact authority,
and migration 223 remains the only binding authority.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from certify_gis_service_slo_binding import (
    NOW,
    SERVICE_A,
    TENANT_A,
    TENANT_B,
    _activate,
    _create_approval,
    _gateway_connection,
    _register_approver,
    _seed_services,
    _stage,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

WORKER = "worker:gis-slo-reconciliation:cert"
WORKLOAD = "workload:gis-slo-binding-controller"
SLO_REF = f"gda://{TENANT_A}/slo_definition/district-features-availability"


def _sqlstate(exc: DBAPIError) -> str:
    original = getattr(exc, "orig", None)
    return str(
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
        or "db-error"
    )


def _expect_rejected(callback) -> str:
    try:
        callback()
    except DBAPIError as exc:
        return _sqlstate(exc)
    raise AssertionError("operation unexpectedly succeeded")


def _query(
    engine: Engine,
    tenant: str,
    statement: str,
    parameters: dict[str, Any] | None = None,
):
    connection, transaction = _gateway_connection(engine, tenant)
    try:
        value = connection.execute(text(statement), parameters or {})
        result = value.mappings().all() if value.returns_rows else []
        transaction.commit()
        return result
    except Exception:
        transaction.rollback()
        raise
    finally:
        connection.close()


def _claim(engine: Engine, *, worker: str = WORKER, lease_seconds: int = 60):
    rows = _query(
        engine,
        TENANT_A,
        """
        SELECT * FROM gda_control.claim_gis_service_slo_reconciliations(
            :tenant, :actor, :worker, :limit, :lease
        )
        """,
        {
            "tenant": TENANT_A,
            "actor": WORKLOAD,
            "worker": worker,
            "limit": 20,
            "lease": lease_seconds,
        },
    )
    return rows


def _complete(engine: Engine, task_id: UUID, *, worker: str = WORKER):
    rows = _query(
        engine,
        TENANT_A,
        """
        SELECT * FROM gda_control.complete_gis_service_slo_reconciliation(
            :tenant, CAST(:task_id AS uuid), :worker, :bound_at
        )
        """,
        {
            "tenant": TENANT_A,
            "task_id": str(task_id),
            "worker": worker,
            "bound_at": NOW,
        },
    )
    return rows[0]


def _fail(engine: Engine, task_id: UUID, *, worker: str = WORKER):
    rows = _query(
        engine,
        TENANT_A,
        """
        SELECT * FROM gda_control.fail_gis_service_slo_reconciliation(
            :tenant, CAST(:task_id AS uuid), :worker, :error, :retry_delay
        )
        """,
        {
            "tenant": TENANT_A,
            "task_id": str(task_id),
            "worker": worker,
            "error": "certification transient failure",
            "retry_delay": 0,
        },
    )
    return rows[0]


def _count(engine: Engine, tenant: str, table: str, where: str = "") -> int:
    rows = _query(
        engine,
        tenant,
        f"SELECT count(*) AS count FROM gda_control.{table} {where}",
    )
    return int(rows[0]["count"])


def _admin(engine: Engine, statement: str, parameters: dict[str, Any] | None = None):
    with engine.begin() as connection:
        return connection.execute(text(statement), parameters or {})


def _security(engine: Engine) -> dict[str, bool]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT c.relrowsecurity, c.relforcerowsecurity,
                       has_table_privilege('gda_control_gateway',
                         'gda_control.gis_service_slo_reconciliation_outbox', 'SELECT'),
                       has_table_privilege('gda_control_gateway',
                         'gda_control.gis_service_slo_reconciliation_outbox', 'INSERT'),
                       has_table_privilege('gda_control_gateway',
                         'gda_control.gis_service_slo_reconciliation_outbox', 'UPDATE'),
                       has_function_privilege('gda_control_gateway',
                         'gda_control.claim_gis_service_slo_reconciliations('
                         'text,text,text,integer,integer)', 'EXECUTE'),
                       has_function_privilege('agent_user',
                         'gda_control.'
                         'enqueue_slo_activation_gis_service_reconciliation()',
                         'EXECUTE')
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'gda_control'
                  AND c.relname = 'gis_service_slo_reconciliation_outbox'
                """
            )
        ).one()
    return {
        "rls_enabled": bool(row[0]),
        "rls_forced": bool(row[1]),
        "gateway_select": bool(row[2]),
        "gateway_insert": bool(row[3]),
        "gateway_update": bool(row[4]),
        "gateway_claim_execute": bool(row[5]),
        "untrusted_runtime_trigger_execute": bool(row[6]),
    }


def certify(engine: Engine) -> dict[str, Any]:
    _seed_services(engine)
    _register_approver(engine)

    fingerprints: dict[int, str] = {}
    approvals: dict[int, str] = {}
    versions: dict[int, str] = {}
    for version in range(1, 7):
        version_ref = f"{SLO_REF}.v{version}"
        approval_ref = f"gda://{TENANT_A}/approval_case/district-slo-v{version}"
        versions[version] = version_ref
        approvals[version] = approval_ref
        fingerprints[version] = _stage(engine, version=version, version_ref=version_ref)
        _create_approval(engine, approval_ref, version_ref, fingerprints[version])

    activation_v1 = _activate(
        engine, versions[1], fingerprints[1], approvals[1], expected=0
    )
    task_v1 = _query(
        engine,
        TENANT_A,
        "SELECT * FROM gda_control.gis_service_slo_reconciliation_outbox",
    )
    assert len(task_v1) == 1 and task_v1[0]["status"] == "pending"
    replay = _activate(
        engine, versions[1], fingerprints[1], approvals[1], expected=activation_v1
    )
    assert replay == activation_v1
    assert _count(engine, TENANT_A, "gis_service_slo_reconciliation_outbox") == 1

    claimed_v1 = _claim(engine)
    assert len(claimed_v1) == 1 and claimed_v1[0]["status"] == "in_flight"
    completed_v1 = _complete(engine, UUID(str(claimed_v1[0]["task_id"])))
    assert completed_v1["status"] == "done"
    assert _count(engine, TENANT_A, "gis_service_slo_binding") == 1

    activation_v2 = _activate(
        engine, versions[2], fingerprints[2], approvals[2], expected=activation_v1
    )
    # A pre-existing exact manual binding is reused by the worker.
    connection, transaction = _gateway_connection(engine, TENANT_A)
    try:
        connection.execute(
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
                "binding_id": str(uuid4()),
                "service": SERVICE_A,
                "definition": SLO_REF,
                "version": versions[2],
                "fingerprint": fingerprints[2],
                "approval": approvals[2],
                "activation": activation_v2,
                "bound_by": "human:gis-service-owner",
                "reason": "manual exact binding before worker delivery",
                "bound_at": NOW,
            },
        )
        transaction.commit()
    except Exception:
        transaction.rollback()
        raise
    finally:
        connection.close()
    claimed_v2 = _claim(engine)
    completed_v2 = _complete(engine, UUID(str(claimed_v2[0]["task_id"])))
    assert completed_v2["status"] == "done"
    assert _count(engine, TENANT_A, "gis_service_slo_binding") == 2

    activation_v3 = _activate(
        engine, versions[3], fingerprints[3], approvals[3], expected=activation_v2
    )
    claimed_v3 = _claim(engine)
    v3_task = next(row for row in claimed_v3 if row["activation_version"] == activation_v3)
    activation_v4 = _activate(
        engine, versions[4], fingerprints[4], approvals[4], expected=activation_v3
    )
    superseded = _complete(engine, UUID(str(v3_task["task_id"])))
    assert superseded["status"] == "superseded"
    assert activation_v4 == activation_v3 + 1

    # Simulate an activation made while the 224 trigger was absent. Claim's
    # compensation scan must discover it after the trigger is restored.
    _admin(
        engine,
        "DROP TRIGGER trg_gda_slo_activation_gis_service_reconciliation "
        "ON gda_control.slo_definition_activation",
    )
    activation_v5 = _activate(
        engine, versions[5], fingerprints[5], approvals[5], expected=activation_v4
    )
    assert _count(engine, TENANT_A, "gis_service_slo_reconciliation_outbox") == 4
    _admin(
        engine,
        """
        CREATE TRIGGER trg_gda_slo_activation_gis_service_reconciliation
        AFTER INSERT OR UPDATE ON gda_control.slo_definition_activation
        FOR EACH ROW EXECUTE FUNCTION
          gda_control.enqueue_slo_activation_gis_service_reconciliation()
        """,
    )
    claimed_v5 = _claim(engine)
    v5_task = next(row for row in claimed_v5 if row["activation_version"] == activation_v5)
    completed_v5 = _complete(engine, UUID(str(v5_task["task_id"])))
    assert completed_v5["status"] == "done"

    activation_v6 = _activate(
        engine, versions[6], fingerprints[6], approvals[6], expected=activation_v5
    )
    lease_claim = _claim(engine, lease_seconds=5)
    v6_task = next(row for row in lease_claim if row["activation_version"] == activation_v6)
    _admin(
        engine,
        """
        UPDATE gda_control.gis_service_slo_reconciliation_outbox
           SET claimed_until = clock_timestamp() - interval '1 second'
         WHERE task_id = CAST(:task_id AS uuid)
        """,
        {"task_id": str(v6_task["task_id"])},
    )
    redelivered = _claim(engine, lease_seconds=5)
    assert any(row["task_id"] == v6_task["task_id"] for row in redelivered)
    redelivery_task = next(row for row in redelivered if row["task_id"] == v6_task["task_id"])
    assert redelivery_task["attempt_count"] == 2
    failed_after_max = _fail(engine, UUID(str(redelivery_task["task_id"])))
    assert failed_after_max["status"] == "pending"
    _admin(
        engine,
        """
        UPDATE gda_control.gis_service_slo_reconciliation_outbox
           SET status = 'in_flight',
               attempt_count = max_attempts,
               claimed_by = :worker,
               claimed_until = clock_timestamp() - interval '1 second'
         WHERE task_id = CAST(:task_id AS uuid)
        """,
        {"task_id": str(redelivery_task["task_id"]), "worker": WORKER},
    )
    assert _claim(engine, lease_seconds=5) == []
    maxed = _query(
        engine,
        TENANT_A,
        "SELECT status FROM gda_control.gis_service_slo_reconciliation_outbox "
        "WHERE task_id = CAST(:task_id AS uuid)",
        {"task_id": str(redelivery_task["task_id"])},
    )
    assert maxed[0]["status"] == "failed"

    cross_tenant_rows = _count(engine, TENANT_B, "gis_service_slo_reconciliation_outbox")
    direct_insert_sqlstate = _expect_rejected(
        lambda: _query(
            engine,
            TENANT_A,
            "INSERT INTO gda_control.gis_service_slo_reconciliation_outbox "
            "(tenant_id, service_urn, slo_definition_ref, active_version_ref, "
            "definition_fingerprint, approval_case_ref, activation_version, "
            "status, available_at, created_at) VALUES "
            "(:tenant, :service, :definition, :version, :fingerprint, :approval, "
            "99, 'pending', :now, :now)",
            {
                "tenant": TENANT_A,
                "service": SERVICE_A,
                "definition": SLO_REF,
                "version": versions[1],
                "fingerprint": fingerprints[1],
                "approval": approvals[1],
                "now": NOW,
            },
        )
    )
    tenant_mismatch_sqlstate = _expect_rejected(
        lambda: _query(
            engine,
            TENANT_A,
            """
            SELECT gda_control.claim_gis_service_slo_reconciliations(
                :tenant, :actor, :worker, 1, 60
            )
            """,
            {"tenant": TENANT_B, "actor": WORKLOAD, "worker": WORKER},
        )
    )

    return {
        "schema": "gda.gis_service_slo_reconciliation_certification.v1",
        "database": str(engine.url.database),
        "migration": "224_gis_service_slo_reconciliation_outbox",
        "catalog_count": len(
            list(
                (Path(__file__).parent.parent / "data_agent/migrations").glob("*.sql")
            )
        ),
        "activation_v1": activation_v1,
        "activation_v4": activation_v4,
        "activation_v5": activation_v5,
        "activation_v6": activation_v6,
        "replay_same_activation": replay == activation_v1,
        "manual_binding_reused": completed_v2["status"] == "done",
        "superseded_old_activation": superseded["status"] == "superseded",
        "backfill_completed": completed_v5["status"] == "done",
        "lease_redelivery_attempt": redelivery_task["attempt_count"],
        "max_attempts_terminal": maxed[0]["status"] == "failed",
        "cross_tenant_visible_rows": cross_tenant_rows,
        "direct_insert_sqlstate": direct_insert_sqlstate,
        "tenant_mismatch_sqlstate": tenant_mismatch_sqlstate,
        "security_contract": _security(engine),
        "done_task_count": _count(
            engine,
            TENANT_A,
            "gis_service_slo_reconciliation_outbox",
            "WHERE status = 'done'",
        ),
        "binding_count": _count(engine, TENANT_A, "gis_service_slo_binding"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "GDA_CERT_DATABASE_URL",
            "postgresql+psycopg2://postgres:postgres@127.0.0.1:5433/gda_224_cert",
        ),
    )
    args = parser.parse_args()
    engine = create_engine(args.database_url)
    print(json.dumps(certify(engine), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
