"""Database-backed retry-budget admission for bounded lakehouse writers."""

from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg2
from psycopg2 import sql

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class RetryAdmission:
    operation_key: str
    worker_id: str
    attempt_number: int
    admitted: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "operation_key": self.operation_key,
            "worker_id": self.worker_id,
            "attempt_number": self.attempt_number,
            "admitted": self.admitted,
            "reason": self.reason,
        }


def _identifier(value: str, label: str) -> sql.Identifier:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid {label}")
    return sql.Identifier(value)


def _tables(schema: str) -> tuple[sql.Identifier, sql.Identifier]:
    return _identifier(schema, "schema"), _identifier("retry_budget", "table")


def ensure_retry_budget_schema(connection, schema: str) -> None:
    schema_id, budget_id = _tables(schema)
    event_id = _identifier("retry_budget_event", "table")
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {} ").format(schema_id))
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {}.{} (
                    operation_key TEXT PRIMARY KEY,
                    max_attempts INTEGER NOT NULL CHECK (max_attempts BETWEEN 1 AND 100),
                    attempt_count INTEGER NOT NULL DEFAULT 0
                        CHECK (attempt_count >= 0),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'exhausted')),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
                )
                """
            ).format(schema_id, budget_id)
        )
        cursor.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {}.{} (
                    event_id BIGSERIAL PRIMARY KEY,
                    operation_key TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    admitted BOOLEAN NOT NULL,
                    reason TEXT NOT NULL,
                    occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
                )
                """
            ).format(schema_id, event_id)
        )
    connection.commit()


def initialize_retry_budget(connection, schema: str, operation_key: str, max_attempts: int) -> None:
    if not operation_key or not 1 <= max_attempts <= 100:
        raise ValueError("invalid retry budget definition")
    schema_id, budget_id = _tables(schema)
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "INSERT INTO {}.{} (operation_key, max_attempts) VALUES (%s, %s)"
            ).format(schema_id, budget_id),
            (operation_key, max_attempts),
        )
    connection.commit()


def admit_retry(
    database_url: str,
    *,
    schema: str,
    operation_key: str,
    worker_id: str,
) -> RetryAdmission:
    if not worker_id:
        raise ValueError("worker_id is required")
    schema_id, budget_id = _tables(schema)
    event_id = _identifier("retry_budget_event", "table")
    connection = psycopg2.connect(database_url)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "SELECT attempt_count, max_attempts, status "
                        "FROM {}.{} WHERE operation_key = %s FOR UPDATE"
                    ).format(schema_id, budget_id),
                    (operation_key,),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError("retry budget operation does not exist")
                attempt_count, max_attempts, status = row
                attempt_number = int(attempt_count) + 1
                admitted = status == "active" and attempt_count < max_attempts
                reason = "budget_admitted" if admitted else "retry_budget_exhausted"
                if admitted:
                    cursor.execute(
                        sql.SQL(
                            "UPDATE {}.{} SET attempt_count = %s, updated_at = clock_timestamp() "
                            "WHERE operation_key = %s"
                        ).format(schema_id, budget_id),
                        (attempt_number, operation_key),
                    )
                    if attempt_number >= max_attempts:
                        cursor.execute(
                            sql.SQL(
                                "UPDATE {}.{} SET status = 'exhausted' WHERE operation_key = %s"
                            ).format(schema_id, budget_id),
                            (operation_key,),
                        )
                cursor.execute(
                    sql.SQL(
                        "INSERT INTO {}.{} "
                        "(operation_key, worker_id, attempt_number, admitted, reason) "
                        "VALUES (%s, %s, %s, %s, %s)"
                    ).format(schema_id, event_id),
                    (operation_key, worker_id, attempt_number, admitted, reason),
                )
                return RetryAdmission(
                    operation_key=operation_key,
                    worker_id=worker_id,
                    attempt_number=attempt_number,
                    admitted=admitted,
                    reason=reason,
                )
    finally:
        connection.close()


def read_retry_budget_ledger(connection, schema: str, operation_key: str) -> dict[str, object]:
    schema_id, budget_id = _tables(schema)
    event_id = _identifier("retry_budget_event", "table")
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL(
                "SELECT attempt_count, max_attempts, status FROM {}.{} WHERE operation_key = %s"
            ).format(schema_id, budget_id),
            (operation_key,),
        )
        budget = cursor.fetchone()
        cursor.execute(
            sql.SQL(
                "SELECT worker_id, attempt_number, admitted, reason "
                "FROM {}.{} WHERE operation_key = %s ORDER BY event_id"
            ).format(schema_id, event_id),
            (operation_key,),
        )
        events = [
            {
                "worker_id": row[0],
                "attempt_number": row[1],
                "admitted": row[2],
                "reason": row[3],
            }
            for row in cursor.fetchall()
        ]
    if budget is None:
        raise KeyError("retry budget operation does not exist")
    return {
        "attempt_count": budget[0],
        "max_attempts": budget[1],
        "status": budget[2],
        "events": events,
    }


def drop_retry_budget_schema(connection, schema: str) -> None:
    schema_id, _ = _tables(schema)
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(schema_id))
    connection.commit()
