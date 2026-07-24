from pathlib import Path

import pytest

from data_agent import migration_runner


def _migration(path: Path, version: str = "100") -> dict:
    return {
        "migration_id": path.stem,
        "version": version,
        "filename": path.name,
        "path": path,
        "checksum": migration_runner._checksum(path),
    }


def test_repository_migration_catalog_is_valid_and_deterministic():
    migrations = migration_runner.discover_migrations()

    assert migrations
    assert len({item["migration_id"] for item in migrations}) == len(migrations)
    assert migrations == sorted(migrations, key=migration_runner._migration_sort_key)
    assert migration_runner.catalog_fingerprint(migrations) == (
        migration_runner.catalog_fingerprint(migrations)
    )


def test_discovery_rejects_new_duplicate_numeric_version(tmp_path):
    (tmp_path / "100_first.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (tmp_path / "100_second.sql").write_text("SELECT 2;\n", encoding="utf-8")

    with pytest.raises(
        migration_runner.MigrationDiscoveryError,
        match="Duplicate migration versions",
    ):
        migration_runner.discover_migrations(tmp_path)


def test_discovery_rejects_filename_outside_contract(tmp_path):
    (tmp_path / "next-change.sql").write_text("SELECT 1;\n", encoding="utf-8")

    with pytest.raises(
        migration_runner.MigrationDiscoveryError,
        match="Invalid migration filenames",
    ):
        migration_runner.discover_migrations(tmp_path)


def test_discovery_rejects_deletion_from_frozen_legacy_set(tmp_path):
    (tmp_path / "011_create_semantic_metrics.sql").write_text(
        "SELECT 1;\n", encoding="utf-8"
    )

    with pytest.raises(
        migration_runner.MigrationDiscoveryError,
        match="Frozen legacy migration set was changed",
    ):
        migration_runner.discover_migrations(tmp_path)


def test_catalog_fingerprint_changes_when_sql_content_changes(tmp_path):
    path = tmp_path / "100_example.sql"
    path.write_text("SELECT 1;\n", encoding="utf-8")
    before = migration_runner.catalog_fingerprint(
        migration_runner.discover_migrations(tmp_path)
    )

    path.write_text("SELECT 2;\n", encoding="utf-8")
    after = migration_runner.catalog_fingerprint(
        migration_runner.discover_migrations(tmp_path)
    )

    assert before != after


def test_report_treats_unapplied_legacy_collision_as_pending(tmp_path):
    first_path = tmp_path / "011_create_semantic_metrics.sql"
    second_path = tmp_path / "011_create_stream_tables.sql"
    first_path.write_text("SELECT 1;\n", encoding="utf-8")
    second_path.write_text("SELECT 2;\n", encoding="utf-8")
    migrations = migration_runner.discover_migrations(tmp_path)
    first = migrations[0]

    report = migration_runner._build_schema_report(
        migrations,
        [
            {
                "migration_id": first["migration_id"],
                "version": first["version"],
                "filename": first["filename"],
                "checksum": first["checksum"],
                "applied_at": None,
            }
        ],
    )

    assert report["status"] == "pending"
    assert report["pending"] == ["011_create_stream_tables"]


def test_legacy_v14_migrations_run_after_their_dependencies():
    migrations = migration_runner.discover_migrations()
    positions = {
        migration["migration_id"]: index
        for index, migration in enumerate(migrations)
    }

    assert positions["014_workflow_checkpoints"] > positions["017_create_workflows"]
    for migration_id in (
        "013_rating_clone",
        "015_version_tags",
        "016_skill_approval",
        "017_skill_deps_webhook",
    ):
        assert positions[migration_id] > positions["021_create_custom_skills"]


class _FakeDialect:
    name = "test"


class _FakeConnection:
    dialect = _FakeDialect()

    def __init__(self, *, fail_sql: bool = False):
        self.fail_sql = fail_sql
        self.rollbacks = 0
        self.commits = 0
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=None):
        rendered = str(statement)
        self.executed.append((rendered, parameters))
        if self.fail_sql and "SELECT broken" in rendered:
            raise RuntimeError("database rejected migration")
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


def test_postgres_advisory_lock_is_released_when_body_fails():
    connection = _FakeConnection()
    connection.dialect = type("PostgresDialect", (), {"name": "postgresql"})()

    with pytest.raises(RuntimeError, match="body failed"):
        with migration_runner._migration_lock(connection):
            raise RuntimeError("body failed")

    statements = [statement for statement, _ in connection.executed]
    assert statements == [
        "SELECT pg_advisory_lock(:lock_id)",
        "SELECT pg_advisory_unlock(:lock_id)",
    ]


def test_runner_rolls_back_and_fails_closed_on_sql_error(tmp_path, monkeypatch):
    path = tmp_path / "100_broken.sql"
    path.write_text("SELECT broken;\n", encoding="utf-8")
    migrations = [_migration(path)]
    connection = _FakeConnection(fail_sql=True)

    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: migrations)
    monkeypatch.setattr(
        migration_runner, "get_engine", lambda: _FakeEngine(connection)
    )
    monkeypatch.setattr(
        migration_runner, "_ensure_migrations_table", lambda conn, catalog: None
    )
    monkeypatch.setattr(migration_runner, "_load_applied", lambda conn: [])

    with pytest.raises(
        migration_runner.MigrationExecutionError,
        match="startup is blocked",
    ):
        migration_runner.run_pending_migrations()

    assert connection.rollbacks == 1
    assert connection.commits == 0


def test_runner_blocks_applied_checksum_drift_before_sql(tmp_path, monkeypatch):
    path = tmp_path / "100_example.sql"
    path.write_text("SELECT 1;\n", encoding="utf-8")
    migration = _migration(path)
    connection = _FakeConnection()
    applied = {
        "migration_id": migration["migration_id"],
        "version": migration["version"],
        "filename": migration["filename"],
        "checksum": "0" * 64,
        "applied_at": None,
    }

    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: [migration])
    monkeypatch.setattr(
        migration_runner, "get_engine", lambda: _FakeEngine(connection)
    )
    monkeypatch.setattr(
        migration_runner, "_ensure_migrations_table", lambda conn, catalog: None
    )
    monkeypatch.setattr(migration_runner, "_load_applied", lambda conn: [applied])

    with pytest.raises(migration_runner.MigrationDriftError):
        migration_runner.run_pending_migrations()

    assert connection.executed == []


def test_environment_report_comparison_surfaces_exact_fields():
    left = {
        "status": "in_sync",
        "catalog_fingerprint": "catalog-a",
        "database_fingerprint": "database-a",
        "catalog_count": 10,
        "applied_count": 10,
    }
    right = {**left, "database_fingerprint": "database-b"}

    result = migration_runner.compare_schema_reports(left, right)

    assert result == {
        "match": False,
        "differences": {
            "database_fingerprint": {
                "left": "database-a",
                "right": "database-b",
            }
        },
    }
