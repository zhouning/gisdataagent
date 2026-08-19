"""Subject-purpose-resource authorization for Chongqing Provider execution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    SubjectContext,
    SubjectType,
    TenantId,
    canonical_json_fingerprint,
)

CHONGQING_FIVE_PROVIDER_EXECUTION_PURPOSE = "cross_store_projection_compensation"


class ChongqingFederatedCompensationExecutionSecurityError(RuntimeError):
    """The execution security decision cannot authorize Provider access."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("execution security time must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


def chongqing_execution_subject_ref(subject_context: SubjectContext) -> str:
    """Return the canonical actor ref represented by a SubjectContext."""

    return f"{subject_context.subject_type.value}:{subject_context.subject_id}"


class ChongqingFederatedCompensationExecutionSecurityResource(_FrozenModel):
    """One exact Provider target covered by an execution policy decision."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-execution-security-resource.v1"
    )
    position: int = Field(ge=0, le=4)
    target_engine: ProjectionEngine
    target_ref: NonEmptyText
    access_mode: Literal["mutate", "read_receipt"]
    provider_action: NonEmptyText
    request_sha256: Sha256
    action_map_item_sha256: Sha256
    action_execution_binding_item_sha256: Sha256
    resource_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationExecutionSecurityResource:
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"resource_sha256"}),
            "resource_sha256",
        )
        if self.resource_sha256 != expected:
            raise ValueError("execution security resource fingerprint is invalid")
        return self


class ChongqingFederatedCompensationExecutionSecurityRequest(_FrozenModel):
    """Exact subject-purpose-resource request evaluated before Provider access."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-execution-security-request.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    subject_context: SubjectContext
    purpose_code: Literal["cross_store_projection_compensation"] = (
        CHONGQING_FIVE_PROVIDER_EXECUTION_PURPOSE
    )
    purpose_version: Literal["v1"] = "v1"
    operation: Literal[
        "chongqing.five_provider.execute",
        "chongqing.five_provider.recover_unknown",
    ]
    request_bundle_sha256: Sha256
    action_map_sha256: Sha256
    action_execution_binding_sha256: Sha256
    production_admission_event_sha256: Sha256
    resources: tuple[ChongqingFederatedCompensationExecutionSecurityResource, ...] = (
        Field(min_length=5, max_length=5)
    )
    prior_execution_result_sha256: Sha256 | None = None
    reconciliation_case_sha256: Sha256 | None = None
    safe_observation_sha256: Sha256 | None = None
    unknown_position: int | None = Field(default=None, ge=0, le=4)
    evaluated_at: datetime
    provider_access_performed: Literal[False] = False
    production_execution_authorized: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    request_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationExecutionSecurityRequest:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("execution security evaluation time must be timezone-aware")
        if self.subject_context.tenant_id != self.tenant_id:
            raise ValueError("execution security subject tenant differs")
        if self.subject_context.subject_type is not SubjectType.WORKLOAD:
            raise ValueError("Provider execution requires a workload SubjectContext")
        if self.subject_context.purpose != self.purpose_code:
            raise ValueError("execution security purpose is not controlled")
        if self.subject_context.trace_id is None:
            raise ValueError("execution security subject requires a trace ID")
        if (
            self.subject_context.delegated_by is not None
            and not self.subject_context.delegated_by.startswith(
                ("human:", "agent:", "workload:")
            )
        ):
            raise ValueError("execution security delegation identity is invalid")
        if tuple(item.position for item in self.resources) != tuple(range(5)):
            raise ValueError("execution security resources must cover five ordered positions")
        if len({item.target_engine for item in self.resources}) != 5:
            raise ValueError("execution security resources must cover every Provider engine")
        recovery_values = (
            self.prior_execution_result_sha256,
            self.reconciliation_case_sha256,
            self.safe_observation_sha256,
            self.unknown_position,
        )
        if self.operation == "chongqing.five_provider.execute":
            if any(value is not None for value in recovery_values) or any(
                item.access_mode != "mutate" for item in self.resources
            ):
                raise ValueError("initial execution security scope is inconsistent")
        else:
            if any(value is None for value in recovery_values):
                raise ValueError("recovery execution security scope is incomplete")
            if any(
                item.access_mode
                != ("read_receipt" if item.position < self.unknown_position else "mutate")
                for item in self.resources
            ):
                raise ValueError("recovery execution security access modes are inconsistent")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_sha256"}),
            "request_sha256",
        )
        if self.request_sha256 != expected:
            raise ValueError("execution security request fingerprint is invalid")
        return self


