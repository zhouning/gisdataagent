import ast
from pathlib import Path

import pytest

from data_agent import migration_runner


def _migration(path: Path, version: str = "100") -> migration_runner.Migration:
    return migration_runner.Migration(
        migration_id=path.stem,
        version=version,
        filename=path.name,
        path=path,
        checksum=migration_runner._checksum(path),
    )


def test_repository_catalog_is_valid_and_deterministic():
    migrations = migration_runner.discover_migrations()

    assert migrations
    assert len({item.migration_id for item in migrations}) == len(migrations)
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


def test_discovery_rejects_changed_frozen_legacy_set(tmp_path):
    (tmp_path / "011_create_semantic_metrics.sql").write_text(
        "SELECT 1;\n", encoding="utf-8"
    )

    with pytest.raises(
        migration_runner.MigrationDiscoveryError,
        match="Frozen legacy migration set was changed",
    ):
        migration_runner.discover_migrations(tmp_path)


def test_discovery_accepts_frozen_parallel_092_histories(tmp_path):
    (tmp_path / "092_platform_control_ledger.sql").write_text(
        "SELECT 1;\n", encoding="utf-8"
    )
    (tmp_path / "092_std_application_mapping_contract.sql").write_text(
        "SELECT 2;\n", encoding="utf-8"
    )

    migrations = migration_runner.discover_migrations(tmp_path)

    assert [migration.migration_id for migration in migrations] == [
        "092_platform_control_ledger",
        "092_std_application_mapping_contract",
    ]


def test_discovery_rejects_third_092_history(tmp_path):
    for filename in (
        "092_platform_control_ledger.sql",
        "092_std_application_mapping_contract.sql",
        "092_unapproved.sql",
    ):
        (tmp_path / filename).write_text("SELECT 1;\n", encoding="utf-8")

    with pytest.raises(
        migration_runner.MigrationDiscoveryError,
        match="Frozen legacy migration set was changed",
    ):
        migration_runner.discover_migrations(tmp_path)


def test_catalog_fingerprint_changes_with_sql_content(tmp_path):
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


def test_report_is_structured_and_marks_missing_checksum_as_drift(tmp_path):
    path = tmp_path / "100_example.sql"
    path.write_text("SELECT 1;\n", encoding="utf-8")
    migration = _migration(path)

    report = migration_runner._build_schema_report(
        [migration],
        [
            {
                "migration_id": migration.migration_id,
                "version": migration.version,
                "filename": migration.filename,
                "checksum": None,
            }
        ],
        ledger_format="legacy",
    )

    assert isinstance(report, migration_runner.MigrationReport)
    assert report.status == "drift"
    assert report.missing_checksums == (migration.migration_id,)
    assert report.to_dict()["missing_checksums"] == [migration.migration_id]


def test_report_treats_second_legacy_collision_file_as_pending(tmp_path):
    first = tmp_path / "011_create_semantic_metrics.sql"
    second = tmp_path / "011_create_stream_tables.sql"
    first.write_text("SELECT 1;\n", encoding="utf-8")
    second.write_text("SELECT 2;\n", encoding="utf-8")
    migrations = migration_runner.discover_migrations(tmp_path)
    applied = migrations[0]

    report = migration_runner._build_schema_report(
        migrations,
        [
            {
                "migration_id": applied.migration_id,
                "version": applied.version,
                "filename": applied.filename,
                "checksum": applied.checksum,
            }
        ],
    )

    assert report.status == "pending"
    assert report.pending == ("011_create_stream_tables",)


def test_deferred_legacy_migrations_follow_dependencies():
    migrations = migration_runner.discover_migrations()
    positions = {
        migration.migration_id: index for index, migration in enumerate(migrations)
    }

    assert positions["014_workflow_checkpoints"] > positions["017_create_workflows"]
    for migration_id in (
        "013_rating_clone",
        "015_version_tags",
        "016_skill_approval",
        "017_skill_deps_webhook",
    ):
        assert positions[migration_id] > positions["021_create_custom_skills"]


class _Result:
    def __init__(self, scalar=True):
        self.scalar = scalar

    def scalar_one(self):
        return self.scalar


class _MappingResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row


class _IdentifierPreparer:
    @staticmethod
    def quote(identifier):
        return f'"{identifier}"'


