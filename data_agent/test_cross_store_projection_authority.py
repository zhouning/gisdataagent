from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from data_agent.cross_store_projection_authority import (
    CROSS_STORE_PROJECTION_AUTHORITY_MIGRATION,
    PostgresProjectionCheckpointAuthority,
    ProjectionCheckpointAuthorityConfigurationError,
    ProjectionCheckpointAuthorityValidationError,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionCheckpoint,
    ProjectionEngine,
    projection_checkpoint_fingerprint,
)


def _checkpoint(**overrides) -> ProjectionCheckpoint:
    values = {
        "tenant_id": "cq-authority-test",
        "projection_id": "cq.land_parcel",
        "source_resource_version_ref": "gda://cq-authority-test/data_product/land-v1",
        "source_content_sha256": "a" * 64,
        "target_engine": ProjectionEngine.POSTGIS,
        "target_ref": "postgis://cq-db/public.land_parcel_current",
        "target_exists": True,
        "target_content_sha256": "b" * 64,
        "target_row_count": 455,
        "checkpoint_version": 1,
        "target_commit_ref": {
            "provider": "postgis",
            "plan_sha256": "c" * 64,
            "idempotency_key": "d" * 64,
        },
        "updated_by": "workload:projection-publisher",
        "updated_at": datetime(2026, 8, 15, 0, 0, tzinfo=UTC),
    }
    values.update(overrides)
    values["checkpoint_sha256"] = projection_checkpoint_fingerprint(**values)
    return ProjectionCheckpoint(**values)


def test_migration_exposes_only_controlled_append_path() -> None:
    migration = CROSS_STORE_PROJECTION_AUTHORITY_MIGRATION.read_text(encoding="utf-8")

    assert "cross_store_projection_checkpoint_history" in migration
    assert "cross_store_projection_checkpoint_current" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET row_security = on" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "USING (tenant_id = gda_control.current_tenant())" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "gda_control.reject_immutable_mutation()" in migration
    assert (
        "REVOKE ALL ON TABLE gda_control.cross_store_projection_checkpoint_history"
        in migration
    )
    assert (
        "GRANT SELECT ON TABLE gda_control.cross_store_projection_checkpoint_history"
        in migration
    )
    assert "GRANT INSERT" not in migration
    assert "p_previous_checkpoint_sha256" in migration
    assert "v_current.checkpoint_version + 1" in migration
    assert "p_target_commit_ref ->> 'plan_sha256'" in migration
    assert "p_target_commit_ref ->> 'idempotency_key'" in migration
    assert "target_content_sha256 IS NOT NULL" in migration
    assert "p_previous_checkpoint_sha256 IS NULL" in migration


def test_repository_requires_postgresql() -> None:
    authority = PostgresProjectionCheckpointAuthority(create_engine("sqlite://"))

    with pytest.raises(
        ProjectionCheckpointAuthorityConfigurationError,
        match="requires PostgreSQL",
    ):
        authority.current(
            tenant_id="cq-authority-test",
            projection_id="cq.land_parcel",
            target_engine=ProjectionEngine.POSTGIS,
            target_ref="postgis://cq-db/public.land_parcel_current",
        )


def test_repository_rejects_unbound_target_commit_before_database_access() -> None:
    checkpoint = _checkpoint(target_commit_ref={"provider": "postgis"})

    with pytest.raises(
        ProjectionCheckpointAuthorityValidationError,
        match="repair plan fingerprint",
    ):
        PostgresProjectionCheckpointAuthority().record(checkpoint)


def test_stored_checkpoint_projection_removes_authority_only_columns() -> None:
    checkpoint = _checkpoint()
    document = checkpoint.model_dump(mode="json") | {
        "repair_plan_sha256": "c" * 64,
        "plan_idempotency_key": "d" * 64,
        "previous_checkpoint_sha256": None,
    }

    restored = PostgresProjectionCheckpointAuthority._checkpoint_from_document(document)

    assert restored == checkpoint


def test_history_query_identity_is_validated_before_database_access() -> None:
    authority = PostgresProjectionCheckpointAuthority()

    with pytest.raises(
        ProjectionCheckpointAuthorityValidationError,
        match="projection_id",
    ):
        authority.history(
            tenant_id="cq-authority-test",
            projection_id="bad projection",
            target_engine=ProjectionEngine.POSTGIS,
            target_ref="postgis://cq-db/public.land_parcel_current",
        )
