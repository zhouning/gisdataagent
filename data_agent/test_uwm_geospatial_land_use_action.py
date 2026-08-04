import pytest

from data_agent.uwm.geospatial_kernel.land_use_action import (
    LAND_USE_ACTION_SCHEMA,
    bind_server_actor,
    build_change_land_use_action,
    build_no_change_action,
    validate_land_use_action,
)
from data_agent.uwm.geospatial_kernel.transition_matrix import (
    LAND_USE_TRANSITION_MATRIX_SCHEMA,
    build_transition_matrix,
    evaluate_transition,
)


SNAPSHOT_DIGEST = "a" * 64


def _parcel() -> dict:
    return {
        "node_id": "parcel-1",
        "node_type": "parcel",
        "current_land_use_class": "residential",
        "planned_land_use_class": "public_service",
        "candidate_land_use_class": None,
        "source_land_use_code": "0701",
    }


def _dictionary() -> dict:
    return {
        "schema": "uwm.land_use_dictionary.v1",
        "version": "dict-v1",
        "classes": ["residential", "public_service", "commercial"],
    }


def _matrix() -> dict:
    return build_transition_matrix(
        version="matrix-v1",
        dictionary_version="dict-v1",
        rules=[
            {
                "from_land_use_class": "residential",
                "to_land_use_class": "public_service",
                "status": "conditionally_allowed",
                "authority_refs": ["authority:rule-1"],
                "conditions": ["planning_review_required"],
            },
            {
                "from_land_use_class": "residential",
                "to_land_use_class": "commercial",
                "status": "prohibited",
                "authority_refs": ["authority:rule-2"],
                "conditions": [],
            },
        ],
    )


def test_transition_matrix_is_versioned_and_fail_closed():
    matrix = _matrix()

    assert matrix["schema"] == LAND_USE_TRANSITION_MATRIX_SCHEMA
    assert evaluate_transition(
        matrix,
        from_land_use_class="residential",
        to_land_use_class="public_service",
    )["status"] == "conditionally_allowed"
    unresolved = evaluate_transition(
        matrix,
        from_land_use_class="public_service",
        to_land_use_class="commercial",
    )
    assert unresolved["status"] == "unresolved"
    assert unresolved["human_review_required"] is True
    assert unresolved["approval_claim"] is False


def test_transition_matrix_same_class_is_no_change_not_approval():
    result = evaluate_transition(
        _matrix(),
        from_land_use_class="residential",
        to_land_use_class="residential",
    )

    assert result["status"] == "no_change"
    assert result["can_enter_rollout"] is True
    assert result["approval_claim"] is False


def test_change_action_requires_server_bound_actor_before_validation():
    action = build_change_land_use_action(
        parcel_id="parcel-1",
        from_land_use_class="residential",
        to_land_use_class="public_service",
        rationale="公共服务情景比较",
        snapshot_digest=SNAPSHOT_DIGEST,
        dictionary_version="dict-v1",
        transition_matrix_version="matrix-v1",
        requested_at="2026-07-11T08:00:00Z",
    )

    assert action["schema"] == LAND_USE_ACTION_SCHEMA
    assert action["actor_binding"] == "unbound"
    validation = validate_land_use_action(
        action,
        parcel=_parcel(),
        actual_snapshot_digest=SNAPSHOT_DIGEST,
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
    )
    assert not validation["valid"]
    assert "actor_not_server_bound" in validation["errors"]

    bound = bind_server_actor(action, actor_id="user-123")
    valid = validate_land_use_action(
        bound,
        parcel=_parcel(),
        actual_snapshot_digest=SNAPSHOT_DIGEST,
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
    )
    assert valid["valid"], valid["errors"]
    assert valid["transition"]["status"] == "conditionally_allowed"
    assert valid["review_required"] is True
    assert valid["approval_claim"] is False