class ChongqingFederatedCompensationExecutionSecurityDecision(_FrozenModel):
    """Live policy result for one exact execution security request."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-execution-security-decision.v1"
    )
    request: ChongqingFederatedCompensationExecutionSecurityRequest
    effect: Literal["allow", "deny"]
    policy_ref: NonEmptyText
    policy_version: NonEmptyText
    evaluator_subject: NonEmptyText
    obligations: tuple[NonEmptyText, ...] = ()
    decided_at: datetime
    expires_at: datetime
    authority_live_read_performed: Literal[True] = True
    provider_access_performed: Literal[False] = False
    decision_grants_production_admission: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    decision_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationExecutionSecurityDecision:
        if (
            self.decided_at.tzinfo is None
            or self.decided_at.utcoffset() is None
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
            or self.expires_at <= self.decided_at
        ):
            raise ValueError("execution security decision window is invalid")
        if not self.evaluator_subject.startswith("workload:"):
            raise ValueError("execution security evaluator must use workload identity")
        if len(self.obligations) != len(set(self.obligations)):
            raise ValueError("execution security obligations must be unique")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"decision_sha256"}),
            "decision_sha256",
        )
        if self.decision_sha256 != expected:
            raise ValueError("execution security decision fingerprint is invalid")
        return self


class ChongqingFederatedCompensationExecutionSecurityCurrentReader(Protocol):
    """Tenant-bound live policy reader used immediately before Provider access."""

    tenant_id: str

    def execution_security_decision_current(
        self,
        request: ChongqingFederatedCompensationExecutionSecurityRequest,
    ) -> ChongqingFederatedCompensationExecutionSecurityDecision: ...


def build_chongqing_federated_compensation_execution_security_resource(
    *,
    position: int,
    target_engine: ProjectionEngine,
    target_ref: str,
    access_mode: Literal["mutate", "read_receipt"],
    provider_action: str,
    request_sha256: str,
    action_map_item_sha256: str,
    action_execution_binding_item_sha256: str,
) -> ChongqingFederatedCompensationExecutionSecurityResource:
    values = {
        "position": position,
        "target_engine": target_engine,
        "target_ref": target_ref,
        "access_mode": access_mode,
        "provider_action": provider_action,
        "request_sha256": request_sha256,
        "action_map_item_sha256": action_map_item_sha256,
        "action_execution_binding_item_sha256": (
            action_execution_binding_item_sha256
        ),
    }
    return ChongqingFederatedCompensationExecutionSecurityResource(
        **values,
        resource_sha256=_fingerprint(
            ChongqingFederatedCompensationExecutionSecurityResource.schema_id,
            values,
            "resource_sha256",
        ),
    )


def build_chongqing_federated_compensation_execution_security_request(
    *,
    tenant_id: str,
    run_id: str,
    subject_context: SubjectContext,
    operation: Literal[
        "chongqing.five_provider.execute",
        "chongqing.five_provider.recover_unknown",
    ],
    request_bundle_sha256: str,
    action_map_sha256: str,
    action_execution_binding_sha256: str,
    production_admission_event_sha256: str,
    resources: tuple[ChongqingFederatedCompensationExecutionSecurityResource, ...],
    evaluated_at: datetime,
    prior_execution_result_sha256: str | None = None,
    reconciliation_case_sha256: str | None = None,
    safe_observation_sha256: str | None = None,
    unknown_position: int | None = None,
) -> ChongqingFederatedCompensationExecutionSecurityRequest:
    values = {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "subject_context": subject_context,
        "purpose_code": CHONGQING_FIVE_PROVIDER_EXECUTION_PURPOSE,
        "purpose_version": "v1",
        "operation": operation,
        "request_bundle_sha256": request_bundle_sha256,
        "action_map_sha256": action_map_sha256,
        "action_execution_binding_sha256": action_execution_binding_sha256,
        "production_admission_event_sha256": production_admission_event_sha256,
        "resources": resources,
        "prior_execution_result_sha256": prior_execution_result_sha256,
        "reconciliation_case_sha256": reconciliation_case_sha256,
        "safe_observation_sha256": safe_observation_sha256,
        "unknown_position": unknown_position,
        "evaluated_at": evaluated_at,
        "provider_access_performed": False,
        "production_execution_authorized": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationExecutionSecurityRequest(
        **values,
        request_sha256=_fingerprint(
            ChongqingFederatedCompensationExecutionSecurityRequest.schema_id,
            values,
            "request_sha256",
        ),
    )


def build_chongqing_federated_compensation_execution_security_decision(
    request: ChongqingFederatedCompensationExecutionSecurityRequest,
    *,
    effect: Literal["allow", "deny"],
    policy_ref: str,
    policy_version: str,
    evaluator_subject: str,
    decided_at: datetime,
    expires_at: datetime,
    obligations: tuple[str, ...] = (),
) -> ChongqingFederatedCompensationExecutionSecurityDecision:
    request = ChongqingFederatedCompensationExecutionSecurityRequest.model_validate(
        request.model_dump(mode="python")
    )
    values = {
        "request": request,
        "effect": effect,
        "policy_ref": policy_ref,
        "policy_version": policy_version,
        "evaluator_subject": evaluator_subject,
        "obligations": tuple(sorted(obligations)),
        "decided_at": decided_at,
        "expires_at": expires_at,
        "authority_live_read_performed": True,
        "provider_access_performed": False,
        "decision_grants_production_admission": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationExecutionSecurityDecision(
        **values,
        decision_sha256=_fingerprint(
            ChongqingFederatedCompensationExecutionSecurityDecision.schema_id,
            values,
            "decision_sha256",
        ),
    )


def authorize_chongqing_federated_compensation_execution_security(
    request: ChongqingFederatedCompensationExecutionSecurityRequest,
    reader: ChongqingFederatedCompensationExecutionSecurityCurrentReader,
) -> ChongqingFederatedCompensationExecutionSecurityDecision:
    """Read and validate the current exact-scope decision before Provider access."""

    try:
        request = ChongqingFederatedCompensationExecutionSecurityRequest.model_validate(
            request.model_dump(mode="python")
        )
        if (
            getattr(reader, "tenant_id", None) != request.tenant_id
            or not callable(
                getattr(reader, "execution_security_decision_current", None)
            )
        ):
            raise ValueError("execution security reader is not tenant-bound")
        decision = ChongqingFederatedCompensationExecutionSecurityDecision.model_validate(
            reader.execution_security_decision_current(request).model_dump(mode="python")
        )
    except Exception as exc:
        raise ChongqingFederatedCompensationExecutionSecurityError(
            "execution security live current read failed"
        ) from exc
    evaluated_at = request.evaluated_at.astimezone(UTC)
    actor_subject = chongqing_execution_subject_ref(request.subject_context)
    if decision.request != request:
        raise ChongqingFederatedCompensationExecutionSecurityError(
            "execution security decision scope drifted"
        )
    if decision.effect != "allow":
        raise ChongqingFederatedCompensationExecutionSecurityError(
            "execution security policy denied Provider access"
        )
    if decision.obligations:
        raise ChongqingFederatedCompensationExecutionSecurityError(
            "execution security decision contains unsupported obligations"
        )
    if decision.evaluator_subject == actor_subject:
        raise ChongqingFederatedCompensationExecutionSecurityError(
            "execution security evaluator is not independent"
        )
    if not (
        decision.decided_at.astimezone(UTC)
        <= evaluated_at
        < decision.expires_at.astimezone(UTC)
    ):
        raise ChongqingFederatedCompensationExecutionSecurityError(
            "execution security decision is not active"
        )
    return decision


__all__ = [
    "CHONGQING_FIVE_PROVIDER_EXECUTION_PURPOSE",
    "ChongqingFederatedCompensationExecutionSecurityCurrentReader",
    "ChongqingFederatedCompensationExecutionSecurityDecision",
    "ChongqingFederatedCompensationExecutionSecurityError",
    "ChongqingFederatedCompensationExecutionSecurityRequest",
    "ChongqingFederatedCompensationExecutionSecurityResource",
    "authorize_chongqing_federated_compensation_execution_security",
    "build_chongqing_federated_compensation_execution_security_decision",
    "build_chongqing_federated_compensation_execution_security_request",
    "build_chongqing_federated_compensation_execution_security_resource",
    "chongqing_execution_subject_ref",
]
