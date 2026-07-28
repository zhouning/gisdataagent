import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from data_agent.metadata_fabric_binding_contract import (
    build_metadata_fabric_binding_record,
)
from data_agent.metadata_fabric_binding_ledger import (
    build_binding_ledger_bundle,
    run_local_rehearsal,
    validate_rehearsal_evidence,
)
from data_agent.platform_gateway import (
    GatewayConflictError,
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
)


DATABASE_URL = os.environ.get("DATABASE_URL")


def _temporary_database_url() -> tuple[object, str, str]:
    admin_url = make_url(DATABASE_URL)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            admin_engine.dispose()
            pytest.skip("binding ledger test requires a PostgreSQL superuser")
        database_name = f"gda_binding_{uuid4().hex}"
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
def test_postgres_binding_ledger_is_idempotent_tenant_scoped_and_append_only():
    admin_engine, database_name, database_url = _temporary_database_url()
    engine = None
    try:
        evidence = run_local_rehearsal(database_url)
        assert validate_rehearsal_evidence(evidence) == []
        assert evidence["first_commit_created"] is True
        assert evidence["replay_commit_created"] is False

        bundle = build_binding_ledger_bundle()
        engine = create_engine(database_url)
        gateway = PlatformGateway(engine)
        assert gateway.get_metadata_fabric_binding(
            bundle.record.tenant_id,
            bundle.record.binding.resource_version_id,
        ) == bundle.record
        with pytest.raises(GatewayNotFoundError):
            gateway.get_metadata_fabric_binding(
                "isolated-tenant",
                bundle.record.binding.resource_version_id,
            )

        missing_evidence = build_metadata_fabric_binding_record(
            binding=bundle.record.binding,
            execution_plan_artifact_id=bundle.record.execution_plan_artifact_id,
            policy_decision_artifact_id=bundle.record.policy_decision_artifact_id,
            approval_artifact_id=bundle.record.approval_artifact_id,
            provider_evidence_artifact_id=uuid4(),
            recorded_by=bundle.record.recorded_by,
            recorded_at=bundle.record.recorded_at,
        )
        with pytest.raises(GatewayValidationError, match="was not found"):
            gateway.commit_metadata_fabric_binding(missing_evidence)

        original_provider_artifact = bundle.artifacts[-1]
        tampered_provider_artifact = original_provider_artifact.model_copy(
            update={"artifact_id": uuid4()}
        )
        gateway.record_artifact(tampered_provider_artifact)
        tampered_evidence = build_metadata_fabric_binding_record(
            binding=bundle.record.binding,
            execution_plan_artifact_id=bundle.record.execution_plan_artifact_id,
            policy_decision_artifact_id=bundle.record.policy_decision_artifact_id,
            approval_artifact_id=bundle.record.approval_artifact_id,
            provider_evidence_artifact_id=tampered_provider_artifact.artifact_id,
            recorded_by=bundle.record.recorded_by,
            recorded_at=bundle.record.recorded_at,
        )
        with pytest.raises(GatewayValidationError, match="metadata does not match"):
            gateway.commit_metadata_fabric_binding(tampered_evidence)

        different_replay = build_metadata_fabric_binding_record(
            binding=bundle.record.binding,
            execution_plan_artifact_id=bundle.record.execution_plan_artifact_id,
            policy_decision_artifact_id=bundle.record.policy_decision_artifact_id,
            approval_artifact_id=bundle.record.approval_artifact_id,
            provider_evidence_artifact_id=bundle.record.provider_evidence_artifact_id,
            recorded_by=bundle.record.recorded_by,
            recorded_at=bundle.record.recorded_at + timedelta(seconds=1),
        )
        with pytest.raises(GatewayConflictError, match="different binding"):
            gateway.commit_metadata_fabric_binding(different_replay)

        with gateway._transaction(bundle.record.tenant_id) as connection:
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            """
                            UPDATE gda_control.metadata_fabric_binding
                            SET recorded_at = recorded_at + interval '1 second'
                            WHERE binding_id = :binding_id
                            """
                        ),
                        {"binding_id": bundle.record.binding_id},
                    )
            with pytest.raises(DBAPIError):
                with connection.begin_nested():
                    connection.execute(
                        text(
                            """
                            DELETE FROM gda_control.metadata_fabric_binding
                            WHERE binding_id = :binding_id
                            """
                        ),
                        {"binding_id": bundle.record.binding_id},
                    )
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temporary_database(admin_engine, database_name)
