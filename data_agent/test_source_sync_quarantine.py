"""Tests for provider-neutral SourceSync quarantine recording."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from data_agent.platform_contracts import (
    SourceSyncCommit,
    SourceSyncDefinitionVersion,
    canonical_json_fingerprint,
    source_sync_commit_fingerprint,
    source_sync_definition_fingerprint,
)
from data_agent.source_sync_quarantine import (
    ProviderQuarantineReceipt,
    SourceSyncQuarantineContract,
    SourceSyncQuarantineRecorder,
)

TENANT = "tenant-a"
DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000201")
PLATFORM_DEFINITION_ID = UUID("00000000-0000-4000-8000-000000000202")
RUN_ID = UUID("00000000-0000-4000-8000-000000000203")
COMMIT_ID = UUID("00000000-0000-4000-8000-000000000204")
NOW = datetime(2026, 8, 5, 10, 0, tzinfo=UTC)
QUARANTINE_URN = "gda://tenant-a/table/roads-quarantine"


class _Gateway:
    def __init__(self, *, created: bool = True) -> None:
        self.created = created
        self.resources = []
        self.versions = []
        self.artifacts = []

    def register_resource(self, value):
        self.resources.append(value)
        return SimpleNamespace(created=self.created)

    def register_resource_version(self, value):
        self.versions.append(value)
        return SimpleNamespace(created=self.created)

    def record_artifact(self, value):
        self.artifacts.append(value)
        return SimpleNamespace(created=self.created)


def _definition(*, target_layer: str = "silver") -> SourceSyncDefinitionVersion:
    governance = {
        "schema": "gda.source_sync_governance.v1",
        "target_layer": target_layer,
        "data_kind": "vector",
        "capture_kind": "micro_batch",
        "source_adapter": {
            "adapter_id": "spark-iceberg",
            "adapter_version": "1.0.0",
            "adapter_fingerprint": "d" * 64,
        },
        "standard_mapping_contract_id": (
            UUID("00000000-0000-4000-8000-000000000205")
            if target_layer in {"silver", "gold"}
            else None
        ),
        "standard_version_id": (
            UUID("00000000-0000-4000-8000-000000000206")
            if target_layer in {"silver", "gold"}
            else None
        ),
        "data_model_version_id": (
            UUID("00000000-0000-4000-8000-000000000207")
            if target_layer in {"silver", "gold"}
            else None
        ),
        "quality_rule_version_refs": ["quality:roads-v1"],
        "classification_policy_version_ref": "classification:internal-v1",
        "retention_policy_version_ref": f"retention:{target_layer}-v1",
        "schema_change_policy": "approval_required",
        "promotion_mode": "quality_gated" if target_layer == "silver" else "blocked",
        "quarantine_resource_urn": (
            QUARANTINE_URN if target_layer in {"silver", "gold"} else None
        ),
        "event_time_field": None,
        "watermark_delay_seconds": None,
    }
    values = {
        "tenant_id": TENANT,
        "sync_definition_urn": "gda://tenant-a/sync_definition/roads-v1",
        "sync_definition_version_id": DEFINITION_ID,
        "platform_definition_version_id": PLATFORM_DEFINITION_ID,
        "source_resource_urn": "gda://tenant-a/source/roads",
        "source_definition_fingerprint": "a" * 64,
        "target_resource_urn": "gda://tenant-a/table/roads-silver",
        "mode": "incremental",
        "write_disposition": "merge",
        "cursor_kind": "provider_token",
        "cursor_field": None,
        "primary_keys": ("road_id",),
        "delete_mode": "hard_delete",
        "config": {},
        "governance_contract": governance,
    }
    return SourceSyncDefinitionVersion(
        **values,
        definition_sha256=source_sync_definition_fingerprint(**values),
        created_by="workload:dataops-controller",
        created_at=NOW,
    )


def _commit() -> SourceSyncCommit:
    previous_cursor = {"offset": 0}
    next_cursor = {"offset": 10}
    values = {
        "tenant_id": TENANT,
        "sync_commit_id": COMMIT_ID,
        "sync_definition_version_id": DEFINITION_ID,
        "run_id": RUN_ID,
        "from_state_version": 0,
        "to_state_version": 1,
        "previous_cursor": previous_cursor,
        "next_cursor": next_cursor,
        "source_slice_sha256": "b" * 64,
        "target_commit_ref": {"provider": "iceberg", "snapshot_id": 1001},
        "target_content_sha256": "c" * 64,
        "records_read": 10,
        "records_inserted": 8,
        "records_updated": 0,
        "records_deleted": 0,
        "records_output": 8,
        "committed_by": "workload:dataops-controller",
        "committed_at": NOW + timedelta(minutes=2),
    }
    return SourceSyncCommit(
        **values,
        previous_cursor_sha256=canonical_json_fingerprint(previous_cursor),
        next_cursor_sha256=canonical_json_fingerprint(next_cursor),
        commit_sha256=source_sync_commit_fingerprint(**values),
    )


def _contract() -> SourceSyncQuarantineContract:
    return SourceSyncQuarantineContract(
        quarantine_resource_urn=QUARANTINE_URN,
        authority_system="spark-iceberg",
        authority_locator="lakehouse.tenant_a.roads_quarantine",
        owner_ref="team:data-platform",
        artifact_key_prefix="roads_quarantine",
    )


def _receipt(**overrides) -> ProviderQuarantineReceipt:
    values = {
        "storage_uri": "s3://lakehouse/quarantine/receipt.json",
        "media_type": "application/json",
        "content_sha256": "e" * 64,
        "size_bytes": 256,
        "records_rejected": 2,
        "reason_counts": {"duplicate": 1, "invalid_geometry": 1},
        "manifest_facets": {"provider": "spark-iceberg", "snapshot_id": 1001},
    }
    values.update(overrides)
    return ProviderQuarantineReceipt(**values)


def test_recorder_builds_complete_provider_binding() -> None:
    gateway = _Gateway()
    record = SourceSyncQuarantineRecorder(
        _contract(), gateway=gateway  # type: ignore[arg-type]
    ).record(
        definition=_definition(),
        commit=_commit(),
        receipt=_receipt(),
        recorded_at=NOW + timedelta(minutes=1),
    )

    assert not record.replayed
    assert record.artifact.artifact_role.value == "quarantine"
    assert record.artifact.manifest["records_rejected"] == 2
    assert record.artifact.manifest["rejected_content_sha256"] == "e" * 64
    assert record.resource_version.content_sha256 == record.artifact.content_sha256
    assert record.evidence.quarantine_artifact_id == record.artifact.artifact_id
    assert record.evidence.reason_counts == _receipt().reason_counts
    assert gateway.resources == [record.resource]
    assert gateway.versions == [record.resource_version]
    assert gateway.artifacts == [record.artifact]


def test_recorder_reports_identity_replay() -> None:
    record = SourceSyncQuarantineRecorder(
        _contract(), gateway=_Gateway(created=False)  # type: ignore[arg-type]
    ).record(
        definition=_definition(),
        commit=_commit(),
        receipt=_receipt(),
        recorded_at=NOW + timedelta(minutes=1),
    )
    assert record.replayed


def test_recorder_accepts_explicit_zero_rejection_receipt() -> None:
    record = SourceSyncQuarantineRecorder(
        _contract(), gateway=_Gateway()  # type: ignore[arg-type]
    ).record(
        definition=_definition(),
        commit=_commit(),
        receipt=_receipt(records_rejected=0, reason_counts={}),
        recorded_at=NOW + timedelta(minutes=1),
    )

    assert record.evidence.records_rejected == 0
    assert record.evidence.reason_counts == {}
    assert record.artifact.manifest["records_rejected"] == 0
    assert record.artifact.manifest["reason_counts"] == {}


def test_recorder_rejects_a_different_quarantine_resource() -> None:
    contract = SourceSyncQuarantineContract(
        quarantine_resource_urn="gda://tenant-a/table/other-quarantine",
        authority_system="spark-iceberg",
        authority_locator="lakehouse.tenant_a.other_quarantine",
        owner_ref="team:data-platform",
        artifact_key_prefix="other_quarantine",
    )

    with pytest.raises(ValueError, match="does not match"):
        SourceSyncQuarantineRecorder(
            contract, gateway=_Gateway()  # type: ignore[arg-type]
        ).record(
            definition=_definition(),
            commit=_commit(),
            receipt=_receipt(),
            recorded_at=NOW + timedelta(minutes=1),
        )


@pytest.mark.parametrize(
    ("definition", "receipt", "recorded_at", "message"),
    [
        (_definition(target_layer="ods"), _receipt(), NOW, "Silver or Gold"),
        (
            _definition(),
            _receipt(manifest_facets={"records_rejected": 999}),
            NOW,
            "cannot override",
        ),
        (
            _definition(),
            _receipt(size_bytes=0),
            NOW,
            "non-empty physical artifact",
        ),
        (
            _definition(),
            _receipt(),
            NOW + timedelta(minutes=3),
            "after its commit",
        ),
    ],
)
def test_recorder_rejects_unsafe_provider_receipts(
    definition,
    receipt,
    recorded_at,
    message,
) -> None:
    with pytest.raises(ValueError, match=message):
        SourceSyncQuarantineRecorder(
            _contract(), gateway=_Gateway()  # type: ignore[arg-type]
        ).record(
            definition=definition,
            commit=_commit(),
            receipt=receipt,
            recorded_at=recorded_at,
        )
