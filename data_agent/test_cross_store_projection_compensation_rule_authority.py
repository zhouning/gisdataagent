from __future__ import annotations

import json
import os

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from data_agent.cross_store_projection_compensation_rule_authority import (
    CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION,
    CustomerCompensationRuleAuthorityConfigurationError,
    CustomerCompensationRuleAuthorityForbiddenError,
    CustomerCompensationRuleAuthorityValidationError,
    PostgresCustomerCompensationRuleAuthorityStore,
)
from data_agent.cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleAuthorityReadRequest,
    CustomerCompensationRuleStatus,
    build_customer_compensation_rule_contract,
)
from data_agent.cross_store_projection_compensation_trust import (
    build_customer_compensation_approval_trust_registry,
)
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.test_cross_store_projection_compensation_rule_contract import (
    _proposal,
    _rule_contract,
    _trust_registry,
)

TENANT = "cq-customer-rule-authority"


def test_migration_exposes_only_governed_immutable_rule_storage() -> None:
    migration = CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION.read_text(
        encoding="utf-8"
    )

    assert "customer_compensation_rule_contract" in migration
    assert "customer_compensation_rule_contract_current" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "chongqing_customer_dataset" in migration
    assert "natural-resource-one-map:2.3.0:587915868b1221af" in migration
    assert "technical_baseline_unreviewed" in migration
    assert "assisted_precheck_not_for_production_decision" in migration
    assert "GRANT INSERT" not in migration


def test_repository_requires_postgresql() -> None:
    store = PostgresCustomerCompensationRuleAuthorityStore(
        TENANT,
        create_engine("sqlite://"),
    )

    with pytest.raises(
        CustomerCompensationRuleAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        store.lookup()


def test_repository_rejects_cross_tenant_contract_before_database_access() -> None:
    proposal = _proposal()
    rule_id = proposal.missing_customer_rule_ids[0]
    contract = _rule_contract(
        proposal,
        rule_id,
        CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
    )
    with pytest.raises(
        CustomerCompensationRuleAuthorityForbiddenError,
        match="tenant",
    ):
        PostgresCustomerCompensationRuleAuthorityStore(
            "cq-other-customer-rule-authority"
        ).record(contract)


def test_approved_rule_requires_deployment_trust_registry() -> None:
    proposal = _proposal()
    contract = _rule_contract(
        proposal,
        proposal.missing_customer_rule_ids[0],
        CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
    )
    store = PostgresCustomerCompensationRuleAuthorityStore(
        proposal.tenant_id,
        create_engine("sqlite://"),
        trust_registry=build_customer_compensation_approval_trust_registry(),
    )

    with pytest.raises(
        CustomerCompensationRuleAuthorityValidationError,
        match="trust",
    ):
        store.record(contract)


def test_trusted_approval_passes_python_boundary_before_postgresql_check() -> None:
    proposal = _proposal()
    contract = _rule_contract(
        proposal,
        proposal.missing_customer_rule_ids[0],
        CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
    )
    registry = _trust_registry((contract,))
    store = PostgresCustomerCompensationRuleAuthorityStore(
        proposal.tenant_id,
        create_engine("sqlite://"),
        trust_registry=registry,
    )

    with pytest.raises(CustomerCompensationRuleAuthorityConfigurationError):
        store.record(contract)


def test_read_request_rejects_invalid_rule_id_and_models_are_non_executable() -> None:
    with pytest.raises(ValidationError):
        CustomerCompensationRuleAuthorityReadRequest(rule_id="not-a-customer-rule")

    proposal = _proposal()
    contract = _rule_contract(
        proposal,
        proposal.missing_customer_rule_ids[0],
        CustomerCompensationRuleStatus.DRAFT_UNREVIEWED,
    )
    forged = contract.model_dump(mode="json")
    forged["execution_allowed"] = True
    with pytest.raises(ValidationError):
        build_customer_compensation_rule_contract(
            tenant_id=contract.tenant_id,
            rule=contract.rule,
            status=contract.status,
        ).model_validate(forged)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_rule_authority_is_idempotent_append_only_and_tenant_scoped() -> None:
    proposal = _proposal()
    rule_id = proposal.missing_customer_rule_ids[0]
    draft = _rule_contract(proposal, rule_id, CustomerCompensationRuleStatus.DRAFT_UNREVIEWED)
    awaiting = _rule_contract(
        proposal,
        rule_id,
        CustomerCompensationRuleStatus.AWAITING_CUSTOMER_APPROVAL,
    )
    approved = _rule_contract(
        proposal,
        rule_id,
        CustomerCompensationRuleStatus.CUSTOMER_APPROVED,
    )

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            for migration_name in (
                    "092_platform_control_ledger.sql",
                    "094_platform_control_gateway.sql",
                ):
                migration = (
                    CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION.parent
                    / migration_name
                )
                connection.exec_driver_sql(
                    migration.read_text(encoding="utf-8").replace("%", "%%")
                )
                connection.exec_driver_sql(
                    CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION.read_text(
                        encoding="utf-8"
                    ).replace("%", "%%")
                )
                lifecycle_guard_migration = (
                    CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION.parent
                    / "184_customer_compensation_rule_lifecycle_guard.sql"
                )
                connection.exec_driver_sql(
                    lifecycle_guard_migration.read_text(encoding="utf-8").replace(
                        "%", "%%"
                    )
                )

        store = PostgresCustomerCompensationRuleAuthorityStore(
            proposal.tenant_id,
            sandbox.runtime_engine,
            trust_registry=_trust_registry((approved,)),
        )
        assert store.record(draft) == draft
        assert store.record(draft) == draft
        assert store.record(awaiting) == awaiting
        assert store.record(approved) == approved
        assert store.current(rule_id) == approved
        assert store.history(rule_id) == (draft, awaiting, approved)
        lookup = store.lookup(rule_id)
        assert lookup is not None
        assert lookup.rule_count == 1
        assert lookup.items[0].current == approved
        assert lookup.items[0].history == (draft, awaiting, approved)
        assert lookup.execution_allowed is False
        assert (
            PostgresCustomerCompensationRuleAuthorityStore(
                "cq-other-customer-rule-authority",
                sandbox.runtime_engine,
            ).lookup(rule_id).items
            == ()
        )

        with pytest.raises(CustomerCompensationRuleAuthorityValidationError, match="regress"):
            store.record(draft)

        with pytest.raises(
            CustomerCompensationRuleAuthorityForbiddenError,
            match="tenant or role was denied",
        ):
            with store._transaction() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.customer_compensation_rule_contract (
                            tenant_id, rule_id, semantic_version, rule_sha256,
                            contract_sha256, status, contract_document
                        ) VALUES (:tenant_id, :rule_id, :semantic_version, :rule_sha256,
                                  :contract_sha256, :status,
                                  CAST(:contract_document AS jsonb))
                        """
                    ),
                    {
                        "tenant_id": proposal.tenant_id,
                        "rule_id": rule_id,
                        "semantic_version": draft.rule.semantic_version,
                        "rule_sha256": draft.rule.rule_sha256,
                        "contract_sha256": "f" * 64,
                        "status": draft.status.value,
                        "contract_document": json.dumps(draft.model_dump(mode="json")),
                    },
                )
