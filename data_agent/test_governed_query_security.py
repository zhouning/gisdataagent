from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from data_agent.governed_query import (
    GovernedQueryRequest,
    QueryExecutionStatus,
    QueryPolicyDeniedError,
    execute_governed_query,
)
from data_agent.governed_query_security import (
    GovernedQuerySecurityDecision,
    GovernedQuerySecurityError,
    InMemoryGovernedQuerySecurityAudit,
    _fingerprint,
)
from data_agent.platform_contracts import SubjectContext, SubjectType


def _request() -> GovernedQueryRequest:
    return GovernedQueryRequest.model_validate(
        {
            "request_id": "security-query-001",
            "question": "土地是什么？",
            "purpose": "validate governed ontology query",
            "channel": "ontology",
            "ontology_plan": {"query_type": "concept_explanation", "subject": "土地"},
        }
    )


def _subject() -> SubjectContext:
    return SubjectContext(
        tenant_id="tenant-a",
        subject_id="analyst-a",
        subject_type=SubjectType.HUMAN,
        roles=("analyst",),
        purpose="validate governed ontology query",
        trace_id="security-query-trace",
    )


class _Reader:
    def __init__(self, effect: str = "allow", error: Exception | None = None):
        self.tenant_id = "tenant-a"
        self.effect = effect
        self.error = error
        self.calls = 0

    def governed_query_security_decision_current(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return _decision(request, effect=self.effect)


def _decision(request, *, effect: str = "allow") -> GovernedQuerySecurityDecision:
    now = datetime.now(UTC)
    values = {
        "request": request,
        "effect": effect,
        "policy_ref": "policy:semantic-query",
        "policy_version": "v1",
        "evaluator_subject": "workload:policy-engine",
        "obligations": (),
        "decided_at": now,
        "expires_at": now + timedelta(minutes=5),
        "authority_live_read_performed": True,
        "provider_access_performed": False,
    }
    return GovernedQuerySecurityDecision(
        **values,
        decision_sha256=_fingerprint(
            GovernedQuerySecurityDecision.schema_id,
            values,
            "decision_sha256",
        ),
    )


def test_query_security_deny_fails_closed_before_adapter(monkeypatch) -> None:
    request = _request()
    subject = _subject()
    audit = InMemoryGovernedQuerySecurityAudit("tenant-a")
    reader = _Reader(effect="deny")
    calls = 0

    def _unexpected(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("adapter must not be called")

    monkeypatch.setattr(
        "data_agent.governed_query.OntologyQueryAdapter.execute", _unexpected
    )
    result = execute_governed_query(
        request,
        subject,
        security_reader=reader,
        security_audit_port=audit,
    )
    assert result.status is QueryExecutionStatus.NOT_ADMITTED
    assert calls == 0
    assert reader.calls == 1
    assert audit.admissions == []


def test_query_security_allow_audits_admission_and_outcome() -> None:
    request = _request()
    subject = _subject()
    audit = InMemoryGovernedQuerySecurityAudit("tenant-a")

    class Reader:
        tenant_id = "tenant-a"

        def governed_query_security_decision_current(self, security_request):
            return _decision(security_request)

    result = execute_governed_query(
        request,
        subject,
        security_reader=Reader(),
        security_audit_port=audit,
    )
    assert result.status is QueryExecutionStatus.COMPLETED
    assert len(audit.admissions) == 1
    assert len(audit.outcomes) == 1
    assert audit.outcomes[0].outcome == "success"
    assert audit.outcomes[0].adapter_invocations == 1


def test_query_security_audit_failure_is_not_hidden() -> None:
    request = _request()
    subject = _subject()

    class Reader:
        tenant_id = "tenant-a"

        def governed_query_security_decision_current(self, security_request):
            return _decision(security_request)

    class BrokenAudit(InMemoryGovernedQuerySecurityAudit):
        def record_outcome(self, *args, **kwargs):
            raise GovernedQuerySecurityError("ledger unavailable")

    with pytest.raises(QueryPolicyDeniedError, match="outcome audit"):
        execute_governed_query(
            request,
            subject,
            security_reader=Reader(),
            security_audit_port=BrokenAudit("tenant-a"),
        )
