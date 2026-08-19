from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres
from data_agent.governed_query import (
    GovernedQueryRequest,
    QueryExecutionStatus,
    execute_governed_query,
)
from data_agent.governed_query_policy_authority import (
    GOVERNED_QUERY_POLICY_AUTHORITY_MIGRATIONS,
    GovernedQueryPolicyAuthorityConfigurationError,
    GovernedQueryPolicyAuthorityConflictError,
    GovernedQueryPolicyAuthorityForbiddenError,
    InMemoryGovernedQueryPolicyAuthority,
    InMemoryGovernedQuerySecurityPortResolver,
    PostgresGovernedQueryPolicyAuthority,
    PostgresGovernedQuerySecurityPortResolver,
    build_policy_revocation,
    build_policy_version,
    build_purpose_registration,
    configure_default_governed_query_security_resolver,
)
from data_agent.governed_query_security import (
    InMemoryGovernedQuerySecurityAudit,
    build_query_security_request,
    configure_governed_query_security_port_resolver,
    governed_query_security_resolver_configured,
)
from data_agent.platform_contracts import SubjectContext, SubjectType

NOW = datetime.now(UTC)


def _authority() -> InMemoryGovernedQueryPolicyAuthority:
    authority = InMemoryGovernedQueryPolicyAuthority(
        "tenant-a", clock=lambda: NOW
    )
    authority.register_purpose(
        build_purpose_registration(
            tenant_id="tenant-a",
            purpose_code="semantic_query",
            description="read governed semantic data",
            registered_by="human:policy-admin",
            registered_at=NOW,
        )
    )
    return authority


def _request(
    *,
    tenant_id: str = "tenant-a",
    subject_id: str = "analyst-a",
    roles: tuple[str, ...] = ("analyst",),
):
    subject = SubjectContext(
        tenant_id=tenant_id,
        subject_id=subject_id,
        subject_type=SubjectType.HUMAN,
        roles=roles,
        purpose="semantic_query",
        trace_id="query-policy-trace",
    )
    return build_query_security_request(
        request_payload_sha256="a" * 64,
        request_id="policy-query-001",
        tenant_id=tenant_id,
        subject_context=subject,
        purpose_code="semantic_query",
        channel="ontology",
        adapter_id="gda.ontology.query",
        resource_refs=("dataset:natural-resource@v1",),
        evaluated_at=NOW,
    )


def _policy(**overrides):
    values = {
        "tenant_id": "tenant-a",
        "policy_ref": "policy:semantic-query",
        "policy_version": "v1",
        "purpose_code": "semantic_query",
        "subject_types": (SubjectType.HUMAN,),
        "required_roles": ("analyst",),
        "channels": ("ontology",),
        "adapter_ids": ("gda.ontology.query",),
        "resource_prefixes": ("dataset:",),
        "valid_from": NOW - timedelta(days=1),
        "expires_at": NOW + timedelta(days=1),
        "published_at": NOW - timedelta(seconds=1),
        "published_by": "human:policy-admin",
    }
    values.update(overrides)
    return build_policy_version(**values)


def test_current_reader_requires_registered_purpose_and_exact_scope() -> None:
    authority = _authority()
    authority.register_policy(_policy())

    decision = authority.governed_query_security_decision_current(_request())
    assert decision.effect == "allow"
    assert decision.policy_version == "v1"
    assert decision.authority_live_read_performed is True

    denied = authority.governed_query_security_decision_current(
        _request(roles=("viewer",))
    )
    assert denied.effect == "deny"
    assert denied.policy_version == "none"


def test_newer_nonmatching_version_replaces_older_current_version() -> None:
    authority = _authority()
    authority.register_policy(_policy())
    authority.register_policy(
        _policy(
            policy_version="v2",
            published_at=NOW,
            subject_ids=("other-user",),
        )
    )

    decision = authority.governed_query_security_decision_current(_request())
    assert decision.effect == "deny"
    assert decision.policy_version == "none"


