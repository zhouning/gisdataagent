from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
import sys
from typing import Any, Mapping


S4_PROJECT_REQUEST_SCHEMA = "uwm.traditional_livability.s4_project_request.v1"

_PROJECT_FIELDS = {
    "actor_id",
    "analysis_area_id",
    "planning_parcel_id",
    "project_description",
    "project_name",
    "uses",
}
_USE_FIELDS = {
    "confirmed_standard_class_id",
    "gfa_m2",
    "human_confirmation",
    "raw_use_type",
    "use_description",
    "use_id",
    "use_name",
}

_DIGEST_CONTRACT = {
    "algorithm": "sha256",
    "encoding": "utf-8",
    "serialization": (
        "canonical_json_sorted_keys_compact_separators_"
        "uses_sorted_by_stable_use_id"
    ),
    "covered_fields": (
        "normalized_project_request_submitted_actor_and_authenticated_actor"
    ),
}


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical payload object keys must be strings")
        return {key: _canonical_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("canonical payload numbers must be finite")
        return value
    raise TypeError(f"unsupported canonical payload value: {type(value).__name__}")


def _estimated_decimal_digits(value: int) -> int:
    bit_length = abs(value).bit_length()
    if bit_length == 0:
        return 1
    return (bit_length * 30103) // 100000 + 1


def _excessive_integer_audit_marker(value: int) -> dict[str, Any]:
    magnitude = abs(value)
    bit_length = magnitude.bit_length()
    byte_length = max(1, (bit_length + 7) // 8)
    digest = sha256()
    digest.update(b"-" if value < 0 else b"+")
    digest.update(magnitude.to_bytes(byte_length, byteorder="big", signed=False))
    return {
        "__raw_audit_marker__": "integer_exceeds_strict_json_digit_limit",
        "type": "int",
        "sign": "negative" if value < 0 else "positive",
        "bit_length": bit_length,
        "sha256": f"sha256:{digest.hexdigest()}",
    }


def _strict_json_audit_value(
    value: Any, *, errors: list[str], path: str = "$"
) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical payload object keys must be strings")
        return {
            key: _strict_json_audit_value(
                value[key],
                errors=errors,
                path=f"{path}.{key}",
            )
            for key in sorted(value)
        }
    if isinstance(value, list):
        return [
            _strict_json_audit_value(
                item,
                errors=errors,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return deepcopy(value)
    if isinstance(value, int):
        digit_limit = sys.get_int_max_str_digits()
        if digit_limit and _estimated_decimal_digits(value) > digit_limit:
            errors.append(f"strict_json_integer_too_large:{path}")
            return _excessive_integer_audit_marker(value)
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical payload numbers must be finite")
        return value
    raise TypeError(f"unsupported canonical payload value: {type(value).__name__}")


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        _canonical_json_value(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(serialized).hexdigest()}"


def _normalized_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _safe_key_repr(key: Any) -> str:
    try:
        rendered = repr(key)
    except Exception:
        rendered = "<repr-unavailable>"
    return rendered if isinstance(rendered, str) else "<repr-not-string>"


def _undeclared_field_errors(
    row: Mapping[Any, Any], *, allowed_fields: set[str], path: str
) -> list[str]:
    string_fields = sorted(
        key for key in row if isinstance(key, str) and key not in allowed_fields
    )
    non_string_fields = sorted(
        (
            type(key).__module__,
            type(key).__qualname__,
            _safe_key_repr(key),
        )
        for key in row
        if not isinstance(key, str)
    )
    errors = [f"{path}undeclared_field:{field}" for field in string_fields]
    errors.extend(
        f"{path}undeclared_non_string_field:{type_name}:{rendered}"
        for _, type_name, rendered in non_string_fields
    )
    return errors


def _normalized_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _normalized_json_value(value[key])
            for key in sorted(value)
            if isinstance(key, str)
        }
    if isinstance(value, list):
        return [_normalized_json_value(item) for item in value]
    if isinstance(value, str):
        return value.strip()
    return deepcopy(value)


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    return f"{prefix}_{_canonical_digest(payload).removeprefix('sha256:')[:20]}"


def _empty_result(actor_id: Any) -> dict[str, Any]:
    return {
        "schema": S4_PROJECT_REQUEST_SCHEMA,
        "valid": False,
        "actor_id": _normalized_string(actor_id),
        "project_id": None,
        "raw_request": None,
        "normalized_request": None,
        "uses": [],
        "total_gfa_m2": None,
        "content_digest": None,
        "digest_contract": deepcopy(_DIGEST_CONTRACT),
        "validation_errors": [],
    }


def _required_string(
    row: Mapping[str, Any], field: str, errors: list[str], *, path: str = ""
) -> str | None:
    value = _normalized_string(row.get(field))
    if value is None:
        errors.append(f"{path}{field}_missing")
    return value


def _optional_string(
    row: Mapping[str, Any], field: str, errors: list[str], *, path: str = ""
) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        errors.append(f"{path}{field}_not_string")
        return None
    return _normalized_string(value)


def _normalize_use(
    row: Mapping[str, Any], index: int, errors: list[str]
) -> dict[str, Any] | None:
    path = f"uses[{index}]."
    errors.extend(
        _undeclared_field_errors(
            row,
            allowed_fields=_USE_FIELDS,
            path=path,
        )
    )
    use_name = _required_string(row, "use_name", errors, path=path)
    raw_use_type = _required_string(row, "raw_use_type", errors, path=path)
    use_description = _optional_string(row, "use_description", errors, path=path)
    confirmed_class = _optional_string(
        row, "confirmed_standard_class_id", errors, path=path
    )

    gfa = row.get("gfa_m2")
    try:
        normalized_gfa = float(gfa)
    except (OverflowError, TypeError, ValueError):
        normalized_gfa = None
    if (
        isinstance(gfa, bool)
        or not isinstance(gfa, (int, float))
        or normalized_gfa is None
        or not math.isfinite(normalized_gfa)
        or normalized_gfa <= 0
    ):
        errors.append(f"{path}gfa_m2_must_be_finite_positive_number")
        normalized_gfa = None

    human_confirmation = row.get("human_confirmation")
    if human_confirmation is not None and not isinstance(human_confirmation, Mapping):
        errors.append(f"{path}human_confirmation_not_object")
        normalized_confirmation = None
    else:
        normalized_confirmation = (
            _normalized_json_value(human_confirmation)
            if human_confirmation is not None
            else None
        )

    explicit_use_id = row.get("use_id")
    if explicit_use_id is not None and not isinstance(explicit_use_id, str):
        errors.append(f"{path}use_id_not_string")
        use_id = None
    else:
        use_id = _normalized_string(explicit_use_id)
        if explicit_use_id is not None and use_id is None:
            errors.append(f"{path}use_id_missing")

    if any(value is None for value in (use_name, raw_use_type, normalized_gfa)):
        return None

    if use_id is None:
        try:
            use_id = _stable_id(
                "s4use",
                {
                    "use_name": use_name,
                    "raw_use_type": raw_use_type,
                    "use_description": use_description,
                    "confirmed_standard_class_id": confirmed_class,
                    "human_confirmation": normalized_confirmation,
                },
            )
        except (OverflowError, TypeError, ValueError):
            if "content_not_canonical_json" not in errors:
                errors.append("content_not_canonical_json")
            return None

    return {
        "use_id": use_id,
        "use_name": use_name,
        "raw_use_type": raw_use_type,
        "use_description": use_description,
        "gfa_m2": normalized_gfa,
        "confirmed_standard_class_id": confirmed_class,
        "human_confirmation": normalized_confirmation,
    }


def validate_s4_project_request(
    payload: Any, *, actor_id: str
) -> dict[str, Any]:
    result = _empty_result(actor_id)
    errors = result["validation_errors"]

    if result["actor_id"] is None:
        errors.append("actor_id_missing")
    if not isinstance(payload, Mapping):
        errors.append("project_request_not_object")
        return result

    errors.extend(
        _undeclared_field_errors(
            payload,
            allowed_fields=_PROJECT_FIELDS,
            path="project_",
        )
    )

    try:
        raw_request = _strict_json_audit_value(payload, errors=errors)
    except (TypeError, ValueError):
        raw_request = None
        errors.append("content_not_canonical_json")
    result["raw_request"] = raw_request

    analysis_area_id = _required_string(payload, "analysis_area_id", errors)
    planning_parcel_id = _required_string(payload, "planning_parcel_id", errors)
    project_name = _required_string(payload, "project_name", errors)
    project_description = _optional_string(payload, "project_description", errors)
    submitted_actor_id = _optional_string(payload, "actor_id", errors)

    raw_uses = payload.get("uses")
    normalized_uses = []
    if not isinstance(raw_uses, list) or not raw_uses:
        errors.append("uses_missing")
    else:
        for index, row in enumerate(raw_uses):
            if not isinstance(row, Mapping):
                errors.append(f"uses[{index}]_not_object")
                continue
            normalized = _normalize_use(row, index, errors)
            if normalized is not None:
                normalized_uses.append(normalized)

    use_ids = [row["use_id"] for row in normalized_uses]
    if len(use_ids) != len(set(use_ids)):
        errors.append("duplicate_use_id")

    if errors:
        return result

    project_id = _stable_id(
        "s4project",
        {
            "analysis_area_id": analysis_area_id,
            "planning_parcel_id": planning_parcel_id,
            "project_name": project_name,
            "project_description": project_description,
        },
    )
    try:
        total_gfa = math.fsum(row["gfa_m2"] for row in normalized_uses)
    except (OverflowError, TypeError, ValueError):
        errors.append("total_gfa_m2_not_finite")
        return result
    if not math.isfinite(total_gfa) or total_gfa <= 0:
        errors.append("total_gfa_m2_not_finite")
        return result

    allocated_share = 0.0
    uses_with_shares = []
    try:
        for index, row in enumerate(normalized_uses):
            if index == len(normalized_uses) - 1:
                share = 1.0 - allocated_share
            else:
                share = row["gfa_m2"] / total_gfa
                allocated_share += share
            if not math.isfinite(share) or share <= 0:
                raise ValueError("GFA share must be finite and positive")
            uses_with_shares.append({**row, "gfa_share": share})
    except (OverflowError, TypeError, ValueError):
        errors.append("gfa_share_not_finite")
        return result

    normalized_request = {
        "analysis_area_id": analysis_area_id,
        "planning_parcel_id": planning_parcel_id,
        "project_name": project_name,
        "project_description": project_description,
        "uses": deepcopy(normalized_uses),
    }
    digest_payload = {
        "schema": S4_PROJECT_REQUEST_SCHEMA,
        "actor_id": result["actor_id"],
        "submitted_actor_id": submitted_actor_id,
        "project_id": project_id,
        "normalized_request": {
            **normalized_request,
            "uses": sorted(
                deepcopy(normalized_request["uses"]),
                key=lambda row: row["use_id"],
            ),
        },
    }

    result.update(
        {
            "valid": True,
            "project_id": project_id,
            "normalized_request": normalized_request,
            "uses": uses_with_shares,
            "total_gfa_m2": total_gfa,
            "content_digest": _canonical_digest(digest_payload),
        }
    )
    return result
