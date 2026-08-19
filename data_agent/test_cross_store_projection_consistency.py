from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from data_agent.cross_store_projection_consistency import (
    InMemoryProjectionCheckpointLedger,
    ProjectionCheckpoint,
    ProjectionCheckpointConflictError,
    ProjectionConsistencyError,
    ProjectionDesiredState,
    ProjectionEngine,
    ProjectionTargetObservation,
    assess_projection_consistency,
    build_projection_checkpoint_from_repair,
    build_projection_repair_plan,
    projection_checkpoint_fingerprint,
)

TENANT = "cq-test"
PROJECTION = "cq.land_parcel"
SOURCE_SHA = "a" * 64
SOURCE_SHA_2 = "d" * 64
TARGET_SHA = "b" * 64
TARGET_SHA_2 = "c" * 64
NOW = datetime(2026, 8, 14, 16, 0, tzinfo=UTC)


def _desired(**overrides) -> ProjectionDesiredState:
    values = {
        "tenant_id": TENANT,
        "projection_id": PROJECTION,
        "source_resource_version_ref": "gda://cq-test/data_product/cq-land-v1",
        "source_content_sha256": SOURCE_SHA,
        "target_engine": ProjectionEngine.POSTGIS,
        "target_ref": "postgis://cq-db/public.land_parcel_current",
        "target_exists": True,
        "expected_target_content_sha256": TARGET_SHA,
        "expected_row_count": 455,
    }
    values.update(overrides)
    return ProjectionDesiredState(**values)


def _observation(**overrides) -> ProjectionTargetObservation:
    values = {
        "tenant_id": TENANT,
        "projection_id": PROJECTION,
        "target_engine": ProjectionEngine.POSTGIS,
        "target_ref": "postgis://cq-db/public.land_parcel_current",
        "target_exists": True,
        "observed_content_sha256": TARGET_SHA,
        "observed_row_count": 455,
        "observed_by": "workload:projection-auditor",
        "observed_at": NOW,
    }
    values.update(overrides)
    return ProjectionTargetObservation(**values)


def _checkpoint(**overrides) -> ProjectionCheckpoint:
    values = {
        "tenant_id": TENANT,
        "projection_id": PROJECTION,
        "source_resource_version_ref": "gda://cq-test/data_product/cq-land-v1",
        "source_content_sha256": SOURCE_SHA,
        "target_engine": ProjectionEngine.POSTGIS,
        "target_ref": "postgis://cq-db/public.land_parcel_current",
        "target_exists": True,
        "target_content_sha256": TARGET_SHA,
        "target_row_count": 455,
        "checkpoint_version": 1,
        "target_commit_ref": {"provider": "postgis", "commit": "v1"},
        "updated_by": "workload:projection-publisher",
        "updated_at": NOW,
    }
    values.update(overrides)
    values["checkpoint_sha256"] = projection_checkpoint_fingerprint(**values)
    return ProjectionCheckpoint(**values)


def test_aligned_projection_is_a_noop():
    result = assess_projection_consistency(_desired(), _observation(), _checkpoint())

    assert result.status == "aligned"
    assert result.action == "noop"
    assert result.reason_codes == ("source_and_target_aligned",)


def test_missing_checkpoint_fails_closed_even_when_target_content_matches():
    result = assess_projection_consistency(_desired(), _observation(), None)

    assert result.status == "checkpoint_missing"
    assert result.action == "fail_closed"


def test_missing_target_requires_rebuild():
    result = assess_projection_consistency(
        _desired(),
        _observation(target_exists=False, observed_content_sha256=None, observed_row_count=0),
        _checkpoint(),
    )

    assert result.status == "target_missing"
    assert result.action == "rebuild"


def test_unwanted_target_requires_delete():
    desired = _desired(
        target_exists=False,
        expected_target_content_sha256=None,
        expected_row_count=0,
    )
    result = assess_projection_consistency(desired, _observation(), _checkpoint())

    assert result.status == "delete_required"
    assert result.action == "delete"


def test_target_drift_fails_closed_before_rebuild():
    result = assess_projection_consistency(
        _desired(),
        _observation(observed_content_sha256=TARGET_SHA_2),
        _checkpoint(),
    )

    assert result.status == "target_drift"
    assert result.action == "fail_closed"


def test_source_advance_with_identical_target_only_advances_checkpoint():
    desired = _desired(source_content_sha256=SOURCE_SHA_2)
    result = assess_projection_consistency(desired, _observation(), _checkpoint())

    assert result.status == "source_advanced_same_target"
    assert result.action == "checkpoint"


def test_source_advance_with_changed_target_requires_rebuild():
    desired = _desired(
        source_content_sha256=SOURCE_SHA_2,
        expected_target_content_sha256=TARGET_SHA_2,
        expected_row_count=456,
    )
    result = assess_projection_consistency(desired, _observation(), _checkpoint())

    assert result.status == "source_advanced"
    assert result.action == "rebuild"


