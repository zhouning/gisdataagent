"""External registration and holdout-opening receipts for state-prior evaluation."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from .state_prior_transition_protocol import (
    validate_dam_gk_state_prior_transition_protocol,
)

DAM_GK_STATE_PRIOR_PROTOCOL_REGISTRATION_SCHEMA = (
    "gwm.geospatial_kernel.state_prior_transition_protocol_registration.v1"
)
DAM_GK_STATE_PRIOR_HOLDOUT_OPENING_SCHEMA = (
    "gwm.geospatial_kernel.state_prior_transition_holdout_opening.v1"
)
STATE_PRIOR_TRANSITION_REGISTRY_KINDS = (
    "write_once_artifact_store",
    "experiment_registry",
    "signed_timestamp_service",
)

_NO_RESULT_CLAIM_BOUNDARY = {
    "scientific_result_claim": False,
    "transition_skill_improvement_claim": False,
    "policy_causal_effect_claim": False,
    "general_geospatial_world_model_validation_claim": False,
}


def build_state_prior_transition_protocol_registration(
    *,
    protocol: Mapping[str, Any],
    registration_id: str,
    registered_at: str,
    registry_kind: str,
    registry_uri: str,
    registry_record_sha256: str,
    registrar_id: str,
    registry_evidence_ref: str,
    evidence_refs: Sequence[str],
) -> dict[str, Any]:
    """Bind a frozen protocol to an externally persisted write-once registry record."""

    protocol_payload = _require_valid_protocol(protocol)
    if not _nonempty_string(registration_id):
        raise ValueError("state_prior_transition_registration_id_required")
    registered = _require_aware_timestamp(registered_at, "registration_registered_at")
    frozen = _parse_aware_timestamp(protocol_payload["frozen_at"])
    access_boundary = _parse_aware_timestamp(protocol_payload["holdout_access_not_before"])
    if frozen is None or registered < frozen:
        raise ValueError("state_prior_transition_registration_before_protocol_freeze")
    if access_boundary is None or registered >= access_boundary:
        raise ValueError("state_prior_transition_registration_after_holdout_boundary")
    if registry_kind not in STATE_PRIOR_TRANSITION_REGISTRY_KINDS:
        raise ValueError("state_prior_transition_registry_kind_invalid")
    for field, value in (
        ("registry_uri", registry_uri),
        ("registrar_id", registrar_id),
        ("registry_evidence_ref", registry_evidence_ref),
    ):
        if not _nonempty_string(value):
            raise ValueError(f"state_prior_transition_{field}_required")
    if not _valid_sha256(registry_record_sha256):
        raise ValueError("state_prior_transition_registry_record_sha256_invalid")
    normalized_evidence = _unique_nonempty_strings(evidence_refs, "registration_evidence_refs")
    if registry_evidence_ref not in normalized_evidence:
        raise ValueError("state_prior_transition_registry_evidence_not_declared")

    receipt = {
        "schema": DAM_GK_STATE_PRIOR_PROTOCOL_REGISTRATION_SCHEMA,
        "version": "0.1",
        "registration_id": str(registration_id),
        "registered_at": str(registered_at),
        "registry_kind": registry_kind,
        "registry_uri": str(registry_uri),
        "registry_record_sha256": registry_record_sha256,
        "registrar_id": str(registrar_id),
        "registry_evidence_ref": str(registry_evidence_ref),
        "protocol_id": protocol_payload["protocol_id"],
        "protocol_sha256": protocol_payload["protocol_sha256"],
        "protocol_frozen_at": protocol_payload["frozen_at"],
        "holdout_access_not_before": protocol_payload["holdout_access_not_before"],
        "registry_write_once_verified": True,
        "mutable_overwrite_permitted": False,
        "evidence_refs": list(normalized_evidence),
        "claim_boundary": copy.deepcopy(_NO_RESULT_CLAIM_BOUNDARY),
    }
    receipt["registration_receipt_sha256"] = (
        compute_state_prior_transition_protocol_registration_sha256(receipt)
    )
    validation = validate_state_prior_transition_protocol_registration(
        receipt,
        protocol=protocol_payload,
    )
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_protocol_registration:" + ";".join(validation["errors"])
        )
    return receipt


def validate_state_prior_transition_protocol_registration(
    payload: Any,
    *,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate registry identity, chronology, claim boundary and canonical digest."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["registration_receipt_must_be_dictionary"]}
    errors: list[str] = []
    protocol_validation = validate_dam_gk_state_prior_transition_protocol(protocol)
    if not protocol_validation["valid"]:
        errors.extend(f"registration_protocol_{error}" for error in protocol_validation["errors"])
    protocol_values = dict(protocol) if isinstance(protocol, Mapping) else {}
    expected_fields = {
        "schema",
        "version",
        "registration_id",
        "registered_at",
        "registry_kind",
        "registry_uri",
        "registry_record_sha256",
        "registrar_id",
        "registry_evidence_ref",
        "protocol_id",
        "protocol_sha256",
        "protocol_frozen_at",
        "holdout_access_not_before",
        "registry_write_once_verified",
        "mutable_overwrite_permitted",
        "evidence_refs",
        "claim_boundary",
        "registration_receipt_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("registration_receipt_field_set_mismatch")
    if payload.get("schema") != DAM_GK_STATE_PRIOR_PROTOCOL_REGISTRATION_SCHEMA:
        errors.append("registration_receipt_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("registration_receipt_version_mismatch")
    for field in (
        "registration_id",
        "registry_uri",
        "registrar_id",
        "registry_evidence_ref",
    ):
        if not _nonempty_string(payload.get(field)):
            errors.append(f"registration_receipt_{field}_required")
    if payload.get("registry_kind") not in STATE_PRIOR_TRANSITION_REGISTRY_KINDS:
        errors.append("registration_receipt_registry_kind_invalid")
    if not _valid_sha256(payload.get("registry_record_sha256")):
        errors.append("registration_receipt_registry_record_sha256_invalid")
    if payload.get("protocol_id") != protocol_values.get("protocol_id"):
        errors.append("registration_receipt_protocol_id_mismatch")
    if payload.get("protocol_sha256") != protocol_values.get("protocol_sha256"):
        errors.append("registration_receipt_protocol_sha256_mismatch")
    if payload.get("protocol_frozen_at") != protocol_values.get("frozen_at"):
        errors.append("registration_receipt_protocol_frozen_at_mismatch")
    if payload.get("holdout_access_not_before") != protocol_values.get("holdout_access_not_before"):
        errors.append("registration_receipt_holdout_boundary_mismatch")

    registered = _parse_aware_timestamp(payload.get("registered_at"))
    frozen = _parse_aware_timestamp(protocol_values.get("frozen_at"))
    access_boundary = _parse_aware_timestamp(protocol_values.get("holdout_access_not_before"))
    if registered is None:
        errors.append("registration_receipt_registered_at_invalid")
    if registered is not None and frozen is not None and registered < frozen:
        errors.append("registration_receipt_before_protocol_freeze")
    if registered is not None and access_boundary is not None and registered >= access_boundary:
        errors.append("registration_receipt_after_holdout_boundary")
    if payload.get("registry_write_once_verified") is not True:
        errors.append("registration_receipt_write_once_verification_required")
    if payload.get("mutable_overwrite_permitted") is not False:
        errors.append("registration_receipt_mutable_overwrite_must_be_false")
    if not _nonempty_strings(payload.get("evidence_refs")):
        errors.append("registration_receipt_evidence_refs_invalid")
    elif payload.get("registry_evidence_ref") not in payload["evidence_refs"]:
        errors.append("registration_receipt_registry_evidence_not_declared")
    if payload.get("claim_boundary") != _NO_RESULT_CLAIM_BOUNDARY:
        errors.append("registration_receipt_claim_boundary_invalid")
    receipt_sha256 = payload.get("registration_receipt_sha256")
    if not _valid_sha256(receipt_sha256):
        errors.append("registration_receipt_sha256_invalid")
    elif receipt_sha256 != compute_state_prior_transition_protocol_registration_sha256(payload):
        errors.append("registration_receipt_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def build_state_prior_transition_holdout_opening(
    *,
    protocol: Mapping[str, Any],
    registration_receipt: Mapping[str, Any],
    opening_id: str,
    opened_at: str,
    holdout_dataset_id: str,
    holdout_manifest_sha256: str,
    accessor_id: str,
    access_log_ref: str,
    access_log_sha256: str,
    evidence_refs: Sequence[str],
) -> dict[str, Any]:
    """Record first label access for one hash-frozen holdout dataset manifest."""

    protocol_payload = _require_valid_protocol(protocol)
    registration_payload = _require_valid_registration(
        registration_receipt,
        protocol=protocol_payload,
    )
    if not _nonempty_string(opening_id):
        raise ValueError("state_prior_transition_holdout_opening_id_required")
    opened = _require_aware_timestamp(opened_at, "holdout_opened_at")
    registered = _parse_aware_timestamp(registration_payload["registered_at"])
    access_boundary = _parse_aware_timestamp(protocol_payload["holdout_access_not_before"])
    if registered is None or opened <= registered:
        raise ValueError("state_prior_transition_holdout_opened_before_registration")
    if access_boundary is None or opened < access_boundary:
        raise ValueError("state_prior_transition_holdout_opened_before_protocol_boundary")
    for field, value in (
        ("holdout_dataset_id", holdout_dataset_id),
        ("accessor_id", accessor_id),
        ("access_log_ref", access_log_ref),
    ):
        if not _nonempty_string(value):
            raise ValueError(f"state_prior_transition_{field}_required")
    if not _valid_sha256(holdout_manifest_sha256):
        raise ValueError("state_prior_transition_holdout_manifest_sha256_invalid")
    if not _valid_sha256(access_log_sha256):
        raise ValueError("state_prior_transition_access_log_sha256_invalid")
    normalized_evidence = _unique_nonempty_strings(evidence_refs, "holdout_opening_evidence_refs")
    if access_log_ref not in normalized_evidence:
        raise ValueError("state_prior_transition_access_log_evidence_not_declared")

    receipt = {
        "schema": DAM_GK_STATE_PRIOR_HOLDOUT_OPENING_SCHEMA,
        "version": "0.1",
        "opening_id": str(opening_id),
        "opened_at": str(opened_at),
        "accessor_id": str(accessor_id),
        "protocol_id": protocol_payload["protocol_id"],
        "protocol_sha256": protocol_payload["protocol_sha256"],
        "registration_id": registration_payload["registration_id"],
        "registration_receipt_sha256": registration_payload["registration_receipt_sha256"],
        "holdout_dataset_id": str(holdout_dataset_id),
        "holdout_manifest_sha256": holdout_manifest_sha256,
        "access_log_ref": str(access_log_ref),
        "access_log_sha256": access_log_sha256,
        "first_label_access_attested": True,
        "holdout_access_before_registration": False,
        "evidence_refs": list(normalized_evidence),
        "claim_boundary": copy.deepcopy(_NO_RESULT_CLAIM_BOUNDARY),
    }
    receipt["holdout_opening_receipt_sha256"] = (
        compute_state_prior_transition_holdout_opening_sha256(receipt)
    )
    validation = validate_state_prior_transition_holdout_opening(
        receipt,
        protocol=protocol_payload,
        registration_receipt=registration_payload,
    )
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_holdout_opening:" + ";".join(validation["errors"])
        )
    return receipt


def validate_state_prior_transition_holdout_opening(
    payload: Any,
    *,
    protocol: Mapping[str, Any],
    registration_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate first-access chronology and bind it to protocol and registration."""

    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["holdout_opening_receipt_must_be_dictionary"]}
    errors: list[str] = []
    protocol_validation = validate_dam_gk_state_prior_transition_protocol(protocol)
    if not protocol_validation["valid"]:
        errors.extend(f"opening_protocol_{error}" for error in protocol_validation["errors"])
    registration_validation = validate_state_prior_transition_protocol_registration(
        registration_receipt,
        protocol=protocol,
    )
    if not registration_validation["valid"]:
        errors.extend(
            f"opening_registration_{error}" for error in registration_validation["errors"]
        )
    protocol_values = dict(protocol) if isinstance(protocol, Mapping) else {}
    registration_values = (
        dict(registration_receipt) if isinstance(registration_receipt, Mapping) else {}
    )
    expected_fields = {
        "schema",
        "version",
        "opening_id",
        "opened_at",
        "accessor_id",
        "protocol_id",
        "protocol_sha256",
        "registration_id",
        "registration_receipt_sha256",
        "holdout_dataset_id",
        "holdout_manifest_sha256",
        "access_log_ref",
        "access_log_sha256",
        "first_label_access_attested",
        "holdout_access_before_registration",
        "evidence_refs",
        "claim_boundary",
        "holdout_opening_receipt_sha256",
    }
    if set(payload) != expected_fields:
        errors.append("holdout_opening_receipt_field_set_mismatch")
    if payload.get("schema") != DAM_GK_STATE_PRIOR_HOLDOUT_OPENING_SCHEMA:
        errors.append("holdout_opening_receipt_schema_mismatch")
    if payload.get("version") != "0.1":
        errors.append("holdout_opening_receipt_version_mismatch")
    for field in (
        "opening_id",
        "accessor_id",
        "holdout_dataset_id",
        "access_log_ref",
    ):
        if not _nonempty_string(payload.get(field)):
            errors.append(f"holdout_opening_receipt_{field}_required")
    if not _valid_sha256(payload.get("holdout_manifest_sha256")):
        errors.append("holdout_opening_receipt_manifest_sha256_invalid")
    if not _valid_sha256(payload.get("access_log_sha256")):
        errors.append("holdout_opening_receipt_access_log_sha256_invalid")
    if payload.get("protocol_id") != protocol_values.get("protocol_id"):
        errors.append("holdout_opening_receipt_protocol_id_mismatch")
    if payload.get("protocol_sha256") != protocol_values.get("protocol_sha256"):
        errors.append("holdout_opening_receipt_protocol_sha256_mismatch")
    if payload.get("registration_id") != registration_values.get("registration_id"):
        errors.append("holdout_opening_receipt_registration_id_mismatch")
    if payload.get("registration_receipt_sha256") != registration_values.get(
        "registration_receipt_sha256"
    ):
        errors.append("holdout_opening_receipt_registration_sha256_mismatch")

    opened = _parse_aware_timestamp(payload.get("opened_at"))
    registered = _parse_aware_timestamp(registration_values.get("registered_at"))
    access_boundary = _parse_aware_timestamp(protocol_values.get("holdout_access_not_before"))
    if opened is None:
        errors.append("holdout_opening_receipt_opened_at_invalid")
    if opened is not None and registered is not None and opened <= registered:
        errors.append("holdout_opening_receipt_before_registration")
    if opened is not None and access_boundary is not None and opened < access_boundary:
        errors.append("holdout_opening_receipt_before_protocol_boundary")
    if payload.get("first_label_access_attested") is not True:
        errors.append("holdout_opening_receipt_first_access_attestation_required")
    if payload.get("holdout_access_before_registration") is not False:
        errors.append("holdout_opening_receipt_access_before_registration_must_be_false")
    if not _nonempty_strings(payload.get("evidence_refs")):
        errors.append("holdout_opening_receipt_evidence_refs_invalid")
    elif payload.get("access_log_ref") not in payload["evidence_refs"]:
        errors.append("holdout_opening_receipt_access_log_evidence_not_declared")
    if payload.get("claim_boundary") != _NO_RESULT_CLAIM_BOUNDARY:
        errors.append("holdout_opening_receipt_claim_boundary_invalid")
    receipt_sha256 = payload.get("holdout_opening_receipt_sha256")
    if not _valid_sha256(receipt_sha256):
        errors.append("holdout_opening_receipt_sha256_invalid")
    elif receipt_sha256 != compute_state_prior_transition_holdout_opening_sha256(payload):
        errors.append("holdout_opening_receipt_sha256_mismatch")
    return {"valid": not errors, "errors": errors}


