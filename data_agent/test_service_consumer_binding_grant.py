"""Contracts for ApprovalCase-governed GIS service binding issuance."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.service_consumer_binding import ServiceConsumerBinding
from data_agent.service_consumer_binding_grant import (
    SERVICE_CONSUMER_BINDING_GRANT_ACTION,
    SERVICE_CONSUMER_BINDING_GRANT_SCHEMA,
    ServiceConsumerBindingGrantPlan,
    build_service_consumer_binding_grant_approval_case,
    build_service_consumer_binding_grant_plan,
)
from data_agent.test_service_consumer_binding import _payload


def test_grant_plan_binds_the_full_service_consumer_binding() -> None:
    binding = ServiceConsumerBinding.model_validate(_payload())
    plan = build_service_consumer_binding_grant_plan(binding)
    now = datetime.fromisoformat("2026-08-21T10:00:00+00:00")
    case = build_service_consumer_binding_grant_approval_case(
        plan,
        requester_subject="workload:service-controller",
        request_reason="grant approved MVT service access",
        requested_at=now,
        expires_at=now + timedelta(hours=1),
    )

    assert case.action == SERVICE_CONSUMER_BINDING_GRANT_ACTION
    assert case.target_resource_urn == binding.service_urn
    assert case.target_fingerprint == plan.plan_sha256
    assert case.approval_case_ref == plan.approval_case_ref()
    assert case.request_context["schema"] == SERVICE_CONSUMER_BINDING_GRANT_SCHEMA
    assert case.request_context["grant_plan_sha256"] == plan.plan_sha256
    assert case.request_context["service_consumer_binding"]["binding_sha256"] == (
        binding.binding_sha256
    )


def test_grant_plan_rejects_an_approval_outcome_or_tampered_fingerprint() -> None:
    binding = ServiceConsumerBinding.model_validate(_payload())
    plan = build_service_consumer_binding_grant_plan(binding)

    with pytest.raises(ValidationError, match="approval_case_ref"):
        ServiceConsumerBindingGrantPlan.model_validate(
            plan.model_dump()
            | {
                "service_consumer_binding": binding.model_dump()
                | {
                    "approval_case_ref": "gda://tenant-a/approval_case/grant-1",
                    "grant_plan_sha256": plan.plan_sha256,
                }
            }
        )
    with pytest.raises(ValidationError, match="plan_sha256"):
        ServiceConsumerBindingGrantPlan.model_validate(
            plan.model_dump() | {"plan_sha256": "0" * 64}
        )


def test_approval_migration_replaces_the_unapproved_recorder() -> None:
    sql = (
        Path(__file__).parent
        / "migrations"
        / "213_gis_service_consumer_binding_approval.sql"
    ).read_text(encoding="utf-8")

    assert "approval_case_ref TEXT" in sql
    assert "grant_plan_sha256 CHAR(64)" in sql
    assert "gda_control.approval_case" in sql
    assert "gis_service_consumer_binding.grant" in sql
    assert "clock_timestamp() >= v_case.expires_at" in sql
    assert "grant ApprovalCase does not authorize" in sql
    assert "REVOKE ALL ON FUNCTION gda_control.record_service_consumer_binding" in sql
    assert "CREATE UNIQUE INDEX uq_gda_service_consumer_binding_approval_case" in sql


def test_revoke_plan_binds_the_immutable_binding_and_approval_target() -> None:
    from data_agent.service_consumer_binding_revocation import (
        SERVICE_CONSUMER_BINDING_REVOKE_ACTION,
        SERVICE_CONSUMER_BINDING_REVOKE_SCHEMA,
        build_service_consumer_binding_revoke_approval_case,
        build_service_consumer_binding_revoke_plan,
    )

    binding = ServiceConsumerBinding.model_validate(_payload())
    plan = build_service_consumer_binding_revoke_plan(
        binding,
        reason="credential owner requested immediate removal",
        context={"ticket": "SEC-214", "incident": "INC-1"},
    )
    now = datetime.fromisoformat("2026-08-21T10:00:00+00:00")
    case = build_service_consumer_binding_revoke_approval_case(
        plan,
        requester_subject="workload:service-controller",
        request_reason="revoke compromised MVT credential",
        requested_at=now,
        expires_at=now + timedelta(hours=1),
    )

    assert case.action == SERVICE_CONSUMER_BINDING_REVOKE_ACTION
    assert case.target_resource_urn == plan.target_resource_urn
    assert case.target_fingerprint == plan.plan_sha256
    assert case.approval_case_ref == plan.approval_case_ref()
    assert case.request_context["schema"] == SERVICE_CONSUMER_BINDING_REVOKE_SCHEMA
    assert case.request_context["binding_sha256"] == binding.binding_sha256
    assert case.request_context["context"] == {"ticket": "SEC-214", "incident": "INC-1"}


def test_revoke_plan_rejects_a_different_binding_target_or_fingerprint() -> None:
    from data_agent.service_consumer_binding_revocation import (
        build_service_consumer_binding_revoke_plan,
    )

    binding = ServiceConsumerBinding.model_validate(_payload())
    plan = build_service_consumer_binding_revoke_plan(binding, reason="rotate key")
    with pytest.raises(ValidationError, match="exact binding"):
        type(plan).model_validate(
            plan.model_dump()
            | {"target_resource_urn": "gda://planning/service_consumer_binding/other"}
        )
    with pytest.raises(ValidationError, match="plan_sha256"):
        type(plan).model_validate(plan.model_dump() | {"plan_sha256": "0" * 64})


def test_revocation_migration_is_append_only_and_excludes_revoked_bindings() -> None:
    sql = (
        Path(__file__).parent
        / "migrations"
        / "214_gis_service_consumer_binding_revocation.sql"
    ).read_text(encoding="utf-8")

    assert "service_consumer_binding_revocation" in sql
    assert "gis_service_consumer_binding.revoke" in sql
    assert "record_service_consumer_binding_revocation" in sql
    assert "FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation()" in sql
    assert "UNIQUE (tenant_id, service_consumer_binding_id)" in sql