def test_untracked_deleted_target_fails_closed_without_delete_plan_evidence():
    desired = _desired(
        source_content_sha256=SOURCE_SHA_2,
        target_exists=False,
        expected_target_content_sha256=None,
        expected_row_count=0,
    )
    observation = _observation(
        target_exists=False,
        observed_content_sha256=None,
        observed_row_count=0,
    )
    result = assess_projection_consistency(desired, observation, _checkpoint())

    assert result.status == "checkpoint_state_drift"
    assert result.action == "fail_closed"


def test_repair_plan_is_sealed_and_idempotent():
    plan = build_projection_repair_plan(
        _desired(),
        _observation(target_exists=False, observed_content_sha256=None, observed_row_count=0),
        _checkpoint(),
    )
    replay = build_projection_repair_plan(
        _desired(),
        _observation(target_exists=False, observed_content_sha256=None, observed_row_count=0),
        _checkpoint(),
    )

    assert plan.action == "rebuild"
    assert plan.plan_sha256 == replay.plan_sha256
    assert plan.plan_idempotency_key == replay.plan_idempotency_key
    assert plan.requires_operator is False


def test_plan_bound_repair_receipt_creates_the_next_checkpoint():
    previous = _checkpoint()
    plan = build_projection_repair_plan(
        _desired(),
        _observation(target_exists=False, observed_content_sha256=None, observed_row_count=0),
        previous,
    )
    checkpoint = build_projection_checkpoint_from_repair(
        plan,
        _observation(observed_at=NOW + timedelta(seconds=1)),
        target_commit_ref={
            "provider": "postgis",
            "version_table": "public.land_parcel__v2",
            "plan_sha256": plan.plan_sha256,
            "idempotency_key": plan.plan_idempotency_key,
        },
        updated_by="workload:projection-publisher",
        updated_at=NOW + timedelta(seconds=2),
    )

    assert checkpoint.checkpoint_version == 2
    assert checkpoint.target_content_sha256 == TARGET_SHA
    ledger = InMemoryProjectionCheckpointLedger()
    ledger.record(previous)
    assert ledger.record(
        checkpoint,
        previous_checkpoint_sha256=previous.checkpoint_sha256,
    ).created


def test_fail_closed_plan_and_mismatched_receipt_cannot_advance_checkpoint():
    blocked = build_projection_repair_plan(_desired(), _observation(), None)
    with pytest.raises(ProjectionConsistencyError, match="fail-closed"):
        build_projection_checkpoint_from_repair(
            blocked,
            _observation(),
            target_commit_ref={
                "plan_sha256": blocked.plan_sha256,
                "idempotency_key": blocked.plan_idempotency_key,
            },
            updated_by="workload:projection-publisher",
            updated_at=NOW + timedelta(seconds=1),
        )

    rebuild = build_projection_repair_plan(
        _desired(),
        _observation(target_exists=False, observed_content_sha256=None, observed_row_count=0),
        _checkpoint(),
    )
    with pytest.raises(ProjectionConsistencyError, match="desired target state"):
        build_projection_checkpoint_from_repair(
            rebuild,
            _observation(observed_content_sha256=TARGET_SHA_2),
            target_commit_ref={
                "plan_sha256": rebuild.plan_sha256,
                "idempotency_key": rebuild.plan_idempotency_key,
            },
            updated_by="workload:projection-publisher",
            updated_at=NOW + timedelta(seconds=1),
        )


def test_ledger_replay_and_predecessor_conflict_are_explicit():
    ledger = InMemoryProjectionCheckpointLedger()
    first = _checkpoint()

    assert ledger.record(first).created is True
    assert ledger.record(first).created is False

    second_values = first.model_dump()
    second_values.update(
        {
            "source_content_sha256": SOURCE_SHA_2,
            "checkpoint_version": 2,
            "target_commit_ref": {"provider": "postgis", "commit": "v2"},
            "updated_at": NOW + timedelta(minutes=1),
        }
    )
    second_values["checkpoint_sha256"] = projection_checkpoint_fingerprint(
        **second_values
    )
    second = ProjectionCheckpoint(**second_values)

    assert ledger.record(second, previous_checkpoint_sha256=first.checkpoint_sha256).created
    assert len(ledger.history(
        tenant_id=TENANT,
        projection_id=PROJECTION,
        target_engine=ProjectionEngine.POSTGIS,
        target_ref="postgis://cq-db/public.land_parcel_current",
    )) == 2
    third_values = second.model_dump()
    third_values.update(
        {
            "checkpoint_version": 3,
            "target_commit_ref": {"provider": "postgis", "commit": "v3"},
            "updated_at": NOW + timedelta(minutes=2),
        }
    )
    third_values["checkpoint_sha256"] = projection_checkpoint_fingerprint(
        **third_values
    )
    third = ProjectionCheckpoint(**third_values)
    with pytest.raises(ProjectionCheckpointConflictError, match="predecessor"):
        ledger.record(third, previous_checkpoint_sha256="f" * 64)


def test_target_identity_mismatch_is_rejected():
    with pytest.raises(ProjectionConsistencyError, match="target identity"):
        assess_projection_consistency(
            _desired(),
            _observation(target_ref="postgis://cq-db/public.other"),
            _checkpoint(),
        )


def test_checkpoint_fingerprint_is_required():
    values = _checkpoint().model_dump()
    values["checkpoint_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="fingerprint"):
        ProjectionCheckpoint(**values)
