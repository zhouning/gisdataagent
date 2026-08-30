from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from data_agent.security_event_ledger import (
    SECURITY_LEDGER_DATABASE_ROLE,
    SecurityEventLedger,
    SecurityEventLedgerConfigurationError,
    SecurityEventLedgerConflictError,
    SecurityEventLedgerForbiddenError,
    SecurityEventLedgerUnavailableError,
    SecurityEventLedgerValidationError,
)


def _postgres_engine():
    connection = MagicMock()
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    engine.connect.return_value.__enter__.return_value = connection
    return engine, connection


def _append_row():
    return {
        "result_event_id": uuid4(),
        "result_sequence_no": 3,
        "result_previous_event_sha256": "a" * 64,
        "result_event_sha256": "b" * 64,
        "result_occurred_at": datetime.now(UTC),
        "result_inserted": True,
    }


def _append(ledger: SecurityEventLedger, **overrides):
    values = {
        "tenant_id": "tenant-a",
        "attempt_id": uuid4(),
        "phase": "admitted",
        "action": "data_anonymize",
        "outcome": "admitted",
        "actor_subject": "human:alice",
        "resource_ref": "postgis://public/roads",
        "reason": "authorized_request",
        "details": {"asset_id": 7},
    }
    values.update(overrides)
    return ledger.append(**values)


def _dbapi_error(sqlstate: str) -> DBAPIError:
    original = SimpleNamespace(pgcode=sqlstate)
    return DBAPIError("statement", {}, original, False)


def test_append_sets_gateway_role_and_tenant_context():
    engine, connection = _postgres_engine()
    result = MagicMock()
    result.mappings.return_value.one.return_value = _append_row()
    connection.execute.side_effect = [MagicMock(), result]

    event = _append(SecurityEventLedger(engine))

    connection.exec_driver_sql.assert_called_once_with(
        f'SET LOCAL ROLE "{SECURITY_LEDGER_DATABASE_ROLE}"'
    )
    tenant_statement, tenant_parameters = connection.execute.call_args_list[0].args
    assert "app.current_tenant" in str(tenant_statement)
    assert tenant_parameters == {"tenant_id": "tenant-a"}
    append_statement, append_parameters = connection.execute.call_args_list[1].args
    assert "gda_control.append_security_event" in str(append_statement)
    assert append_parameters["details"] == '{"asset_id":7}'
    assert event.sequence_no == 3
    assert event.previous_event_sha256 == "a" * 64
    assert event.event_sha256 == "b" * 64
    assert event.inserted is True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant_id": "Tenant A"}, "tenant_id"),
        ({"attempt_id": "not-a-uuid"}, "attempt_id"),
        ({"phase": "outcome", "outcome": "admitted"}, "phase/outcome"),
        ({"action": "Bad Action"}, "action"),
        ({"actor_subject": "alice"}, "actor_subject"),
        ({"resource_ref": ""}, "resource_ref"),
        ({"reason": ""}, "reason"),
        ({"details": []}, "details"),
        ({"details": {"value": float("nan")}}, "JSON values"),
    ],
)
def test_append_rejects_invalid_parameters(overrides, message):
    engine, _ = _postgres_engine()

    with pytest.raises(SecurityEventLedgerValidationError, match=message):
        _append(SecurityEventLedger(engine), **overrides)


def test_append_requires_postgresql():
    engine, _ = _postgres_engine()
    engine.dialect.name = "duckdb"

    with pytest.raises(SecurityEventLedgerConfigurationError, match="PostgreSQL"):
        _append(SecurityEventLedger(engine))


def test_append_maps_row_and_idempotent_replay_flag():
    engine, connection = _postgres_engine()
    row = _append_row()
    row["result_inserted"] = False
    result = MagicMock()
    result.mappings.return_value.one.return_value = row
    connection.execute.side_effect = [MagicMock(), result]

    event = _append(SecurityEventLedger(engine))

    assert event.event_id == row["result_event_id"]
    assert event.occurred_at == row["result_occurred_at"]
    assert event.inserted is False


