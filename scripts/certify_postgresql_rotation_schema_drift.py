#!/usr/bin/env python3
"""Certify real PostgreSQL credential rotation and schema drift detection."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import dotenv_values
from psycopg2 import sql

from data_agent.connectors.database import _connection_url
from data_agent.source_connector_governance import (
    CertificationStatus,
    CredentialAuthType,
    CredentialReference,
    MappingCredentialResolver,
    SourceConnectorKind,
    SourceDefinition,
    certify_source_connector,
    detect_schema_drift,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    REPO_ROOT / ".tmp/source-connector-certification/postgresql-rotation-drift-report.json"
)


def _settings() -> dict[str, str]:
    values = {
        key: str(value)
        for key, value in dotenv_values(REPO_ROOT / ".env").items()
        if value is not None
    }
    return {**values, **os.environ}


class _PostgresCertificationSandbox:
    """Own one random schema and login role, then remove only those objects."""

    def __init__(self, admin_url: str) -> None:
        suffix = secrets.token_hex(5)
        self.schema = f"gda_connector_cert_{suffix}"
        self.table = "source_asset"
        self.role = f"gda_connector_reader_{suffix}"
        self.password_v1 = secrets.token_urlsafe(32)
        self.password_v2 = secrets.token_urlsafe(32)
        self._connection = psycopg2.connect(admin_url)
        self._connection.autocommit = True
        self._created_schema = False
        self._created_role = False

    @property
    def qualified_table(self) -> str:
        return f"{self.schema}.{self.table}"

    def setup(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)",
                (self.schema,),
            )
            if cursor.fetchone()[0]:
                raise RuntimeError("random certification schema already exists")
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)",
                (self.role,),
            )
            if cursor.fetchone()[0]:
                raise RuntimeError("random certification role already exists")
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(self.role)),
                (self.password_v1,),
            )
            self._created_role = True
            cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
            self._created_schema = True
            cursor.execute(
                sql.SQL("CREATE TABLE {}.{} (id INTEGER PRIMARY KEY, name TEXT NOT NULL)").format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table),
                )
            )
            cursor.execute(
                sql.SQL("INSERT INTO {}.{} (id, name) VALUES (%s, %s), (%s, %s)").format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table),
                ),
                (1, "Chongqing", 2, "Bishan"),
            )
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.role),
                )
            )
            cursor.execute(
                sql.SQL("GRANT SELECT ON {}.{} TO {}").format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table),
                    sql.Identifier(self.role),
                )
            )

    def rotate_password(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ALTER ROLE {} PASSWORD %s").format(sql.Identifier(self.role)),
                (self.password_v2,),
            )

    def add_nullable_column(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ALTER TABLE {}.{} ADD COLUMN observed_at TIMESTAMPTZ").format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table),
                )
            )

    def change_primary_key_type(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("ALTER TABLE {}.{} ALTER COLUMN id TYPE BIGINT").format(
                    sql.Identifier(self.schema),
                    sql.Identifier(self.table),
                )
            )

    def cleanup(self) -> dict[str, bool]:
        with self._connection.cursor() as cursor:
            if self._created_schema:
                cursor.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
                )
            if self._created_role:
                cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(self.role)))
            cursor.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)",
                (self.schema,),
            )
            schema_removed = bool(cursor.fetchone()[0])
            cursor.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)",
                (self.role,),
            )
            role_removed = bool(cursor.fetchone()[0])
        self._connection.close()
        return {
            "schema_removed": schema_removed,
            "role_removed": role_removed,
        }


def _credential(version: int) -> CredentialReference:
    return CredentialReference(
        credential_id="credential:postgresql-rotation-drift-certification",
        version=version,
        auth_type=CredentialAuthType.BASIC,
        provider="ephemeral-postgresql-role",
    )


def _definition(
    endpoint_url: str,
    qualified_table: str,
    credential: CredentialReference,
) -> SourceDefinition:
    return SourceDefinition(
        source_id="postgresql-rotation-drift-certification",
        version=f"1.0.{credential.version - 1}",
        source_kind=SourceConnectorKind.DATABASE,
        endpoint_url=endpoint_url,
        owner_ref="team:data-platform",
        credential_reference=credential,
        connector_version="1.0.0",
        query_config={"table": qualified_table},
    )


def _auth(role: str, password: str) -> dict[str, str]:
    return {"type": "basic", "username": role, "password": password}


def _provider_write_denial(
    endpoint_url: str,
    role: str,
    password: str,
    qualified_table: str,
) -> dict[str, Any]:
    connection = psycopg2.connect(_connection_url(endpoint_url, _auth(role, password)))
    try:
        schema, table = qualified_table.split(".", 1)
        denied_sqlstate: str | None = None
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                )
            )
            before_row_count = int(cursor.fetchone()[0])
            try:
                cursor.execute(
                    sql.SQL("INSERT INTO {}.{} (id, name) VALUES (%s, %s)").format(
                        sql.Identifier(schema),
                        sql.Identifier(table),
                    ),
                    (999, "must-not-write"),
                )
            except psycopg2.Error as exc:
                denied_sqlstate = exc.pgcode
            finally:
                connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                )
            )
            after_row_count = int(cursor.fetchone()[0])
        return {
            "denied": denied_sqlstate == "42501" and before_row_count == after_row_count,
            "sqlstate": denied_sqlstate,
            "before_row_count": before_row_count,
            "after_row_count": after_row_count,
        }
    finally:
        connection.close()


def _fields(report) -> list[dict[str, Any]]:
    if report.discovery is None or len(report.discovery.resources) != 1:
        raise RuntimeError("scoped database discovery did not return exactly one table")
    return [field.model_dump(mode="json") for field in report.discovery.resources[0].fields]


async def _certify(
    endpoint_url: str,
    sandbox: _PostgresCertificationSandbox,
) -> dict[str, Any]:
    reference_v1 = _credential(1)
    reference_v2 = _credential(2)
    definition_v1 = _definition(endpoint_url, sandbox.qualified_table, reference_v1)
    definition_v2 = _definition(endpoint_url, sandbox.qualified_table, reference_v2)
    now = datetime.now(UTC)

    initial = await certify_source_connector(
        definition_v1,
        MappingCredentialResolver(
            {(reference_v1.credential_id, 1): _auth(sandbox.role, sandbox.password_v1)}
        ),
        certified_at=now,
    )
    provider_write_denial = _provider_write_denial(
        endpoint_url,
        sandbox.role,
        sandbox.password_v1,
        sandbox.qualified_table,
    )
    sandbox.rotate_password()
    stale_credential = await certify_source_connector(
        definition_v1,
        MappingCredentialResolver(
            {(reference_v1.credential_id, 1): _auth(sandbox.role, sandbox.password_v1)}
        ),
        certified_at=now,
    )
    rotated = await certify_source_connector(
        definition_v2,
        MappingCredentialResolver(
            {(reference_v2.credential_id, 2): _auth(sandbox.role, sandbox.password_v2)}
        ),
        certified_at=now,
    )

    sandbox.add_nullable_column()
    additive = await certify_source_connector(
        definition_v2,
        MappingCredentialResolver(
            {(reference_v2.credential_id, 2): _auth(sandbox.role, sandbox.password_v2)}
        ),
        certified_at=now,
    )
    if initial.discovery is None or additive.discovery is None:
        raise RuntimeError("additive drift certification did not produce discovery snapshots")
    additive_event = detect_schema_drift(
        definition_v2.source_id,
        initial.discovery,
        additive.discovery,
    )

    sandbox.change_primary_key_type()
    breaking = await certify_source_connector(
        definition_v2,
        MappingCredentialResolver(
            {(reference_v2.credential_id, 2): _auth(sandbox.role, sandbox.password_v2)}
        ),
        certified_at=now,
    )
    if breaking.discovery is None:
        raise RuntimeError("breaking drift certification did not produce a discovery snapshot")
    breaking_event = detect_schema_drift(
        definition_v2.source_id,
        additive.discovery,
        breaking.discovery,
    )

    reports = [initial, rotated, additive, breaking]
    secret_free_payload = json.dumps(
        [report.model_dump(mode="json") for report in reports]
        + [stale_credential.model_dump(mode="json")],
        sort_keys=True,
    )
    checks = {
        "initial_credential_passed": initial.status is CertificationStatus.PASSED,
        "provider_write_denied": provider_write_denial["denied"],
        "stale_credential_failed_after_rotation": (
            stale_credential.status is CertificationStatus.FAILED
        ),
        "rotated_credential_passed": rotated.status is CertificationStatus.PASSED,
        "credential_reference_changed": (
            reference_v1.fingerprint != reference_v2.fingerprint
            and definition_v1.fingerprint != definition_v2.fingerprint
        ),
        "rotation_preserved_schema": (
            initial.discovery is not None
            and rotated.discovery is not None
            and initial.discovery.fingerprint == rotated.discovery.fingerprint
        ),
        "additive_mutation_detected": (
            additive_event is not None
            and not additive_event.breaking
            and additive_event.changed_resources == (sandbox.qualified_table,)
        ),
        "breaking_mutation_detected": (
            breaking_event is not None
            and breaking_event.breaking
            and breaking_event.changed_resources == (sandbox.qualified_table,)
        ),
        "credential_secrets_redacted": (
            sandbox.password_v1 not in secret_free_payload
            and sandbox.password_v2 not in secret_free_payload
        ),
    }
    return {
        "schema": "gda.postgresql_rotation_schema_drift.acceptance.v1",
        "generated_at": now.isoformat(),
        "status": "passed" if all(checks.values()) else "failed",
        "provider": {
            "name": initial.provider,
            "version": initial.provider_version,
        },
        "sandbox": {
            "schema": sandbox.schema,
            "table": sandbox.qualified_table,
            "role": sandbox.role,
            "persistent": False,
        },
        "checks": checks,
        "least_privilege": provider_write_denial,
        "credential_rotation": {
            "before_reference_fingerprint": reference_v1.fingerprint,
            "after_reference_fingerprint": reference_v2.fingerprint,
            "before_definition_fingerprint": definition_v1.fingerprint,
            "after_definition_fingerprint": definition_v2.fingerprint,
            "stale_credential_status": stale_credential.status.value,
            "rotated_credential_status": rotated.status.value,
            "discovery_fingerprint_stable": checks["rotation_preserved_schema"],
        },
        "schema_drift": {
            "initial_fields": _fields(initial),
            "additive_fields": _fields(additive),
            "breaking_fields": _fields(breaking),
            "additive_event": {
                **additive_event.model_dump(mode="json"),
                "event_id": additive_event.event_id,
            }
            if additive_event
            else None,
            "breaking_event": {
                **breaking_event.model_dump(mode="json"),
                "event_id": breaking_event.event_id,
            }
            if breaking_event
            else None,
        },
        "certifications": {
            "initial": initial.model_dump(mode="json"),
            "stale_credential": stale_credential.model_dump(mode="json"),
            "rotated": rotated.model_dump(mode="json"),
            "additive_schema": additive.model_dump(mode="json"),
            "breaking_schema": breaking.model_dump(mode="json"),
        },
        "not_claimed": [
            "object-storage credential rotation",
            "STAC credential rotation",
            "automatic schema migration",
            "incremental ingestion or CDC",
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
    sandbox = _PostgresCertificationSandbox(_connection_url(args.postgres_url, admin_auth))
    report: dict[str, Any] | None = None
    try:
        sandbox.setup()
        report = asyncio.run(_certify(args.postgres_url, sandbox))
    finally:
        cleanup = sandbox.cleanup()
    if report is None:
        raise RuntimeError("PostgreSQL certification did not produce a report")
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
