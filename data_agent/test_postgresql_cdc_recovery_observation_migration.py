"""Static contract checks for the durable CDC recovery observation authority."""

from __future__ import annotations

from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "147_postgresql_cdc_recovery_observation.sql"
)


def test_recovery_observation_migration_is_append_only_and_tenant_scoped() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    required = (
        "CREATE TABLE IF NOT EXISTS gda_control.postgresql_cdc_recovery_observation",
        "FOREIGN KEY (artifact_id)",
        "source_sync_definition",
        "platform_run",
        "record_postgresql_cdc_recovery_observation(",
        "SECURITY DEFINER",
        "SET row_security = on",
        "ON CONFLICT DO NOTHING",
        "guard_postgresql_cdc_recovery_observation_insert",
        "reject_immutable_mutation()",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "USING (tenant_id = gda_control.current_tenant())",
        "WITH CHECK (tenant_id = gda_control.current_tenant())",
        "REVOKE ALL ON TABLE gda_control.postgresql_cdc_recovery_observation",
        "GRANT SELECT ON TABLE gda_control.postgresql_cdc_recovery_observation",
        "GRANT EXECUTE ON FUNCTION gda_control.record_postgresql_cdc_recovery_observation",
    )
    missing = [marker for marker in required if marker not in sql]
    assert not missing, f"migration contract markers missing: {missing}"


def test_recovery_observation_migration_does_not_grant_direct_gateway_writes() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "GRANT INSERT ON TABLE gda_control.postgresql_cdc_recovery_observation" not in sql
    assert "GRANT UPDATE ON TABLE gda_control.postgresql_cdc_recovery_observation" not in sql
    assert "GRANT DELETE ON TABLE gda_control.postgresql_cdc_recovery_observation" not in sql