def test_verify_chain_uses_tenant_scoped_function():
    engine, connection = _postgres_engine()
    result = MagicMock()
    result.scalar_one.return_value = True
    connection.execute.side_effect = [MagicMock(), result]

    assert SecurityEventLedger(engine).verify_chain("tenant-a") is True
    statement, parameters = connection.execute.call_args_list[1].args
    assert "gda_control.verify_security_event_chain" in str(statement)
    assert parameters == {"tenant_id": "tenant-a"}


def test_attempt_lock_is_tenant_scoped_and_non_blocking():
    engine, connection = _postgres_engine()
    result = MagicMock()
    result.scalar_one.return_value = True
    connection.execute.side_effect = [MagicMock(), result]
    attempt_id = uuid4()

    with SecurityEventLedger(engine).attempt_lock("tenant-a", attempt_id) as acquired:
        assert acquired is True

    statement, parameters = connection.execute.call_args_list[1].args
    assert "pg_try_advisory_xact_lock" in str(statement)
    assert set(parameters) == {"lock_class", "lock_object"}
    assert all(isinstance(value, int) for value in parameters.values())


def test_attempt_lock_rejects_non_uuid_identity():
    engine, _connection = _postgres_engine()

    with pytest.raises(SecurityEventLedgerValidationError, match="attempt_id"):
        with SecurityEventLedger(engine).attempt_lock("tenant-a", "invalid"):
            pass


