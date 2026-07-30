import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from data_agent.active_metadata_change_contract import (
    build_active_metadata_registration,
    build_metadata_activation_intent,
    build_metadata_activation_request,
)
from data_agent.active_metadata_consumer import ActiveMetadataConsumer
from data_agent.metadata_fabric_active_metadata_outbox import (
    CONSUMER_SUBJECT,
    TENANT,
    WORKER_1,
    WORKER_2,
    build_active_metadata_bundle,
)
from data_agent.platform_gateway import (
    GatewayNotFoundError,
    GatewayValidationError,
    PlatformGateway,
)

DATABASE_URL = os.environ.get("DATABASE_URL")
MIGRATIONS = tuple(
    Path(__file__).resolve().parent / "migrations" / filename
    for filename in (
        "092_platform_control_ledger.sql",
        "093_app_user_tenant_context.sql",
        "094_platform_control_gateway.sql",
        "099_active_metadata_change_outbox.sql",
        "100_active_metadata_activation_request.sql",
    )
)


def _temporary_database_url() -> tuple[object, str, str]:
    admin_url = make_url(DATABASE_URL)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        is_superuser = connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one()
        if not is_superuser:
            admin_engine.dispose()
            pytest.skip("Active Metadata consumer test requires a superuser")
        database_name = f"gda_active_consumer_{uuid4().hex}"
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


def _apply_migrations(engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS agent_app_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL
            )
            """
        )
        for migration in MIGRATIONS:
            connection.execute(text(migration.read_text(encoding="utf-8")))


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_consumer_stages_request_atomically_and_fail_closed():
    admin_engine, database_name, database_url = _temporary_database_url()
    engine = create_engine(database_url)
    try:
        _apply_migrations(engine)
        gateway = PlatformGateway(engine)
        bundle = build_active_metadata_bundle()
        gateway.register_resource(bundle.resource)
        gateway.register_resource_version_with_metadata_event(
            bundle.registration,
            max_attempts=3,
        )
        claimed = gateway.claim_metadata_changes(
            TENANT,
            WORKER_1,
            consumer_subject=CONSUMER_SUBJECT,
            lease_seconds=60,
        )
        assert len(claimed) == 1
        intent = build_metadata_activation_intent(
            claimed[0].event,
            routed_by=CONSUMER_SUBJECT,
        )
        request = build_metadata_activation_request(intent)

        with pytest.raises(
            GatewayValidationError,
            match="platform contract was rejected",
        ):
            gateway.complete_metadata_change(
                TENANT,
                claimed[0].event.event_id,
                worker_id=WORKER_1,
                activation_intent=intent,
            )
        still_claimed = gateway.get_metadata_change_delivery(
            TENANT,
            claimed[0].event.event_id,
        )
        assert still_claimed.status.value == "in_flight"

        first = gateway.stage_metadata_activation_request(
            TENANT,
            claimed[0].event.event_id,
            worker_id=WORKER_1,
            request=request,
        )
        replay = gateway.stage_metadata_activation_request(
            TENANT,
            claimed[0].event.event_id,
            worker_id=WORKER_1,
            request=request,
        )
        assert first.created is True
        assert replay.created is False
        assert replay.value == request
        assert gateway.get_metadata_activation_request(
            TENANT,
            request.request_id,
        ) == request
        completed = gateway.get_metadata_change_delivery(
            TENANT,
            claimed[0].event.event_id,
        )
        assert completed.status.value == "processed"
        assert completed.activation_intent_sha256 == intent.intent_sha256

        next_version = bundle.registration.resource_version.model_copy(
            update={
                "resource_version_id": UUID(
                    "a4000000-0000-4000-8000-000000000003"
                ),
                "version_key": "snapshot-2",
                "predecessor_version_id": (
                    bundle.registration.resource_version.resource_version_id
                ),
                "content_sha256": "c" * 64,
                "authority_version_ref": {"snapshot_id": 2},
            }
        )
        next_registration = build_active_metadata_registration(
            next_version,
            consumer_subject=CONSUMER_SUBJECT,
        )
        gateway.register_resource_version_with_metadata_event(
            next_registration,
            max_attempts=3,
        )
        result = ActiveMetadataConsumer(
            gateway,
            consumer_subject=CONSUMER_SUBJECT,
        ).run_once(
            TENANT,
            worker_id=WORKER_2,
            limit=1,
            lease_seconds=60,
        )
        assert result.claimed == result.staged == 1
        assert result.replayed == result.retry_pending == result.failed == 0

        with pytest.raises(GatewayNotFoundError):
            gateway.get_metadata_activation_request(
                "active-metadata-isolated",
                request.request_id,
            )

        with engine.connect() as connection:
            privileges = connection.exec_driver_sql(
                """
                SELECT
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_request',
                        'SELECT,INSERT'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_request', 'UPDATE'
                    ),
                    has_table_privilege(
                        'gda_control_gateway',
                        'gda_control.metadata_activation_request', 'DELETE'
                    ),
                    has_function_privilege(
                        'gda_control_gateway',
                        'gda_control.stage_metadata_activation_request(text,uuid,text,jsonb)',
                        'EXECUTE'
                    )
                """
            ).one()
            assert privileges == (True, False, False, True)

        with gateway._transaction(TENANT) as connection:
            for statement in (
                """
                UPDATE gda_control.metadata_activation_request
                SET status = 'awaiting_authorization'
                WHERE request_id = :request_id
                """,
                """
                DELETE FROM gda_control.metadata_activation_request
                WHERE request_id = :request_id
                """,
            ):
                with pytest.raises(DBAPIError):
                    with connection.begin_nested():
                        connection.execute(text(statement), {"request_id": request.request_id})

        with engine.connect() as connection:
            request_count = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM gda_control.metadata_activation_request"
            ).scalar_one()
            processed_count = connection.exec_driver_sql(
                """
                SELECT COUNT(*)
                FROM gda_control.metadata_change_outbox
                WHERE status = 'processed'
                """
            ).scalar_one()
        assert request_count == processed_count == 2
    finally:
        engine.dispose()
        _drop_temporary_database(admin_engine, database_name)