class _Dialect:
    name = "postgresql"
    identifier_preparer = _IdentifierPreparer()


class _FakeConnection:
    dialect = _Dialect()

    def __init__(
        self,
        *,
        lock_acquired=True,
        fail_sql=False,
        role_exists=True,
        ledger_permissions=None,
    ):
        self.lock_acquired = lock_acquired
        self.fail_sql = fail_sql
        self.role_exists = role_exists
        self.ledger_permissions = ledger_permissions or {
            "can_select": True,
            "can_write": False,
            "can_use_sequence": False,
        }
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=None):
        rendered = str(statement)
        self.executed.append((rendered, parameters))
        if "pg_try_advisory_lock" in rendered:
            return _Result(self.lock_acquired)
        if "pg_advisory_unlock" in rendered:
            return _Result(True)
        if "FROM pg_roles" in rendered:
            return _Result(self.role_exists)
        if "has_table_privilege" in rendered:
            return _MappingResult(self.ledger_permissions)
        if self.fail_sql and "SELECT broken" in rendered:
            raise RuntimeError("database rejected migration")
        return _Result(True)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


def test_runtime_role_identifier_is_validated_before_database_lookup(monkeypatch):
    connection = _FakeConnection()
    monkeypatch.setenv(
        migration_runner.MIGRATION_RUNTIME_ROLE_ENV, "agent_user; DROP ROLE postgres"
    )

    with pytest.raises(migration_runner.MigrationStateError, match="identifier"):
        migration_runner._validated_runtime_role(connection)

    assert connection.executed == []


def test_missing_runtime_role_fails_closed(monkeypatch):
    connection = _FakeConnection(role_exists=False)
    monkeypatch.setenv(migration_runner.MIGRATION_RUNTIME_ROLE_ENV, "agent_user")

    with pytest.raises(migration_runner.MigrationStateError, match="does not exist"):
        migration_runner._validated_runtime_role(connection)


def test_runtime_ledger_access_revokes_broad_defaults_and_grants_only_select():
    connection = _FakeConnection()

    migration_runner._restrict_runtime_ledger_access(connection, "agent_user")

    statements = [statement for statement, _ in connection.executed]
    assert any(
        "ALTER TABLE schema_migrations OWNER TO CURRENT_USER" in statement
        for statement in statements
    )
    assert any(
        "ALTER SEQUENCE schema_migrations_id_seq OWNER TO CURRENT_USER" in statement
        for statement in statements
    )
    assert any(
        "REVOKE ALL PRIVILEGES ON TABLE schema_migrations FROM PUBLIC" in statement
        for statement in statements
    )
    assert any(
        'GRANT SELECT ON TABLE schema_migrations TO "agent_user"' in statement
        for statement in statements
    )
    assert any(
        "REVOKE ALL PRIVILEGES ON SEQUENCE schema_migrations_id_seq" in statement
        for statement in statements
    )
    assert connection.commits == 1


def test_runtime_ledger_access_rejects_effective_inherited_write_privilege():
    connection = _FakeConnection(
        ledger_permissions={
            "can_select": True,
            "can_write": True,
            "can_use_sequence": False,
        }
    )

    with pytest.raises(
        migration_runner.MigrationStateError,
        match="retains effective migration ledger write privileges",
    ):
        migration_runner._restrict_runtime_ledger_access(connection, "agent_user")

    assert connection.rollbacks == 1


def test_advisory_lock_conflict_fails_without_running_body():
    connection = _FakeConnection(lock_acquired=False)
    entered = False

    with pytest.raises(migration_runner.MigrationLockError):
        with migration_runner._migration_lock(connection):
            entered = True

    assert entered is False


def test_advisory_lock_is_released_when_body_fails():
    connection = _FakeConnection()

    with pytest.raises(RuntimeError, match="body failed"):
        with migration_runner._migration_lock(connection):
            raise RuntimeError("body failed")

    statements = [statement for statement, _ in connection.executed]
    assert any("pg_try_advisory_lock" in statement for statement in statements)
    assert any("pg_advisory_unlock" in statement for statement in statements)


