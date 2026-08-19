from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from data_agent.cross_store_projection_authority import PostgresProjectionCheckpointAuthority
from data_agent.cross_store_projection_compensation_checkpoint_admission import (
    build_federated_compensation_checkpoint_admission_request,
)
from data_agent.cross_store_projection_compensation_checkpoint_authority_read import (
    FederatedProjectionCompensationCheckpointAuthorityReadError,
    build_federated_compensation_checkpoint_authority_read_preview,
)
from data_agent.cross_store_projection_consistency import (
    ProjectionCheckpoint,
    projection_checkpoint_fingerprint,
)
from data_agent.test_cross_store_projection_compensation_checkpoint_admission import (
    _admission_inputs,
)


class _ReadOnlyAuthority:
    def __init__(self, current_by_projection=None):
        self.current_by_projection = current_by_projection or {}
        self.current_calls: list[str] = []
        self.record_calls = 0

    def current(self, *, tenant_id, projection_id, target_engine, target_ref):
        self.current_calls.append(projection_id)
        return self.current_by_projection.get(projection_id)

    def record(self, *args, **kwargs):
        self.record_calls += 1
        raise AssertionError("authority read preview must not call record")


def _current_checkpoint(candidate):
    values = {
        "tenant_id": candidate.tenant_id,
        "projection_id": candidate.projection_id,
        "source_resource_version_ref": candidate.source_resource_version_ref,
        "source_content_sha256": candidate.source_content_sha256,
        "target_engine": candidate.target_engine,
        "target_ref": candidate.target_ref,
        "target_exists": candidate.target_exists,
        "target_content_sha256": candidate.target_content_sha256,
        "target_row_count": candidate.target_row_count,
        "checkpoint_version": 1,
        "target_commit_ref": {
            "provider": candidate.target_engine.value,
            "plan_sha256": candidate.source_plan_sha256,
            "idempotency_key": candidate.provider_idempotency_key,
        },
        "updated_by": "workload:checkpoint-authority-test",
        "updated_at": datetime(2026, 8, 17, tzinfo=UTC),
    }
    return ProjectionCheckpoint(
        **values,
        checkpoint_sha256=projection_checkpoint_fingerprint(**values),
    )


def test_authority_read_preview_matches_initial_predecessors_without_writing() -> None:
    candidate_set, plan_set, materialization, repair_plans = _admission_inputs()
    request = build_federated_compensation_checkpoint_admission_request(
        candidate_set,
        plan_set,
        materialization,
        repair_plans,
    )
    authority = _ReadOnlyAuthority()

    preview = build_federated_compensation_checkpoint_authority_read_preview(
        request,
        authority,
    )

    assert preview.authority_current_read_performed is True
    assert preview.all_predecessors_match is True
    assert tuple(snapshot.position for snapshot in preview.snapshots) == (0, 1, 2)
    assert all(snapshot.current_checkpoint_sha256 is None for snapshot in preview.snapshots)
    assert all(snapshot.current_checkpoint_version == 0 for snapshot in preview.snapshots)
    assert preview.authority_admission_performed is False
    assert preview.authority_write_allowed is False
    assert preview.checkpoint_write_allowed is False
    assert preview.compensation_completion_allowed is False
    assert authority.record_calls == 0
    assert len(authority.current_calls) == 3


def test_authority_read_preview_rejects_live_predecessor_drift() -> None:
    candidate_set, plan_set, materialization, repair_plans = _admission_inputs()
    request = build_federated_compensation_checkpoint_admission_request(
        candidate_set,
        plan_set,
        materialization,
        repair_plans,
    )
    authority = _ReadOnlyAuthority(
        {
            candidate_set.candidates[0].projection_id: _current_checkpoint(
                candidate_set.candidates[0]
            )
        }
    )

    with pytest.raises(
        FederatedProjectionCompensationCheckpointAuthorityReadError,
        match="differs from candidate predecessor or version",
    ):
        build_federated_compensation_checkpoint_authority_read_preview(
            request,
            authority,
        )


def test_authority_read_preview_requires_postgresql_authority_configuration() -> None:
    candidate_set, plan_set, materialization, repair_plans = _admission_inputs()
    request = build_federated_compensation_checkpoint_admission_request(
        candidate_set,
        plan_set,
        materialization,
        repair_plans,
    )
    authority = PostgresProjectionCheckpointAuthority(create_engine("sqlite://"))

    with pytest.raises(
        FederatedProjectionCompensationCheckpointAuthorityReadError,
        match="authority current checkpoint read failed",
    ):
        build_federated_compensation_checkpoint_authority_read_preview(
            request,
            authority,
        )
