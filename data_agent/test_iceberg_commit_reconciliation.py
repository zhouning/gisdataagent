"""Contracts for cancel and uncertain Iceberg commit reconciliation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from data_agent.iceberg_commit_reconciliation import (
    IcebergCommitIntent,
    IcebergCommitReconciliationError,
    IcebergSnapshotEvidence,
    reconcile_iceberg_commit,
)

SOURCE_SHA = "a" * 64
CONTENT_SHA = "b" * 64


def _intent(**overrides) -> IcebergCommitIntent:
    values = {
        "source_slice_sha256": SOURCE_SHA,
        "commit_token": SOURCE_SHA,
        "baseline_snapshot_id": "100",
        "expected_record_count": 7,
        "expected_matching_records": 4,
        "expected_content_sha256": CONTENT_SHA,
    }
    values.update(overrides)
    return IcebergCommitIntent(**values)


def _snapshot(**overrides) -> IcebergSnapshotEvidence:
    values = {
        "snapshot_id": "101",
        "parent_snapshot_id": "100",
        "operation": "append",
        "record_count": 7,
        "matching_records": 4,
        "commit_token": SOURCE_SHA,
        "content_sha256": CONTENT_SHA,
    }
    values.update(overrides)
    return IcebergSnapshotEvidence(**values)


def test_commit_token_must_be_the_source_slice_fingerprint() -> None:
    with pytest.raises(ValidationError, match="source-slice fingerprint"):
        _intent(commit_token="c" * 64)


def test_confirmed_cancel_without_snapshot_never_advances_authorities() -> None:
    decision = reconcile_iceberg_commit(_intent(), (), cancel_confirmed=True)

    assert decision.status == "cancelled_uncommitted"
    assert decision.advance_source_sync is False
    assert decision.retry_provider_write is False
    assert decision.publish_data_product is False


def test_unacknowledged_exact_snapshot_is_recovered_without_provider_retry() -> None:
    decision = reconcile_iceberg_commit(_intent(), (_snapshot(),), cancel_confirmed=False)

    assert decision.status == "committed_unacknowledged"
    assert decision.advance_source_sync is True
    assert decision.retry_provider_write is False
    assert decision.target_commit_ref == {
        "provider": "iceberg",
        "snapshot_id": "101",
        "parent_snapshot_id": "100",
        "operation": "append",
        "source_slice_sha256": SOURCE_SHA,
        "content_sha256": CONTENT_SHA,
    }


def test_recorded_snapshot_is_an_idempotent_skip() -> None:
    decision = reconcile_iceberg_commit(
        _intent(),
        (_snapshot(),),
        cancel_confirmed=False,
        recorded_snapshot_id="101",
    )

    assert decision.status == "already_recorded"
    assert decision.advance_source_sync is False
    assert decision.retry_provider_write is False


@pytest.mark.parametrize(
    "snapshots",
    [
        (_snapshot(content_sha256="c" * 64),),
        (_snapshot(), _snapshot(snapshot_id="102", parent_snapshot_id="101")),
        (
            _snapshot(
                record_count=5,
                matching_records=2,
                content_sha256="d" * 64,
            ),
        ),
    ],
)
def test_ambiguous_or_mismatched_provider_evidence_fails_closed(
    snapshots: tuple[IcebergSnapshotEvidence, ...],
) -> None:
    with pytest.raises(IcebergCommitReconciliationError):
        reconcile_iceberg_commit(_intent(), snapshots, cancel_confirmed=False)
