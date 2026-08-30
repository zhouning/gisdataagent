"""Contract tests for the generic bitemporal entity authority."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pydantic import ValidationError

from data_agent.temporal_entity_authority import (
    GATEWAY_DATABASE_ROLE,
    TemporalEntityAssertion,
    TemporalEntityAssertionDraft,
    TemporalEntityAuthority,
    TemporalEntityHistoryError,
    TemporalEntityQuery,
    TemporalLifecycleState,
    TemporalMutationKind,
    TemporalQueryMode,
    resolve_temporal_snapshot,
    temporal_transition_allowed,
)

TENANT = "temporal-contract"
ENTITY_REF = f"gda://{TENANT}/entity/parcel-001"
SOURCE_REF = f"gda://{TENANT}/resource_version/source-v1"
EVALUATED_AT = datetime(2026, 8, 14, 12, tzinfo=UTC)


def _at(month: int, day: int = 1) -> datetime:
    return datetime(2026, month, day, 10, tzinfo=UTC)


def _draft(**changes) -> TemporalEntityAssertionDraft:
    values = {
        "tenant_id": TENANT,
        "entity_ref": ENTITY_REF,
        "object_type": "natural_resource.parcel",
        "lifecycle_state": TemporalLifecycleState.ACTIVE,
        "attributes": {"name": "parcel 001"},
        "valid_from": _at(1),
        "valid_to": None,
        "source_version_refs": (SOURCE_REF,),
        "mutation_kind": TemporalMutationKind.INITIAL,
        "supersedes_assertion_id": None,
        "idempotency_key": "parcel-001.initial",
        "owner_subject": "team:natural-resource-governance",
        "recorded_by": "human:data-steward",
        "reason": "record governed entity state",
    }
    values.update(changes)
    return TemporalEntityAssertionDraft(**values)


def _assertion(
    assertion_number: int,
    *,
    recorded_at: datetime,
    **changes,
) -> TemporalEntityAssertion:
    draft = _draft(**changes)
    return TemporalEntityAssertion(
        **draft.model_dump(),
        assertion_id=UUID(f"00000000-0000-4000-8000-{assertion_number:012d}"),
        assertion_sha256=f"{assertion_number:x}" * 64,
        recorded_at=recorded_at,
    )


def _query(mode: TemporalQueryMode, **changes) -> TemporalEntityQuery:
    values = {
        "tenant_id": TENANT,
        "entity_ref": ENTITY_REF,
        "mode": mode,
    }
    values.update(changes)
    return TemporalEntityQuery(**values)


def test_draft_rejects_invalid_time_identity_source_and_correction_shape() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _draft(valid_from=datetime(2026, 1, 1, 10))
    with pytest.raises(ValidationError, match="must use tenant_id"):
        _draft(entity_ref="gda://other/entity/parcel-001")
    with pytest.raises(ValidationError, match="source versions must use tenant_id"):
        _draft(source_version_refs=("gda://other/resource_version/source-v1",))
    with pytest.raises(ValidationError, match="valid_to must be after"):
        _draft(valid_to=_at(1))
    with pytest.raises(ValidationError, match="only corrections require"):
        _draft(
            mutation_kind=TemporalMutationKind.CORRECTION,
            supersedes_assertion_id=None,
        )
    with pytest.raises(ValidationError, match="sorted and unique"):
        _draft(source_version_refs=(SOURCE_REF, SOURCE_REF))


@pytest.mark.parametrize(
    ("mode", "parameters"),
    [
        (TemporalQueryMode.CURRENT, {"valid_at": _at(1)}),
        (TemporalQueryMode.VALID_AT, {}),
        (TemporalQueryMode.KNOWN_AT, {}),
        (TemporalQueryMode.AS_OF, {"known_at": _at(1)}),
    ],
)
def test_query_modes_require_exact_time_axes(mode, parameters) -> None:
    with pytest.raises(ValidationError, match="query requires"):
        _query(mode, **parameters)


def test_current_valid_known_and_as_of_queries_keep_time_axes_independent() -> None:
    draft = _assertion(
        1,
        recorded_at=_at(1, 2),
        lifecycle_state=TemporalLifecycleState.DRAFT,
    )
    active = _assertion(
        2,
        recorded_at=_at(2, 2),
        lifecycle_state=TemporalLifecycleState.ACTIVE,
        valid_from=_at(2),
        mutation_kind=TemporalMutationKind.TRANSITION,
        idempotency_key="parcel-001.active",
    )
    late_suspension = _assertion(
        3,
        recorded_at=_at(7),
        lifecycle_state=TemporalLifecycleState.SUSPENDED,
        valid_from=_at(3),
        mutation_kind=TemporalMutationKind.TRANSITION,
        idempotency_key="parcel-001.suspended",
    )
    history = (draft, active, late_suspension)

    current = resolve_temporal_snapshot(
        history,
        _query(TemporalQueryMode.CURRENT),
        evaluated_at=EVALUATED_AT,
    )
    valid_at = resolve_temporal_snapshot(
        history,
        _query(TemporalQueryMode.VALID_AT, valid_at=_at(2, 15)),
        evaluated_at=EVALUATED_AT,
    )
    known_at = resolve_temporal_snapshot(
        history,
        _query(TemporalQueryMode.KNOWN_AT, known_at=_at(2, 15)),
        evaluated_at=EVALUATED_AT,
    )
    before_late_fact = resolve_temporal_snapshot(
        history,
        _query(
            TemporalQueryMode.AS_OF,
            valid_at=_at(4),
            known_at=_at(6),
        ),
        evaluated_at=EVALUATED_AT,
    )
    after_late_fact = resolve_temporal_snapshot(
        history,
        _query(
            TemporalQueryMode.AS_OF,
            valid_at=_at(4),
            known_at=_at(8),
        ),
        evaluated_at=EVALUATED_AT,
    )

    assert current is not None
    assert current.assertion.assertion_id == late_suspension.assertion_id
    assert valid_at is not None and valid_at.assertion.assertion_id == active.assertion_id
    assert known_at is not None and known_at.assertion.assertion_id == active.assertion_id
    assert before_late_fact is not None
    assert before_late_fact.assertion.assertion_id == active.assertion_id
    assert after_late_fact is not None
    assert after_late_fact.assertion.assertion_id == late_suspension.assertion_id


def test_correction_changes_knowledge_without_overwriting_prior_view() -> None:
    original = _assertion(1, recorded_at=_at(1, 2))
    correction = _assertion(
        2,
        recorded_at=_at(3),
        attributes={"name": "corrected parcel name"},
        mutation_kind=TemporalMutationKind.CORRECTION,
        supersedes_assertion_id=original.assertion_id,
        idempotency_key="parcel-001.correction-1",
    )
    second_correction = _assertion(
        3,
        recorded_at=_at(4),
        attributes={"name": "final parcel name"},
        mutation_kind=TemporalMutationKind.CORRECTION,
        supersedes_assertion_id=correction.assertion_id,
        idempotency_key="parcel-001.correction-2",
    )
    history = (original, correction, second_correction)

    before = resolve_temporal_snapshot(
        history,
        _query(
            TemporalQueryMode.AS_OF,
            valid_at=_at(2),
            known_at=_at(2),
        ),
        evaluated_at=EVALUATED_AT,
    )
    after = resolve_temporal_snapshot(
        history,
        _query(TemporalQueryMode.CURRENT),
        evaluated_at=EVALUATED_AT,
    )

    assert before is not None and before.assertion.assertion_id == original.assertion_id
    assert after is not None
    assert after.assertion.assertion_id == second_correction.assertion_id
    assert after.assertion.attributes["name"] == "final parcel name"


def test_expired_latest_event_does_not_fall_back_to_an_older_state() -> None:
    active = _assertion(1, recorded_at=_at(1, 2))
    retired = _assertion(
        2,
        recorded_at=_at(2, 2),
        lifecycle_state=TemporalLifecycleState.RETIRED,
        valid_from=_at(2),
        valid_to=_at(3),
        mutation_kind=TemporalMutationKind.TRANSITION,
        idempotency_key="parcel-001.retired",
    )

    snapshot = resolve_temporal_snapshot(
        (active, retired),
        _query(TemporalQueryMode.VALID_AT, valid_at=_at(4)),
        evaluated_at=EVALUATED_AT,
    )

    assert snapshot is None


def test_deleted_state_is_returned_as_an_explicit_tombstone() -> None:
    draft = _assertion(
        1,
        recorded_at=_at(1, 2),
        lifecycle_state=TemporalLifecycleState.DRAFT,
    )
    deleted = _assertion(
        2,
        recorded_at=_at(2, 2),
        lifecycle_state=TemporalLifecycleState.DELETED,
        valid_from=_at(2),
        mutation_kind=TemporalMutationKind.TRANSITION,
        idempotency_key="parcel-001.deleted",
    )

    snapshot = resolve_temporal_snapshot(
        (draft, deleted),
        _query(TemporalQueryMode.CURRENT),
        evaluated_at=EVALUATED_AT,
    )

    assert snapshot is not None
    assert snapshot.is_tombstone is True
    assert snapshot.assertion.lifecycle_state is TemporalLifecycleState.DELETED


def test_history_rejects_missing_competing_and_semantically_invalid_corrections() -> None:
    original = _assertion(1, recorded_at=_at(1, 2))
    missing = _assertion(
        2,
        recorded_at=_at(2),
        mutation_kind=TemporalMutationKind.CORRECTION,
        supersedes_assertion_id=UUID("00000000-0000-4000-8000-999999999999"),
        idempotency_key="parcel-001.missing-correction",
    )
    with pytest.raises(TemporalEntityHistoryError, match="target is absent"):
        resolve_temporal_snapshot(
            (original, missing),
            _query(TemporalQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )

    correction_one = _assertion(
        3,
        recorded_at=_at(3),
        mutation_kind=TemporalMutationKind.CORRECTION,
        supersedes_assertion_id=original.assertion_id,
        idempotency_key="parcel-001.competing-1",
    )
    correction_two = _assertion(
        4,
        recorded_at=_at(4),
        mutation_kind=TemporalMutationKind.CORRECTION,
        supersedes_assertion_id=original.assertion_id,
        idempotency_key="parcel-001.competing-2",
    )
    with pytest.raises(TemporalEntityHistoryError, match="competing corrections"):
        resolve_temporal_snapshot(
            (original, correction_one, correction_two),
            _query(TemporalQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )

    changed_state = _assertion(
        5,
        recorded_at=_at(5),
        lifecycle_state=TemporalLifecycleState.SUSPENDED,
        mutation_kind=TemporalMutationKind.CORRECTION,
        supersedes_assertion_id=original.assertion_id,
        idempotency_key="parcel-001.invalid-correction",
    )
    with pytest.raises(TemporalEntityHistoryError, match="cannot change"):
        resolve_temporal_snapshot(
            (original, changed_state),
            _query(TemporalQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )


def test_history_rejects_duplicate_events_invalid_transitions_and_identity_drift() -> None:
    initial = _assertion(
        1,
        recorded_at=_at(1, 2),
        lifecycle_state=TemporalLifecycleState.DRAFT,
    )
    duplicate = _assertion(
        2,
        recorded_at=_at(1, 3),
        lifecycle_state=TemporalLifecycleState.ACTIVE,
        mutation_kind=TemporalMutationKind.TRANSITION,
        idempotency_key="parcel-001.duplicate",
    )
    with pytest.raises(TemporalEntityHistoryError, match="duplicate base"):
        resolve_temporal_snapshot(
            (initial, duplicate),
            _query(TemporalQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )

    invalid_transition = _assertion(
        3,
        recorded_at=_at(2, 2),
        lifecycle_state=TemporalLifecycleState.SUSPENDED,
        valid_from=_at(2),
        mutation_kind=TemporalMutationKind.TRANSITION,
        idempotency_key="parcel-001.invalid-transition",
    )
    with pytest.raises(TemporalEntityHistoryError, match="invalid lifecycle"):
        resolve_temporal_snapshot(
            (initial, invalid_transition),
            _query(TemporalQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )

    changed_owner = _assertion(
        4,
        recorded_at=_at(2, 2),
        lifecycle_state=TemporalLifecycleState.ACTIVE,
        valid_from=_at(2),
        mutation_kind=TemporalMutationKind.TRANSITION,
        idempotency_key="parcel-001.changed-owner",
        owner_subject="team:other-owner",
    )
    with pytest.raises(TemporalEntityHistoryError, match="stable object type or owner"):
        resolve_temporal_snapshot(
            (initial, changed_owner),
            _query(TemporalQueryMode.CURRENT),
            evaluated_at=EVALUATED_AT,
        )


def test_future_knowledge_time_is_rejected() -> None:
    initial = _assertion(1, recorded_at=_at(1, 2))
    query = _query(TemporalQueryMode.KNOWN_AT, known_at=datetime(2027, 1, 1, tzinfo=UTC))

    with pytest.raises(TemporalEntityHistoryError, match="later than evaluated"):
        resolve_temporal_snapshot(
            (initial,),
            query,
            evaluated_at=EVALUATED_AT,
        )


def test_lifecycle_transition_table_is_fail_closed() -> None:
    assert temporal_transition_allowed(
        TemporalLifecycleState.DRAFT,
        TemporalLifecycleState.ACTIVE,
    )
    assert temporal_transition_allowed(
        TemporalLifecycleState.SUSPENDED,
        TemporalLifecycleState.RETIRED,
    )
    assert not temporal_transition_allowed(
        TemporalLifecycleState.DRAFT,
        TemporalLifecycleState.SUSPENDED,
    )
    assert not temporal_transition_allowed(
        TemporalLifecycleState.DELETED,
        TemporalLifecycleState.ACTIVE,
    )


def test_database_transaction_sets_gateway_role_and_local_tenant() -> None:
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    connection.begin.return_value.__enter__.return_value = MagicMock()
    authority = TemporalEntityAuthority(engine=engine)

    with authority._transaction(TENANT) as yielded:
        assert yielded is connection

    connection.exec_driver_sql.assert_called_once_with(
        f'SET LOCAL ROLE "{GATEWAY_DATABASE_ROLE}"'
    )
    tenant_call = connection.execute.call_args_list[0]
    assert "set_config('app.current_tenant'" in str(tenant_call.args[0])
    assert tenant_call.args[1] == {"tenant": TENANT}


def test_migration_is_append_only_tenant_scoped_and_minimum_privilege() -> None:
    sql = (
        Path(__file__).parent / "migrations/160_bitemporal_entity_authority.sql"
    ).read_text(encoding="utf-8")

    for marker in (
        "CREATE TABLE IF NOT EXISTS gda_control.temporal_entity_identity",
        "CREATE TABLE IF NOT EXISTS gda_control.temporal_entity_assertion",
        "record_temporal_entity_assertion",
        "supersedes_assertion_id",
        "uq_gda_temporal_entity_base_event",
        "uq_gda_temporal_entity_correction_target",
        "late temporal transition invalidates its successor",
        "temporal-idempotency|",
        "FORCE ROW LEVEL SECURITY",
        "trg_gda_temporal_entity_identity_immutable",
        "trg_gda_temporal_entity_assertion_immutable",
        "FROM PUBLIC, gda_control_gateway",
        "GRANT SELECT ON TABLE gda_control.temporal_entity_assertion",
        "GRANT EXECUTE ON FUNCTION gda_control.record_temporal_entity_assertion",
    ):
        assert marker in sql
    assert sql.count("FORCE ROW LEVEL SECURITY") == 2
    assert "GRANT INSERT ON TABLE gda_control.temporal_entity" not in sql
    assert "GRANT UPDATE ON TABLE gda_control.temporal_entity" not in sql
    assert "GRANT DELETE ON TABLE gda_control.temporal_entity" not in sql
