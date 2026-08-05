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
    SourceSyncCommitGovernanceEvidence,
    SourceSyncDefinitionVersion,
    SourceSyncQuarantineEvidence,
    canonical_json_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_commit_governance_evidence_fingerprint,
    source_sync_definition_fingerprint,
    source_sync_quarantine_evidence_fingerprint,
)
from data_agent.source_sync_authority import (
    SourceSyncAuthority,
    SourceSyncValidationError,
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
TARGET_VERSION_ID = UUID("00000000-0000-4000-8000-000000000105")
OUTPUT_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000106")
QUALITY_RESULT_ID = UUID("00000000-0000-4000-8000-000000000107")
LINEAGE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000108")
METADATA_CHANGE_ID = UUID("00000000-0000-4000-8000-000000000109")
QUARANTINE_VERSION_ID = UUID("00000000-0000-4000-8000-000000000110")
QUARANTINE_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000111")
NOW = datetime(2026, 8, 2, 13, 0, tzinfo=UTC)


def _governance(**overrides) -> dict:
    values = {
        "schema": "gda.source_sync_governance.v1",
        "target_layer": "ods",
        "data_kind": "vector",
        "capture_kind": "micro_batch",
        "source_adapter": {
            "adapter_id": "spark-iceberg",
            "adapter_version": "1.0.0",
            "adapter_fingerprint": "d" * 64,
        },
        "standard_mapping_contract_id": None,
        "standard_version_id": None,
        "data_model_version_id": None,
        "quality_rule_version_refs": ("quality:source-integrity-v1",),
        "classification_policy_version_ref": "classification:internal-v1",
        "retention_policy_version_ref": "retention:ods-v1",
        "schema_change_policy": "approval_required",
        "promotion_mode": "blocked",
        "quarantine_resource_urn": None,
        "event_time_field": None,
        "watermark_delay_seconds": None,
    }
    values.update(overrides)
    return values


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
        "governance_contract": _governance(),
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
            "governance_contract",
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


def _governance_evidence(**overrides) -> SourceSyncCommitGovernanceEvidence:
    values = {
        "tenant_id": TENANT,
        "sync_commit_id": COMMIT_ID,
        "target_resource_version_id": TARGET_VERSION_ID,
        "output_artifact_id": OUTPUT_ARTIFACT_ID,
        "quality_result_ids": (QUALITY_RESULT_ID,),
        "lineage_event_id": LINEAGE_EVENT_ID,
        "metadata_change_id": METADATA_CHANGE_ID,
        "approval_case_ref": None,
    }
    supplied_fingerprint = overrides.pop("evidence_sha256", None)
    values.update(overrides)
    values["evidence_sha256"] = supplied_fingerprint or (
        source_sync_commit_governance_evidence_fingerprint(**values)
    )
    return SourceSyncCommitGovernanceEvidence(**values)


def _quarantine_evidence(**overrides) -> SourceSyncQuarantineEvidence:
    values = {
        "tenant_id": TENANT,
        "sync_commit_id": COMMIT_ID,
        "source_slice_sha256": "b" * 64,
        "quarantine_resource_version_id": QUARANTINE_VERSION_ID,
        "quarantine_artifact_id": QUARANTINE_ARTIFACT_ID,
        "records_rejected": 2,
        "reason_counts": {"duplicate": 1, "late": 1},
    }
    supplied_fingerprint = overrides.pop("evidence_sha256", None)
    values.update(overrides)
    values["evidence_sha256"] = supplied_fingerprint or (
        source_sync_quarantine_evidence_fingerprint(**values)
    )
    return SourceSyncQuarantineEvidence(**values)


def test_incremental_merge_definition_is_frozen_and_projects_resource_chain() -> None:
    definition = _definition()
    resource = source_sync_resource(definition, owner_ref="team:data-platform")
    version = source_sync_resource_version(definition)

    assert resource.resource_urn == SYNC_URN
    assert resource.resource_kind == "sync_definition"
    assert resource.authority_system == "gda_control"
    assert version.resource_version_id == SYNC_VERSION_ID
    assert version.content_sha256 == definition.definition_sha256
    assert resource.governance_ref["source_sync_governance"]["target_layer"] == "ods"
    assert version.authority_version_ref["capture_kind"] == "micro_batch"
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
        governance_contract=_governance(capture_kind="batch"),
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
            governance_contract=_governance(capture_kind="batch"),
        )


