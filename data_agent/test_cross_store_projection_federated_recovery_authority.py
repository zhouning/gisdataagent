from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine

from data_agent.cross_store_projection_federated_recovery import (
    FederatedProjectionRecoveryError,
    FederatedProjectionRecoveryState,
)
from data_agent.cross_store_projection_federated_recovery_authority import (
    FEDERATED_PROJECTION_RECOVERY_LEDGER_MIGRATION,
    FederatedProjectionRecoveryAuthorityConfigurationError,
    FederatedProjectionRecoveryAuthorityForbiddenError,
    PostgresFederatedProjectionRecoveryLedger,
)
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.cross_store_projection_recovery_authority import (
    PROJECTION_RECOVERY_LEDGER_MIGRATION,
    PostgresProjectionRecoveryLedger,
)
from data_agent.test_cross_store_projection_federated_recovery import (
    TENANT,
    _coordinator,
    _dependencies,
    _plans,
)


def test_migration_exposes_only_controlled_append_path() -> None:
    migration = FEDERATED_PROJECTION_RECOVERY_LEDGER_MIGRATION.read_text(
        encoding="utf-8"
    )

    assert "cross_store_projection_federated_recovery_event_history" in migration
    assert "cross_store_projection_federated_recovery_snapshot_history" in migration
    assert "cross_store_projection_federated_recovery_snapshot_current" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "jsonb_array_length(p_plan_sha256s) NOT BETWEEN 2 AND 32" in migration
    assert "federated recovery event chain is not append-only" in migration
    assert "UNIQUE (tenant_id, plan_sha256, event_sha256)" in migration
    assert "events.plan_sha256 = p_plan_sha256" in migration
    assert "GRANT INSERT" not in migration


def test_repository_requires_postgresql() -> None:
    ledger = PostgresFederatedProjectionRecoveryLedger(
        TENANT,
        create_engine("sqlite://"),
    )

    with pytest.raises(
        FederatedProjectionRecoveryAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        ledger.current("cq-federated-run")


def test_repository_rejects_cross_tenant_snapshot_before_database_access() -> None:
    plans = _plans()
    providers, authorities = _dependencies(plans)
    snapshot = _coordinator(plans, providers, authorities).snapshot

    with pytest.raises(
        FederatedProjectionRecoveryAuthorityForbiddenError,
        match="tenant",
    ):
        PostgresFederatedProjectionRecoveryLedger("cq-other-tenant").append(snapshot)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_federated_ledger_restart_and_isolation() -> None:
    plans = _plans()
    providers, authorities = _dependencies(plans, authority_fail_index=1)

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            for migration in (
                PROJECTION_RECOVERY_LEDGER_MIGRATION,
                FEDERATED_PROJECTION_RECOVERY_LEDGER_MIGRATION,
            ):
                connection.exec_driver_sql(
                    migration.read_text(encoding="utf-8").replace("%", "%%")
                )

        aggregate = PostgresFederatedProjectionRecoveryLedger(
            TENANT,
            sandbox.runtime_engine,
        )
        plan_ledgers = {
            plan.plan_sha256: PostgresProjectionRecoveryLedger(
                TENANT,
                sandbox.runtime_engine,
            )
            for plan in plans
        }
        first = _coordinator(
            plans,
            providers,
            authorities,
            ledger=aggregate,
            plan_ledgers=plan_ledgers,
        )
        yielded = first.advance(max_steps_per_item=1)

        assert (
            yielded.state is FederatedProjectionRecoveryState.RUNNING
        ), (
            yielded.last_error_code,
            yielded.events[-1].model_dump(mode="json"),
            yielded.items[yielded.current_position].model_dump(mode="json"),
        )
        assert yielded.current_position == 1
        assert providers[plans[1].plan_sha256].execute_count == 1

        reloaded = PostgresFederatedProjectionRecoveryLedger(
            TENANT,
            sandbox.runtime_engine,
        )
        assert reloaded.current("cq-federated-run") == yielded
        assert reloaded.append(yielded) == yielded
        assert (
            PostgresFederatedProjectionRecoveryLedger(
                "cq-federated-other",
                sandbox.runtime_engine,
            ).current("cq-federated-run")
            is None
        )

        completed = _coordinator(
            plans,
            providers,
            authorities,
            ledger=reloaded,
            plan_ledgers=plan_ledgers,
        ).advance()

        assert completed.state is FederatedProjectionRecoveryState.COMPLETED
        assert providers[plans[1].plan_sha256].execute_count == 1
        assert len(reloaded.history("cq-federated-run")) == len(completed.events)

        forged = completed.model_copy(update={"snapshot_sha256": "e" * 64})
        with pytest.raises(FederatedProjectionRecoveryError, match="append-only"):
            reloaded.append(forged)