@pytest.mark.parametrize(
    ("mutator", "error"),
    [
        (lambda action: action.update({"parcel_id": "parcel-missing"}), "parcel_id_mismatch"),
        (
            lambda action: action.update({"from_land_use_class": "commercial"}),
            "from_land_use_class_mismatch",
        ),
        (lambda action: action.update({"to_land_use_class": "unknown"}), "unknown_to_land_use_class"),
        (lambda action: action.update({"snapshot_digest": "b" * 64}), "snapshot_digest_mismatch"),
        (lambda action: action.update({"dictionary_version": "dict-old"}), "dictionary_version_mismatch"),
        (
            lambda action: action.update({"transition_matrix_version": "matrix-old"}),
            "transition_matrix_version_mismatch",
        ),
        (lambda action: action.update({"actor_binding": "client_payload"}), "actor_not_server_bound"),
    ],
)
def test_change_action_rejects_stale_unknown_or_client_trusted_requests(mutator, error):
    action = bind_server_actor(
        build_change_land_use_action(
            parcel_id="parcel-1",
            from_land_use_class="residential",
            to_land_use_class="public_service",
            rationale="公共服务情景比较",
            snapshot_digest=SNAPSHOT_DIGEST,
            dictionary_version="dict-v1",
            transition_matrix_version="matrix-v1",
            requested_at="2026-07-11T08:00:00Z",
        ),
        actor_id="user-123",
    )
    mutator(action)

    validation = validate_land_use_action(
        action,
        parcel=_parcel(),
        actual_snapshot_digest=SNAPSHOT_DIGEST,
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
    )

    assert not validation["valid"]
    assert error in validation["errors"]


def test_change_action_rejects_no_change_disguised_as_change():
    action = bind_server_actor(
        build_change_land_use_action(
            parcel_id="parcel-1",
            from_land_use_class="residential",
            to_land_use_class="residential",
            rationale="不应伪装变更",
            snapshot_digest=SNAPSHOT_DIGEST,
            dictionary_version="dict-v1",
            transition_matrix_version="matrix-v1",
            requested_at="2026-07-11T08:00:00Z",
        ),
        actor_id="user-123",
    )

    validation = validate_land_use_action(
        action,
        parcel=_parcel(),
        actual_snapshot_digest=SNAPSHOT_DIGEST,
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
    )

    assert not validation["valid"]
    assert "change_action_requires_distinct_land_use_classes" in validation["errors"]


def test_no_change_action_validates_without_fabricating_approval():
    action = bind_server_actor(
        build_no_change_action(
            parcel_id="parcel-1",
            current_land_use_class="residential",
            rationale="反事实基线",
            snapshot_digest=SNAPSHOT_DIGEST,
            dictionary_version="dict-v1",
            transition_matrix_version="matrix-v1",
            requested_at="2026-07-11T08:00:00Z",
        ),
        actor_id="user-123",
    )

    validation = validate_land_use_action(
        action,
        parcel=_parcel(),
        actual_snapshot_digest=SNAPSHOT_DIGEST,
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
    )

    assert validation["valid"], validation["errors"]
    assert validation["transition"]["status"] == "no_change"
    assert validation["approval_claim"] is False


def test_change_action_uses_effective_class_for_a_future_scenario_state():
    future_parcel = {
        **_parcel(),
        "effective_land_use_class": "public_service",
        "candidate_land_use_class": "public_service",
        "state_time": "t1_post_change",
    }
    action = bind_server_actor(
        build_change_land_use_action(
            parcel_id="parcel-1",
            from_land_use_class="public_service",
            to_land_use_class="commercial",
            rationale="在第一步情景状态上继续推演",
            snapshot_digest=SNAPSHOT_DIGEST,
            dictionary_version="dict-v1",
            transition_matrix_version="matrix-v1",
            requested_at="2026-07-11T08:01:00Z",
        ),
        actor_id="user-123",
    )

    validation = validate_land_use_action(
        action,
        parcel=future_parcel,
        actual_snapshot_digest=SNAPSHOT_DIGEST,
        land_use_dictionary=_dictionary(),
        transition_matrix=_matrix(),
    )

    assert validation["valid"], validation["errors"]
    assert validation["transition"]["status"] == "unresolved"
    assert validation["review_required"] is True
