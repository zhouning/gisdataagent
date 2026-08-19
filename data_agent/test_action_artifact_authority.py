from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import create_engine, text

from data_agent.action_artifact_authority import (
    ACTION_ARTIFACT_AUTHORITY_MIGRATION,
    ActionArtifactAuthorityConfigurationError,
    ActionArtifactAuthorityConflictError,
    ActionArtifactAuthorityForbiddenError,
    ActionArtifactAuthorityValidationError,
    ActionArtifactKind,
    PostgresActionArtifactAuthority,
)
from data_agent.action_runtime import (
    ChangeOperation,
    ObjectStateChange,
    build_change_set,
)
from data_agent.test_action_runtime import NOW, _Executor, _fixture, _runtime


def test_migration_is_immutable_tenant_scoped_and_does_not_create_action_scheduler():
    migration = ACTION_ARTIFACT_AUTHORITY_MIGRATION.read_text(encoding="utf-8")

    assert "action_artifact" in migration
    assert "SECURITY DEFINER" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert "GRANT INSERT" not in migration
    assert "ActionRun" not in migration


def test_authority_requires_postgresql():
    store = PostgresActionArtifactAuthority("tenant-action", create_engine("sqlite://"))

    with pytest.raises(ActionArtifactAuthorityConfigurationError, match="requires PostgreSQL"):
        store.get(ActionArtifactKind.PROPOSAL, "a" * 64)


def test_authority_rejects_cross_tenant_and_invalid_kind_before_database_access():
    _, _, intent, _ = _fixture(l3=False)
    proposal = intent.proposal
    store = PostgresActionArtifactAuthority("other-tenant", create_engine("sqlite://"))

    with pytest.raises(ActionArtifactAuthorityForbiddenError, match="tenant differs"):
        store.record(proposal)

    tenant_store = PostgresActionArtifactAuthority("tenant-action", create_engine("sqlite://"))
    with pytest.raises(ActionArtifactAuthorityValidationError, match="kind is invalid"):
        tenant_store.get("proposal", "a" * 64)  # type: ignore[arg-type]


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL is not configured")
def test_real_postgres_action_artifacts_are_idempotent_and_tenant_scoped():
    from data_agent.cross_store_projection_postgres_rehearsal import _temporary_postgres

    capability, definition, intent, _ = _fixture(l3=False)
    proposal = intent.proposal
    change_set = intent.change_set
    response = _runtime(capability).execute(
        definition=definition,
        intent=intent,
        executor=_Executor(),
        now=NOW,
    )
    with _temporary_postgres(os.environ["DATABASE_URL"]) as sandbox:
        assert sandbox.runtime_engine is not None
        with sandbox.admin_connection() as connection:
            connection.exec_driver_sql(
                ACTION_ARTIFACT_AUTHORITY_MIGRATION.read_text(encoding="utf-8").replace("%", "%%")
            )
        store = PostgresActionArtifactAuthority(proposal.tenant_id, sandbox.runtime_engine)
        assert store.record(proposal) == proposal
        assert store.record(proposal) == proposal
        assert store.get(ActionArtifactKind.PROPOSAL, proposal.proposal_sha256) == proposal
        assert store.record(change_set) == change_set
        assert store.get(ActionArtifactKind.CHANGE_SET, change_set.change_set_sha256) == change_set
        changed = build_change_set(
            tenant_id=change_set.tenant_id,
            action_definition_sha256=change_set.action_definition_sha256,
            target_versions=change_set.target_versions,
            expected_changes=(
                ObjectStateChange(
                    object_urn=change_set.expected_changes[0].object_urn,
                    operation=ChangeOperation.DERIVE,
                    after_sha256="c" * 64,
                ),
            ),
            idempotency_key=change_set.idempotency_key,
        )
        with pytest.raises(ActionArtifactAuthorityConflictError, match="different content"):
            store.record(changed)
        assert store.record(response.result) == response.result
        assert (
            store.get(ActionArtifactKind.ACTION_RESULT, response.result.result_sha256)
            == response.result
        )
        other = PostgresActionArtifactAuthority("other-tenant", sandbox.runtime_engine)
        assert other.get(ActionArtifactKind.PROPOSAL, proposal.proposal_sha256) is None

        with pytest.raises(ActionArtifactAuthorityForbiddenError, match="denied"):
            with store._transaction() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_control.action_artifact (
                            tenant_id, artifact_kind, artifact_sha256,
                            identity_key, run_id, artifact_document
                        ) VALUES (
                            :tenant_id, 'proposal', :artifact_sha256,
                            :identity_key, :run_id,
                            CAST(:artifact_document AS jsonb)
                        )
                        """
                    ),
                    {
                        "tenant_id": proposal.tenant_id,
                        "artifact_sha256": proposal.proposal_sha256,
                        "identity_key": str(proposal.proposal_artifact_id),
                        "run_id": proposal.proposed_run_id,
                        "artifact_document": json.dumps(proposal.model_dump(mode="json")),
                    },
                )
