import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from data_agent import metadata_fabric_real_feature_ledger_promotion as promotion
from data_agent.platform_gateway import GatewayConflictError, PlatformGateway

DATABASE_URL = os.environ.get("DATABASE_URL")


def _temporary_database_url(prefix: str) -> tuple[object, str, str]:
    admin_url = make_url(DATABASE_URL)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        if not connection.exec_driver_sql(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).scalar_one():
            admin_engine.dispose()
            pytest.skip("M3-23 PostgreSQL test requires a superuser")
        database_name = f"{prefix}_{uuid4().hex}"
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
def test_real_m3_22_candidates_promote_atomically_on_fresh_postgres():
    admin_engine, database_name, database_url = _temporary_database_url(
        "gda_real_feature_promotion"
    )
    try:
        evidence = promotion.run_postgres_rehearsal(database_url)

        assert promotion.validate_rehearsal_evidence(evidence) == []
        assert evidence["first_promotion_created"] is True
        assert evidence["replay_promotion_created"] is False
        assert evidence["failure_injection_rollback_verified"] is True
        assert evidence["candidate_row_counts"] == {
            "resource_versions": 1,
            "artifacts": 2,
            "quality_results": 1,
            "lineage_events": 1,
        }
        assert evidence["platform_run_status"] == "accepted"
        assert evidence["success_finalization_rejected"] is True
        assert evidence["promotion_persisted_to_gda_control"] is True
        assert evidence["platform_run_succeeded"] is False
    finally:
        _drop_temporary_database(admin_engine, database_name)


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_partial_preexisting_promotion_is_rejected_without_new_rows():
    admin_engine, database_name, database_url = _temporary_database_url(
        "gda_partial_real_feature_promotion"
    )
    engine = None
    try:
        source = json.loads(
            promotion.DEFAULT_SOURCE_EVIDENCE_PATH.read_text(encoding="utf-8")
        )
        bundle = promotion.build_promotion(source)
        prerequisites = promotion.build_prerequisites(source, bundle)
        engine = create_engine(database_url)
        promotion._apply_migrations(engine)
        gateway = PlatformGateway(engine)
        promotion._register_prerequisites(
            gateway,
            prerequisites,
            include_output_authority=True,
        )
        gateway.register_resource_version(bundle.output_resource_version)

        with pytest.raises(
            GatewayConflictError,
            match="partial pre-existing state",
        ):
            promotion.RunOutputLedgerPromoter(gateway).promote(bundle)

        assert promotion._candidate_counts(engine, bundle) == {
            "resource_versions": 1,
            "artifacts": 0,
            "quality_results": 0,
            "lineage_events": 0,
        }
        assert gateway.get_run(promotion.TENANT, promotion.RUN_ID).status.value == (
            "accepted"
        )
    finally:
        if engine is not None:
            engine.dispose()
        _drop_temporary_database(admin_engine, database_name)
