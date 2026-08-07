"""Fail-closed reconciliation for uncertain Iceberg provider commits."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IcebergCommitReconciliationError(RuntimeError):
    """The provider evidence cannot be reconciled without operator review."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IcebergCommitIntent(_FrozenModel):
    """Immutable source-slice expectations recorded before provider dispatch."""

    source_slice_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    commit_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_snapshot_id: str = Field(pattern=r"^[0-9]+$")
    expected_record_count: int = Field(ge=0)
    expected_matching_records: int = Field(gt=0)
    expected_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _token_binds_source_slice(self) -> IcebergCommitIntent:
        if self.commit_token != self.source_slice_sha256:
            raise ValueError("commit_token must equal the source-slice fingerprint")
        if self.expected_matching_records > self.expected_record_count:
            raise ValueError("matching records cannot exceed the final record count")
        return self


class IcebergSnapshotEvidence(_FrozenModel):
    """Content evidence observed by independently reading one Iceberg snapshot."""

    snapshot_id: str = Field(pattern=r"^[0-9]+$")
    parent_snapshot_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    operation: str = Field(min_length=1, max_length=64)
    record_count: int = Field(ge=0)
    matching_records: int = Field(ge=0)
    commit_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _marker_is_complete(self) -> IcebergSnapshotEvidence:
        if self.matching_records > self.record_count:
            raise ValueError("matching records cannot exceed snapshot records")
        if (self.matching_records > 0) != (self.commit_token is not None):
            raise ValueError("commit_token and matching records must be present together")
        return self


class IcebergReconciliationDecision(_FrozenModel):
    status: Literal[
        "not_committed",
        "cancelled_uncommitted",
        "committed_unacknowledged",
        "already_recorded",
    ]
    advance_source_sync: bool
    retry_provider_write: bool
    publish_data_product: Literal[False] = False
    snapshot_id: str | None = Field(default=None, pattern=r"^[0-9]+$")
    target_commit_ref: dict[str, str] | None = None

    @model_validator(mode="after")
    def _decision_is_consistent(self) -> IcebergReconciliationDecision:
        committed = self.status in {"committed_unacknowledged", "already_recorded"}
        if committed != (self.snapshot_id is not None):
            raise ValueError("committed decisions require one snapshot")
        if committed != (self.target_commit_ref is not None):
            raise ValueError("committed decisions require one target reference")
        if self.advance_source_sync != (self.status == "committed_unacknowledged"):
            raise ValueError("only an unacknowledged exact commit may advance SourceSync")
        if self.retry_provider_write != (self.status == "not_committed"):
            raise ValueError("only an uncommitted active run may retry the provider")
        return self


def reconcile_iceberg_commit(
    intent: IcebergCommitIntent,
    snapshots: tuple[IcebergSnapshotEvidence, ...],
    *,
    cancel_confirmed: bool,
    recorded_snapshot_id: str | None = None,
) -> IcebergReconciliationDecision:
    """Resolve one intent from provider truth without guessing or publishing a product."""

    marked = tuple(item for item in snapshots if item.commit_token == intent.commit_token)
    if any(item.matching_records > intent.expected_matching_records for item in marked):
        raise IcebergCommitReconciliationError(
            "commit token contains more records than the source-slice intent"
        )
    terminal = tuple(
        item for item in marked if item.matching_records == intent.expected_matching_records
    )
    malformed = tuple(
        item
        for item in terminal
        if item.record_count != intent.expected_record_count
        or item.content_sha256 != intent.expected_content_sha256
        or item.operation != "append"
    )
    if malformed:
        raise IcebergCommitReconciliationError(
            "commit token is bound to unexpected Iceberg content"
        )
    if len(terminal) > 1:
        raise IcebergCommitReconciliationError(
            "multiple terminal snapshots are bound to one source slice"
        )
    if marked and not terminal:
        raise IcebergCommitReconciliationError(
            "partial source-slice snapshots require checkpoint recovery"
        )

    if recorded_snapshot_id is not None:
        if len(terminal) != 1 or terminal[0].snapshot_id != recorded_snapshot_id:
            raise IcebergCommitReconciliationError(
                "recorded SourceSync target does not match provider truth"
            )
        candidate = terminal[0]
        return IcebergReconciliationDecision(
            status="already_recorded",
            advance_source_sync=False,
            retry_provider_write=False,
            snapshot_id=candidate.snapshot_id,
            target_commit_ref=_target_ref(intent, candidate),
        )

    if terminal:
        candidate = terminal[0]
        return IcebergReconciliationDecision(
            status="committed_unacknowledged",
            advance_source_sync=True,
            retry_provider_write=False,
            snapshot_id=candidate.snapshot_id,
            target_commit_ref=_target_ref(intent, candidate),
        )

    return IcebergReconciliationDecision(
        status="cancelled_uncommitted" if cancel_confirmed else "not_committed",
        advance_source_sync=False,
        retry_provider_write=not cancel_confirmed,
    )


def _target_ref(
    intent: IcebergCommitIntent,
    snapshot: IcebergSnapshotEvidence,
) -> dict[str, str]:
    return {
        "provider": "iceberg",
        "snapshot_id": snapshot.snapshot_id,
        "parent_snapshot_id": snapshot.parent_snapshot_id or "",
        "operation": snapshot.operation,
        "source_slice_sha256": intent.source_slice_sha256,
        "content_sha256": snapshot.content_sha256,
    }