def test_runner_rolls_back_and_stops_on_first_sql_error(tmp_path, monkeypatch):
    path = tmp_path / "100_broken.sql"
    path.write_text("SELECT broken;\n", encoding="utf-8")
    migration = _migration(path)
    connection = _FakeConnection(fail_sql=True)

    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: [migration])
    monkeypatch.setattr(
        migration_runner, "get_engine", lambda: _FakeEngine(connection)
    )
    monkeypatch.setattr(
        migration_runner, "_ensure_migrations_table", lambda conn, catalog: None
    )
    monkeypatch.setattr(
        migration_runner, "_load_applied", lambda conn: ([], "strict")
    )

    with pytest.raises(
        migration_runner.MigrationExecutionError,
        match="later migrations were not attempted",
    ):
        migration_runner.run_pending_migrations()

    assert connection.rollbacks >= 1


def test_runner_blocks_checksum_drift_before_migration_sql(tmp_path, monkeypatch):
    path = tmp_path / "100_example.sql"
    path.write_text("SELECT should_not_run;\n", encoding="utf-8")
    migration = _migration(path)
    connection = _FakeConnection()
    applied = {
        "migration_id": migration.migration_id,
        "version": migration.version,
        "filename": migration.filename,
        "checksum": "0" * 64,
    }

    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: [migration])
    monkeypatch.setattr(
        migration_runner, "get_engine", lambda: _FakeEngine(connection)
    )
    monkeypatch.setattr(
        migration_runner, "_ensure_migrations_table", lambda conn, catalog: None
    )
    monkeypatch.setattr(
        migration_runner, "_load_applied", lambda conn: ([applied], "strict")
    )

    with pytest.raises(migration_runner.MigrationDriftError):
        migration_runner.run_pending_migrations()

    assert not any("should_not_run" in statement for statement, _ in connection.executed)


def test_unapproved_migration_cannot_be_reconciled():
    with pytest.raises(
        migration_runner.MigrationReconciliationError,
        match="no approved reconciliation probes",
    ):
        migration_runner._run_probes(_FakeConnection(), "999_unapproved")


def test_schema_verification_fails_closed_when_pending(monkeypatch):
    report = migration_runner.MigrationReport(
        status="pending",
        generated_at="now",
        catalog_fingerprint="catalog",
        catalog_count=1,
        pending=("100_example",),
    )
    monkeypatch.setattr(migration_runner, "get_schema_report", lambda: report)

    with pytest.raises(
        migration_runner.MigrationStateError,
        match="explicit legacy reconciliation",
    ):
        migration_runner.verify_schema_state()


def test_runtime_schema_verification_allows_only_unrelated_pending(monkeypatch):
    report = migration_runner.MigrationReport(
        status="pending",
        generated_at="now",
        catalog_fingerprint="catalog",
        catalog_count=2,
        pending=("213_unrelated_capability",),
    )
    migrations = [
        migration_runner.Migration(
            migration_id="012_virtual_sources",
            version="012",
            filename="012_virtual_sources.sql",
            path=Path("012_virtual_sources.sql"),
            checksum="checksum",
        ),
        migration_runner.Migration(
            migration_id="213_unrelated_capability",
            version="213",
            filename="213_unrelated_capability.sql",
            path=Path("213_unrelated_capability.sql"),
            checksum="checksum",
        ),
    ]
    monkeypatch.setattr(migration_runner, "get_schema_report", lambda: report)
    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: migrations)

    observed = migration_runner.verify_runtime_schema_state(
        required_migrations=("012_virtual_sources",)
    )

    assert observed is report


def test_runtime_schema_verification_allows_unrelated_drift(monkeypatch):
    report = migration_runner.MigrationReport(
        status="drift",
        generated_at="now",
        catalog_fingerprint="catalog",
        catalog_count=3,
        pending=("230_unrelated_capability",),
        checksum_mismatches=(
            {
                "migration_id": "229_unrelated_capability",
                "expected": "new",
                "actual": "old",
            },
        ),
    )
    migrations = [
        migration_runner.Migration(
            migration_id="012_virtual_sources",
            version="012",
            filename="012_virtual_sources.sql",
            path=Path("012_virtual_sources.sql"),
            checksum="checksum",
        ),
        migration_runner.Migration(
            migration_id="229_unrelated_capability",
            version="229",
            filename="229_unrelated_capability.sql",
            path=Path("229_unrelated_capability.sql"),
            checksum="new",
        ),
        migration_runner.Migration(
            migration_id="230_unrelated_capability",
            version="230",
            filename="230_unrelated_capability.sql",
            path=Path("230_unrelated_capability.sql"),
            checksum="checksum",
        ),
    ]
    monkeypatch.setattr(migration_runner, "get_schema_report", lambda: report)
    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: migrations)

    observed = migration_runner.verify_runtime_schema_state(
        required_migrations=("012_virtual_sources",)
    )

    assert observed is report


