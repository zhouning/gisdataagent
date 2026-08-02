"""Contract tests for source sync definition, commit, and checkpoint authority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.platform_contracts import (
    SourceSyncCheckpoint,
    SourceSyncCommit,
    SourceSyncDefinitionVersion,
    canonical_json_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_definition_fingerprint,
)
from data_agent.source_sync_authority import (
    SourceSyncAuthority,
    source_sync_resource,
    source_sync_resource_version,
)

TENANT = "tenant-a"
SYNC_URN = "gda://tenant-a/sync_definition/roads-incremental-v1"
SOURCE_URN = "gda://tenant-a/source/osm-roads"
TARGET_URN = "gda://tenant-a/table/osm-roads-bronze"
SYNC_VERSION_ID = UUID("00000000-0000-4000-8000-000000000101")
PLATFORM_DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000102")
RUN_ID = UUID("00000000-0000-4000-8000-000000000103")
COMMIT_ID = UUID("00000000-0000-4000-8000-000000000104")
NOW = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)


def _definition(**overrides) -> SourceSyncDefinitionVersion:
    values = {
        "tenant_id": TENANT,
        "sync_definition_urn": SYNC_URN,
        "sync_definition_version_id": SYNC_VERSION_ID,
        "platform_definition_version_id": PLATFORM_DEFINITION_ID,
        "source_resource_urn": SOURCE_URN,
        "source_definition_fingerprint": "a" * 64,
        "target_resource_urn": TARGET_URN,
        "mode": "incremental",
        "write_disposition": "merge",
        "cursor_kind": "field",
        "cursor_field": "updated_at",
        "primary_keys": ("road_id",),
        "delete_mode": "hard_delete",
        "config": {"late_arrival_seconds": 300},
        "created_by": "workload:dataops-controller",
        "created_at": NOW,
    }
    values.update(overrides)
    semantic = {
        key: values[key]
        for key in (
            "tenant_id",
            "sync_definition_urn",
            "sync_definition_version_id",
            "platform_definition_version_id",
            "source_resource_urn",
            "source_definition_fingerprint",
            "target_resource_urn",
            "mode",
            "write_disposition",
            "cursor_kind",
            "cursor_field",
            "primary_keys",
            "delete_mode",
            "config",
        )
    }
    values.setdefault("definition_sha256", source_sync_definition_fingerprint(**semantic))
    return SourceSyncDefinitionVersion(**values)


def _commit(**overrides) -> SourceSyncCommit:
    previous_cursor = {"updated_at": "2026-08-02T12:00:00Z", "road_id": "r-10"}
    next_cursor = {"updated_at": "2026-08-02T13:00:00Z", "road_id": "r-20"}
    values = {
        "tenant_id": TENANT,
        "sync_commit_id": COMMIT_ID,
        "sync_definition_version_id": SYNC_VERSION_ID,
        "run_id": RUN_ID,
        "from_state_version": 0,
        "to_state_version": 1,
        "previous_cursor": previous_cursor,
        "previous_cursor_sha256": canonical_json_fingerprint(previous_cursor),
        "next_cursor": next_cursor,
        "next_cursor_sha256": canonical_json_fingerprint(next_cursor),
        "source_slice_sha256": "b" * 64,
        "target_commit_ref": {"provider": "iceberg", "snapshot_id": 1001},
        "target_content_sha256": "c" * 64,
        "records_read": 3,
        "records_inserted": 1,
        "records_updated": 1,
        "records_deleted": 1,
        "records_output": 50366,
        "committed_by": "workload:dataops-controller",
        "committed_at": NOW + timedelta(minutes=5),
    }
    values.update(overrides)
    evidence = {
        key: values[key]
        for key in (
            "tenant_id",
            "sync_commit_id",
            "sync_definition_version_id",
            "run_id",
            "from_state_version",
            "to_state_version",
            "previous_cursor",
            "next_cursor",
            "source_slice_sha256",
            "target_commit_ref",
            "target_content_sha256",
            "records_read",
            "records_inserted",
            "records_updated",
            "records_deleted",
            "records_output",
            "committed_by",
            "committed_at",
        )
    }
    values.setdefault("commit_sha256", source_sync_commit_fingerprint(**evidence))
    return SourceSyncCommit(**values)


def test_incremental_merge_definition_is_frozen_and_projects_resource_chain() -> None:
    definition = _definition()
    resource = source_sync_resource(definition, owner_ref="team:data-platform")
    version = source_sync_resource_version(definition)

    assert resource.resource_urn == SYNC_URN
    assert resource.resource_kind == "sync_definition"
    assert resource.authority_system == "gda_control"
    assert version.resource_version_id == SYNC_VERSION_ID
    assert version.content_sha256 == definition.definition_sha256
    with pytest.raises(ValidationError, match="frozen"):
        definition.mode = "full"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"cursor_kind": "none", "cursor_field": None}, "requires a cursor"),
        ({"cursor_kind": "field", "cursor_field": None}, "cursor_field"),
        ({"primary_keys": ()}, "requires primary keys"),
        ({"primary_keys": ("road_id", "road_id")}, "must be unique"),
        ({"write_disposition": "append"}, "source deletes require merge"),
        ({"target_resource_urn": "gda://tenant-b/table/roads"}, "target tenant"),
    ],
)
def test_incremental_definition_rejects_unsafe_semantics(overrides, message) -> None:
    with pytest.raises(ValidationError, match=message):
        _definition(**overrides)


def test_full_sync_requires_overwrite_and_no_cursor() -> None:
    full = _definition(
        mode="full",
        write_disposition="overwrite",
        cursor_kind="none",
        cursor_field=None,
        primary_keys=(),
        delete_mode="ignore",
    )
    assert full.mode.value == "full"
    with pytest.raises(ValidationError, match="overwrite"):
        _definition(
            mode="full",
            write_disposition="append",
            cursor_kind="none",
            cursor_field=None,
            primary_keys=(),
            delete_mode="ignore",
        )


def test_checkpoint_requires_matching_cursor_hash_and_complete_commit_evidence() -> None:
    initial = SourceSyncCheckpoint(
        tenant_id=TENANT,
        sync_definition_version_id=SYNC_VERSION_ID,
        cursor={},
        cursor_sha256=canonical_json_fingerprint({}),
        updated_by="workload:dataops-controller",
        updated_at=NOW,
    )
    assert initial.state_version == 0
    with pytest.raises(ValidationError, match="cursor fingerprint"):
        SourceSyncCheckpoint.model_validate(
            {**initial.model_dump(mode="python"), "cursor_sha256": "f" * 64}
        )
    with pytest.raises(ValidationError, match="complete commit evidence"):
        SourceSyncCheckpoint(
            tenant_id=TENANT,
            sync_definition_version_id=SYNC_VERSION_ID,
            state_version=1,
            cursor={"offset": 10},
            cursor_sha256=canonical_json_fingerprint({"offset": 10}),
            last_sync_commit_id=COMMIT_ID,
            updated_by="workload:dataops-controller",
            updated_at=NOW,
        )


def test_sync_commit_binds_cursor_move_counts_target_and_workload() -> None:
    commit = _commit()
    assert commit.to_state_version == 1
    assert commit.commit_sha256 == source_sync_commit_fingerprint(
        **{
            key: value
            for key, value in commit.model_dump(mode="python").items()
            if key
            not in {
                "previous_cursor_sha256",
                "next_cursor_sha256",
                "commit_sha256",
            }
        }
    )
    with pytest.raises(ValidationError, match="different cursor"):
        _commit(
            next_cursor=_commit().previous_cursor,
            next_cursor_sha256=_commit().previous_cursor_sha256,
        )
    with pytest.raises(ValidationError, match="workload identity"):
        _commit(committed_by="human:operator")
    with pytest.raises(ValidationError, match="cannot exceed"):
        _commit(records_read=2)


def test_migration_enforces_rls_append_only_cas_and_run_binding() -> None:
    sql = (
        Path(__file__).parent
        / "migrations/104_source_sync_checkpoint_authority.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.source_sync_definition",
        "CREATE TABLE IF NOT EXISTS gda_control.source_sync_checkpoint",
        "CREATE TABLE IF NOT EXISTS gda_control.source_sync_commit",
        "commit_source_sync",
        "source sync checkpoint version or cursor conflict",
        "source sync commit is not authorized by its PlatformRun",
        "fk_gda_source_sync_checkpoint_last_commit",
        "FOR UPDATE",
        "FORCE ROW LEVEL SECURITY",
        "GRANT SELECT, INSERT ON gda_control.source_sync_definition",
        "GRANT SELECT, INSERT ON gda_control.source_sync_checkpoint",
        "GRANT SELECT ON gda_control.source_sync_commit",
    ):
        assert marker in sql
    assert "GRANT UPDATE ON gda_control.source_sync_checkpoint" not in sql
    assert "GRANT INSERT ON gda_control.source_sync_commit" not in sql


def test_source_slice_preflight_is_available_before_provider_write() -> None:
    assert callable(SourceSyncAuthority.find_source_slice_commit)
