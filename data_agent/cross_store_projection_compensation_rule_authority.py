"""PostgreSQL authority for immutable customer compensation rule contracts.

The authority stores lifecycle evidence supplied by a trusted internal service.
It exposes current/history reads to the platform gateway, but has no public
write, approval, candidate-selection, or execution surface.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .cross_store_projection_authority import _sqlstate
from .cross_store_projection_compensation_proposal import (
    FederatedProjectionCompensationProposal,
    FederatedProjectionCompensationProposalReadRequest,
)
from .cross_store_projection_compensation_rule_contract import (
    CustomerCompensationRuleAuthorityItem,
    CustomerCompensationRuleAuthorityReadRequest,
    CustomerCompensationRuleAuthorityReadResponse,
    CustomerCompensationRuleContract,
    CustomerCompensationRuleError,
    CustomerCompensationRuleStatus,
    CustomerCompensationRuleTechnicalBaselineBootstrapResult,
    FederatedProjectionCompensationRuleAssessment,
    FederatedProjectionCompensationRuleAuthorityAssessmentEvidence,
    assess_federated_projection_compensation_rules,
    build_customer_compensation_rule_technical_baseline_drafts,
)
from .cross_store_projection_compensation_trust import (
    CustomerCompensationApprovalTrustRegistry,
    load_customer_compensation_approval_trust_registry,
)
from .db_engine import get_engine
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "179_cross_store_projection_compensation_rule_authority.sql"
)


class CustomerCompensationRuleAuthorityError(RuntimeError):
    """Base error for the durable customer-rule authority."""


class CustomerCompensationRuleAuthorityConfigurationError(
    CustomerCompensationRuleAuthorityError
):
    """The database or trust configuration cannot enforce the authority."""


class CustomerCompensationRuleAuthorityForbiddenError(
    CustomerCompensationRuleAuthorityError
):
    """The current role or tenant context was denied."""


class CustomerCompensationRuleAuthorityValidationError(
    CustomerCompensationRuleAuthorityError
):
    """A rule contract or authority query is invalid."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_value(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _postgres_validation_message(exc: DBAPIError) -> str:
    """Keep the governed SQL function's validation reason without exposing SQL."""

    diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
    detail = getattr(diagnostic, "message_primary", None)
    if isinstance(detail, str) and detail.strip():
        return f"customer compensation rule contract was rejected: {detail.strip()}"
    return "customer compensation rule contract was rejected"


