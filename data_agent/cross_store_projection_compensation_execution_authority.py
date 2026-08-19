"""One-time authority for a separately approved compensation execution verdict.

Consuming the verdict reserves it for a future controlled executor.  It does
not invoke a Provider and the returned receipt is not an execution result.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .cross_store_projection_authority import _sqlstate
from .db_engine import get_engine
from .platform_contracts import (
    NonEmptyText,
    ResourceURNText,
    Sha256,
    TenantId,
    parse_resource_urn,
)
from .temporal_entity_authority import GATEWAY_DATABASE_ROLE

FEDERATED_COMPENSATION_EXECUTION_AUTHORIZATION_MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "180_federated_compensation_execution_authorization.sql"
)


class FederatedCompensationExecutionAuthorityError(RuntimeError):
    """Base error for one-time execution authorization consumption."""


class FederatedCompensationExecutionAuthorityConfigurationError(
    FederatedCompensationExecutionAuthorityError
):
    """PostgreSQL or the returned authority record is not trustworthy."""


class FederatedCompensationExecutionAuthorityForbiddenError(
    FederatedCompensationExecutionAuthorityError
):
    """The database role or tenant boundary denied the request."""


class FederatedCompensationExecutionAuthorityValidationError(
    FederatedCompensationExecutionAuthorityError
):
    """The approval chain drifted, expired, or was already consumed."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FederatedCompensationExecutionAuthorizationConsumptionRequest(_FrozenModel):
    """Exact approval-chain identity reserved by a future executor."""

    schema_id: ClassVar[str] = (
        "gda.federated-compensation-execution-authorization-consumption-request.v1"
    )
    tenant_id: TenantId
    execution_approval_case_ref: ResourceURNText
    review_approval_case_ref: ResourceURNText
    proposal_sha256: Sha256
    candidate_sha256: Sha256
    execution_authorization_sha256: Sha256
    review_binding_sha256: Sha256
    consumed_by: NonEmptyText
    consume_reason: str = Field(min_length=1, max_length=1024)

    @model_validator(mode="after")
    def _tenant_bound_chain(
        self,
    ) -> FederatedCompensationExecutionAuthorizationConsumptionRequest:
        if self.execution_approval_case_ref == self.review_approval_case_ref:
            raise ValueError("execution and review ApprovalCase references must differ")
        for reference in (
            self.execution_approval_case_ref,
            self.review_approval_case_ref,
        ):
            identity = parse_resource_urn(reference)
            if (
                identity["tenant_id"] != self.tenant_id
                or identity["resource_kind"] != "approval_case"
            ):
                raise ValueError("execution authorization ApprovalCase tenant differs")
        if not self.consumed_by.startswith(("human:", "agent:", "workload:")):
            raise ValueError("execution authorization consumer must use typed identity")
        if any(character.isspace() for character in self.consumed_by):
            raise ValueError("execution authorization consumer cannot contain whitespace")
        if not self.consume_reason.strip():
            raise ValueError("execution authorization consume reason is required")
        return self


class FederatedCompensationExecutionAuthorizationConsumptionReceipt(_FrozenModel):
    """Durable reservation evidence, explicitly not Provider outcome evidence."""

    schema_id: ClassVar[str] = (
        "gda.federated-compensation-execution-authorization-consumption-receipt.v1"
    )
    tenant_id: TenantId
    execution_approval_case_ref: ResourceURNText
    review_approval_case_ref: ResourceURNText
    proposal_sha256: Sha256
    candidate_sha256: Sha256
    execution_authorization_sha256: Sha256
    review_binding_sha256: Sha256
    execution_decided_by: NonEmptyText
    review_decided_by: NonEmptyText
    consumed_by: NonEmptyText
    consume_reason: NonEmptyText
    consumed_at: datetime
    authorization_consumed: Literal[True] = True
    provider_execution_performed: Literal[False] = False
    receipt_is_provider_execution_result: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )

    @field_validator("consumed_at")
    @classmethod
    def _aware_consumed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution authorization consumed_at must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _independent_verdicts(
        self,
    ) -> FederatedCompensationExecutionAuthorizationConsumptionReceipt:
        request = FederatedCompensationExecutionAuthorizationConsumptionRequest(
            tenant_id=self.tenant_id,
            execution_approval_case_ref=self.execution_approval_case_ref,
            review_approval_case_ref=self.review_approval_case_ref,
            proposal_sha256=self.proposal_sha256,
            candidate_sha256=self.candidate_sha256,
            execution_authorization_sha256=(
                self.execution_authorization_sha256
            ),
            review_binding_sha256=self.review_binding_sha256,
            consumed_by=self.consumed_by,
            consume_reason=self.consume_reason,
        )
        if not self.execution_decided_by.startswith("human:") or not (
            self.review_decided_by.startswith("human:")
        ):
            raise ValueError("execution authorization verdicts must use human identities")
        if self.execution_decided_by == self.review_decided_by:
            raise ValueError("execution and review verdicts must be independent")
        if request.tenant_id != self.tenant_id:
            raise ValueError("execution authorization receipt tenant differs")
        return self


