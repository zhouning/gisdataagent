import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from data_agent import metadata_fabric_active_metadata_binding_reconciliation as binding
from data_agent import metadata_fabric_active_metadata_projection_execution as execution
from data_agent.dolphinscheduler_adapter import DolphinSchedulerDefinitionBinding
from data_agent.metadata_fabric_binding_contract import (
    ACTIVE_METADATA_PROJECTION_EVIDENCE_SCHEMA,
    build_metadata_fabric_binding_record,
    build_metadata_fabric_provider_evidence,
    build_metadata_fabric_provider_evidence_artifact,
)
from data_agent.platform_gateway import GatewayNotFoundError, PlatformGateway

DATABASE_URL = os.environ.get("DATABASE_URL")
AT = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _temporary_database_url() -> tuple[object, str, str]:
    admin_url = make_url(DATABASE_URL)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        if not connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one():
            admin_engine.dispose()
            pytest.skip("binding reconciliation test requires a PostgreSQL superuser")
        database_name = f"gda_binding_reconciliation_{uuid4().hex}"
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
    database_url = admin_url.set(database=database_name).render_as_string(
        hide_password=False
    )
    return admin_engine, database_name, database_url


def _drop_temporary_database(admin_engine, database_name: str) -> None:
    with admin_engine.connect() as connection:
        connection.execute(
            text(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :database_name
                  AND pid <> pg_backend_pid()
                """
            ),
            {"database_name": database_name},
        )
        connection.exec_driver_sql(f'DROP DATABASE "{database_name}"')
    admin_engine.dispose()


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_real_m3_18_binding_commits_idempotently_to_fresh_postgres():
    admin_engine, database_name, database_url = _temporary_database_url()
    engine = None
    try:
        source = json.loads(
            binding.DEFAULT_SOURCE_EVIDENCE_PATH.read_text(encoding="utf-8")
        )
        profile = execution.build_projection_profile(AT)
        bound = binding.build_bound_source(source, profile)
        plan = binding.build_projection_plan(bound.version.content_sha256, profile)
        request = execution.build_execution_request(plan)
        definition = binding.build_scheduler_definition(
            "http://host.docker.internal:43123/v1/execute-projection",
            request,
            created_at=AT,
        )
        scheduler_binding = DolphinSchedulerDefinitionBinding(
            tenant_id=binding.TENANT,
            definition_version_id=binding.DEFINITION_ID,
            project_code=190000000000101,
            workflow_definition_code=190000000000102,
            workflow_definition_version=1,
            compiled_sha256=definition.workflow.compiled_sha256,
        )
        dispatch = binding.build_dispatch_bundle(
            bound.version.content_sha256,
            bound,
            definition,
            scheduler_binding,
            authorized_at=AT,
        )
        apply_authorization = execution.build_provider_apply_authorization(
            plan,
            dispatch.run,
            profile,
        )
        first = source["first_apply"]
        provider_evidence = build_metadata_fabric_provider_evidence(
            binding=bound.binding,
            source_evidence_schema=ACTIVE_METADATA_PROJECTION_EVIDENCE_SCHEMA,
            source_evidence_sha256=source["evidence_sha256"],
            openmetadata_snapshot_sha256=first["openmetadata"]["snapshot_sha256"],
            gravitino_snapshot_sha256=first["gravitino"]["snapshot_sha256"],
            first_apply_status="created",
            first_apply_mutation_count=4,
            observed_at=AT,
        )
        provider_artifact = build_metadata_fabric_provider_evidence_artifact(
            provider_evidence,
            created_by=binding.RUNNER,
        )
        record = build_metadata_fabric_binding_record(
            binding=bound.binding,
            execution_plan_artifact_id=(
                apply_authorization.execution_plan_artifact.artifact_id
            ),
            policy_decision_artifact_id=(
                apply_authorization.policy_decision_artifact.artifact_id
            ),
            approval_artifact_id=apply_authorization.approval_artifact.artifact_id,
            provider_evidence_artifact_id=provider_artifact.artifact_id,
            recorded_by=binding.RUNNER,
            recorded_at=AT,
        )

        engine = create_engine(database_url)
        binding._apply_migrations(engine)
        gateway = PlatformGateway(engine)
        binding._register_control_chain(gateway, dispatch, apply_authorization)
        gateway.record_artifact(provider_artifact)

        first_commit = gateway.commit_metadata_fabric_binding(record)
        replay_commit = gateway.commit_metadata_fabric_binding(record)
        stored = gateway.get_metadata_fabric_binding(binding.TENANT, binding.SOURCE_ID)
        with pytest.raises(GatewayNotFoundError):
            gateway.get_metadata_fabric_binding("isolated-tenant", binding.SOURCE_ID)
        update_blocked, delete_blocked = binding._direct_binding_mutations_blocked(
            gateway,
            record,
        )
        row_count, append_only, force_rls = binding._binding_ledger_state(
            engine,
            record,
        )

        assert first_commit.created is True
        assert replay_commit.created is False
        assert first_commit.value == replay_commit.value == stored == record
        assert row_count == 1
        assert update_blocked and delete_blocked
        assert append_only and force_rls
        assert stored.binding.binding_sha256 == (
            source["first_apply"]["binding_candidate_sha256"]
        )
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temporary_database(admin_engine, database_name)
