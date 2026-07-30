import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from data_agent.metadata_fabric_active_metadata_outbox import (
    CONSUMER_SUBJECT,
    TENANT,
    build_active_metadata_bundle,
    run_local_rehearsal,
    validate_rehearsal_evidence,
)
from data_agent.platform_gateway import GatewayNotFoundError, PlatformGateway


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
            pytest.skip("Active Metadata test requires a PostgreSQL superuser")
        database_name = f"gda_active_metadata_{uuid4().hex}"
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
def test_postgres_active_metadata_outbox_is_atomic_scoped_and_retryable():
    admin_engine, database_name, database_url = _temporary_database_url()
    engine = None
    try:
        evidence = run_local_rehearsal(database_url)

        assert validate_rehearsal_evidence(evidence) == []
        assert evidence["first_registration_created"] is True
        assert evidence["exact_replay_created"] is False
        assert evidence["final_attempt_count"] == 3
        assert evidence["legacy_backfill_blocked"] is True
        assert evidence["authoritative_event_count"] == 1

        bundle = build_active_metadata_bundle()
        engine = create_engine(database_url)
        gateway = PlatformGateway(engine)
        stored = gateway.get_metadata_change_delivery(
            TENANT,
            bundle.registration.event.event_id,
        )
        assert stored.status.value == "processed"
        assert gateway.claim_metadata_changes(
            TENANT,
            "worker:post-test",
            consumer_subject=CONSUMER_SUBJECT,
        ) == []
        with pytest.raises(GatewayNotFoundError):
            gateway.get_metadata_change_delivery(
                "active-metadata-isolated",
                bundle.registration.event.event_id,
            )

        with gateway._transaction(TENANT) as connection:
            for statement in (
                """
                UPDATE gda_control.metadata_change_outbox
                SET attempt_count = attempt_count + 1
                WHERE event_id = :event_id
                """,
                """
                DELETE FROM gda_control.metadata_change_outbox
                WHERE event_id = :event_id
                """,
            ):
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        connection.execute(
                            text(statement),
                            {"event_id": bundle.registration.event.event_id},
                        )
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temporary_database(admin_engine, database_name)