def test_future_version_and_revocation_do_not_take_effect_early() -> None:
    authority = _authority()
    policy = _policy()
    authority.register_policy(policy)
    authority.register_policy(
        _policy(
            policy_version="v2",
            published_at=NOW + timedelta(minutes=5),
            valid_from=NOW + timedelta(minutes=5),
            subject_ids=("other-user",),
        )
    )
    authority.revoke_policy(
        build_policy_revocation(
            tenant_id="tenant-a",
            policy_ref=policy.policy_ref,
            policy_version=policy.policy_version,
            revoked_at=NOW + timedelta(minutes=10),
            revoked_by="human:policy-admin",
            reason="scheduled revocation",
        )
    )

    decision = authority.governed_query_security_decision_current(_request())
    assert decision.effect == "allow"
    assert decision.policy_version == "v1"


def test_revocation_is_append_only_and_fails_closed() -> None:
    authority = _authority()
    policy = _policy()
    authority.register_policy(policy)
    revocation = build_policy_revocation(
        tenant_id="tenant-a",
        policy_ref=policy.policy_ref,
        policy_version=policy.policy_version,
        revoked_at=NOW,
        revoked_by="human:policy-admin",
        reason="superseded during development",
    )
    authority.revoke_policy(revocation)
    assert authority.governed_query_security_decision_current(_request()).effect == "deny"

    with pytest.raises(GovernedQueryPolicyAuthorityConflictError):
        authority.revoke_policy(revocation.model_copy(update={"reason": "changed"}))


def test_immutable_registration_rejects_different_duplicate() -> None:
    authority = _authority()
    registration = build_purpose_registration(
        tenant_id="tenant-a",
        purpose_code="semantic_query",
        description="changed",
        registered_by="human:policy-admin",
        registered_at=NOW,
    )
    with pytest.raises(GovernedQueryPolicyAuthorityConflictError):
        authority.register_purpose(registration)


def test_tenant_bound_resolver_rejects_unknown_tenant() -> None:
    resolver = InMemoryGovernedQuerySecurityPortResolver(
        {"tenant-a": _authority()}
    )
    with pytest.raises(GovernedQueryPolicyAuthorityForbiddenError):
        resolver.resolve("tenant-b")


def test_policy_authority_migration_is_tenant_scoped_and_append_only() -> None:
    migration = "\n".join(
        path.read_text(encoding="utf-8")
        for path in GOVERNED_QUERY_POLICY_AUTHORITY_MIGRATIONS
    )
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "governed_query_policy_version" in migration
    assert "governed_query_policy_revocation" in migration
    assert "GRANT SELECT ON gda_control.governed_query_policy_version" in migration
    assert "register_governed_query_purpose" in migration
    assert "register_governed_query_policy_version" in migration
    assert "revoke_governed_query_policy" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "GRANT EXECUTE ON FUNCTION" in migration
    assert "GRANT INSERT" not in migration


def test_postgres_authority_requires_postgresql() -> None:
    authority = PostgresGovernedQueryPolicyAuthority(
        "tenant-a", create_engine("sqlite://")
    )
    with pytest.raises(
        GovernedQueryPolicyAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        authority.governed_query_security_decision_current(_request())


def test_postgres_authority_rejects_cross_tenant_before_database_access() -> None:
    authority = PostgresGovernedQueryPolicyAuthority(
        "tenant-b", create_engine("sqlite://")
    )
    with pytest.raises(GovernedQueryPolicyAuthorityForbiddenError, match="tenant differs"):
        authority.register_policy(_policy())


def test_postgres_resolver_returns_tenant_bound_policy_and_audit_ports() -> None:
    resolver = PostgresGovernedQuerySecurityPortResolver(create_engine("sqlite://"))
    reader, audit = resolver.resolve("tenant-a")
    assert reader.tenant_id == "tenant-a"
    assert audit.tenant_id == "tenant-a"


def test_default_resolver_configuration_is_disabled_in_development(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "0")
    configure_governed_query_security_port_resolver(None)

    assert configure_default_governed_query_security_resolver() is False
    assert governed_query_security_resolver_configured() is False


def test_default_resolver_configuration_requires_postgresql(monkeypatch) -> None:
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "1")
    configure_governed_query_security_port_resolver(None)
    with pytest.raises(
        GovernedQueryPolicyAuthorityConfigurationError,
        match="needs PostgreSQL",
    ):
        configure_default_governed_query_security_resolver(create_engine("sqlite://"))


def test_default_resolver_configuration_preserves_explicit_resolver(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "1")
    explicit = InMemoryGovernedQuerySecurityPortResolver({"tenant-a": _authority()})
    configure_governed_query_security_port_resolver(explicit)
    try:
        assert configure_default_governed_query_security_resolver() is False
        reader, _ = explicit.resolve("tenant-a")
        assert reader.tenant_id == "tenant-a"
    finally:
        configure_governed_query_security_port_resolver(None)


