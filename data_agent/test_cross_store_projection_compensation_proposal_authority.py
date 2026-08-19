from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import create_engine, text

from data_agent.cross_store_projection_compensation_proposal import (
    build_federated_projection_compensation_proposal,
)
from data_agent.cross_store_projection_compensation_proposal_authority import (
    FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_MIGRATION,
    FederatedProjectionCompensationProposalConfigurationError,
    FederatedProjectionCompensationProposalForbiddenError,
    FederatedProjectionCompensationProposalValidationError,
    PostgresFederatedProjectionCompensationProposalStore,
)
from data_agent.cross_store_projection_federated_recovery import (
    FederatedProjectionRecoveryState,
)
from data_agent.cross_store_projection_federated_recovery_authority import (
    FEDERATED_PROJECTION_RECOVERY_LEDGER_MIGRATION,
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


def test_migration_exposes_only_governed_immutable_proposal_storage() -> None:
    migration = FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_MIGRATION.read_text(
        encoding="utf-8"
    )

    assert "cross_store_projection_compensation_proposal" in migration
    assert (
        "REFERENCES gda_control."
        "cross_store_projection_federated_recovery_snapshot_history"
        in migration
    )
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "chongqing_customer_dataset" in migration
    assert "natural-resource-one-map:2.3.0:587915868b1221af" in migration
    assert "GRANT INSERT" not in migration


def test_repository_requires_postgresql() -> None:
    store = PostgresFederatedProjectionCompensationProposalStore(
        TENANT,
        create_engine("sqlite://"),
    )

    with pytest.raises(
        FederatedProjectionCompensationProposalConfigurationError,
        match="requires PostgreSQL",
    ):
        store.current("cq-federated-run")


def test_repository_rejects_cross_tenant_proposal_before_database_access() -> None:
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )
    snapshot = _coordinator(plans, providers, authorities).advance()
    proposal = build_federated_projection_compensation_proposal(plans, snapshot)

    with pytest.raises(
        FederatedProjectionCompensationProposalForbiddenError,
        match="tenant",
    ):
        PostgresFederatedProjectionCompensationProposalStore(
            "cq-other-tenant"
        ).record(proposal)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_proposal_persists_idempotently_and_isolates_tenants() -> None:
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            for migration in (
                PROJECTION_RECOVERY_LEDGER_MIGRATION,
                FEDERATED_PROJECTION_RECOVERY_LEDGER_MIGRATION,
                FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_MIGRATION,
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
        snapshot = _coordinator(
            plans,
            providers,
            authorities,
            ledger=aggregate,
            plan_ledgers=plan_ledgers,
        ).advance()
        assert snapshot.state is FederatedProjectionRecoveryState.COMPENSATION_REQUIRED
        proposal = build_federated_projection_compensation_proposal(plans, snapshot)

        store = PostgresFederatedProjectionCompensationProposalStore(
            TENANT,
            sandbox.runtime_engine,
        )
        assert store.record(proposal) == proposal
        assert store.record(proposal) == proposal
        assert store.current(proposal.run_id) == proposal
        assert store.history(proposal.run_id) == (proposal,)
        lookup = store.lookup(proposal.run_id)
        assert lookup is not None
        assert lookup.current == proposal
        assert lookup.history == (proposal,)
        assert lookup.history_count == 1
        assert lookup.execution_allowed is False
        assert (
            PostgresFederatedProjectionCompensationProposalStore(
                "cq-other-tenant",
                sandbox.runtime_engine,
            ).lookup(proposal.run_id)
            is None
        )

        forged_document = proposal.model_dump(mode="json")
        forged_document["execution_allowed"] = True
        with pytest.raises(
            FederatedProjectionCompensationProposalValidationError,
            match="rejected",
        ):
            with store._transaction() as connection:
                connection.execute(
                    text(
                        """
                        SELECT gda_control.record_cross_store_projection_compensation_proposal(
                            :tenant_id, :run_id, :source_snapshot_sha256,
                            :blocked_plan_sha256, :proposal_sha256,
                            :ontology_content_sha256,
                            CAST(:proposal_document AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": TENANT,
                        "run_id": proposal.run_id,
                        "source_snapshot_sha256": proposal.source_snapshot_sha256,
                        "blocked_plan_sha256": proposal.blocked_plan_sha256,
                        "proposal_sha256": proposal.proposal_sha256,
                        "ontology_content_sha256": (
                            proposal.ontology.content_sha256
                        ),
                        "proposal_document": json.dumps(forged_document),
                    },
                )
