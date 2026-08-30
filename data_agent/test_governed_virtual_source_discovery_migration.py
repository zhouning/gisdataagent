from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parent
    / "migrations"
    / "182_governed_virtual_source_discovery.sql"
)


def test_virtual_source_discovery_migration_is_secret_free_and_durable() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    for column in (
        "credential_reference",
        "source_definition",
        "discovery_snapshot",
        "discovery_fingerprint",
        "profile_snapshot",
        "profile_fingerprint",
        "last_discovery_at",
        "discovery_status",
    ):
        assert column in sql
    assert "ADD COLUMN IF NOT EXISTS password" not in sql
    assert "ADD COLUMN IF NOT EXISTS token" not in sql
    assert "contains_source_rows" not in sql
