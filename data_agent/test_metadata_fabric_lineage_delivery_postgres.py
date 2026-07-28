import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from data_agent.metadata_fabric_lineage_delivery import (
    WORKER_ID,
    build_lineage_delivery_bundle,
    run_local_rehearsal,
    validate_rehearsal_evidence,
)
from data_agent.platform_gateway import (
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
            pytest.skip("lineage delivery test requires a PostgreSQL superuser")
        database_name = f"gda_lineage_{uuid4().hex}"
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
def test_postgres_lineage_delivery_is_tenant_scoped_retryable_and_idempotent():
    admin_engine, database_name, database_url = _temporary_database_url()
    engine = None
    try:
        evidence = run_local_rehearsal(database_url)
        assert validate_rehearsal_evidence(evidence) == []
        assert evidence["first_attempt_response_status"] == 503
        assert evidence["final_response_status"] == 200
        assert evidence["receiver_unique_accept_count"] == 1
        assert evidence["receiver_duplicate_count"] == 1

        bundle = build_lineage_delivery_bundle()
        engine = create_engine(database_url)
        gateway = PlatformGateway(engine)
        stored = gateway.get_metadata_fabric_lineage_delivery(
            bundle.delivery.tenant_id,
            bundle.delivery.delivery_id,
        )
        assert stored.status.value == "delivered"
        assert stored.attempt_count == 2
        assert gateway.claim_metadata_fabric_lineage(
            bundle.delivery.tenant_id,
            WORKER_ID,
            actor_subject=bundle.delivery.actor_subject,
        ) == []
        replay = gateway.enqueue_metadata_fabric_lineage(
            bundle.delivery,
            source_plan=bundle.source_plan,
        )
        assert replay.created is False
        assert replay.value == stored

        with pytest.raises(GatewayNotFoundError):
            gateway.get_metadata_fabric_lineage_delivery(
                "isolated-tenant",
                bundle.delivery.delivery_id,
            )
        wrong_source = bundle.source_plan.model_copy(
            update={
                "resource_version_id": bundle.source_plan.source_resource_version_id
            }
        )
        with pytest.raises(GatewayValidationError, match="content-bound"):
            gateway.enqueue_metadata_fabric_lineage(
                bundle.delivery,
                source_plan=wrong_source,
            )

        with gateway._transaction(bundle.delivery.tenant_id) as connection:
            for statement in (
                """
                UPDATE gda_control.metadata_fabric_lineage_outbox
                SET attempt_count = attempt_count + 1
                WHERE delivery_id = :delivery_id
                """,
                """
                DELETE FROM gda_control.metadata_fabric_lineage_outbox
                WHERE delivery_id = :delivery_id
                """,
            ):
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        connection.execute(
                            text(statement),
                            {"delivery_id": bundle.delivery.delivery_id},
                        )
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temporary_database(admin_engine, database_name)