class PostgresFederatedCompensationExecutionAuthorizationAuthority:
    """Tenant-bound one-time consumption path with no Provider dependency."""

    def __init__(self, tenant_id: str, engine: Any = None):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise FederatedCompensationExecutionAuthorityValidationError(
                "federated compensation execution authority tenant_id is required"
            )
        self.tenant_id = tenant_id.strip()
        self._engine = engine

    def _get_engine(self):
        engine = self._engine or get_engine()
        if engine is None or engine.dialect.name != "postgresql":
            raise FederatedCompensationExecutionAuthorityConfigurationError(
                "federated compensation execution authority requires PostgreSQL"
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
                        raise (
                            FederatedCompensationExecutionAuthorityConfigurationError(
                                "database login is not a member of the platform gateway role"
                            )
                        ) from exc
                    connection.execute(
                        text("SELECT set_config('app.current_tenant', :tenant, true)"),
                        {"tenant": self.tenant_id},
                    )
                    yield connection
        except FederatedCompensationExecutionAuthorityError:
            raise
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state in {"23505", "40001", "55000"}:
                raise FederatedCompensationExecutionAuthorityValidationError(
                    "execution authorization was already consumed differently"
                ) from exc
            if state == "42501":
                raise FederatedCompensationExecutionAuthorityForbiddenError(
                    "execution authorization tenant or role was denied"
                ) from exc
            if state in {"22023", "22P02", "23502", "23503", "23514"}:
                raise FederatedCompensationExecutionAuthorityValidationError(
                    "execution authorization approval chain was rejected"
                ) from exc
            raise FederatedCompensationExecutionAuthorityConfigurationError(
                "execution authorization authority operation failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise FederatedCompensationExecutionAuthorityConfigurationError(
                "execution authorization authority operation failed"
            ) from exc

    @staticmethod
    def _receipt(
        row: Any,
    ) -> FederatedCompensationExecutionAuthorizationConsumptionReceipt:
        try:
            return FederatedCompensationExecutionAuthorizationConsumptionReceipt(
                **dict(row),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise FederatedCompensationExecutionAuthorityConfigurationError(
                "stored execution authorization receipt is invalid"
            ) from exc

    def consume(
        self,
        request: FederatedCompensationExecutionAuthorizationConsumptionRequest,
    ) -> FederatedCompensationExecutionAuthorizationConsumptionReceipt:
        """Reserve the verdict once without invoking or importing a Provider."""

        try:
            request = FederatedCompensationExecutionAuthorizationConsumptionRequest.model_validate(
                request.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError, ValidationError) as exc:
            raise FederatedCompensationExecutionAuthorityValidationError(
                "execution authorization consumption request is invalid"
            ) from exc
        if request.tenant_id != self.tenant_id:
            raise FederatedCompensationExecutionAuthorityForbiddenError(
                "execution authorization request tenant differs from the authority"
            )
        with self._transaction() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT tenant_id, execution_approval_case_ref,
                           review_approval_case_ref, proposal_sha256,
                           candidate_sha256, execution_authorization_sha256,
                           review_binding_sha256, execution_decided_by,
                           review_decided_by, consumed_by, consume_reason,
                           consumed_at
                    FROM gda_control.
                         consume_federated_compensation_execution_authorization(
                            :tenant_id, :execution_approval_case_ref,
                            :review_approval_case_ref, :proposal_sha256,
                            :candidate_sha256, :execution_authorization_sha256,
                            :review_binding_sha256, :consumed_by, :consume_reason
                         )
                    """
                ),
                request.model_dump(mode="python"),
            ).mappings().one()
        return self._receipt(row)


__all__ = [
    "FEDERATED_COMPENSATION_EXECUTION_AUTHORIZATION_MIGRATION",
    "FederatedCompensationExecutionAuthorizationConsumptionReceipt",
    "FederatedCompensationExecutionAuthorizationConsumptionRequest",
    "FederatedCompensationExecutionAuthorityConfigurationError",
    "FederatedCompensationExecutionAuthorityError",
    "FederatedCompensationExecutionAuthorityForbiddenError",
    "FederatedCompensationExecutionAuthorityValidationError",
    "PostgresFederatedCompensationExecutionAuthorizationAuthority",
]
