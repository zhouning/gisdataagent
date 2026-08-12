from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.platform_runtime import recovery_rehearsal
from data_agent.platform_runtime.deployment_profile import load_deployment_profile
from data_agent.platform_runtime.recovery_rehearsal import (
    RECOVERY_LIMITATIONS,
    RecoveryRehearsalError,
    collect_database_state,
    database_logical_identity,
    failure_report,
    local_object_tree_facts,
    migration_entries_fingerprint,
    resolve_recovery_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO_ROOT / "config" / "deployment_profiles" / "main-compose-dev.json"


def test_resolve_recovery_contract_uses_non_secret_compose_identity() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    compose_model = {
        "services": {
            "db": {
                "image": "postgis:test",
                "environment": {
                    "POSTGRES_DB": "gis_agent",
                    "POSTGRES_USER": "postgres",
                    "POSTGRES_PASSWORD": "must-not-leak",
                },
            },
            "minio": {},
            "minio-bucket-init": {
                "environment": {
                    "AWS_S3_BUCKET": "gis-agent-uploads",
                    "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
                    "MINIO_ROOT_PASSWORD": "must-not-leak",
                }
            },
        }
    }

    contract = resolve_recovery_contract(profile, compose_model)

    assert contract.database_service == "db"
    assert contract.database_name == "gis_agent"
    assert contract.buckets == ("gis-agent-uploads", "gis-agent-lakehouse")
    assert "must-not-leak" not in repr(contract)


def test_recovery_contract_rejects_unsafe_bucket_names() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    compose_model = {
        "services": {
            "db": {
                "image": "postgis:test",
                "environment": {"POSTGRES_DB": "gis_agent", "POSTGRES_USER": "postgres"},
            },
            "minio": {},
            "minio-bucket-init": {
                "environment": {
                    "AWS_S3_BUCKET": "../source",
                    "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
                }
            },
        }
    }

    with pytest.raises(RecoveryRehearsalError) as error:
        resolve_recovery_contract(profile, compose_model)

    assert error.value.stage == "contract.bucket_names"


def test_object_tree_fingerprint_is_content_and_relative_key_bound(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source"
    restored_path = tmp_path / "restored"
    (source_path / "a").mkdir(parents=True)
    (restored_path / "a").mkdir(parents=True)
    (source_path / "a" / "data.parquet").write_bytes(b"0123456789")
    (source_path / "catalog.json").write_bytes(b"{}")
    (restored_path / "catalog.json").write_bytes(b"{}")
    (restored_path / "a" / "data.parquet").write_bytes(b"0123456789")

    source = local_object_tree_facts(source_path)
    restored = local_object_tree_facts(restored_path)

    assert source == restored
    assert source["object_count"] == 2
    assert source["bytes"] == 12

    (restored_path / "a" / "data.parquet").write_bytes(b"0123456788")
    assert local_object_tree_facts(restored_path) != source


def test_failure_report_is_sparse_and_always_blocks_promotion() -> None:
    report = failure_report(
        profile_id="main-compose-dev",
        stage="database.restore",
        error_type="RecoveryRehearsalError",
    )
    rendered = json.dumps(report, sort_keys=True)

    assert report["technical_pass"] is False
    assert report["promotion_ready"] is False
    assert set(RECOVERY_LIMITATIONS).issubset(report["promotion_blockers"])
    assert "/Users/" not in rendered
    assert "password" not in rendered.lower()


def test_migration_fingerprint_is_order_independent_and_content_bound() -> None:
    entries = [("002_second", "b" * 64), ("001_first", "a" * 64)]

    fingerprint = migration_entries_fingerprint(entries)

    assert fingerprint == migration_entries_fingerprint(list(reversed(entries)))
    assert fingerprint != migration_entries_fingerprint([
        ("002_second", "c" * 64),
        ("001_first", "a" * 64),
    ])


def test_database_logical_identity_ignores_physical_storage_layout_only() -> None:
    source = {"database_bytes": 100, "migration_count": 93, "standard": {"count": 174}}
    restored = {"database_bytes": 80, "migration_count": 93, "standard": {"count": 174}}

    assert database_logical_identity(source) == database_logical_identity(restored)
    restored["migration_count"] = 92
    assert database_logical_identity(source) != database_logical_identity(restored)


def test_collect_database_state_uses_the_shared_query_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    facts = {
        "database_bytes": 100,
        "standard": {
            "doc_code": profile.released_standard.doc_code,
            "version_label": profile.released_standard.version_label,
            "status": "released",
            "element_count": profile.released_standard.element_count,
        },
        "representative_table_counts": {
            "twm_state_object": 1,
            "twm_state_relation": 2,
            "twm_evidence_item": 3,
        },
        "geometry_column_count": 4,
        "extensions": {"postgis": "3.4.3"},
    }
    migrations = [
        (f"migration-{index}", f"{index:064x}")
        for index in range(profile.migrations.count)
    ]
    elements = [object() for _ in range(profile.released_standard.element_count)]
    monkeypatch.setattr(
        recovery_rehearsal,
        "migration_entries_fingerprint",
        lambda _entries: profile.migrations.fingerprint,
    )
    monkeypatch.setattr(
        recovery_rehearsal,
        "standard_elements_fingerprint",
        lambda _elements: profile.released_standard.elements_sha256,
    )
    monkeypatch.setattr(
        recovery_rehearsal,
        "_standard_element_from_json",
        lambda _value: elements[0],
    )

    def query(sql: str, database: str | None) -> str:
        assert database is None
        if "pg_database_size" in sql:
            return json.dumps(facts)
        if "schema_migrations" in sql:
            return "\n".join(f"{name}\t{checksum}" for name, checksum in migrations)
        return "\n".join("{}" for _ in elements)

    state = collect_database_state(profile=profile, query=query)

    assert state["database_bytes"] == 100
    assert state["representative_table_counts"]["twm_state_relation"] == 2
    assert state["migration_fingerprint"] == profile.migrations.fingerprint


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (b'ERROR: role "agent_user" does not exist', "database.restore.missing_role"),
        (b"ERROR: no space left on device", "database.restore.capacity"),
        (b"ERROR: relation already exists", "database.restore.object_conflict"),
        (b"ERROR: unknown", "database.restore"),
    ],
)
def test_restore_failure_is_classified_without_raw_output(
    stderr: bytes, expected: str
) -> None:
    assert recovery_rehearsal._classify_restore_failure(stderr) == expected
