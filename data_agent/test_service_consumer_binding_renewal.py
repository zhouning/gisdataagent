from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.service_consumer_binding import (
    ServiceConsumerBinding,
    service_consumer_binding_fingerprint,
)
from data_agent.service_consumer_binding_renewal import (
    SERVICE_CONSUMER_BINDING_RENEWAL_ACTION,
    SERVICE_CONSUMER_BINDING_RENEWAL_SCHEMA,
    build_service_consumer_binding_renewal_approval_case,
    build_service_consumer_binding_renewal_plan,
)
from data_agent.test_service_consumer_binding import _payload


def _target() -> ServiceConsumerBinding:
    values = _payload()
    values.update(
        {
            "service_consumer_binding_id": UUID(
                "00000000-0000-4000-8000-000000000911"
            ),
            "credential_ref": "credential:district-map-reader-v2",
            "expires_at": datetime(2026, 9, 30, 12, tzinfo=UTC),
            "created_at": datetime(2026, 8, 21, 12, 1, tzinfo=UTC),
        }
    )
    values["binding_sha256"] = service_consumer_binding_fingerprint(values)
    return ServiceConsumerBinding.model_validate(values)


def test_renewal_plan_binds_source_and_new_immutable_target() -> None:
    source = ServiceConsumerBinding.model_validate(_payload())
    plan = build_service_consumer_binding_renewal_plan(source, _target())
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    case = build_service_consumer_binding_renewal_approval_case(
        plan,
        requester_subject="workload:service-controller",
        request_reason="extend the approved MVT consumer lease",
        requested_at=now,
        expires_at=now + timedelta(hours=1),
    )

    assert case.action == SERVICE_CONSUMER_BINDING_RENEWAL_ACTION
    assert case.target_resource_urn == plan.target_resource_urn
    assert case.target_fingerprint == plan.plan_sha256
    assert case.approval_case_ref == plan.approval_case_ref()
    assert case.request_context["schema"] == SERVICE_CONSUMER_BINDING_RENEWAL_SCHEMA
    assert case.request_context["source_binding_sha256"] == source.binding_sha256
    assert case.request_context["service_consumer_binding"]["binding_sha256"] == (
        plan.service_consumer_binding.binding_sha256
    )


def test_renewal_rejects_non_extending_or_same_identity_target() -> None:
    source = ServiceConsumerBinding.model_validate(_payload())
    same_expiry = _target().model_copy(update={"expires_at": source.expires_at})
    with pytest.raises(ValueError, match="extend"):
        build_service_consumer_binding_renewal_plan(source, same_expiry)

    same_id_values = _payload()
    same_id_values.update(
        {
            "service_consumer_binding_id": source.service_consumer_binding_id,
            "expires_at": _target().expires_at,
            "created_at": _target().created_at,
        }
    )
    same_id_values["binding_sha256"] = service_consumer_binding_fingerprint(
        same_id_values
    )
    same_id = ServiceConsumerBinding.model_validate(same_id_values)
    with pytest.raises(ValueError, match="new binding identity"):
        build_service_consumer_binding_renewal_plan(source, same_id)


def test_renewal_lifecycle_fields_are_mutually_exclusive() -> None:
    values = _payload()
    values["renewal_of_binding_id"] = UUID("00000000-0000-4000-8000-000000000910")
    values["binding_sha256"] = service_consumer_binding_fingerprint(values)
    with pytest.raises(ValidationError, match="renewal binding fields"):
        ServiceConsumerBinding.model_validate(values)


def test_renewal_migration_is_append_only_and_gateway_recorder_only() -> None:
    sql = (
        Path(__file__).parent
        / "migrations"
        / "215_gis_service_consumer_binding_renewal.sql"
    ).read_text(encoding="utf-8")

    assert "service_consumer_binding_renewal" in sql
    assert "gis_service_consumer_binding.renew" in sql
    assert "record_service_consumer_binding_renewal" in sql
    assert "FOR EACH ROW EXECUTE FUNCTION gda_control.reject_immutable_mutation()" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "GRANT EXECUTE ON FUNCTION gda_control.record_service_consumer_binding_renewal" in sql

    guard_sql = (
        Path(__file__).parent
        / "migrations"
        / "216_gis_service_consumer_binding_renewal_decision_guard.sql"
    ).read_text(encoding="utf-8")
    assert "record_service_consumer_binding_renewal_unverified" in guard_sql
    assert "decided_by IS DISTINCT FROM p_renewed_by" in guard_sql
    assert "decided_at IS DISTINCT FROM p_renewed_at" in guard_sql
