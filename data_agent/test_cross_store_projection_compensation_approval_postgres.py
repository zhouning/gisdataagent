from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.cross_store_projection_compensation_approval import (
    FederatedProjectionCompensationApprovalCaseRequest,
    FederatedProjectionCompensationApprovalService,
)
from data_agent.cross_store_projection_compensation_proposal import (
    CompensationProposalAction,
    build_federated_projection_compensation_proposal,
)
from data_agent.cross_store_projection_compensation_proposal_authority import (
    FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_MIGRATION,
    PostgresFederatedProjectionCompensationProposalStore,
)
from data_agent.cross_store_projection_compensation_rule_authority import (
    CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION,
    PostgresCustomerCompensationRuleAuthorityStore,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleStatus,
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
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _rule_contract,
    _trust_registry,
)
from data_agent.test_cross_store_projection_federated_recovery import (
    TENANT,
    _coordinator,
    _dependencies,
    _plans,
)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_trusted_candidate_creates_idempotent_review_case() -> None:
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        migration_dir = CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION.parent
        with sandbox.admin_connection() as connection:
            for migration in (
                migration_dir / "092_platform_control_ledger.sql",
                migration_dir / "094_platform_control_gateway.sql",
                migration_dir / "102_source_schema_drift_ledger.sql",
                migration_dir / "103_unified_approval_case_authority.sql",
                PROJECTION_RECOVERY_LEDGER_MIGRATION,
                FEDERATED_PROJECTION_RECOVERY_LEDGER_MIGRATION,
                FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_MIGRATION,
                CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION,
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
        PostgresFederatedProjectionCompensationProposalStore(
            TENANT,
            sandbox.runtime_engine,
        ).record(proposal)

        candidate = next(
            item
            for item in proposal.candidates
            if item.action is CompensationProposalAction.CORRECTIVE_FORWARD
        )
        contracts = tuple(
            _rule_contract(
                proposal,
                rule_id,
                CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
            )
            for rule_id in candidate.missing_customer_rule_ids
        )
        rule_store = PostgresCustomerCompensationRuleAuthorityStore(
            TENANT,
            sandbox.runtime_engine,
            trust_registry=_trust_registry(contracts),
        )
        for contract in contracts:
            rule_store.record(contract)

        request = FederatedProjectionCompensationApprovalCaseRequest(
            run_id=proposal.run_id,
            candidate_sha256=candidate.candidate_sha256,
            idempotency_key="postgres-compensation-review-001",
            request_reason="Review trusted persisted customer-rule evidence",
            requested_at=datetime(2026, 8, 16, 12, tzinfo=UTC),
            expires_at=datetime(2026, 8, 16, 12, tzinfo=UTC)
            + timedelta(hours=8),
        )
        service = FederatedProjectionCompensationApprovalService(
            rule_store,
            ApprovalCaseAuthority(sandbox.runtime_engine),
        )

        first = service.request_review(
            request,
            requester_subject="human:operator-1",
            owner_ref="team:data-platform",
        )
        second = service.request_review(
            request,
            requester_subject="human:operator-1",
            owner_ref="team:data-platform",
        )

        assert first.created is True
        assert second.created is False
        assert first.approval_case == second.approval_case
        assert first.binding.execution_allowed is False
        assert first.approval_case_is_execution_authority is False
