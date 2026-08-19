from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_compensation_trust import (
    CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_ENV,
    CustomerCompensationApprovalTrustAnchorStatus,
    CustomerCompensationApprovalTrustConfigurationError,
    build_customer_compensation_approval_trust_anchor,
    build_customer_compensation_approval_trust_registry,
    load_customer_compensation_approval_trust_registry,
)

NOW = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)


def _anchor(*, status=CustomerCompensationApprovalTrustAnchorStatus.ACTIVE):
    return build_customer_compensation_approval_trust_anchor(
        tenant_id="cq-federated-recovery",
        customer_authority_ref="customer-authority:chongqing-natural-resources",
        signature_key_id="customer-key-ed25519",
        signature_algorithm="ed25519",
        public_key_sha256="a" * 64,
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=1),
        status=status,
    )


def test_registry_is_sorted_fingerprinted_and_immutable() -> None:
    registry = build_customer_compensation_approval_trust_registry((_anchor(),))

    assert registry.anchors[0].anchor_sha256
    assert registry.registry_sha256
    with pytest.raises(ValidationError):
        type(registry).model_validate(
            {
                **registry.model_dump(mode="json"),
                "registry_sha256": "f" * 64,
            }
        )


def test_loader_accepts_only_deployment_json_and_rejects_malformed_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor = _anchor()
    monkeypatch.setenv(
        CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_ENV,
        json.dumps([anchor.model_dump(mode="json")]),
    )
    loaded = load_customer_compensation_approval_trust_registry()
    assert loaded.anchors == (anchor,)

    monkeypatch.setenv(
        CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_ENV,
        "{malformed",
    )
    with pytest.raises(CustomerCompensationApprovalTrustConfigurationError):
        load_customer_compensation_approval_trust_registry()

    monkeypatch.setenv(
        CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_ENV,
        json.dumps({"anchors": [anchor.model_dump(mode="json")]}),
    )
    with pytest.raises(CustomerCompensationApprovalTrustConfigurationError):
        load_customer_compensation_approval_trust_registry()


def test_unset_loader_is_empty_and_never_a_trust_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(CUSTOMER_COMPENSATION_APPROVAL_TRUST_REGISTRY_ENV, raising=False)

    registry = load_customer_compensation_approval_trust_registry()
    decision = registry.evaluate(
        tenant_id="cq-federated-recovery",
        customer_authority_ref="customer-authority:chongqing-natural-resources",
        signature_key_id="customer-key-ed25519",
        signature_algorithm="ed25519",
        public_key_sha256="a" * 64,
        signed_at=NOW,
        evaluated_at=NOW,
    )
    assert decision.trusted is False
    assert decision.reason_code == "customer_approval_trust_registry_missing"