def test_runtime_schema_verification_blocks_required_checksum_drift(monkeypatch):
    report = migration_runner.MigrationReport(
        status="drift",
        generated_at="now",
        catalog_fingerprint="catalog",
        catalog_count=1,
        checksum_mismatches=(
            {
                "migration_id": "012_virtual_sources",
                "expected": "new",
                "actual": "old",
            },
        ),
    )
    migration = migration_runner.Migration(
        migration_id="012_virtual_sources",
        version="012",
        filename="012_virtual_sources.sql",
        path=Path("012_virtual_sources.sql"),
        checksum="new",
    )
    monkeypatch.setattr(migration_runner, "get_schema_report", lambda: report)
    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: [migration])

    with pytest.raises(migration_runner.MigrationStateError, match="runtime capability"):
        migration_runner.verify_runtime_schema_state(
            required_migrations=("012_virtual_sources",)
        )


def test_runtime_schema_verification_blocks_required_missing_checksum(monkeypatch):
    report = migration_runner.MigrationReport(
        status="drift",
        generated_at="now",
        catalog_fingerprint="catalog",
        catalog_count=1,
        missing_checksums=("012_virtual_sources",),
    )
    migration = migration_runner.Migration(
        migration_id="012_virtual_sources",
        version="012",
        filename="012_virtual_sources.sql",
        path=Path("012_virtual_sources.sql"),
        checksum="checksum",
    )
    monkeypatch.setattr(migration_runner, "get_schema_report", lambda: report)
    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: [migration])

    with pytest.raises(migration_runner.MigrationStateError, match="runtime capability"):
        migration_runner.verify_runtime_schema_state(
            required_migrations=("012_virtual_sources",)
        )


def test_runtime_schema_verification_blocks_pending_required_migration(monkeypatch):
    report = migration_runner.MigrationReport(
        status="pending",
        generated_at="now",
        catalog_fingerprint="catalog",
        catalog_count=1,
        pending=("182_governed_virtual_source_discovery",),
    )
    migration = migration_runner.Migration(
        migration_id="182_governed_virtual_source_discovery",
        version="182",
        filename="182_governed_virtual_source_discovery.sql",
        path=Path("182_governed_virtual_source_discovery.sql"),
        checksum="checksum",
    )
    monkeypatch.setattr(migration_runner, "get_schema_report", lambda: report)
    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: [migration])

    with pytest.raises(migration_runner.MigrationStateError, match="runtime capability"):
        migration_runner.verify_runtime_schema_state(
            required_migrations=("182_governed_virtual_source_discovery",)
        )


def test_environment_report_comparison_surfaces_exact_difference():
    left = {
        "status": "in_sync",
        "catalog_fingerprint": "catalog",
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


def test_app_startup_only_verifies_runtime_schema_and_has_no_schema_ensure_calls():
    app_path = Path(__file__).with_name("app.py")
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    forbidden = {
        "ensure_users_table",
        "ensure_memory_table",
        "ensure_token_table",
        "ensure_table_ownership_table",
        "ensure_share_links_table",
        "ensure_audit_table",
        "ensure_templates_table",
        "ensure_semantic_tables",
        "ensure_teams_table",
        "ensure_data_catalog_table",
        "ensure_annotations_table",
        "ensure_chainlit_tables",
        "ensure_workflow_tables",
        "ensure_fusion_tables",
        "ensure_knowledge_graph_tables",
        "ensure_failure_table",
        "ensure_self_evolution_tables",
        "ensure_custom_skills_table",
        "ensure_kb_tables",
        "ensure_user_tools_table",
        "ensure_workflow_template_tables",
        "ensure_skill_bundles_table",
        "ensure_virtual_sources_table",
        "ensure_registry_table",
        "ensure_chains_table",
        "ensure_plugins_table",
        "ensure_observations_table",
        "run_pending_migrations",
    }

    assert "verify_runtime_schema_state" in calls
    assert not calls.intersection(forbidden)