def test_governance_contract_controls_lakehouse_promotion_and_capture() -> None:
    ods = _definition()
    assert ods.governance_contract is not None
    assert ods.governance_contract.target_layer.value == "ods"

    with pytest.raises(ValidationError, match="standard, model, and quarantine"):
        _definition(
            governance_contract=_governance(
                target_layer="silver",
                promotion_mode="quality_gated",
            )
        )
    with pytest.raises(ValidationError, match="event time and watermark"):
        _definition(
            governance_contract=_governance(capture_kind="event_stream")
        )
    with pytest.raises(ValidationError, match="token or offset cursor"):
        _definition(
            cursor_kind="field",
            cursor_field="updated_at",
            governance_contract=_governance(capture_kind="cdc"),
        )
    with pytest.raises(ValidationError, match="quarantine tenant"):
        _definition(
            governance_contract=_governance(
                target_layer="silver",
                promotion_mode="quality_gated",
                standard_mapping_contract_id=UUID(
                    "00000000-0000-4000-8000-000000000111"
                ),
                standard_version_id=UUID("00000000-0000-4000-8000-000000000112"),
                data_model_version_id=UUID(
                    "00000000-0000-4000-8000-000000000113"
                ),
                quarantine_resource_urn="gda://tenant-b/table/roads-quarantine",
            )
        )


