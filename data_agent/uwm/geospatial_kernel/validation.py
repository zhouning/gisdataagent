"""Validation for closed-world geospatial kernel contracts."""

from __future__ import annotations

from typing import Any

from .contracts import (
    EFFECT_LEVELS,
    GEOSPATIAL_KERNEL_SCHEMA,
    MAX_CLAIM_LEVEL,
    NODE_TYPES,
    PARCEL_LAND_USE_FIELDS,
    RELATION_TYPES,
    STATE_TIMES,
    SUPPORT_LEVELS,
)


def validate_geospatial_kernel_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate semantic closure and the kernel claim ceiling."""

    errors: list[str] = []
    if payload.get("schema") != GEOSPATIAL_KERNEL_SCHEMA:
        errors.append("schema_mismatch")
    _require_exact(payload, "node_types", NODE_TYPES, "node_types_mismatch", errors)
    _require_exact(
        payload, "relation_types", RELATION_TYPES, "relation_types_mismatch", errors
    )
    _require_exact(payload, "state_times", STATE_TIMES, "state_times_mismatch", errors)
    _require_exact(
        payload, "support_levels", SUPPORT_LEVELS, "support_levels_mismatch", errors
    )
    _require_exact(
        payload, "effect_levels", EFFECT_LEVELS, "effect_levels_mismatch", errors
    )
    _require_exact(
        payload,
        "parcel_land_use_fields",
        PARCEL_LAND_USE_FIELDS,
        "parcel_land_use_fields_mismatch",
        errors,
    )
    if not _nonempty_strings(payload.get("evidence_refs")):
        errors.append("evidence_refs_missing")
    if payload.get("trusted_actor_source") != "server_authenticated_identity":
        errors.append("trusted_actor_source_must_be_server_authenticated_identity")
    if (payload.get("claim_boundary") or {}).get("max_claim_level") != MAX_CLAIM_LEVEL:
        errors.append("max_claim_level_exceeds_kernel_boundary")
    if payload.get("empirical_policy_effect_claim") is not False:
        errors.append("empirical_policy_effect_claim_must_be_false")

    enabled = payload.get("enabled_support_levels") or []
    if "learned_calibrated" in enabled and not _nonempty_strings(
        payload.get("calibration_evidence_refs")
    ):
        errors.append("learned_calibrated_requires_calibration_evidence")
    if any(value not in SUPPORT_LEVELS for value in enabled):
        errors.append("enabled_support_levels_invalid")
    return {"valid": not errors, "errors": errors}


def _require_exact(
    payload: dict[str, Any],
    field: str,
    expected: list[str],
    error: str,
    errors: list[str],
) -> None:
    if payload.get(field) != expected:
        errors.append(error)


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )
