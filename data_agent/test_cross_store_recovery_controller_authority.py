from __future__ import annotations

import json
import os
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.platform_runtime.cross_store_recovery_controller import (
    CrossStoreRecoveryController,
    CrossStoreRecoveryControllerError,
    CrossStoreRecoveryControllerEvent,
    CrossStoreRecoveryControllerSnapshot,
    CrossStoreRecoveryRunState,
    recovery_controller_event_fingerprint,
    recovery_controller_snapshot_fingerprint,
)
from data_agent.platform_runtime.cross_store_recovery_controller_authority import (
    CONTROLLER_AUTHORITY_MIGRATION,
    CrossStoreRecoveryControllerAuthorityConfigurationError,
    CrossStoreRecoveryControllerAuthorityValidationError,
    PostgresCrossStoreRecoveryControllerLedger,
)
from data_agent.test_cross_store_recovery_admission import _admit


def _install_controller_authority(sandbox) -> None:
    with sandbox.admin_connection() as connection:
        connection.exec_driver_sql(
            CONTROLLER_AUTHORITY_MIGRATION.read_text(encoding="utf-8").replace("%", "%%")
        )


def test_controller_authority_migration_exposes_durable_append_only_contract() -> None:
    migration = CONTROLLER_AUTHORITY_MIGRATION.read_text(encoding="utf-8")
    assert "cross_store_recovery_controller_history" in migration
    assert "cross_store_recovery_controller_current" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "GRANT INSERT" not in migration
    assert "initial controller snapshot must contain one event" in migration


def test_controller_authority_requires_postgresql() -> None:
    ledger = PostgresCrossStoreRecoveryControllerLedger(
        ("tenant-a",), create_engine("sqlite://")
    )
    with pytest.raises(
        CrossStoreRecoveryControllerAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        ledger.current("run-1")


def test_controller_authority_rejects_unsorted_or_duplicate_tenants() -> None:
    with pytest.raises(CrossStoreRecoveryControllerError, match="sorted and unique"):
        PostgresCrossStoreRecoveryControllerLedger(("tenant-b", "tenant-a"))
    with pytest.raises(CrossStoreRecoveryControllerError, match="sorted and unique"):
        PostgresCrossStoreRecoveryControllerLedger(("tenant-a", "tenant-a"))


def _tampered_append_snapshot(snapshot: CrossStoreRecoveryControllerSnapshot):
    first = snapshot.events[0]
    tampered_values = {
        "sequence": first.sequence,
        "event_type": first.event_type,
        "occurred_at": first.occurred_at,
        "detail": {"tampered": True},
    }
    tampered_first = CrossStoreRecoveryControllerEvent(
        **tampered_values,
        event_sha256=recovery_controller_event_fingerprint(**tampered_values),
    )
    tail = list(snapshot.events[1:])
    next_values = {
        "sequence": len(snapshot.events) + 1,
        "event_type": "completed",
        "occurred_at": snapshot.events[-1].occurred_at,
        "detail": {"binding_sha256": snapshot.binding_sha256},
    }
    tail.append(
        CrossStoreRecoveryControllerEvent(
            **next_values,
            event_sha256=recovery_controller_event_fingerprint(**next_values),
        )
    )
    events = (tampered_first, *tail)
    values = {
        "run_id": snapshot.run_id,
        "state": snapshot.state,
        "next_action": snapshot.next_action,
        "tenant_ids": snapshot.tenant_ids,
        "binding_sha256": snapshot.binding_sha256,
        "events": events,
    }
    return replace(
        snapshot,
        events=events,
        snapshot_sha256=recovery_controller_snapshot_fingerprint(**values),
    )


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_controller_is_durable_tenant_copied_and_append_only() -> None:
    admission = _admit()
    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        _install_controller_authority(sandbox)
        ledger = PostgresCrossStoreRecoveryControllerLedger(
            admission.binding.tenant_ids, sandbox.runtime_engine
        )
        controller = CrossStoreRecoveryController(
            "controller-authority-run", ledger=ledger
        )
        assert controller.snapshot.state is CrossStoreRecoveryRunState.PLANNED
        admitted = controller.admit(admission)
        completed = controller.complete(admission)
        assert admitted.state is CrossStoreRecoveryRunState.ADMITTED
        assert completed.state is CrossStoreRecoveryRunState.COMPLETED
        assert ledger.append(completed) == completed

        restarted_ledger = PostgresCrossStoreRecoveryControllerLedger(
            admission.binding.tenant_ids, sandbox.runtime_engine
        )
        restarted = CrossStoreRecoveryController(
            "controller-authority-run", ledger=restarted_ledger
        )
        assert restarted.snapshot == completed
        assert restarted_ledger.current(completed.run_id) == completed
        assert len(restarted_ledger.history(completed.run_id)) == 3

        failed = CrossStoreRecoveryController(
            "controller-failed-before-admission", ledger=restarted_ledger
        ).fail_closed("admission evidence unavailable")
        failed_restart = CrossStoreRecoveryController(
            "controller-failed-before-admission",
            ledger=PostgresCrossStoreRecoveryControllerLedger(
                admission.binding.tenant_ids, sandbox.runtime_engine
            ),
        )
        assert failed.state is CrossStoreRecoveryRunState.FAILED_CLOSED
        assert failed_restart.snapshot == failed

        with pytest.raises(DBAPIError):
            with sandbox.runtime_engine.connect() as connection:
                with connection.begin():
                    connection.exec_driver_sql(
                        'SET LOCAL ROLE "gda_control_gateway"'
                    )
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": "tenant-a"},
                    )
                    connection.execute(
                        text(
                            """
                            INSERT INTO gda_control.cross_store_recovery_controller_history
                                (tenant_id, run_id, snapshot_version, snapshot_sha256,
                                 snapshot_document)
                            VALUES (:tenant, :run_id, 99, :sha, CAST(:document AS jsonb))
                            """
                        ),
                        {
                            "tenant": "tenant-a",
                            "run_id": completed.run_id,
                            "sha": "f" * 64,
                            "document": json.dumps(completed.as_dict()),
                        },
                    )

        with pytest.raises(
            CrossStoreRecoveryControllerAuthorityValidationError,
            match="append-only|predecessor",
        ):
            restarted_ledger.append(_tampered_append_snapshot(completed))

        with sandbox.admin_connection() as connection:
            row_count = connection.execute(
                text(
                    "SELECT count(*) FROM "
                    "gda_control.cross_store_recovery_controller_history"
                )
            ).scalar_one()
            copy_count = connection.execute(
                text(
                    """
                    SELECT count(DISTINCT snapshot_document)
                    FROM gda_control.cross_store_recovery_controller_history
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": completed.run_id},
            ).scalar_one()
            failed_row_count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM gda_control.cross_store_recovery_controller_history
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": failed.run_id},
            ).scalar_one()
        assert row_count == 10
        assert copy_count == 3
        assert failed_row_count == 4

        isolated = PostgresCrossStoreRecoveryControllerLedger(
            ("tenant-c",), sandbox.runtime_engine
        )
        assert isolated.current(completed.run_id) is None
