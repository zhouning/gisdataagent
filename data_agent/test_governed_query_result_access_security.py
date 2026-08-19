from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from data_agent.governed_query_policy_authority import (
    InMemoryGovernedQueryPolicyAuthority,
    build_policy_version,
    build_purpose_registration,
)
from data_agent.governed_query_result_access_security import (
    GovernedQueryResultAccessSecurityDeniedError,
    GovernedQueryResultAccessSecurityUnavailableError,
    build_governed_query_result_access_security_request,
    evaluate_governed_query_result_access_security,
)
from data_agent.platform_contracts import SubjectType

NOW = datetime(2026, 8, 19, 10, 30, tzinfo=UTC)


def _request(*, channel: str = "metric_result"):
    adapter_id = (
        "gda.metric-query.result-access.v1"
        if channel == "metric_result"
        else "gda.gis-analysis.result-access.v1"
    )
    return build_governed_query_result_access_security_request(
        tenant_id="tenant-a",
        request_id="result-access:00000000-0000-4000-8000-000000000001",
        actor_subject="human:analyst-a",
        roles=("analyst",),
        purpose_code="query_result_access",
        channel=channel,
        adapter_id=adapter_id,
        consumption_mode="download",
        resource_refs=(
            "gda://tenant-a/run/00000000-0000-4000-8000-000000000101",
            "gda://tenant-a/artifact/00000000-0000-4000-8000-000000000102",
        ),
        request_payload={
            "run_id": "00000000-0000-4000-8000-000000000101",
            "delivery": "presigned_get",
            "expires_in_seconds": 120,
        },
        evaluated_at=NOW,
    )


def _authority(
    *,
    adapter_id: str = "gda.metric-query.result-access.v1",
    obligations: tuple[str, ...] = (),
):
    authority = InMemoryGovernedQueryPolicyAuthority(
        "tenant-a", clock=lambda: NOW
    )
    authority.register_purpose(
        build_purpose_registration(
            tenant_id="tenant-a",
            purpose_code="query_result_access",
            description="Read an immutable governed query result",
            registered_by="human:policy-admin",
            registered_at=NOW - timedelta(minutes=1),
        )
    )
    authority.register_policy(
        build_policy_version(
            tenant_id="tenant-a",
            policy_ref="policy:query-result-access",
            policy_version="v1",
            purpose_code="query_result_access",
            subject_types=(SubjectType.HUMAN,),
            required_roles=("analyst",),
            channels=("metric_result",),
            adapter_ids=(adapter_id,),
            resource_prefixes=("gda://tenant-a/",),
            obligations=obligations,
            valid_from=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(days=1),
            published_at=NOW - timedelta(seconds=1),
            published_by="human:policy-admin",
        )
    )
    return authority


def test_result_access_security_translates_to_current_policy_and_reseals() -> None:
    request = _request()

    decision = evaluate_governed_query_result_access_security(
        request,
        _authority(),
        evaluated_at=NOW,
    )

    assert decision.request == request
    assert decision.effect == "allow"
    assert decision.policy_ref == "policy:query-result-access"
    assert decision.request.resources[1].consumption_mode == "download"
    assert decision.external_access_performed is False


def test_result_access_security_denies_nonmatching_channel() -> None:
    with pytest.raises(GovernedQueryResultAccessSecurityDeniedError):
        evaluate_governed_query_result_access_security(
            _request(channel="gis_result"),
            _authority(),
            evaluated_at=NOW,
        )


def test_result_access_security_rejects_unsupported_obligation() -> None:
    with pytest.raises(
        GovernedQueryResultAccessSecurityDeniedError,
        match="unsupported obligations",
    ):
        evaluate_governed_query_result_access_security(
            _request(),
            _authority(obligations=("mask_sensitive_fields",)),
            evaluated_at=NOW,
        )


def test_result_access_security_rejects_cross_tenant_reader() -> None:
    other = InMemoryGovernedQueryPolicyAuthority("tenant-b", clock=lambda: NOW)

    with pytest.raises(
        GovernedQueryResultAccessSecurityUnavailableError,
        match="tenant-bound",
    ):
        evaluate_governed_query_result_access_security(
            _request(),
            other,
            evaluated_at=NOW,
        )