class PostgresCustomerCompensationRuleAuthorityStore:
    """Tenant-bound append-only rule contract repository."""

    def __init__(
        self,
        tenant_id: str,
        engine: Any = None,
        trust_registry: CustomerCompensationApprovalTrustRegistry | None = None,
    ):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise CustomerCompensationRuleAuthorityValidationError(
                "customer compensation rule authority tenant_id is required"
            )
        self.tenant_id = tenant_id.strip()
        self._engine = engine
        self._trust_registry = trust_registry

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "customer compensation rule authority requires PostgreSQL"
            )
        return engine

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        try:
            with self._get_engine().connect() as connection:
                with connection.begin():
                    try:
                        connection.exec_driver_sql(
                            f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
                        )
                    except DBAPIError as exc:
                        raise CustomerCompensationRuleAuthorityConfigurationError(
                            "database login is not a member of the platform gateway role"
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except CustomerCompensationRuleAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise CustomerCompensationRuleAuthorityValidationError(
                    "customer compensation rule authority idempotency conflict"
                ) from exc
            if state == "42501":
                raise CustomerCompensationRuleAuthorityForbiddenError(
                    "customer compensation rule authority tenant or role was denied"
                ) from exc
            if state in {"22023", "22P02", "23502", "23514"}:
                raise CustomerCompensationRuleAuthorityValidationError(
                    _postgres_validation_message(exc)
                ) from exc
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "customer compensation rule authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "customer compensation rule authority operation failed"
            ) from exc

    @staticmethod
    def _contract(document: Any) -> CustomerCompensationRuleContract:
        try:
            return CustomerCompensationRuleContract.model_validate(_json_value(document))
        except (TypeError, ValueError, ValidationError) as exc:
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "stored customer compensation rule contract is invalid"
            ) from exc

    @staticmethod
    def _proposal(document: Any) -> FederatedProjectionCompensationProposal:
        try:
            return FederatedProjectionCompensationProposal.model_validate(
                _json_value(document)
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "stored projection compensation proposal is invalid"
            ) from exc

    def _assessment_trust_registry(
        self,
    ) -> CustomerCompensationApprovalTrustRegistry:
        return (
            self._trust_registry
            if self._trust_registry is not None
            else load_customer_compensation_approval_trust_registry()
        )

    def _trusted_approval(self, contract: CustomerCompensationRuleContract) -> None:
        if contract.status is not CustomerCompensationRuleStatus.CUSTOMER_APPROVED:
            return
        evidence = contract.approval_evidence
        if evidence is None:
            raise CustomerCompensationRuleAuthorityValidationError(
                "customer-approved rule lacks approval evidence"
            )
        registry = self._trust_registry
        if registry is None:
            try:
                registry = load_customer_compensation_approval_trust_registry()
            except RuntimeError as exc:
                raise CustomerCompensationRuleAuthorityConfigurationError(
                    str(exc)
                ) from exc
        decision = registry.evaluate(
            tenant_id=contract.tenant_id,
            customer_authority_ref=evidence.customer_authority_ref,
            signature_key_id=evidence.signature_key_id,
            signature_algorithm=evidence.signature_algorithm,
            public_key_sha256=evidence.public_key_sha256,
            signed_at=evidence.signed_at,
            evaluated_at=datetime.now(UTC),
        )
        if not decision.trusted:
            raise CustomerCompensationRuleAuthorityValidationError(
                decision.reason_code or "customer approval key is not trusted"
            )

    def record(
        self,
        contract: CustomerCompensationRuleContract,
    ) -> CustomerCompensationRuleContract:
        """Append one validated lifecycle record through the governed SQL function."""

        if contract.tenant_id != self.tenant_id:
            raise CustomerCompensationRuleAuthorityForbiddenError(
                "customer compensation rule contract tenant differs from the store"
            )
        try:
            contract = CustomerCompensationRuleContract.model_validate(
                contract.model_dump(mode="json")
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise CustomerCompensationRuleAuthorityValidationError(
                "customer compensation rule contract is invalid"
            ) from exc
        self._trusted_approval(contract)
        current = self.current(contract.rule.rule_id)
        if current is not None:
            status_rank = {
                CustomerCompensationRuleStatus.DRAFT_UNREVIEWED: 1,
                CustomerCompensationRuleStatus.AWAITING_CUSTOMER_APPROVAL: 2,
                CustomerCompensationRuleStatus.CUSTOMER_APPROVED: 3,
            }
            if status_rank[contract.status] < status_rank[current.status]:
                raise CustomerCompensationRuleAuthorityValidationError(
                    "customer compensation rule lifecycle cannot regress"
                )
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT contract_document, created
                    FROM gda_control.record_customer_compensation_rule_contract(
                        :tenant_id, :rule_id, :semantic_version,
                        :rule_sha256, :contract_sha256, :status,
                        CAST(:contract_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "rule_id": contract.rule.rule_id,
                    "semantic_version": contract.rule.semantic_version,
                    "rule_sha256": contract.rule.rule_sha256,
                    "contract_sha256": contract.contract_sha256,
                    "status": contract.status.value,
                    "contract_document": _json(contract.model_dump(mode="json")),
                },
            ).mappings().one()
        stored = self._contract(row["contract_document"])
        if stored.contract_sha256 != contract.contract_sha256:
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "customer rule authority returned a different contract"
            )
        return stored

    @staticmethod
    def _query(rule_id: str | None) -> CustomerCompensationRuleAuthorityReadRequest:
        try:
            return CustomerCompensationRuleAuthorityReadRequest(rule_id=rule_id)
        except ValidationError as exc:
            raise CustomerCompensationRuleAuthorityValidationError(
                "customer compensation rule authority rule_id is invalid"
            ) from exc

    def current(self, rule_id: str) -> CustomerCompensationRuleContract | None:
        query = self._query(rule_id)
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT contract_document
                    FROM gda_control.customer_compensation_rule_contract_current
                    WHERE tenant_id = :tenant_id AND rule_id = :rule_id
                    """
                ),
                {"tenant_id": self.tenant_id, "rule_id": query.rule_id},
            ).mappings().one_or_none()
        return None if row is None else self._contract(row["contract_document"])

    def history(
        self,
        rule_id: str,
    ) -> tuple[CustomerCompensationRuleContract, ...]:
        query = self._query(rule_id)
        with self._transaction() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT contract_document
                    FROM gda_control.customer_compensation_rule_contract
                    WHERE tenant_id = :tenant_id AND rule_id = :rule_id
                    ORDER BY recorded_at, contract_sha256
                    """
                ),
                {"tenant_id": self.tenant_id, "rule_id": query.rule_id},
            ).mappings().all()
        return tuple(self._contract(row["contract_document"]) for row in rows)

    def lookup(
        self,
        rule_id: str | None = None,
    ) -> CustomerCompensationRuleAuthorityReadResponse:
        """Read current and complete history in one PostgreSQL statement."""

        query = self._query(rule_id)
        with self._transaction() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT current.rule_id,
                           current.contract_document AS current_document,
                           history.history_documents
                    FROM gda_control.customer_compensation_rule_contract_current
                         AS current
                    CROSS JOIN LATERAL (
                        SELECT COALESCE(
                            jsonb_agg(
                                stored.contract_document
                                ORDER BY stored.recorded_at, stored.contract_sha256
                            ),
                            '[]'::jsonb
                        ) AS history_documents
                        FROM gda_control.customer_compensation_rule_contract AS stored
                        WHERE stored.tenant_id = :tenant_id
                          AND stored.rule_id = current.rule_id
                    ) AS history
                    WHERE current.tenant_id = :tenant_id
                      AND (
                          CAST(:rule_id AS TEXT) IS NULL
                          OR current.rule_id = CAST(:rule_id AS TEXT)
                      )
                    ORDER BY current.rule_id
                    """
                ),
                {"tenant_id": self.tenant_id, "rule_id": query.rule_id},
            ).mappings().all()
        items = []
        for row in rows:
            current = self._contract(row["current_document"])
            documents = _json_value(row["history_documents"])
            if not isinstance(documents, list):
                raise CustomerCompensationRuleAuthorityConfigurationError(
                    "stored customer rule authority history is invalid"
                )
            history = tuple(self._contract(document) for document in documents)
            items.append(
                CustomerCompensationRuleAuthorityItem(
                    tenant_id=self.tenant_id,
                    rule_id=current.rule.rule_id,
                    current=current,
                    history=history,
                    history_count=len(history),
                )
            )
        try:
            return CustomerCompensationRuleAuthorityReadResponse(
                tenant_id=self.tenant_id,
                requested_rule_id=query.rule_id,
                items=tuple(items),
                rule_count=len(items),
            )
        except ValidationError as exc:
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "stored customer rule authority lookup is inconsistent"
            ) from exc

    def assessment_evidence_current(
        self,
        run_id: str,
    ) -> FederatedProjectionCompensationRuleAuthorityAssessmentEvidence | None:
        """Load and assess proposal/rule current state in one DB snapshot."""

        try:
            query = FederatedProjectionCompensationProposalReadRequest(run_id=run_id)
        except ValidationError as exc:
            raise CustomerCompensationRuleAuthorityValidationError(
                "federated compensation rule assessment run_id is invalid"
            ) from exc
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT proposal.proposal_document,
                           COALESCE(
                               (
                                   SELECT jsonb_agg(
                                       rule.contract_document ORDER BY rule.rule_id
                                   )
                                   FROM gda_control.
                                        customer_compensation_rule_contract_current
                                        AS rule
                                   WHERE rule.tenant_id = :tenant_id
                               ),
                               '[]'::jsonb
                           ) AS current_rule_documents
                    FROM gda_control.
                         cross_store_projection_compensation_proposal_current
                         AS proposal
                    WHERE proposal.tenant_id = :tenant_id
                      AND proposal.run_id = :run_id
                    """
                ),
                {"tenant_id": self.tenant_id, "run_id": query.run_id},
            ).mappings().one_or_none()
        if row is None:
            return None
        proposal = self._proposal(row["proposal_document"])
        documents = _json_value(row["current_rule_documents"])
        if not isinstance(documents, list):
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "stored customer rule authority current projection is invalid"
            )
        current_by_rule_id = {}
        for document in documents:
            contract = self._contract(document)
            if contract.rule.rule_id in current_by_rule_id:
                raise CustomerCompensationRuleAuthorityConfigurationError(
                    "stored customer rule authority current projection is duplicated"
                )
            current_by_rule_id[contract.rule.rule_id] = contract
        rules = tuple(
            current_by_rule_id[rule_id]
            for rule_id in proposal.missing_customer_rule_ids
            if rule_id in current_by_rule_id
        )
        try:
            assessment = assess_federated_projection_compensation_rules(
                proposal,
                rules,
                self._assessment_trust_registry(),
            )
            return FederatedProjectionCompensationRuleAuthorityAssessmentEvidence(
                proposal=proposal,
                current_rules=rules,
                assessment=assessment,
            )
        except (CustomerCompensationRuleError, ValidationError) as exc:
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "stored customer rule authority cannot be assessed"
            ) from exc

    def assess_current(
        self,
        run_id: str,
    ) -> FederatedProjectionCompensationRuleAssessment | None:
        """Return the read-only assessment projection for one persisted run."""

        evidence = self.assessment_evidence_current(run_id)
        return None if evidence is None else evidence.assessment

    def _record_technical_baseline_if_absent(
        self,
        contract: CustomerCompensationRuleContract,
    ) -> tuple[CustomerCompensationRuleContract, bool]:
        """Record one draft only when no lifecycle current exists for its rule."""

        with self._transaction() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_advisory_xact_lock(
                        hashtextextended(:authority_identity, 0)
                    )
                    """
                ),
                {
                    "authority_identity": (
                        "customer-compensation-rule|"
                        f"{self.tenant_id}|{contract.rule.rule_id}"
                    )
                },
            )
            current_row = connection.execute(
                text(
                    """
                    SELECT contract_document
                    FROM gda_control.customer_compensation_rule_contract_current
                    WHERE tenant_id = :tenant_id AND rule_id = :rule_id
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "rule_id": contract.rule.rule_id,
                },
            ).mappings().one_or_none()
            if current_row is not None:
                return self._contract(current_row["contract_document"]), False
            recorded_row = connection.execute(
                text(
                    """
                    SELECT contract_document, created
                    FROM gda_control.record_customer_compensation_rule_contract(
                        :tenant_id, :rule_id, :semantic_version,
                        :rule_sha256, :contract_sha256, :status,
                        CAST(:contract_document AS jsonb)
                    )
                    """
                ),
                {
                    "tenant_id": self.tenant_id,
                    "rule_id": contract.rule.rule_id,
                    "semantic_version": contract.rule.semantic_version,
                    "rule_sha256": contract.rule.rule_sha256,
                    "contract_sha256": contract.contract_sha256,
                    "status": contract.status.value,
                    "contract_document": _json(contract.model_dump(mode="json")),
                },
            ).mappings().one()
        stored = self._contract(recorded_row["contract_document"])
        return stored, bool(recorded_row["created"])

    def bootstrap_technical_baseline(
        self,
        proposal: FederatedProjectionCompensationProposal,
    ) -> CustomerCompensationRuleTechnicalBaselineBootstrapResult:
        """Idempotently fill absent rules with proposal-derived draft evidence."""

        if proposal.tenant_id != self.tenant_id:
            raise CustomerCompensationRuleAuthorityForbiddenError(
                "projection compensation proposal tenant differs from the store"
            )
        proposal = self._proposal(proposal.model_dump(mode="json"))
        desired = build_customer_compensation_rule_technical_baseline_drafts(proposal)
        created_rule_ids = []
        reused_rule_ids = []
        current_contracts = []
        for contract in desired:
            current, created = self._record_technical_baseline_if_absent(contract)
            current_contracts.append(current)
            (created_rule_ids if created else reused_rule_ids).append(
                contract.rule.rule_id
            )
        try:
            assessment = assess_federated_projection_compensation_rules(
                proposal,
                tuple(current_contracts),
                self._assessment_trust_registry(),
            )
            return CustomerCompensationRuleTechnicalBaselineBootstrapResult(
                tenant_id=self.tenant_id,
                run_id=proposal.run_id,
                proposal_sha256=proposal.proposal_sha256,
                desired_draft_contracts=desired,
                created_draft_rule_ids=tuple(created_rule_ids),
                reused_current_rule_ids=tuple(reused_rule_ids),
                invalid_or_drifted_rule_ids=(
                    assessment.invalid_or_drifted_rule_ids
                ),
                assessment=assessment,
            )
        except (CustomerCompensationRuleError, ValidationError) as exc:
            raise CustomerCompensationRuleAuthorityConfigurationError(
                "customer rule technical baseline result is inconsistent"
            ) from exc


__all__ = [
    "CUSTOMER_COMPENSATION_RULE_AUTHORITY_MIGRATION",
    "CustomerCompensationRuleAuthorityConfigurationError",
    "CustomerCompensationRuleAuthorityError",
    "CustomerCompensationRuleAuthorityForbiddenError",
    "CustomerCompensationRuleAuthorityValidationError",
    "PostgresCustomerCompensationRuleAuthorityStore",
]