def compute_state_prior_transition_protocol_registration_sha256(
    payload: Mapping[str, Any],
) -> str:
    """Compute the canonical protocol-registration receipt digest."""

    return _canonical_sha256(payload, excluded_key="registration_receipt_sha256")


def compute_state_prior_transition_holdout_opening_sha256(
    payload: Mapping[str, Any],
) -> str:
    """Compute the canonical holdout-opening receipt digest."""

    return _canonical_sha256(payload, excluded_key="holdout_opening_receipt_sha256")


def _require_valid_protocol(protocol: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(protocol, Mapping):
        raise ValueError("state_prior_transition_receipt_protocol_required")
    payload = copy.deepcopy(dict(protocol))
    validation = validate_dam_gk_state_prior_transition_protocol(payload)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_receipt_protocol:" + ";".join(validation["errors"])
        )
    return payload


def _require_valid_registration(
    registration_receipt: Mapping[str, Any],
    *,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(registration_receipt, Mapping):
        raise ValueError("state_prior_transition_registration_receipt_required")
    payload = copy.deepcopy(dict(registration_receipt))
    validation = validate_state_prior_transition_protocol_registration(
        payload,
        protocol=protocol,
    )
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_transition_registration_receipt:" + ";".join(validation["errors"])
        )
    return payload


def _canonical_sha256(payload: Mapping[str, Any], *, excluded_key: str) -> str:
    content = {key: value for key, value in dict(payload).items() if key != excluded_key}
    encoded = json.dumps(
        content,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_aware_timestamp(value: Any, field: str) -> datetime:
    parsed = _parse_aware_timestamp(value)
    if parsed is None:
        raise ValueError(f"state_prior_transition_{field}_invalid")
    return parsed


def _parse_aware_timestamp(value: Any) -> datetime | None:
    if not _nonempty_string(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _unique_nonempty_strings(values: Sequence[Any], field_name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"state_prior_transition_{field_name}_must_be_sequence")
    normalized = tuple(str(value).strip() for value in values)
    if not normalized or any(not value for value in normalized):
        raise ValueError(f"state_prior_transition_{field_name}_required")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"state_prior_transition_{field_name}_must_be_unique")
    return normalized


def _nonempty_strings(value: Any) -> bool:
    return bool(
        isinstance(value, list)
        and value
        and all(_nonempty_string(item) for item in value)
        and len(value) == len(set(value))
    )


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
