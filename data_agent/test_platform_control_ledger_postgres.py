import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


DATABASE_URL = os.environ.get("DATABASE_URL")
MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "092_platform_control_ledger.sql"
)
TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
RUN_ID = "00000000-0000-4000-8000-000000000020"
DEFINITION_VERSION_ID = "00000000-0000-4000-8000-000000000010"
SOURCE_VERSION_ID = "00000000-0000-4000-8000-000000000030"
TARGET_VERSION_ID = "00000000-0000-4000-8000-000000000040"


def _assert_rejected(connection, statement: str) -> None:
    with pytest.raises(DBAPIError):
        with connection.begin_nested():
            connection.exec_driver_sql(statement)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_enforces_platform_control_ledger_contract():
    engine = create_engine(DATABASE_URL)
    role_name = f"gda_ledger_test_{uuid4().hex}"

    try:
        with engine.connect() as connection:
            is_superuser = connection.exec_driver_sql(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ).scalar_one()
            connection.rollback()
            if not is_superuser:
                pytest.skip("control ledger DDL test requires a PostgreSQL superuser")

            transaction = connection.begin()
            try:
                connection.execute(text(MIGRATION.read_text(encoding="utf-8")))
                connection.exec_driver_sql(
                    f'CREATE ROLE "{role_name}" NOLOGIN NOSUPERUSER NOBYPASSRLS'
                )

                connection.exec_driver_sql(
                    f"""
                    INSERT INTO gda_control.resource (
                        tenant_id, resource_urn, resource_kind,
                        authority_system, authority_locator, owner_ref
                    ) VALUES
                        ('{TENANT_A}', 'gda://{TENANT_A}/definition/parcel-publish',
                         'definition', 'gda', 'definition/parcel-publish', 'dataops'),
                        ('{TENANT_A}', 'gda://{TENANT_A}/dataset/source-parcels',
                         'dataset', 'iceberg', 'geo.source_parcels', 'dataops'),
                        ('{TENANT_A}', 'gda://{TENANT_A}/dataset/published-parcels',
                         'dataset', 'iceberg', 'geo.published_parcels', 'dataops'),
                        ('{TENANT_B}', 'gda://{TENANT_B}/dataset/private-parcels',
                         'dataset', 'iceberg', 'geo.private_parcels', 'dataops')
                    """
                )
                connection.exec_driver_sql(
                    f"""
                    INSERT INTO gda_control.resource_version (
                        tenant_id, resource_version_id, resource_urn,
                        version_key, content_sha256, authority_version_ref, created_by
                    ) VALUES
                        ('{TENANT_A}', '{DEFINITION_VERSION_ID}',
                         'gda://{TENANT_A}/definition/parcel-publish',
                         'v1', repeat('d', 64), '{{"revision": 1}}', 'dataops'),
                        ('{TENANT_A}', '{SOURCE_VERSION_ID}',
                         'gda://{TENANT_A}/dataset/source-parcels',
                         'snapshot-1', repeat('a', 64), '{{"snapshot": 1}}', 'dataops'),
                        ('{TENANT_A}', '{TARGET_VERSION_ID}',
                         'gda://{TENANT_A}/dataset/published-parcels',
                         'snapshot-2', repeat('b', 64), '{{"snapshot": 2}}', 'dataops')
                    """
                )
                connection.exec_driver_sql(
                    f"""
                    INSERT INTO gda_control.platform_definition_version (
                        tenant_id, definition_version_id, definition_urn,
                        orchestration_class, capability_id, portability_class,
                        definition_document, input_contract, output_contract,
                        definition_sha256
                    ) VALUES (
                        '{TENANT_A}', '{DEFINITION_VERSION_ID}',
                        'gda://{TENANT_A}/definition/parcel-publish',
                        'dataops', 'land_use.publish', 'portable',
                        '{{"tasks": ["publish"]}}', '{{"source": "dataset"}}',
                        '{{"product": "dataset"}}', repeat('d', 64)
                    )
                    """
                )
                connection.exec_driver_sql(
                    f"""
                    INSERT INTO gda_control.platform_run (
                        tenant_id, run_id, definition_version_id,
                        orchestration_class, subject_context, idempotency_key,
                        submitted_by
                    ) VALUES (
                        '{TENANT_A}', '{RUN_ID}', '{DEFINITION_VERSION_ID}',
                        'dataops',
                        '{{"tenant_id":"{TENANT_A}","subject_id":"dataops",'
                        '"subject_type":"workload","roles":["dataops"],'
                        '"purpose":"contract-test"}}',
                        'contract-test-run', 'workload:dataops'
                    )
                    """
                )

                initial_event = connection.exec_driver_sql(
                    f"""
                    SELECT sequence_no, from_status, to_status
                    FROM gda_control.platform_run_event
                    WHERE run_id = '{RUN_ID}'
                    """
                ).one()
                assert initial_event == (0, None, "accepted")

                _assert_rejected(
                    connection,
                    f"""
                    INSERT INTO gda_control.platform_run (
                        tenant_id, run_id, definition_version_id,
                        orchestration_class, subject_context, idempotency_key,
                        submitted_by
                    ) VALUES (
                        '{TENANT_A}', '00000000-0000-4000-8000-000000000021',
                        '{DEFINITION_VERSION_ID}', 'dataops',
                        '{{"tenant_id":"{TENANT_A}","subject_id":"dataops",'
                        '"subject_type":"workload","roles":[]}}',
                        'missing-purpose', 'workload:dataops'
                    )
                    """,
                )
                _assert_rejected(
                    connection,
                    f"""
                    INSERT INTO gda_control.resource_version (
                        tenant_id, resource_version_id, resource_urn, version_key,
                        predecessor_version_id, content_sha256,
                        authority_version_ref, created_by
                    ) VALUES (
                        '{TENANT_B}', '00000000-0000-4000-8000-000000000041',
                        'gda://{TENANT_B}/dataset/private-parcels', 'snapshot-1',
                        '{SOURCE_VERSION_ID}', repeat('c', 64), '{{"snapshot": 1}}',
                        'dataops'
                    )
                    """,
                )
                _assert_rejected(
                    connection,
                    f"UPDATE gda_control.platform_run SET status = 'running', "
                    f"state_version = 1 WHERE run_id = '{RUN_ID}'",
                )
                _assert_rejected(
                    connection,
                    f"UPDATE gda_control.resource_version SET version_key = 'changed' "
                    f"WHERE resource_version_id = '{SOURCE_VERSION_ID}'",
                )
                _assert_rejected(
                    connection,
                    f"""
                    INSERT INTO gda_control.artifact (
                        tenant_id, artifact_key, artifact_role, storage_uri,
                        media_type, content_sha256, size_bytes, run_id, created_by
                    ) VALUES (
                        '{TENANT_B}', 'cross-tenant', 'output', 's3://bucket/key',
                        'application/octet-stream', repeat('e', 64), 1,
                        '{RUN_ID}', 'dataops'
                    )
                    """,
                )
                _assert_rejected(
                    connection,
                    f"""
                    INSERT INTO gda_control.artifact (
                        tenant_id, artifact_key, artifact_role, storage_uri,
                        media_type, content_sha256, size_bytes, run_id, created_by
                    ) VALUES (
                        '{TENANT_A}', 'unsafe-uri', 'output', 'file://relative/key',
                        'application/octet-stream', repeat('e', 64), 1,
                        '{RUN_ID}', 'dataops'
                    )
                    """,
                )

                connection.exec_driver_sql(
                    f'GRANT USAGE ON SCHEMA gda_control TO "{role_name}"'
                )
                connection.exec_driver_sql(
                    f'GRANT SELECT ON ALL TABLES IN SCHEMA gda_control TO "{role_name}"'
                )
                connection.exec_driver_sql(
                    f"GRANT EXECUTE ON FUNCTION gda_control.current_tenant() "
                    f'TO "{role_name}"'
                )
                connection.exec_driver_sql(
                    f"GRANT EXECUTE ON FUNCTION gda_control.transition_platform_run("
                    f"text, uuid, integer, text, text, text, jsonb) TO \"{role_name}\""
                )
                connection.exec_driver_sql(
                    f"SET LOCAL app.current_tenant = '{TENANT_A}'"
                )
                connection.exec_driver_sql(f'SET LOCAL ROLE "{role_name}"')

                version = connection.exec_driver_sql(
                    f"""
                    SELECT gda_control.transition_platform_run(
                        '{TENANT_A}', '{RUN_ID}', 0, 'dispatching',
                        'workload:dataops', 'accepted by provider', '{{}}'
                    )
                    """
                ).scalar_one()
                assert version == 1
                _assert_rejected(
                    connection,
                    f"""
                    SELECT gda_control.transition_platform_run(
                        '{TENANT_B}', '{RUN_ID}', 1, 'running',
                        'workload:dataops', 'wrong tenant', '{{}}'
                    )
                    """,
                )
                connection.exec_driver_sql("RESET ROLE")

                _assert_rejected(
                    connection,
                    f"""
                    SELECT gda_control.transition_platform_run(
                        '{TENANT_A}', '{RUN_ID}', 0, 'running',
                        'workload:dataops', 'stale state', '{{}}'
                    )
                    """,
                )
                _assert_rejected(
                    connection,
                    f"""
                    SELECT gda_control.transition_platform_run(
                        '{TENANT_A}', '{RUN_ID}', 1, 'succeeded',
                        'workload:dataops', 'invalid skip', '{{}}'
                    )
                    """,
                )
                assert connection.exec_driver_sql(
                    f"""
                    SELECT gda_control.transition_platform_run(
                        '{TENANT_A}', '{RUN_ID}', 1, 'running',
                        'workload:dataops', 'provider running', '{{}}'
                    )
                    """
                ).scalar_one() == 2
                assert connection.exec_driver_sql(
                    f"""
                    SELECT gda_control.transition_platform_run(
                        '{TENANT_A}', '{RUN_ID}', 2, 'succeeded',
                        'workload:dataops', 'artifacts verified', '{{}}'
                    )
                    """
                ).scalar_one() == 3
                _assert_rejected(
                    connection,
                    f"""
                    SELECT gda_control.transition_platform_run(
                        '{TENANT_A}', '{RUN_ID}', 3, 'running',
                        'workload:dataops', 'terminal restart', '{{}}'
                    )
                    """,
                )

                connection.exec_driver_sql(
                    f"""
                    INSERT INTO gda_control.framework_attempt_observation (
                        tenant_id, run_id, attempt_no, framework_kind,
                        external_namespace, external_run_id, observed_state,
                        observation_sha256, observed_at
                    ) VALUES (
                        '{TENANT_A}', '{RUN_ID}', 1, 'dolphinscheduler',
                        'project-a', 'provider-run-1', 'SUCCESS', repeat('f', 64), now()
                    )
                    """
                )
                run_state = connection.exec_driver_sql(
                    f"SELECT status, state_version FROM gda_control.platform_run "
                    f"WHERE run_id = '{RUN_ID}'"
                ).one()
                assert run_state == ("succeeded", 3)
                assert connection.exec_driver_sql(
                    f"SELECT count(*) FROM gda_control.platform_run_event "
                    f"WHERE run_id = '{RUN_ID}'"
                ).scalar_one() == 4

                connection.exec_driver_sql(f'SET LOCAL ROLE "{role_name}"')
                connection.exec_driver_sql("SET LOCAL app.current_tenant = ''")
                assert connection.exec_driver_sql(
                    "SELECT count(*) FROM gda_control.resource"
                ).scalar_one() == 0
                connection.exec_driver_sql(
                    f"SET LOCAL app.current_tenant = '{TENANT_A}'"
                )
                assert connection.exec_driver_sql(
                    "SELECT count(*) FROM gda_control.resource"
                ).scalar_one() == 3
                connection.exec_driver_sql(
                    f"SET LOCAL app.current_tenant = '{TENANT_B}'"
                )
                assert connection.exec_driver_sql(
                    "SELECT count(*) FROM gda_control.resource"
                ).scalar_one() == 1
                connection.exec_driver_sql("RESET ROLE")
            finally:
                if connection.in_transaction():
                    transaction.rollback()
    finally:
        engine.dispose()