def test_governance_contract_is_fingerprinted_without_rewriting_legacy_hashes() -> None:
    governed = _definition()
    legacy = _definition(governance_contract=None)
    assert governed.definition_sha256 != legacy.definition_sha256
    governed_document = governed.model_dump(mode="json")
    assert governed_document["governance_contract"]["schema"] == (
        "gda.source_sync_governance.v1"
    )
    assert SourceSyncDefinitionVersion.model_validate(governed_document) == governed
    legacy_semantic = {
        key: value
        for key, value in legacy.model_dump(mode="python").items()
        if key
        not in {
            "governance_contract",
            "definition_sha256",
            "created_by",
            "created_at",
        }
    }
    assert legacy.definition_sha256 == source_sync_definition_fingerprint(
        **legacy_semantic
    )
    with pytest.raises(SourceSyncValidationError, match="governance contract"):
        SourceSyncAuthority().create_definition(
            legacy,
            owner_ref="team:data-platform",
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


def test_sync_commit_governance_evidence_is_complete_canonical_and_fingerprinted() -> None:
    evidence = _governance_evidence()
    assert evidence.sync_commit_id == COMMIT_ID
    assert evidence.evidence_sha256 == (
        source_sync_commit_governance_evidence_fingerprint(
            **evidence.model_dump(mode="python", exclude={"evidence_sha256"})
        )
    )
    with pytest.raises(ValidationError, match="must be unique"):
        _governance_evidence(
            quality_result_ids=(QUALITY_RESULT_ID, QUALITY_RESULT_ID)
        )
    with pytest.raises(ValidationError, match="canonically sorted"):
        _governance_evidence(
            quality_result_ids=(
                UUID("00000000-0000-4000-8000-000000000202"),
                UUID("00000000-0000-4000-8000-000000000201"),
            )
        )
    with pytest.raises(ValidationError, match="approval tenant"):
        _governance_evidence(
            approval_case_ref="gda://tenant-b/approval_case/source-sync-promote"
        )
    with pytest.raises(ValidationError, match="fingerprint"):
        _governance_evidence(evidence_sha256="f" * 64)


def test_source_sync_quarantine_evidence_reconciles_rejected_records() -> None:
    evidence = _quarantine_evidence()
    assert evidence.records_rejected == 2
    assert evidence.evidence_sha256 == source_sync_quarantine_evidence_fingerprint(
        **evidence.model_dump(mode="python", exclude={"evidence_sha256"})
    )
    with pytest.raises(ValidationError, match="must equal records rejected"):
        _quarantine_evidence(records_rejected=3)
    with pytest.raises(ValidationError, match="zero rejected records"):
        _quarantine_evidence(records_rejected=0)
    zero_values = {
        "records_rejected": 0,
        "reason_counts": {},
    }
    assert _quarantine_evidence(**zero_values).reason_counts == {}
    with pytest.raises(ValidationError, match="fingerprint"):
        _quarantine_evidence(evidence_sha256="f" * 64)
    with pytest.raises(ValidationError, match="less than or equal"):
        _quarantine_evidence(
            records_rejected=9_223_372_036_854_775_808,
            reason_counts={"overflow": 9_223_372_036_854_775_808},
        )


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

    governance_sql = (
        Path(__file__).parent
        / "migrations/141_source_sync_governance_contract.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "ADD COLUMN IF NOT EXISTS governance_contract JSONB",
        "gda.source_sync_governance.v1",
        "source_sync_quality_refs_valid",
        "new source sync definition requires governance contract",
        "'batch', 'micro_batch', 'cdc', 'event_stream'",
        "'landing', 'ods', 'silver', 'gold'",
        "quarantine_resource_urn",
    ):
        assert marker in governance_sql

    commit_governance_sql = (
        Path(__file__).parent
        / "migrations/142_source_sync_commit_governance_evidence.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "source_sync_commit_governance_evidence",
        "source_sync_commit_governance_evidence_sha256",
        "commit_source_sync_v104",
        "quality evidence does not exactly satisfy sync contract",
        "ApprovalCase does not authorize source sync promotion",
        "metadata outbox change does not match LineageEvent",
        "cross-run replay must reuse original governance evidence",
        "FORCE ROW LEVEL SECURITY",
        "GRANT SELECT ON TABLE gda_control.source_sync_commit_governance_evidence",
    ):
        assert marker in commit_governance_sql
    assert (
        "GRANT INSERT ON TABLE gda_control.source_sync_commit_governance_evidence"
        not in commit_governance_sql
    )

    quarantine_sql = (
        Path(__file__).parent
        / "migrations/143_source_sync_quarantine_evidence.sql"
    ).read_text(encoding="utf-8")
    for marker in (
        "source_sync_quarantine_evidence",
        "source_sync_quarantine_evidence_sha256",
        "bind_source_sync_quarantine_evidence",
        "gda.source_sync_quarantine.v1",
        "trg_gda_source_sync_commit_requires_quarantine",
        "DEFERRABLE INITIALLY DEFERRED",
        "v_quarantine_version.content_sha256 IS DISTINCT FROM",
        "FORCE ROW LEVEL SECURITY",
        "GRANT SELECT ON TABLE gda_control.source_sync_quarantine_evidence",
    ):
        assert marker in quarantine_sql
    assert (
        "GRANT INSERT ON TABLE gda_control.source_sync_quarantine_evidence"
        not in quarantine_sql
    )


def test_source_slice_preflight_is_available_before_provider_write() -> None:
    assert callable(SourceSyncAuthority.find_source_slice_commit)


def test_authority_rejects_governance_evidence_for_a_different_commit() -> None:
    with pytest.raises(SourceSyncValidationError, match="requested commit"):
        SourceSyncAuthority().commit(
            _commit(),
            _governance_evidence(
                sync_commit_id=UUID("00000000-0000-4000-8000-000000000999")
            ),
        )


def test_authority_rejects_quarantine_evidence_for_a_different_commit() -> None:
    with pytest.raises(SourceSyncValidationError, match="requested commit"):
        SourceSyncAuthority().commit(
            _commit(),
            quarantine_evidence=_quarantine_evidence(
                sync_commit_id=UUID("00000000-0000-4000-8000-000000000999")
            ),
        )
