"""Process-local permits for unsupported Chongqing mutation helpers.

The low-level deployment, source-lineage, and profile executors are composition
primitives, not production entry points.  A permit is intentionally opaque,
process-local, bound to one sealed run and one registry instance, and omitted
from every serialized result.  The governed five-Provider entry point issues a
production permit only after its live-current admission checks have passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from pydantic import ValidationError

from .cross_store_projection_compensation_dispatch import (
    FederatedProjectionCompensationDispatchIntent,
)
from .cross_store_projection_compensation_federated_run import (
    FederatedCompensationProviderInvokerRegistry,
)

if TYPE_CHECKING:
    from .cross_store_projection_compensation_chongqing_execution_security import (
        ChongqingFederatedCompensationExecutionSecurityDecision,
    )
    from .cross_store_projection_compensation_production_admission import (
        ChongqingFiveProviderProductionAdmissionEvent,
    )


class ChongqingFederatedCompensationInternalExecutionPermitError(RuntimeError):
    """An internal mutating helper was reached without its exact run permit."""


class _InternalExecutionPurpose(StrEnum):
    GOVERNED_PRODUCTION = "governed_production"
    TECHNICAL_CONTRACT_TEST = "technical_contract_test"
    RECONCILIATION_FIXTURE = "reconciliation_fixture"


_PERMIT_ISSUER = object()


@dataclass(frozen=True, slots=True)
class _ChongqingFederatedCompensationInternalExecutionPermit:
    tenant_id: str
    run_id: str
    dispatch_intent_sha256: str
    registry: FederatedCompensationProviderInvokerRegistry = field(
        repr=False,
        compare=False,
    )
    purpose: _InternalExecutionPurpose
    production_admission_event_sha256: str | None
    execution_security_decision_sha256: str | None
    _issuer: object = field(repr=False, compare=False)


def _validated_run(
    intent: FederatedProjectionCompensationDispatchIntent,
    registry: FederatedCompensationProviderInvokerRegistry,
) -> FederatedProjectionCompensationDispatchIntent:
    try:
        intent = FederatedProjectionCompensationDispatchIntent.model_validate(
            intent.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "internal execution permit requires a sealed dispatch intent"
        ) from exc
    if not isinstance(registry, FederatedCompensationProviderInvokerRegistry):
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "internal execution permit requires the governed Provider registry"
        )
    return intent


def _issue_chongqing_federated_compensation_technical_test_execution_permit(
    *,
    intent: FederatedProjectionCompensationDispatchIntent,
    registry: FederatedCompensationProviderInvokerRegistry,
    purpose: Literal["technical_contract_test", "reconciliation_fixture"],
    production_execution_authorized: Literal[False],
) -> _ChongqingFederatedCompensationInternalExecutionPermit:
    """Issue an unsupported test-only permit with an explicit non-production claim."""

    intent = _validated_run(intent, registry)
    if production_execution_authorized is not False:
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "technical test permit cannot authorize production execution"
        )
    try:
        normalized_purpose = _InternalExecutionPurpose(purpose)
    except (TypeError, ValueError) as exc:
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "technical test permit purpose is unsupported"
        ) from exc
    if normalized_purpose is _InternalExecutionPurpose.GOVERNED_PRODUCTION:
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "technical test permit cannot use the production purpose"
        )
    return _ChongqingFederatedCompensationInternalExecutionPermit(
        tenant_id=intent.tenant_id,
        run_id=intent.run_id,
        dispatch_intent_sha256=intent.dispatch_intent_sha256,
        registry=registry,
        purpose=normalized_purpose,
        production_admission_event_sha256=None,
        execution_security_decision_sha256=None,
        _issuer=_PERMIT_ISSUER,
    )


def _issue_chongqing_federated_compensation_governed_execution_permit(
    *,
    intent: FederatedProjectionCompensationDispatchIntent,
    registry: FederatedCompensationProviderInvokerRegistry,
    production_admission_event: ChongqingFiveProviderProductionAdmissionEvent,
    execution_security_decision: ChongqingFederatedCompensationExecutionSecurityDecision,
    evaluated_at: datetime,
) -> _ChongqingFederatedCompensationInternalExecutionPermit:
    """Issue a run-bound permit after live admission and SPR authorization."""

    from .cross_store_projection_compensation_chongqing_execution_security import (
        ChongqingFederatedCompensationExecutionSecurityDecision,
    )
    from .cross_store_projection_compensation_production_admission import (
        ChongqingFiveProviderProductionAdmissionEvent,
    )

    intent = _validated_run(intent, registry)
    try:
        event = ChongqingFiveProviderProductionAdmissionEvent.model_validate(
            production_admission_event.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "governed internal execution permit requires a sealed admission event"
        ) from exc
    try:
        security_decision = (
            ChongqingFederatedCompensationExecutionSecurityDecision.model_validate(
                execution_security_decision.model_dump(mode="python")
            )
        )
    except (AttributeError, TypeError, ValueError, ValidationError) as exc:
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "governed internal execution permit requires a sealed SPR decision"
        ) from exc
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "governed internal execution permit evaluation time must be timezone-aware"
        )
    if (
        event.tenant_id != intent.tenant_id
        or event.run_id != intent.run_id
        or event.target.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or event.admission_state != "active"
        or not event.production_execution_authorized
        or not event.authorized_at <= evaluated_at < event.expires_at
        or security_decision.request.tenant_id != intent.tenant_id
        or security_decision.request.run_id != intent.run_id
        or security_decision.request.operation
        != "chongqing.five_provider.execute"
        or security_decision.request.production_admission_event_sha256
        != event.event_sha256
        or security_decision.effect != "allow"
        or security_decision.obligations
        or not security_decision.decided_at <= evaluated_at < security_decision.expires_at
    ):
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "governed internal execution permit differs from admission or SPR policy"
        )
    return _ChongqingFederatedCompensationInternalExecutionPermit(
        tenant_id=intent.tenant_id,
        run_id=intent.run_id,
        dispatch_intent_sha256=intent.dispatch_intent_sha256,
        registry=registry,
        purpose=_InternalExecutionPurpose.GOVERNED_PRODUCTION,
        production_admission_event_sha256=event.event_sha256,
        execution_security_decision_sha256=security_decision.decision_sha256,
        _issuer=_PERMIT_ISSUER,
    )


def _validate_chongqing_federated_compensation_internal_execution_permit(
    permit: _ChongqingFederatedCompensationInternalExecutionPermit | None,
    *,
    intent: FederatedProjectionCompensationDispatchIntent,
    registry: FederatedCompensationProviderInvokerRegistry,
) -> None:
    """Reject absent, forged, cross-run, or cross-registry helper invocation."""

    intent = _validated_run(intent, registry)
    if (
        not isinstance(
            permit,
            _ChongqingFederatedCompensationInternalExecutionPermit,
        )
        or permit._issuer is not _PERMIT_ISSUER
        or permit.registry is not registry
        or permit.tenant_id != intent.tenant_id
        or permit.run_id != intent.run_id
        or permit.dispatch_intent_sha256 != intent.dispatch_intent_sha256
        or (
            permit.purpose is _InternalExecutionPurpose.GOVERNED_PRODUCTION
            and (
                permit.production_admission_event_sha256 is None
                or permit.execution_security_decision_sha256 is None
            )
        )
        or (
            permit.purpose is not _InternalExecutionPurpose.GOVERNED_PRODUCTION
            and (
                permit.production_admission_event_sha256 is not None
                or permit.execution_security_decision_sha256 is not None
            )
        )
    ):
        raise ChongqingFederatedCompensationInternalExecutionPermitError(
            "internal execution permit is absent or differs from the sealed run"
        )


__all__ = ["ChongqingFederatedCompensationInternalExecutionPermitError"]
