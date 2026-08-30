from pathlib import Path

from data_agent.grid_anonymize import (
    grid_anonymize_pg,
    poi_grid_aggregate_pg,
    verify_anonymization,
)

MIGRATION = (
    Path(__file__).parent / "migrations" / "109_data_asset_security_boundary.sql"
)


def test_migration_forces_rls_and_separates_read_from_write_policies():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "DROP POLICY IF EXISTS assets_isolation" in sql
    assert sql.count("CREATE POLICY agent_data_assets_") == 4
    assert "CREATE POLICY agent_data_assets_select" in sql
    assert "OR is_shared = TRUE" in sql

    update_policy = sql.split("CREATE POLICY agent_data_assets_update", 1)[1]
    update_policy = update_policy.split("CREATE POLICY agent_data_assets_delete", 1)[0]
    assert "is_shared" not in update_policy


def test_grid_anonymization_rejects_unsafe_identifiers_before_database_access():
    result = grid_anonymize_pg(
        source_table='roads"; DROP TABLE agent_data_assets; --',
        output_table="roads_grid",
    )

    assert result["status"] == "error"
    assert "identifier" in result["message"]


def test_poi_anonymization_rejects_unsafe_category_column():
    result = poi_grid_aggregate_pg(
        source_table="poi",
        output_table="poi_grid",
        category_column='kind" FROM poi; --',
    )

    assert result["status"] == "error"
    assert "category_column" in result["message"]


def test_anonymization_verification_rejects_unsafe_output_table():
    result = verify_anonymization(
        source_table="roads",
        output_table="roads_grid; SELECT 1",
    )

    assert result["status"] == "error"
    assert "output_table" in result["message"]
