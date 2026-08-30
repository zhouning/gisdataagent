from __future__ import annotations

from pathlib import Path

import pytest

from data_agent.agentops_specialist_retry_budget import (
    RETRY_BUDGET_MIGRATION,
    InMemorySpecialistRetryBudgetAuthority,
    SpecialistRetryBudgetError,
    provider_operation_family_key,
)
from data_agent.agentops_temporal_contracts import (
    TemporalActivityRequest,
    derive_temporal_activity_id,
    temporal_contract_fingerprint,
)
from data_agent.test_agentops_specialist_operation_authority import _request


def _request_attempt(attempt_no: int) -> TemporalActivityRequest:
    request = _request()
    values = request.model_dump(mode="python")
    values["attempt_no"] = attempt_no
    values["activity_id"] = derive_temporal_activity_id(
        run_id=request.run_id, tool_call_id=request.tool_call_id, attempt_no=attempt_no
    )
    values["request_sha256"] = temporal_contract_fingerprint(
        TemporalActivityRequest.schema_id, values, "request_sha256"
    )
    return TemporalActivityRequest(**values)


def test_budget_is_keyed_by_tool_call_and_survives_worker_replacement() -> None:
    request = _request_attempt(1)
    key = provider_operation_family_key(request)
    authority = InMemorySpecialistRetryBudgetAuthority()

    first = authority.admit(
        request,
        operation_key=key,
        max_attempts=1,
        worker_id="workload:worker-a",
    )
    replay = authority.admit(
        request,
        operation_key=key,
        max_attempts=1,
        worker_id="workload:worker-b",
    )

    assert first == replay
    assert first.admitted is True
    observed = authority.observe(tenant_id=request.tenant_id, operation_key=key)
    assert observed is not None
    assert observed.attempt_count == 1
    assert len(observed.admissions) == 1


def test_budget_denies_new_attempt_after_restart_without_resetting_count() -> None:
    first_request = _request_attempt(1)
    second_values = first_request.model_dump(mode="python")
    second_values["attempt_no"] = 2
    second_values["activity_id"] = derive_temporal_activity_id(
        run_id=first_request.run_id,
        tool_call_id=first_request.tool_call_id,
        attempt_no=2,
    )
    second_values["request_sha256"] = temporal_contract_fingerprint(
        TemporalActivityRequest.schema_id, second_values, "request_sha256"
    )
    second_request = TemporalActivityRequest(**second_values)
    key = provider_operation_family_key(first_request)
    authority = InMemorySpecialistRetryBudgetAuthority()

    authority.admit(
        first_request,
        operation_key=key,
        max_attempts=1,
        worker_id="workload:worker-a",
    )
    denied = authority.admit(
        second_request,
        operation_key=key,
        max_attempts=1,
        worker_id="workload:worker-b",
    )

    assert denied.admitted is False
    assert denied.reason == "retry_budget_exhausted"
    observed = authority.observe(tenant_id=first_request.tenant_id, operation_key=key)
    assert observed is not None
    assert observed.attempt_count == 1
    assert observed.status == "exhausted"


def test_budget_rejects_family_policy_drift() -> None:
    request = _request_attempt(1)
    key = provider_operation_family_key(request)
    authority = InMemorySpecialistRetryBudgetAuthority()
    authority.admit(
        request,
        operation_key=key,
        max_attempts=2,
        worker_id="workload:worker-a",
    )
    with pytest.raises(SpecialistRetryBudgetError, match="differs from existing family"):
        authority.admit(
            request,
            operation_key=key,
            max_attempts=3,
            worker_id="workload:worker-b",
        )


def test_migration_is_append_only_and_gateway_bound() -> None:
    migration = Path(RETRY_BUDGET_MIGRATION).read_text(encoding="utf-8")
    assert "agentops_specialist_retry_budget" in migration
    assert "agentops_specialist_retry_admission_history" in migration
    assert "record_agentops_specialist_retry_admission" in migration
    assert "pg_advisory_xact_lock" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "GRANT INSERT" not in migration
