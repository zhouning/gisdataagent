import os

import pytest
from sqlalchemy import create_engine, text

from data_agent.migration_runner import discover_migrations
from scripts.certify_gis_service_control_plane import certify

DATABASE_URL = os.environ.get("DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is not configured")
def test_postgres_gis_service_control_plane_certification():
    engine = create_engine(DATABASE_URL)
    try:
        with engine.connect() as connection:
            is_superuser = connection.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            ).scalar_one()
        if not is_superuser:
            pytest.skip("GIS service certification requires a PostgreSQL superuser")
    finally:
        engine.dispose()

    report = certify(DATABASE_URL)
    assert report["status"] == "passed"
    assert report["authority"]["inactive_product_source_rejected"] is True
    assert report["authority"]["mixed_layer_style_rejected"] is True
    assert report["authority"]["deployment_without_release_rejected"] is True
    assert report["authority"]["cache_policy_created"] is True
    assert report["authority"]["service_policy_created"] is True
    assert report["authority"]["unapproved_service_consumer_grant_rejected"] is True
    assert report["authority"]["pending_service_consumer_grant_rejected"] is True
    assert report["authority"]["approved_service_consumer_grant_created"] is True
    assert report["authority"]["service_consumer_grant_replay_created"] is False
    assert report["authority"]["service_consumer_approval_payload_mismatch_rejected"] is True
    assert report["authority"]["active_binding_before_renewal"] is True
    assert report["authority"]["pending_service_consumer_renewal_rejected"] is True
    assert report["authority"]["approved_service_consumer_renewal_created"] is True
    assert report["authority"]["service_consumer_renewal_replay_created"] is False
    assert report["authority"]["renewal_decision_identity_rejected"] is True
    assert report["authority"]["active_binding_after_renewal_is_target"] is True
    assert report["authority"]["pending_service_consumer_revoke_rejected"] is True
    assert report["authority"]["approved_service_consumer_revoke_created"] is True
    assert report["authority"]["service_consumer_revoke_replay_created"] is False
    assert report["authority"]["service_consumer_revoke_payload_mismatch_rejected"] is True
    assert report["authority"]["active_binding_after_revoke"] is False
    assert report["authority"]["vector_tile_without_cache_rejected"] is True
    assert report["authority"]["serving_projection_created"] is True
    assert report["authority"]["serving_projection_replay_created"] is False
    assert report["authority"]["mismatched_source_hash_rejected"] is True
    assert report["authority"]["vector_tile_without_serving_projection_rejected"] is True
    assert report["authority"]["generic_deployment_observation_rejected"] is True
    assert report["authority"]["legacy_observation_rejected_for_ready"] is True
    assert report["authority"]["failed_settlement_rolled_back"] is True
    assert report["authority"]["deployment_settlement_created"] is True
    assert report["authority"]["deployment_settlement_replay_created"] is False
    assert report["authority"]["endpoint_uri_mismatch_rejected"] is True
    assert report["security"]["gateway_control_projection_privileges"] == [True] * 15
    assert report["counts"]["cache_policies"] == 1
    assert report["counts"]["service_policies"] == 1
    assert report["counts"]["service_consumer_bindings"] == 2
    assert report["counts"]["service_consumer_binding_revocations"] == 1
    assert report["counts"]["service_consumer_binding_renewals"] == 1
    assert report["security"]["service_consumer_binding_privileges"] == [
        True,
        False,
        False,
        True,
    ]
    assert report["security"]["service_consumer_binding_revocation_privileges"] == [
        True,
        False,
        True,
    ]
    assert report["security"]["service_consumer_binding_renewal_privileges"] == [
        True,
        False,
        True,
    ]
    assert report["counts"]["serving_projections"] == 1
    assert report["authority"]["active_pointer_versions"] == [1, 2, 3]
    assert report["counts"]["release_bindings"] == 1
    assert report["security"]["cross_tenant_rows"] == 0
    migrations = discover_migrations()
    assert report["migration_catalog"]["latest"] == migrations[-1].migration_id
    assert any(
        item.migration_id == "154_gis_service_release_binding" for item in migrations
    )
    assert any(
        item.migration_id == "203_gis_service_cache_policy_authority"
        for item in migrations
    )
    assert any(
        item.migration_id == "204_gis_service_policy_binding" for item in migrations
    )
    assert any(
        item.migration_id == "205_gis_mvt_serving_projection" for item in migrations
    )
    assert any(
        item.migration_id == "206_gis_mvt_serving_projection_hardening"
        for item in migrations
    )
    assert any(
        item.migration_id == "207_gis_service_deployment_observation_hardening"
        for item in migrations
    )
    assert any(
        item.migration_id == "208_gis_service_endpoint_readiness_binding"
        for item in migrations
    )
    assert any(
        item.migration_id == "209_gis_service_gateway_privilege_repair"
        for item in migrations
    )
    assert any(
        item.migration_id == "210_gis_mvt_postgis_function_schema"
        for item in migrations
    )
    assert any(
        item.migration_id == "211_gis_mvt_postgis_operator_schema"
        for item in migrations
    )
    assert any(
        item.migration_id == "212_gis_service_consumer_binding"
        for item in migrations
    )
    assert any(
        item.migration_id == "213_gis_service_consumer_binding_approval"
        for item in migrations
    )
    assert any(
        item.migration_id == "214_gis_service_consumer_binding_revocation"
        for item in migrations
    )
    assert any(
        item.migration_id == "215_gis_service_consumer_binding_renewal"
        for item in migrations
    )
    assert any(
        item.migration_id == "216_gis_service_consumer_binding_renewal_decision_guard"
        for item in migrations
    )
