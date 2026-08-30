from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine

from data_agent.agentops_specialist_operation_authority import (
    AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION,
    AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION,
    PostgresSpecialistOperationAuthority,
    SpecialistOperationAuthorityConfigurationError,
    SpecialistOperationAuthorityForbiddenError,
    SpecialistOperationAuthorityValidationError,
)
from data_agent.agentops_specialist_providers import (
    InMemorySpecialistOperationAuthority,
    SpecialistOperationReceipt,
    SpecialistOperationStatus,
    SpecialistUncertaintyType,
    build_gwm_provider_spec,
)
from data_agent.agentops_temporal_contracts import (
    TemporalActivityRequest,
    temporal_contract_fingerprint,
)
from data_agent.test_agentops_temporal_adapter import _activity_request


def _request(*, tenant_id: str = "planning") -> TemporalActivityRequest:
    _harness, _workflow_id, _call, request = _activity_request()
    values = request.model_dump(mode="python")
    values["tenant_id"] = tenant_id
    values["subject_context"] = request.subject_context.model_copy(
        update={"tenant_id": tenant_id}
    )
    values["provider_spec"] = build_gwm_provider_spec(input_artifact_ids=())
    values["request_sha256"] = temporal_contract_fingerprint(
        TemporalActivityRequest.schema_id, values, "request_sha256"
    )
    return TemporalActivityRequest(**values)


def test_request_fixture_keeps_subject_tenant_consistent() -> None:
    request = _request(tenant_id="other-tenant")

    assert request.tenant_id == "other-tenant"
    assert request.subject_context.tenant_id == "other-tenant"


def test_migration_is_append_only_and_rls_bound() -> None:
    migration = AGENTOPS_SPECIALIST_OPERATION_AUTHORITY_MIGRATION.read_text()
    assert "agentops_specialist_operation_receipt_history" in migration
    assert "agentops_specialist_operation_receipt_current" in migration
    assert "record_agentops_specialist_operation_receipt" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "pg_advisory_xact_lock" in migration
    assert "GRANT INSERT" not in migration
    assert "output_artifact_id" in migration
    assert "first specialist operation receipt must be submitted" in migration
    uncertainty_migration = AGENTOPS_SPECIALIST_OPERATION_UNCERTAINTY_MIGRATION.read_text()
    assert "GENERATED ALWAYS" in uncertainty_migration
    assert "ck_gda_agentops_specialist_operation_uncertainty" in uncertainty_migration
    assert "agentops_specialist_operation_receipt_current" in uncertainty_migration


def test_repository_requires_postgresql() -> None:
    authority = PostgresSpecialistOperationAuthority("planning", create_engine("sqlite://"))
    with pytest.raises(
        SpecialistOperationAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        authority.observe("mmfe.execute_fusion.v1://activity")


def test_tenant_and_actor_are_validated_before_database_access() -> None:
    with pytest.raises(
        SpecialistOperationAuthorityValidationError,
        match="typed subject",
    ):
        PostgresSpecialistOperationAuthority(
            "planning", recorded_by="anonymous"
        )

    authority = PostgresSpecialistOperationAuthority("other-tenant")
    request = _request()
    with pytest.raises(
        SpecialistOperationAuthorityForbiddenError,
        match="differs from authority",
    ):
        authority.submit(
            request,
            provider_ref="provider:gwm.local",
            operation_ref="gwm.render_canonical_observation.v1://activity",
            provider_receipt_ref="provider://receipt",
        )


def test_stored_receipt_tamper_is_rejected() -> None:
    request = _request()
    in_memory = InMemorySpecialistOperationAuthority()
    receipt = in_memory.submit(
        request,
        provider_ref="provider:gwm.local",
        operation_ref="gwm.render_canonical_observation.v1://activity",
        provider_receipt_ref="provider://receipt",
    )
    tampered = receipt.model_copy(update={"status": SpecialistOperationStatus.SUCCEEDED})
    with pytest.raises(ValueError, match="receipt_sha256"):
        SpecialistOperationReceipt.model_validate(tampered.model_dump(mode="python"))


def test_definitive_provider_cancellation_is_distinct_from_cancel_request() -> None:
    authority = InMemorySpecialistOperationAuthority()
    request = _request()
    operation = "gwm.render_canonical_observation.v1://cancel-contract"
    authority.submit(
        request,
        provider_ref="provider:gwm.local",
        operation_ref=operation,
        provider_receipt_ref="provider://receipt/cancel-contract",
    )
    pending = authority.request_cancellation(operation)
    assert pending.status is SpecialistOperationStatus.UNKNOWN
    cancelled = authority.cancel(operation, "ProviderConfirmedCancellation")
    assert cancelled.status is SpecialistOperationStatus.CANCELLED
    assert cancelled.failure_type == "ProviderConfirmedCancellation"


def test_cancellation_reason_is_durable_and_terminal_cancel_clears_uncertainty() -> None:
    authority = InMemorySpecialistOperationAuthority()
    request = _request()
    operation = "gwm.render_canonical_observation.v1://reason-contract"
    authority.submit(
        request,
        provider_ref="provider:gwm.local",
        operation_ref=operation,
        provider_receipt_ref="provider://receipt/reason-contract",
    )
    pending = authority.request_cancellation(
        operation,
        uncertainty_type=SpecialistUncertaintyType.FLINK_CANCELLATION_PERMISSION_DENIED,
    )
    assert pending.status is SpecialistOperationStatus.UNKNOWN
    assert (
        pending.uncertainty_type
        is SpecialistUncertaintyType.FLINK_CANCELLATION_PERMISSION_DENIED
    )
    observed = authority.observe(operation)
    assert observed is not None
    assert observed.uncertainty_type is pending.uncertainty_type
    cancelled = authority.cancel(operation, "ProviderCancellationConfirmed")
    assert cancelled.uncertainty_type is None


def test_operation_observation_fingerprint_normalizes_observed_datetime() -> None:
    request = _request()
    authority = InMemorySpecialistOperationAuthority()
    receipt = authority.submit(
        request,
        provider_ref="provider:gwm.local",
        operation_ref="gwm.render_canonical_observation.v1://observation",
        provider_receipt_ref="provider://receipt/observation",
    )
    observation = PostgresSpecialistOperationAuthority._observation(receipt)
    assert observation.observation_sha256


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="DATABASE_URL is not configured"
)
def test_real_postgres_operation_receipt_rehearsal() -> None:
    from data_agent.agentops_specialist_operation_authority_postgres_rehearsal import (
        run_agentops_specialist_operation_authority_postgres_rehearsal,
    )

    report = run_agentops_specialist_operation_authority_postgres_rehearsal(
        os.environ["DATABASE_URL"]
    )
    assert report.passed, report.failure_reasons
