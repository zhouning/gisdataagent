import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from data_agent.metadata_fabric_active_metadata_authorization import (
    run_local_rehearsal,
)
from data_agent.spatial_dataset_bundle import build_shapefile_bundle_inventory

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
            pytest.skip("Active Metadata authorization test requires a superuser")
        database_name = f"gda_active_authorization_{uuid4().hex}"
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


def _inventory(tmp_path: Path) -> dict:
    stem = tmp_path / "districts"
    for suffix, content in (
        (".shp", b"shape"),
        (".shx", b"index"),
        (".dbf", b"attributes"),
        (".prj", b"crs"),
        (".cpg", b"UTF-8"),
    ):
        stem.with_suffix(suffix).write_bytes(content)
    return build_shapefile_bundle_inventory(
        stem.with_suffix(".shp"), source_label="postgres-golden-slice"
    )


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_authorization_and_dispatch_are_atomic_fail_closed_and_idempotent(tmp_path):
    admin_engine, database_name, database_url = _temporary_database_url()
    try:
        evidence = run_local_rehearsal(database_url, _inventory(tmp_path))

        assert evidence["local_postgresql_authorization_dispatch_verified"] is True
        assert evidence["ordinary_dispatch_without_activation_authorization_blocked"]
        assert evidence["orphan_authorization_rollback_verified"] is True
        assert evidence["authorization_absent_after_rollback"] is True
        assert evidence["authorization_count"] == 1
        assert evidence["dispatch_command_count"] == 1
        assert evidence["dispatch_command_status"] == "pending"
        assert evidence["exact_authorization_replay_created"] is False
        assert evidence["gateway_function_only_insert_verified"] is True
        assert evidence["direct_authorization_mutation_blocked"] is True
        assert evidence["force_rls_verified"] is True
        assert evidence["provider_apply_authorized"] is False
        assert evidence["production_scheduler_submission_verified"] is False
    finally:
        _drop_temporary_database(admin_engine, database_name)
