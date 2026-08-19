"""Deployment-owned trust anchors for customer compensation approvals.

Approval evidence remains caller-supplied, but trust roots never are.  This
module loads a strict tenant-scoped allowlist from server configuration and
only exposes fingerprint matching; it does not approve or execute a rule.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)

CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_ENV = (
    "GDA_CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_JSON"
)

CustomerApprovalSignatureAlgorithm = Literal[
    "ed25519",
    "ecdsa-p256-sha256",
    "rsa-pss-sha256",
]


class CustomerCompensationApprovalTrustConfigurationError(RuntimeError):
    """The deployment-owned customer approval trust registry is invalid."""


class CustomerCompensationApprovalTrustAnchorStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _fingerprint(schema: str, values: dict[str, Any], hash_field: str) -> str:
    payload = dict(values)
    payload.pop(hash_field, None)
    return canonical_json_fingerprint({"schema": schema, "data": payload})


def customer_compensation_approval_trust_anchor_fingerprint(
    **values: Any,
) -> str:
    return _fingerprint(
        CustomerCompensationApprovalTrustAnchor.schema_id,
        values,
        "anchor_sha256",
    )


def customer_compensation_approval_trust_registry_fingerprint(
    **values: Any,
) -> str:
    return _fingerprint(
        CustomerCompensationApprovalTrustRegistry.schema_id,
        values,
        "registry_sha256",
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("customer approval trust timestamps must be timezone-aware")
    return value.astimezone(UTC)


class CustomerCompensationApprovalTrustAnchor(_FrozenModel):
    """One immutable deployment-owned customer approval key fingerprint."""

    schema_id: ClassVar[str] = (
        "gda.customer-compensation-approval-trust-anchor.v1"
    )
    tenant_id: TenantId
    customer_authority_ref: NonEmptyText
    signature_key_id: NonEmptyText
    signature_algorithm: CustomerApprovalSignatureAlgorithm
    public_key_sha256: Sha256
    valid_from: datetime
    valid_until: datetime
    status: CustomerCompensationApprovalTrustAnchorStatus
    anchor_sha256: Sha256

    @field_validator("valid_from", "valid_until")
    @classmethod
    def _timezone_aware(cls, value: datetime) -> datetime:
        return _aware_utc(value)

    @model_validator(mode="after")
    def _sealed_anchor(self) -> CustomerCompensationApprovalTrustAnchor:
        if self.valid_until <= self.valid_from:
            raise ValueError("customer approval trust validity window is empty")
        expected = customer_compensation_approval_trust_anchor_fingerprint(
            **self.model_dump(mode="json", exclude={"anchor_sha256"})
        )
        if self.anchor_sha256 != expected:
            raise ValueError("customer approval trust anchor fingerprint is invalid")
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return (
            self.tenant_id,
            self.customer_authority_ref,
            self.signature_key_id,
        )


@dataclass(frozen=True)
class CustomerCompensationApprovalTrustDecision:
    trusted: bool
    reason_code: str | None
    anchor_sha256: str | None


class CustomerCompensationApprovalTrustRegistry(_FrozenModel):
    """Strict immutable trust-root set supplied only by deployment config."""

    schema_id: ClassVar[str] = (
        "gda.customer-compensation-approval-trust-registry.v1"
    )
    anchors: tuple[CustomerCompensationApprovalTrustAnchor, ...] = Field(
        max_length=256
    )
    registry_sha256: Sha256

    @model_validator(mode="after")
    def _sealed_registry(self) -> CustomerCompensationApprovalTrustRegistry:
        identities = tuple(anchor.identity for anchor in self.anchors)
        if tuple(sorted(set(identities))) != identities:
            raise ValueError(
                "customer approval trust anchors must be unique and sorted"
            )
        expected = customer_compensation_approval_trust_registry_fingerprint(
            **self.model_dump(mode="json", exclude={"registry_sha256"})
        )
        if self.registry_sha256 != expected:
            raise ValueError("customer approval trust registry fingerprint is invalid")
        return self

    def evaluate(
        self,
        *,
        tenant_id: str,
        customer_authority_ref: str,
        signature_key_id: str,
        signature_algorithm: str,
        public_key_sha256: str,
        signed_at: datetime,
        evaluated_at: datetime,
    ) -> CustomerCompensationApprovalTrustDecision:
        """Evaluate one verified signature against deployment trust roots."""

        if not self.anchors:
            return CustomerCompensationApprovalTrustDecision(
                trusted=False,
                reason_code="customer_approval_trust_registry_missing",
                anchor_sha256=None,
            )
        identity = (tenant_id, customer_authority_ref, signature_key_id)
        anchor = next(
            (item for item in self.anchors if item.identity == identity),
            None,
        )
        if anchor is None:
            return CustomerCompensationApprovalTrustDecision(
                trusted=False,
                reason_code="customer_approval_key_not_trusted",
                anchor_sha256=None,
            )
        if anchor.status is CustomerCompensationApprovalTrustAnchorStatus.REVOKED:
            return CustomerCompensationApprovalTrustDecision(
                trusted=False,
                reason_code="customer_approval_key_revoked",
                anchor_sha256=anchor.anchor_sha256,
            )
        if (
            anchor.signature_algorithm != signature_algorithm
            or anchor.public_key_sha256 != public_key_sha256
        ):
            return CustomerCompensationApprovalTrustDecision(
                trusted=False,
                reason_code="customer_approval_key_not_trusted",
                anchor_sha256=anchor.anchor_sha256,
            )
        signature_time = _aware_utc(signed_at)
        evaluation_time = _aware_utc(evaluated_at)
        if not (
            anchor.valid_from <= signature_time < anchor.valid_until
            and anchor.valid_from <= evaluation_time < anchor.valid_until
        ):
            return CustomerCompensationApprovalTrustDecision(
                trusted=False,
                reason_code="customer_approval_key_outside_validity",
                anchor_sha256=anchor.anchor_sha256,
            )
        return CustomerCompensationApprovalTrustDecision(
            trusted=True,
            reason_code=None,
            anchor_sha256=anchor.anchor_sha256,
        )


def build_customer_compensation_approval_trust_anchor(
    *,
    tenant_id: str,
    customer_authority_ref: str,
    signature_key_id: str,
    signature_algorithm: CustomerApprovalSignatureAlgorithm,
    public_key_sha256: str,
    valid_from: datetime,
    valid_until: datetime,
    status: CustomerCompensationApprovalTrustAnchorStatus,
) -> CustomerCompensationApprovalTrustAnchor:
    """Seal one deployment trust anchor without creating customer approval."""

    values = {
        "tenant_id": tenant_id,
        "customer_authority_ref": customer_authority_ref,
        "signature_key_id": signature_key_id,
        "signature_algorithm": signature_algorithm,
        "public_key_sha256": public_key_sha256,
        "valid_from": _aware_utc(valid_from).isoformat().replace("+00:00", "Z"),
        "valid_until": _aware_utc(valid_until).isoformat().replace("+00:00", "Z"),
        "status": status,
    }
    return CustomerCompensationApprovalTrustAnchor(
        **values,
        anchor_sha256=customer_compensation_approval_trust_anchor_fingerprint(
            **values
        ),
    )


def build_customer_compensation_approval_trust_registry(
    anchors: tuple[CustomerCompensationApprovalTrustAnchor, ...] = (),
) -> CustomerCompensationApprovalTrustRegistry:
    """Normalize and seal an immutable deployment trust registry."""

    by_identity: dict[tuple[str, str, str], CustomerCompensationApprovalTrustAnchor] = {}
    for anchor in anchors:
        previous = by_identity.get(anchor.identity)
        if previous is not None:
            raise ValueError("duplicate customer approval trust anchor identity")
        by_identity[anchor.identity] = anchor
    ordered = tuple(sorted(by_identity.values(), key=lambda anchor: anchor.identity))
    values = {
        "anchors": tuple(anchor.model_dump(mode="json") for anchor in ordered),
    }
    return CustomerCompensationApprovalTrustRegistry(
        **values,
        registry_sha256=customer_compensation_approval_trust_registry_fingerprint(
            **values
        ),
    )


def load_customer_compensation_approval_trust_registry(
) -> CustomerCompensationApprovalTrustRegistry:
    """Load the deployment-only registry; an unset variable is an empty registry."""

    raw = os.getenv(CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_ENV)
    if raw is None or not raw.strip():
        return build_customer_compensation_approval_trust_registry()
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CustomerCompensationApprovalTrustConfigurationError(
            "customer approval trust registry must be valid JSON"
        ) from exc
    if not isinstance(document, list):
        raise CustomerCompensationApprovalTrustConfigurationError(
            "customer approval trust registry must be a JSON array"
        )
    try:
        anchors = tuple(
            CustomerCompensationApprovalTrustAnchor.model_validate(item)
            for item in document
        )
        return build_customer_compensation_approval_trust_registry(anchors)
    except (ValidationError, ValueError) as exc:
        raise CustomerCompensationApprovalTrustConfigurationError(
            "customer approval trust registry violates its sealed contract"
        ) from exc


__all__ = [
    "CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_ENV",
    "CustomerCompensationApprovalTrustAnchor",
    "CustomerCompensationApprovalTrustAnchorStatus",
    "CustomerCompensationApprovalTrustConfigurationError",
    "CustomerCompensationApprovalTrustDecision",
    "CustomerCompensationApprovalTrustRegistry",
    "build_customer_compensation_approval_trust_anchor",
    "build_customer_compensation_approval_trust_registry",
    "customer_compensation_approval_trust_anchor_fingerprint",
    "customer_compensation_approval_trust_registry_fingerprint",
    "load_customer_compensation_approval_trust_registry",
]
