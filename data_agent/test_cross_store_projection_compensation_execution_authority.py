from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from data_agent.approval_case_authority import ApprovalCaseAuthority
from data_agent.cross_store_projection_compensation_approval import (
    FederatedProjectionCompensationApprovalCaseRequest,
    FederatedProjectionCompensationApprovalService,
    FederatedProjectionCompensationExecutionApprovalRequest,
    FederatedProjectionCompensationExecutionApprovalService,
)
from data_agent.cross_store_projection_compensation_execution_authority import (
    FEDERATED_COMPENSATION_EXECUTION_AUTHORIZATION_MIGRATION,
    FederatedCompensationExecutionAuthorityConfigurationError,
    FederatedCompensationExecutionAuthorityForbiddenError,
    FederatedCompensationExecutionAuthorityValidationError,
    FederatedCompensationExecutionAuthorizationConsumptionRequest,
    PostgresFederatedCompensationExecutionAuthorizationAuthority,
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
from data_agent.cross_store_projection_federated_recovery_authority import (
    FEDERATED_PROJECTION_RECOVERY_LEDGER_MIGRATION,
    PostgresFederatedProjectionRecoveryLedger,
)
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.cross_store_projection_recovery_authority import (
    PROJECTION_RECOVERY_LEDGER_MIGRATION,
    PostgresProjectionRecoveryLedger,
)
from data_agent.platform_contracts import ApprovalCaseStatus
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


def _request(
    *,
    tenant_id: str = TENANT,
    consumed_by: str = "workload:controlled-compensation-executor",
) -> FederatedCompensationExecutionAuthorizationConsumptionRequest:
    return FederatedCompensationExecutionAuthorizationConsumptionRequest(
        tenant_id=tenant_id,
        execution_approval_case_ref=(
            f"gda://{tenant_id}/approval_case/compensation-execute-001"
        ),
        review_approval_case_ref=(
            f"gda://{tenant_id}/approval_case/compensation-review-001"
        ),
        proposal_sha256="a" * 64,
        candidate_sha256="b" * 64,
        execution_authorization_sha256="c" * 64,
        review_binding_sha256="d" * 64,
        consumed_by=consumed_by,
        consume_reason="Reserve the independently approved candidate",
    )


def test_migration_is_one_time_append_only_and_provider_free() -> None:
    migration = FEDERATED_COMPENSATION_EXECUTION_AUTHORIZATION_MIGRATION.read_text(
        encoding="utf-8"
    )

    assert "federated_compensation_execution_authorization_consumption" in migration
    assert "projection.federated.compensation.review" in migration
    assert "projection.federated.compensation.execute" in migration
    assert "execution verdict is not independent from review verdict" in migration
    assert "review ApprovalCase was already consumed for execution" in migration
    assert "compensation candidate current drifted before consumption" in migration
    assert "customer compensation rule current drifted before consumption" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "GRANT INSERT" not in migration
    assert "GRANT UPDATE" not in migration
    assert "GRANT DELETE" not in migration


def test_request_rejects_untyped_actor_and_cross_tenant_case() -> None:
    with pytest.raises(ValidationError, match="typed identity"):
        _request(consumed_by="executor")

    forged = _request().model_dump(mode="python")
    forged["review_approval_case_ref"] = (
        "gda://cq-other/approval_case/compensation-review-001"
    )
    with pytest.raises(ValidationError, match="tenant differs"):
        FederatedCompensationExecutionAuthorizationConsumptionRequest(**forged)


def test_authority_requires_postgresql_and_rejects_store_tenant_drift() -> None:
    request = _request()
    with pytest.raises(
        FederatedCompensationExecutionAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        PostgresFederatedCompensationExecutionAuthorizationAuthority(
            TENANT,
            create_engine("sqlite://"),
        ).consume(request)

    with pytest.raises(
        FederatedCompensationExecutionAuthorityForbiddenError,
        match="tenant differs",
    ):
        PostgresFederatedCompensationExecutionAuthorizationAuthority(
            "cq-other"
        ).consume(request)


def test_mocked_postgres_row_builds_non_execution_receipt() -> None:
    request = _request()
    row = {
        **request.model_dump(mode="python"),
        "execution_decided_by": "human:execution-reviewer",
        "review_decided_by": "human:evidence-reviewer",
        "consumed_at": datetime(2026, 8, 16, 12, tzinfo=UTC),
    }
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    connection.begin.return_value.__enter__.return_value = MagicMock()
    query_result = MagicMock()
    query_result.mappings.return_value.one.return_value = row
    connection.execute.side_effect = [MagicMock(), query_result]

    receipt = PostgresFederatedCompensationExecutionAuthorizationAuthority(
        TENANT,
        engine,
    ).consume(request)

    assert receipt.authorization_consumed is True
    assert receipt.provider_execution_performed is False
    assert receipt.receipt_is_provider_execution_result is False
    assert receipt.review_state == "technical_baseline_unreviewed"
    assert receipt.intended_use == "assisted_precheck_not_for_production_decision"
    assert connection.execute.call_count == 2


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_consumes_two_independent_approvals_exactly_once() -> None:
    plans = _plans()
    providers, authorities = _dependencies(
        plans,
        provider_modes={1: "unknown_without_receipt"},
    )

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            migration_dir = FEDERATED_COMPENSATION_EXECUTION_AUTHORIZATION_MIGRATION.parent
            for migration in (
                migration_dir / "092_platform_control_ledger.sql",
                migration_dir / "094_platform_control_gateway.sql",
                migration_dir / "102_source_schema_drift_ledger.sql",
                migration_dir / "103_unified_approval_case_authority.sql",
                PROJECTION_RECOVERY_LEDGER_MIGRATION,
                FEDERATED_PROJECTION_RECOVERY_LEDGER_MIGRATION,
                FEDERATED_PROJECTION_COMPENSATION_PROPOSAL_MIGRATION,
                CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION,
                FEDERATED_COMPENSATION_EXECUTION_AUTHORIZATION_MIGRATION,
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
        contract = _rule_contract(
            proposal,
            candidate.missing_customer_rule_ids[0],
            CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
        )
        rule_authority = PostgresCustomerCompensationRuleAuthorityStore(
            TENANT,
            sandbox.runtime_engine,
            trust_registry=_trust_registry((contract,)),
        )
        rule_authority.record(contract)

        approval_authority = ApprovalCaseAuthority(sandbox.runtime_engine)
        now = datetime.now(UTC)
        review = FederatedProjectionCompensationApprovalService(
            rule_authority,
            approval_authority,
        ).request_review(
            FederatedProjectionCompensationApprovalCaseRequest(
                run_id=proposal.run_id,
                candidate_sha256=candidate.candidate_sha256,
                idempotency_key="postgres-review-001",
                request_reason="Review current customer-rule candidate evidence",
                requested_at=now,
                expires_at=now + timedelta(hours=6),
            ),
            requester_subject="human:operator",
            owner_ref="team:data-platform",
        )
        reviewed_case = approval_authority.decide(
            tenant_id=TENANT,
            approval_case_ref=review.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:evidence-reviewer",
            reason="Current technical evidence is internally consistent",
        )

        execution = FederatedProjectionCompensationExecutionApprovalService(
            rule_authority,
            approval_authority,
        ).request_execution_authorization(
            FederatedProjectionCompensationExecutionApprovalRequest(
                run_id=proposal.run_id,
                candidate_sha256=candidate.candidate_sha256,
                review_approval_case_ref=reviewed_case.approval_case_ref,
                idempotency_key="postgres-execution-review-001",
                request_reason="Request an independent execution verdict",
                requested_at=reviewed_case.decided_at,
                expires_at=reviewed_case.expires_at - timedelta(minutes=1),
            ),
            requester_subject="human:operator",
            owner_ref="team:data-platform",
        )
        execution_case = approval_authority.decide(
            tenant_id=TENANT,
            approval_case_ref=execution.approval_case.approval_case_ref,
            expected_state_version=0,
            verdict=ApprovalCaseStatus.APPROVED,
            actor_subject="human:execution-reviewer",
            reason="Separately authorize one controlled consumption",
        )
        binding = execution.execution_binding
        consume_request = (
            FederatedCompensationExecutionAuthorizationConsumptionRequest(
                tenant_id=TENANT,
                execution_approval_case_ref=execution_case.approval_case_ref,
                review_approval_case_ref=reviewed_case.approval_case_ref,
                proposal_sha256=binding.proposal_sha256,
                candidate_sha256=binding.candidate_sha256,
                execution_authorization_sha256=(
                    binding.execution_authorization_sha256
                ),
                review_binding_sha256=binding.review_binding.binding_sha256,
                consumed_by="workload:controlled-compensation-executor",
                consume_reason="Reserve the approved candidate for controlled execution",
            )
        )
        authority = PostgresFederatedCompensationExecutionAuthorizationAuthority(
            TENANT,
            sandbox.runtime_engine,
        )
        first = authority.consume(consume_request)
        replay = authority.consume(consume_request)

        assert replay == first
        assert first.authorization_consumed is True
        assert first.provider_execution_performed is False
        with pytest.raises(
            FederatedCompensationExecutionAuthorityValidationError,
            match="already consumed differently",
        ):
            authority.consume(
                consume_request.model_copy(
                    update={"consume_reason": "A conflicting replay"}
                )
            )
