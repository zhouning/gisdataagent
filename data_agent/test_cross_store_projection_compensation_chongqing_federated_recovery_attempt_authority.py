from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from data_agent.cross_store_projection_compensation_chongqing_federated_recovery_attempt import (
    ChongqingFederatedCompensationUnknownResumeAttemptReceipt,
    build_chongqing_federated_compensation_unknown_resume_attempt_receipt,
    build_chongqing_federated_compensation_unknown_resume_attempt_request,
)
from data_agent.cross_store_projection_compensation_chongqing_federated_recovery_attempt_authority import (  # noqa: E501
    CHONGQING_FIVE_PROVIDER_UNKNOWN_RESUME_ATTEMPT_AUTHORITY_MIGRATION,
    ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError,
    ChongqingFiveProviderUnknownResumeAttemptAuthorityConflictError,
    ChongqingFiveProviderUnknownResumeAttemptAuthorityForbiddenError,
    PostgresChongqingFiveProviderUnknownResumeAttemptAuthority,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres

_TENANT = "cq-federated-recovery"
_REQUESTED_AT = datetime(2026, 8, 18, 12, 1, tzinfo=UTC)


def _request(*, position: int = 1):
    return build_chongqing_federated_compensation_unknown_resume_attempt_request(
        tenant_id=_TENANT,
        run_id="run-unknown-resume-1",
        prior_execution_result_sha256="a" * 64,
        reconciliation_case_sha256="b" * 64,
        request_bundle_sha256="c" * 64,
        action_map_sha256="d" * 64,
        action_execution_binding_sha256="e" * 64,
        position=position,
        target_engine=ProjectionEngine.POSTGIS,
        request_sha256="f" * 64,
        unknown_outcome_sha256="1" * 64,
        observation_sha256="2" * 64,
        attempt_id=uuid4(),
        consumed_by="workload:projection-recovery",
        requested_at=_REQUESTED_AT,
    )


def test_attempt_contract_is_hash_sealed_and_non_authorizing() -> None:
    request = _request()
    receipt = build_chongqing_federated_compensation_unknown_resume_attempt_receipt(
        request
    )

    assert request.expected_consumed_attempts == 0
    assert request.attempt_limit == 1
    assert request.committed_prefix_replay_allowed is False
    assert request.provider_invocation_performed is False
    assert request.production_execution_authorized is False
    assert receipt.attempt_number == 1
    assert receipt.authority_write_performed is True
    assert receipt.provider_invocation_performed is False
    assert receipt.cross_store_transaction_performed is False

    tampered = receipt.model_dump(mode="python")
    tampered["request"]["position"] = 2
    with pytest.raises(ValidationError):
        ChongqingFederatedCompensationUnknownResumeAttemptReceipt.model_validate(tampered)


def test_migration_enforces_append_only_rls_and_atomic_cas() -> None:
    migration = (
        CHONGQING_FIVE_PROVIDER_UNKNOWN_RESUME_ATTEMPT_AUTHORITY_MIGRATION.read_text(
            encoding="utf-8"
        )
    )

    assert "chongqing_five_provider_unknown_resume_attempt_ledger" in migration
    assert "chongqing_five_provider_unknown_resume_attempt_current" in migration
    assert "expected_consumed_attempts" in migration
    assert "pg_advisory_xact_lock" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "GRANT INSERT" not in migration


def test_repository_requires_postgresql() -> None:
    authority = PostgresChongqingFiveProviderUnknownResumeAttemptAuthority(
        _TENANT,
        create_engine("sqlite://"),
    )

    with pytest.raises(
        ChongqingFiveProviderUnknownResumeAttemptAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        authority.current(
            run_id="run-unknown-resume-1",
            request_bundle_sha256="c" * 64,
            position=1,
        )


def test_repository_rejects_cross_tenant_request_before_database_access() -> None:
    authority = PostgresChongqingFiveProviderUnknownResumeAttemptAuthority(
        "another-tenant",
        create_engine("sqlite://"),
    )

    with pytest.raises(
        ChongqingFiveProviderUnknownResumeAttemptAuthorityForbiddenError,
        match="tenant differs",
    ):
        authority.consume(_request())


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_attempt_budget_is_single_consumer_and_tenant_scoped() -> None:
    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            connection.exec_driver_sql(
                CHONGQING_FIVE_PROVIDER_UNKNOWN_RESUME_ATTEMPT_AUTHORITY_MIGRATION.read_text(
                    encoding="utf-8"
                ).replace("%", "%%")
            )

        authority = PostgresChongqingFiveProviderUnknownResumeAttemptAuthority(
            _TENANT,
            sandbox.runtime_engine,
        )
        first_request = _request()
        first_receipt = authority.consume(first_request)
        assert first_receipt.request == first_request
        assert authority.current(
            run_id=first_request.run_id,
            request_bundle_sha256=first_request.request_bundle_sha256,
            position=first_request.position,
        ) == first_receipt

        with pytest.raises(
            ChongqingFiveProviderUnknownResumeAttemptAuthorityConflictError,
            match="stale or exhausted",
        ):
            authority.consume(first_request)

        competing_requests = (_request(position=2), _request(position=2))

        def consume_competing(request):
            try:
                authority.consume(request)
            except ChongqingFiveProviderUnknownResumeAttemptAuthorityConflictError:
                return "conflict"
            return "consumed"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(consume_competing, competing_requests))
        assert sorted(outcomes) == ["conflict", "consumed"]

        other_tenant = PostgresChongqingFiveProviderUnknownResumeAttemptAuthority(
            "another-tenant",
            sandbox.runtime_engine,
        )
        assert (
            other_tenant.current(
                run_id=first_request.run_id,
                request_bundle_sha256=first_request.request_bundle_sha256,
                position=first_request.position,
            )
            is None
        )

        with pytest.raises(
            ChongqingFiveProviderUnknownResumeAttemptAuthorityForbiddenError,
            match="tenant or role was denied",
        ):
            with authority._transaction() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.
                            chongqing_five_provider_unknown_resume_attempt_ledger
                        SELECT * FROM gda_control.
                            chongqing_five_provider_unknown_resume_attempt_ledger
                        WHERE FALSE
                        """
                    )
                )

        with pytest.raises(DBAPIError):
            with sandbox.admin_connection() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE gda_control.
                            chongqing_five_provider_unknown_resume_attempt_ledger
                        SET consumed_by = consumed_by
                        WHERE tenant_id = :tenant_id
                        """
                    ),
                    {"tenant_id": _TENANT},
                )
