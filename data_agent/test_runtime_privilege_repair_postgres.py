"""Real PostgreSQL regression for the DataProduct gateway ACL repair."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from data_agent.cross_store_projection_postgres_rehearsal import (
    _temporary_postgres,
)
from data_agent.runtime_privilege_contract import (
    inspect_runtime_privilege_contract,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
MIGRATION_DIR = Path(__file__).resolve().parent / "migrations"
INCIDENT_MIGRATION = MIGRATION_DIR / "098_platform_data_incident.sql"
GATEWAY_MIGRATION = MIGRATION_DIR / "094_platform_control_gateway.sql"
REPAIR_MIGRATION = MIGRATION_DIR / "189_data_product_gateway_privilege_repair.sql"
DATA_PRODUCT_OBJECTS = {
    "table:gda_control.data_product",
    "table:gda_control.data_product_version",
    "table:gda_control.data_product_event",
}


def _execute_sql(connection, sql: str) -> None:
    connection.exec_driver_sql(sql.replace("%", "%%"))


def _observe(sandbox) -> dict:
    assert sandbox.runtime_engine is not None
    with sandbox.runtime_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        return inspect_runtime_privilege_contract(
            connection,
            profile="test",
            runtime_role=sandbox.role,
        )


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_forward_migration_repairs_only_reproduced_data_product_acl_drift():
    assert DATABASE_URL is not None
    with _temporary_postgres(DATABASE_URL) as sandbox:
        with sandbox.admin_connection() as connection:
            _execute_sql(
                connection,
                """
                CREATE TABLE gda_control.data_product (id integer PRIMARY KEY);
                CREATE TABLE gda_control.data_product_version (id integer PRIMARY KEY);
                CREATE TABLE gda_control.data_product_event (id integer PRIMARY KEY);
                GRANT SELECT, INSERT, UPDATE ON gda_control.data_product
                    TO gda_control_gateway;
                GRANT SELECT, INSERT ON gda_control.data_product_version
                    TO gda_control_gateway;
                GRANT SELECT, INSERT ON gda_control.data_product_event
                    TO gda_control_gateway;
                """,
            )
            _execute_sql(
                connection,
                INCIDENT_MIGRATION.read_text(encoding="utf-8"),
            )

        baseline = _observe(sandbox)
        assert baseline["status"] == "in_sync"

        with sandbox.admin_connection() as connection:
            _execute_sql(
                connection,
                GATEWAY_MIGRATION.read_text(encoding="utf-8"),
            )
            _execute_sql(
                connection,
                INCIDENT_MIGRATION.read_text(encoding="utf-8"),
            )

        drifted = _observe(sandbox)
        assert drifted["status"] == "blocked"
        assert {item["object_id"] for item in drifted["drift"]} == (DATA_PRODUCT_OBJECTS)

        with sandbox.admin_connection() as connection:
            _execute_sql(
                connection,
                REPAIR_MIGRATION.read_text(encoding="utf-8"),
            )

        repaired = _observe(sandbox)
        assert repaired["status"] == "in_sync"
        assert repaired["admission_allowed"] is True
        assert repaired["drift"] == []
        assert repaired["contract_fingerprint"] == baseline["contract_fingerprint"]