def test_default_resolver_configuration_installs_durable_resolver(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GDA_GOVERNED_QUERY_SECURITY_REQUIRED", "1")
    configure_governed_query_security_port_resolver(None)
    engine = create_engine("postgresql+psycopg2://invalid:invalid@127.0.0.1:1/invalid")
    try:
        assert configure_default_governed_query_security_resolver(engine) is True
        assert governed_query_security_resolver_configured() is True
    finally:
        configure_governed_query_security_port_resolver(None)
        engine.dispose()


def test_app_source_installs_default_query_security_resolver() -> None:
    source = Path(__file__).with_name("app.py").read_text(encoding="utf-8")
    assert "configure_default_governed_query_security_resolver()" in source


def test_authority_drives_governed_query_with_controlled_purpose_code() -> None:
    authority = _authority()
    authority.register_policy(
        _policy(
            resource_prefixes=("channel:ontology",),
            adapter_ids=("gda.ontology.typed-query.v1",),
        )
    )
    query = GovernedQueryRequest.model_validate(
        {
            "request_id": "policy-query-e2e",
            "question": "土地是什么？",
            "purpose": "free text business explanation",
            "channel": "ontology",
            "ontology_plan": {
                "query_type": "concept_explanation",
                "subject": "土地",
            },
        }
    )
    subject = SubjectContext(
        tenant_id="tenant-a",
        subject_id="analyst-a",
        subject_type=SubjectType.HUMAN,
        roles=("analyst",),
        purpose=query.purpose,
        trace_id=query.request_id,
    )
    audit = InMemoryGovernedQuerySecurityAudit("tenant-a")

    result = execute_governed_query(
        query,
        subject,
        security_reader=authority,
        security_audit_port=audit,
    )

    assert result.status is QueryExecutionStatus.COMPLETED
    assert len(audit.admissions) == 1
    assert audit.admissions[0].policy_version == "v1"


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL is not configured",
)
def test_real_postgres_policy_authority_is_current_append_only_and_tenant_scoped() -> None:
    registration = build_purpose_registration(
        tenant_id="tenant-a",
        purpose_code="semantic_query",
        description="read governed semantic data",
        registered_by="human:policy-admin",
        registered_at=NOW,
    )
    policy = _policy()
    revocation = build_policy_revocation(
        tenant_id="tenant-a",
        policy_ref=policy.policy_ref,
        policy_version=policy.policy_version,
        revoked_at=NOW,
        revoked_by="human:policy-admin",
        reason="development revocation rehearsal",
    )

    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            for migration in GOVERNED_QUERY_POLICY_AUTHORITY_MIGRATIONS:
                connection.exec_driver_sql(
                    migration.read_text(encoding="utf-8").replace("%", "%%")
                )

        authority = PostgresGovernedQueryPolicyAuthority(
            "tenant-a", sandbox.runtime_engine
        )
        assert authority.register_purpose(registration) == registration
        assert authority.register_purpose(registration) == registration
        assert authority.register_policy(policy) == policy
        assert authority.register_policy(policy) == policy
        allow = authority.governed_query_security_decision_current(_request())
        assert allow.effect == "allow"
        assert allow.policy_version == "v1"
        assert allow.evaluator_subject == "workload:postgres-query-policy-authority"

        assert authority.revoke_policy(revocation) == revocation
        assert authority.revoke_policy(revocation) == revocation
        assert authority.governed_query_security_decision_current(_request()).effect == "deny"

        other = PostgresGovernedQueryPolicyAuthority(
            "tenant-b", sandbox.runtime_engine
        )
        assert (
            other.governed_query_security_decision_current(
                _request(tenant_id="tenant-b")
            ).effect
            == "deny"
        )

        with pytest.raises(GovernedQueryPolicyAuthorityForbiddenError):
            with authority._transaction() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.governed_query_policy_revocation (
                            tenant_id, policy_ref, policy_version, revoked_at,
                            revoked_by, reason, revocation_sha256
                        ) VALUES (
                            :tenant_id, :policy_ref, :policy_version, :revoked_at,
                            :revoked_by, :reason, :revocation_sha256
                        )
                        """
                    ),
                    revocation.model_dump(mode="python"),
                )
