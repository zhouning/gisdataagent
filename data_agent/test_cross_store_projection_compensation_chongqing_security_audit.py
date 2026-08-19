from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_agent.cross_store_projection_compensation_chongqing_execution_security import (
    CHONGQING_FIVE_PROVIDER_EXECUTION_PURPOSE,
    build_chongqing_federated_compensation_execution_security_decision,
    build_chongqing_federated_compensation_execution_security_request,
    build_chongqing_federated_compensation_execution_security_resource,
)
from data_agent.cross_store_projection_compensation_chongqing_security_audit import (
    InMemoryChongqingCompensationSecurityAudit,
    audit_attempt_id,
    require_security_audit_port,
)
from data_agent.cross_store_projection_consistency import ProjectionEngine
from data_agent.platform_contracts import SubjectContext

TENANT = "cq-security-audit"
NOW = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)


def _request():
    subject = SubjectContext(
        tenant_id=TENANT,
        subject_id="five-provider-dispatcher",
        subject_type="workload",
        roles=("compensation_executor",),
        purpose=CHONGQING_FIVE_PROVIDER_EXECUTION_PURPOSE,
        trace_id="trace-security-audit",
    )
    resources = tuple(
        build_chongqing_federated_compensation_execution_security_resource(
            position=position,
            target_engine=engine,
            target_ref=f"target-{position}",
            access_mode="mutate",
            provider_action="rebuild",
            request_sha256=f"{position + 1:064x}",
            action_map_item_sha256=f"{position + 11:064x}",
            action_execution_binding_item_sha256=f"{position + 21:064x}",
        )
        for position, engine in enumerate(ProjectionEngine)
    )
    return build_chongqing_federated_compensation_execution_security_request(
        tenant_id=TENANT,
        run_id="security-audit-run",
        subject_context=subject,
        operation="chongqing.five_provider.execute",
        request_bundle_sha256="a" * 64,
        action_map_sha256="b" * 64,
        action_execution_binding_sha256="c" * 64,
        production_admission_event_sha256="d" * 64,
        resources=resources,
        evaluated_at=NOW,
    )


def test_in_memory_security_audit_binds_admission_and_outcome():
    request = _request()
    decision = build_chongqing_federated_compensation_execution_security_decision(
        request,
        effect="allow",
        policy_ref="gda://policy/cq",
        policy_version="1.0.0",
        evaluator_subject="workload:policy-evaluator",
        decided_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
    )
    audit = InMemoryChongqingCompensationSecurityAudit(TENANT)
    admission = audit.record_admission(request, decision)
    outcome = audit.record_outcome(
        admission,
        outcome="success",
        evidence_sha256="e" * 64,
        provider_invocations=5,
        recorded_at=NOW,
    )

    assert audit_attempt_id(request) == audit_attempt_id(request)
    assert admission.decision_sha256 == decision.decision_sha256
    assert admission.resource_scope_sha256
    assert outcome.admission_sha256 == admission.admission_sha256
    assert outcome.provider_invocations == 5
    assert len(audit.admissions) == len(audit.outcomes) == 1


def test_security_audit_port_rejects_cross_tenant_and_missing_port():
    request = _request()
    decision = build_chongqing_federated_compensation_execution_security_decision(
        request,
        effect="allow",
        policy_ref="gda://policy/cq",
        policy_version="1.0.0",
        evaluator_subject="workload:policy-evaluator",
        decided_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
    )
    audit = InMemoryChongqingCompensationSecurityAudit(TENANT)
    with pytest.raises(RuntimeError, match="tenant"):
        InMemoryChongqingCompensationSecurityAudit("other-tenant").record_admission(
            request, decision
        )
    with pytest.raises(RuntimeError, match="tenant-bound"):
        require_security_audit_port(None, TENANT)
    with pytest.raises(RuntimeError, match="tenant"):
        audit.record_admission(request.model_copy(update={"tenant_id": "other-tenant"}), decision)


def test_prometheus_rules_cover_audit_failure_and_unclosed_admission():
    rules = (Path(__file__).parent / "prometheus" / "alert_rules.yml").read_text(
        encoding="utf-8"
    )
    assert "agent_security_execution_audit_events_total" in rules
    assert "GovernedExecutionAuditFailure" in rules
    assert "GovernedExecutionAuditAdmissionWithoutOutcome" in rules