def test_record_operation_receipt_uses_guarded_database_function():
    engine, connection = _postgres_engine()
    attempt_id = uuid4()
    receipt_id = uuid4()
    recorded_at = datetime.now(UTC)
    result = MagicMock()
    result.mappings.return_value.one.return_value = {
        "result_receipt_id": receipt_id,
        "result_receipt_sha256": "c" * 64,
        "result_recorded_at": recorded_at,
        "result_inserted": True,
    }
    connection.execute.side_effect = [MagicMock(), result]
    evidence = {
        "schema": "gda.spatial_anonymization_receipt.v1",
        "attempt_id": str(attempt_id),
    }

    receipt = SecurityEventLedger(engine).record_operation_receipt(
        tenant_id="tenant-a",
        attempt_id=attempt_id,
        action="data_anonymize",
        resource_ref="postgis://geo/roads->postgis://public/roads_grid",
        receipt_type="gda.spatial_anonymization_receipt.v1",
        evidence=evidence,
        recorded_by="workload:spatial-anonymization",
    )

    statement, parameters = connection.execute.call_args_list[1].args
    assert "gda_control.record_security_operation_receipt" in str(statement)
    assert parameters["evidence"] == json.dumps(
        evidence,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert receipt.receipt_id == receipt_id
    assert receipt.receipt_sha256 == "c" * 64
    assert receipt.inserted is True


def test_record_operation_receipt_can_join_caller_owned_transaction():
    engine, connection = _postgres_engine()
    connection.in_transaction.return_value = True
    attempt_id = uuid4()
    receipt_id = uuid4()
    recorded_at = datetime.now(UTC)
    result = MagicMock()
    result.mappings.return_value.one.return_value = {
        "result_receipt_id": receipt_id,
        "result_receipt_sha256": "d" * 64,
        "result_recorded_at": recorded_at,
        "result_inserted": True,
    }
    connection.execute.side_effect = [MagicMock(), result]
    evidence = {
        "schema": "gda.spatial_anonymization_receipt.v1",
        "attempt_id": str(attempt_id),
    }

    receipt = SecurityEventLedger(engine).record_operation_receipt_in_transaction(
        connection,
        tenant_id="tenant-a",
        attempt_id=attempt_id,
        action="data_anonymize",
        resource_ref="postgis://geo/roads->postgis://public/roads_grid",
        receipt_type="gda.spatial_anonymization_receipt.v1",
        evidence=evidence,
        recorded_by="workload:spatial-anonymization",
    )

    engine.connect.assert_not_called()
    assert connection.exec_driver_sql.call_args_list[0].args == (
        'SET LOCAL ROLE "gda_control_gateway"',
    )
    assert connection.exec_driver_sql.call_args_list[1].args == ("RESET ROLE",)
    statement, parameters = connection.execute.call_args_list[1].args
    assert "gda_control.record_security_operation_receipt" in str(statement)
    assert parameters["evidence"] == json.dumps(
        evidence,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert receipt.receipt_id == receipt_id
    assert receipt.receipt_sha256 == "d" * 64


def test_get_and_verify_operation_receipt():
    engine, connection = _postgres_engine()
    attempt_id = uuid4()
    row = {
        "tenant_id": "tenant-a",
        "receipt_id": uuid4(),
        "attempt_id": attempt_id,
        "action": "data_anonymize",
        "resource_ref": "postgis://geo/roads->postgis://public/roads_grid",
        "receipt_type": "gda.spatial_anonymization_receipt.v1",
        "receipt_sha256": "c" * 64,
        "evidence": {"status": "success"},
        "recorded_by": "workload:spatial-anonymization",
        "recorded_at": datetime.now(UTC),
    }
    get_result = MagicMock()
    get_result.mappings.return_value.one_or_none.return_value = row
    verify_result = MagicMock()
    verify_result.scalar_one.return_value = True
    connection.execute.side_effect = [
        MagicMock(),
        get_result,
        MagicMock(),
        verify_result,
    ]
    ledger = SecurityEventLedger(engine)

    receipt = ledger.get_operation_receipt("tenant-a", attempt_id)
    verified = ledger.verify_operation_receipts("tenant-a")

    assert receipt.receipt_id == row["receipt_id"]
    assert receipt.inserted is False
    assert verified is True
    verify_statement, _ = connection.execute.call_args_list[3].args
    assert "gda_control.verify_security_operation_receipts" in str(verify_statement)


def test_list_events_maps_tenant_rows():
    engine, connection = _postgres_engine()
    attempt_id = uuid4()
    row = {
        "tenant_id": "tenant-a",
        "event_id": uuid4(),
        "sequence_no": 4,
        "attempt_id": attempt_id,
        "phase": "outcome",
        "action": "data_anonymize",
        "outcome": "success",
        "actor_subject": "human:alice",
        "resource_ref": "postgis://public/roads",
        "reason": "anonymization_succeeded",
        "details": {"rows": 5},
        "previous_event_sha256": "a" * 64,
        "event_sha256": "b" * 64,
        "occurred_at": datetime.now(UTC),
    }
    result = MagicMock()
    result.mappings.return_value.all.return_value = [row]
    connection.execute.side_effect = [MagicMock(), result]

    events = SecurityEventLedger(engine).list_events(
        "tenant-a", attempt_id=attempt_id, limit=10
    )

    assert len(events) == 1
    assert events[0].event_id == row["event_id"]
    assert events[0].details == {"rows": 5}
    assert events[0].inserted is False
    _, parameters = connection.execute.call_args_list[1].args
    assert parameters == {
        "tenant_id": "tenant-a",
        "attempt_id": attempt_id,
        "limit": 10,
    }


def test_list_incomplete_admissions_uses_anti_join_and_cutoff():
    engine, connection = _postgres_engine()
    attempt_id = uuid4()
    cutoff = datetime.now(UTC)
    row = {
        "tenant_id": "tenant-a",
        "event_id": uuid4(),
        "sequence_no": 7,
        "attempt_id": attempt_id,
        "phase": "admitted",
        "action": "data_anonymize",
        "outcome": "admitted",
        "actor_subject": "human:alice",
        "resource_ref": "postgis://geo/roads->postgis://public/roads_grid",
        "reason": "authorized_request",
        "details": {"output_table": "public.roads_grid"},
        "previous_event_sha256": "a" * 64,
        "event_sha256": "b" * 64,
        "occurred_at": cutoff,
    }
    result = MagicMock()
    result.mappings.return_value.all.return_value = [row]
    connection.execute.side_effect = [MagicMock(), result]

    events = SecurityEventLedger(engine).list_incomplete_admissions(
        "tenant-a",
        older_than=cutoff,
        attempt_id=attempt_id,
        limit=5,
    )

    assert events[0].event_id == row["event_id"]
    statement, parameters = connection.execute.call_args_list[1].args
    assert "NOT EXISTS" in str(statement)
    assert "outcome.phase = 'outcome'" in str(statement)
    assert parameters == {
        "tenant_id": "tenant-a",
        "older_than": cutoff,
        "attempt_id": attempt_id,
        "limit": 5,
    }


def test_list_incomplete_admissions_requires_timezone_aware_cutoff():
    engine, _ = _postgres_engine()

    with pytest.raises(SecurityEventLedgerValidationError, match="timezone-aware"):
        SecurityEventLedger(engine).list_incomplete_admissions(
            "tenant-a",
            older_than=datetime.now(),
        )


@pytest.mark.parametrize("limit", [True, 0, 1001, "10"])
def test_list_events_rejects_invalid_limit(limit):
    engine, _ = _postgres_engine()

    with pytest.raises(SecurityEventLedgerValidationError, match="limit"):
        SecurityEventLedger(engine).list_events("tenant-a", limit=limit)


@pytest.mark.parametrize(
    ("sqlstate", "error_type"),
    [
        ("42501", SecurityEventLedgerForbiddenError),
        ("40001", SecurityEventLedgerConflictError),
        ("23505", SecurityEventLedgerConflictError),
        ("22023", SecurityEventLedgerValidationError),
        ("23514", SecurityEventLedgerValidationError),
        ("08006", SecurityEventLedgerUnavailableError),
    ],
)
def test_database_sqlstate_maps_to_stable_error(sqlstate, error_type):
    engine, connection = _postgres_engine()
    connection.execute.side_effect = [MagicMock(), _dbapi_error(sqlstate)]

    with pytest.raises(error_type):
        _append(SecurityEventLedger(engine))


def test_missing_gateway_membership_is_configuration_error():
    engine, connection = _postgres_engine()
    connection.exec_driver_sql.side_effect = _dbapi_error("42501")

    with pytest.raises(SecurityEventLedgerConfigurationError, match="not a member"):
        _append(SecurityEventLedger(engine))


def test_migration_defines_append_only_tenant_hash_chain():
    migration = (
        Path(__file__).parent / "migrations/110_immutable_security_event_ledger.sql"
    ).read_text(encoding="utf-8")

    required_fragments = [
        "CREATE TABLE gda_control.security_event",
        "UNIQUE (tenant_id, sequence_no)",
        "UNIQUE (tenant_id, attempt_id, phase)",
        "digest(",
        "pg_advisory_xact_lock",
        "CREATE TRIGGER trg_gda_security_event_immutable",
        "ALTER TABLE gda_control.security_event FORCE ROW LEVEL SECURITY",
        "CREATE POLICY tenant_isolation ON gda_control.security_event",
        "REVOKE ALL ON gda_control.security_event FROM gda_control_gateway",
        "GRANT SELECT ON gda_control.security_event TO gda_control_gateway",
        "GRANT EXECUTE ON FUNCTION gda_control.append_security_event",
        "GRANT EXECUTE ON FUNCTION gda_control.verify_security_event_chain",
    ]
    for fragment in required_fragments:
        assert fragment in migration

    assert "GRANT INSERT ON gda_control.security_event" not in migration
    assert "GRANT UPDATE ON gda_control.security_event" not in migration
    assert "GRANT DELETE ON gda_control.security_event" not in migration


def test_migration_defines_immutable_guarded_operation_receipts():
    migration = (
        Path(__file__).parent / "migrations/111_security_operation_receipt.sql"
    ).read_text(encoding="utf-8")

    required_fragments = [
        "CREATE TABLE gda_control.security_operation_receipt",
        "UNIQUE (tenant_id, attempt_id)",
        "matching admitted security event was not found",
        "security receipt output table does not exist",
        "security receipt output row count does not match",
        "index_method.amname = 'gist'",
        "CREATE TRIGGER trg_gda_security_operation_receipt_immutable",
        "ALTER TABLE gda_control.security_operation_receipt FORCE ROW LEVEL SECURITY",
        "GRANT SELECT ON gda_control.security_operation_receipt TO gda_control_gateway",
        "GRANT EXECUTE ON FUNCTION gda_control.record_security_operation_receipt",
        "GRANT EXECUTE ON FUNCTION gda_control.verify_security_operation_receipts",
    ]
    for fragment in required_fragments:
        assert fragment in migration

    assert "GRANT INSERT ON gda_control.security_operation_receipt" not in migration
    assert "GRANT UPDATE ON gda_control.security_operation_receipt" not in migration
    assert "GRANT DELETE ON gda_control.security_operation_receipt" not in migration
