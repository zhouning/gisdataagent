"""Sealed contract for one durable Chongqing unknown-position resume attempt."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cross_store_projection_consistency import ProjectionEngine
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _json_ready(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("unknown-resume attempt datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": _json_ready(payload)})


class ChongqingFederatedCompensationUnknownResumeAttemptRequest(_FrozenModel):
    """CAS request that consumes the sole resume attempt before Provider mutation."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-unknown-resume-attempt-request.v1"
    )
    tenant_id: TenantId
    run_id: NonEmptyText
    prior_execution_result_sha256: Sha256
    reconciliation_case_sha256: Sha256
    request_bundle_sha256: Sha256
    action_map_sha256: Sha256
    action_execution_binding_sha256: Sha256
    position: int = Field(ge=0, le=31)
    target_engine: ProjectionEngine
    request_sha256: Sha256
    unknown_outcome_sha256: Sha256
    observation_sha256: Sha256
    attempt_id: UUID
    expected_consumed_attempts: Literal[0] = 0
    attempt_limit: Literal[1] = 1
    consumed_by: NonEmptyText
    requested_at: datetime
    committed_prefix_replay_allowed: Literal[False] = False
    provider_invocation_performed: Literal[False] = False
    production_execution_authorized: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    request_fingerprint_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationUnknownResumeAttemptRequest:
        if self.requested_at.tzinfo is None or self.requested_at.utcoffset() is None:
            raise ValueError("unknown-resume attempt request time must be timezone-aware")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"request_fingerprint_sha256"}),
            "request_fingerprint_sha256",
        )
        if self.request_fingerprint_sha256 != expected:
            raise ValueError("unknown-resume attempt request fingerprint is invalid")
        return self


class ChongqingFederatedCompensationUnknownResumeAttemptReceipt(_FrozenModel):
    """Durable evidence that the one-attempt budget was consumed pre-callback."""

    schema_id: ClassVar[str] = (
        "gda.chongqing-federated-compensation-unknown-resume-attempt-receipt.v1"
    )
    request: ChongqingFederatedCompensationUnknownResumeAttemptRequest
    attempt_number: Literal[1] = 1
    consumed_at: datetime
    authority_write_performed: Literal[True] = True
    provider_invocation_performed: Literal[False] = False
    cross_store_transaction_performed: Literal[False] = False
    production_execution_authorized: Literal[False] = False
    review_state: Literal["technical_baseline_unreviewed"] = (
        "technical_baseline_unreviewed"
    )
    intended_use: Literal["assisted_precheck_not_for_production_decision"] = (
        "assisted_precheck_not_for_production_decision"
    )
    receipt_sha256: Sha256

    @model_validator(mode="after")
    def _sealed(self) -> ChongqingFederatedCompensationUnknownResumeAttemptReceipt:
        if self.consumed_at.tzinfo is None or self.consumed_at.utcoffset() is None:
            raise ValueError("unknown-resume attempt receipt time must be timezone-aware")
        if self.consumed_at != self.request.requested_at:
            raise ValueError("unknown-resume attempt receipt time differs from its request")
        expected = _fingerprint(
            self.schema_id,
            self.model_dump(mode="json", exclude={"receipt_sha256"}),
            "receipt_sha256",
        )
        if self.receipt_sha256 != expected:
            raise ValueError("unknown-resume attempt receipt fingerprint is invalid")
        return self


class ChongqingFederatedCompensationUnknownResumeAttemptAuthority(Protocol):
    """Tenant-bound authority that atomically consumes an attempt budget."""

    tenant_id: str

    def consume(
        self,
        request: ChongqingFederatedCompensationUnknownResumeAttemptRequest,
    ) -> ChongqingFederatedCompensationUnknownResumeAttemptReceipt: ...


def build_chongqing_federated_compensation_unknown_resume_attempt_request(
    *,
    tenant_id: str,
    run_id: str,
    prior_execution_result_sha256: str,
    reconciliation_case_sha256: str,
    request_bundle_sha256: str,
    action_map_sha256: str,
    action_execution_binding_sha256: str,
    position: int,
    target_engine: ProjectionEngine,
    request_sha256: str,
    unknown_outcome_sha256: str,
    observation_sha256: str,
    attempt_id: UUID,
    consumed_by: str,
    requested_at: datetime,
) -> ChongqingFederatedCompensationUnknownResumeAttemptRequest:
    values = {
        "tenant_id": tenant_id,
        "run_id": run_id,
        "prior_execution_result_sha256": prior_execution_result_sha256,
        "reconciliation_case_sha256": reconciliation_case_sha256,
        "request_bundle_sha256": request_bundle_sha256,
        "action_map_sha256": action_map_sha256,
        "action_execution_binding_sha256": action_execution_binding_sha256,
        "position": position,
        "target_engine": target_engine,
        "request_sha256": request_sha256,
        "unknown_outcome_sha256": unknown_outcome_sha256,
        "observation_sha256": observation_sha256,
        "attempt_id": attempt_id,
        "expected_consumed_attempts": 0,
        "attempt_limit": 1,
        "consumed_by": consumed_by,
        "requested_at": requested_at,
        "committed_prefix_replay_allowed": False,
        "provider_invocation_performed": False,
        "production_execution_authorized": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationUnknownResumeAttemptRequest(
        **values,
        request_fingerprint_sha256=_fingerprint(
            ChongqingFederatedCompensationUnknownResumeAttemptRequest.schema_id,
            values,
            "request_fingerprint_sha256",
        ),
    )


def build_chongqing_federated_compensation_unknown_resume_attempt_receipt(
    request: ChongqingFederatedCompensationUnknownResumeAttemptRequest,
) -> ChongqingFederatedCompensationUnknownResumeAttemptReceipt:
    request = ChongqingFederatedCompensationUnknownResumeAttemptRequest.model_validate(
        request.model_dump(mode="python")
    )
    values = {
        "request": request,
        "attempt_number": 1,
        "consumed_at": request.requested_at,
        "authority_write_performed": True,
        "provider_invocation_performed": False,
        "cross_store_transaction_performed": False,
        "production_execution_authorized": False,
        "review_state": "technical_baseline_unreviewed",
        "intended_use": "assisted_precheck_not_for_production_decision",
    }
    return ChongqingFederatedCompensationUnknownResumeAttemptReceipt(
        **values,
        receipt_sha256=_fingerprint(
            ChongqingFederatedCompensationUnknownResumeAttemptReceipt.schema_id,
            values,
            "receipt_sha256",
        ),
    )


__all__ = [
    "ChongqingFederatedCompensationUnknownResumeAttemptAuthority",
    "ChongqingFederatedCompensationUnknownResumeAttemptReceipt",
    "ChongqingFederatedCompensationUnknownResumeAttemptRequest",
    "build_chongqing_federated_compensation_unknown_resume_attempt_receipt",
    "build_chongqing_federated_compensation_unknown_resume_attempt_request",
]
