"""Controlled land-use actions for parcel counterfactuals."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .transition_matrix import LAND_USE_TRANSITION_MATRIX_SCHEMA, evaluate_transition


LAND_USE_ACTION_SCHEMA = "uwm.geospatial_kernel.land_use_action.v1"


def build_change_land_use_action(
    *,
    parcel_id: str,
    from_land_use_class: str,
    to_land_use_class: str,
    rationale: str,
    snapshot_digest: str,
    dictionary_version: str,
    transition_matrix_version: str,
    requested_at: str,
) -> dict[str, Any]:
    """Build an untrusted action request awaiting server actor binding."""

    return _action(
        action_type="change_land_use_class",
        parcel_id=parcel_id,
        from_land_use_class=from_land_use_class,
        to_land_use_class=to_land_use_class,
        rationale=rationale,
        snapshot_digest=snapshot_digest,
        dictionary_version=dictionary_version,
        transition_matrix_version=transition_matrix_version,
        requested_at=requested_at,
    )


def build_no_change_action(
    *,
    parcel_id: str,
    current_land_use_class: str,
    rationale: str,
    snapshot_digest: str,
    dictionary_version: str,
    transition_matrix_version: str,
    requested_at: str,
) -> dict[str, Any]:
    """Build a baseline action request awaiting server actor binding."""

    return _action(
        action_type="no_change",
        parcel_id=parcel_id,
        from_land_use_class=current_land_use_class,
        to_land_use_class=current_land_use_class,
        rationale=rationale,
        snapshot_digest=snapshot_digest,
        dictionary_version=dictionary_version,
        transition_matrix_version=transition_matrix_version,
        requested_at=requested_at,
    )


def bind_server_actor(action: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
    """Return a copy whose actor identity came from authenticated server context."""

    bound = deepcopy(action)
    bound["actor_id"] = str(actor_id)
    bound["actor_binding"] = "server_authenticated_identity"
    return bound


def validate_land_use_action(
    action: dict[str, Any],
    *,
    parcel: dict[str, Any],
    actual_snapshot_digest: str,
    land_use_dictionary: dict[str, Any],
    transition_matrix: dict[str, Any],
) -> dict[str, Any]:
    """Validate an action against current state and controlled versions."""

    errors: list[str] = []
    if action.get("schema") != LAND_USE_ACTION_SCHEMA:
        errors.append("schema_mismatch")
    if action.get("parcel_id") != parcel.get("node_id"):
        errors.append("parcel_id_mismatch")
    effective_source_class = parcel.get("effective_land_use_class") or parcel.get(
        "current_land_use_class"
    )
    if action.get("from_land_use_class") != effective_source_class:
        errors.append("from_land_use_class_mismatch")
    classes = set(land_use_dictionary.get("classes") or [])
    if action.get("from_land_use_class") not in classes:
        errors.append("unknown_from_land_use_class")
    if action.get("to_land_use_class") not in classes:
        errors.append("unknown_to_land_use_class")
    if action.get("snapshot_digest") != actual_snapshot_digest:
        errors.append("snapshot_digest_mismatch")
    if action.get("dictionary_version") != land_use_dictionary.get("version"):
        errors.append("dictionary_version_mismatch")
    if transition_matrix.get("schema") != LAND_USE_TRANSITION_MATRIX_SCHEMA:
        errors.append("transition_matrix_schema_mismatch")
    if action.get("transition_matrix_version") != transition_matrix.get("version"):
        errors.append("transition_matrix_version_mismatch")
    if transition_matrix.get("dictionary_version") != land_use_dictionary.get("version"):
        errors.append("transition_matrix_dictionary_version_mismatch")
    if action.get("actor_binding") != "server_authenticated_identity" or not action.get(
        "actor_id"
    ):
        errors.append("actor_not_server_bound")
    if not str(action.get("rationale") or "").strip():
        errors.append("rationale_missing")
    if not str(action.get("requested_at") or "").strip():
        errors.append("requested_at_missing")
    action_type = action.get("action_type")
    if action_type not in {"no_change", "change_land_use_class"}:
        errors.append("invalid_action_type")
    if (
        action_type == "change_land_use_class"
        and action.get("from_land_use_class") == action.get("to_land_use_class")
    ):
        errors.append("change_action_requires_distinct_land_use_classes")
    if (
        action_type == "no_change"
        and action.get("from_land_use_class") != action.get("to_land_use_class")
    ):
        errors.append("no_change_action_requires_same_land_use_class")

    transition = evaluate_transition(
        transition_matrix,
        from_land_use_class=str(action.get("from_land_use_class") or ""),
        to_land_use_class=str(action.get("to_land_use_class") or ""),
    )
    if transition["status"] == "prohibited":
        errors.append("transition_prohibited")
    return {
        "valid": not errors,
        "errors": errors,
        "transition": transition,
        "review_required": transition["human_review_required"],
        "approval_claim": False,
    }


def _action(
    *,
    action_type: str,
    parcel_id: str,
    from_land_use_class: str,
    to_land_use_class: str,
    rationale: str,
    snapshot_digest: str,
    dictionary_version: str,
    transition_matrix_version: str,
    requested_at: str,
) -> dict[str, Any]:
    return {
        "schema": LAND_USE_ACTION_SCHEMA,
        "action_type": action_type,
        "parcel_id": str(parcel_id),
        "from_land_use_class": str(from_land_use_class),
        "to_land_use_class": str(to_land_use_class),
        "rationale": str(rationale),
        "snapshot_digest": str(snapshot_digest),
        "dictionary_version": str(dictionary_version),
        "transition_matrix_version": str(transition_matrix_version),
        "requested_at": str(requested_at),
        "actor_id": None,
        "actor_binding": "unbound",
        "approval_claim": False,
    }
