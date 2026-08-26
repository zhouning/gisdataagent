"""Fail-closed temporal quality checks for incoming customer event data."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .customer_gdb_network import _require_private_output_root

SCHEMA = "gwm.abu_dhabi_flood.customer_event_validation.v1"
SUPPORTED_EVENT_KINDS = {
    "rainfall",
    "coastal_boundary",
    "inundation_observation",
    "pump_operation",
}
_PUBLIC_PROXY_TERMS = (
    "open-meteo",
    "open meteo",
    "public proxy",
    "公开代理",
    "synthetic",
    "合成测试",
)


@dataclass(frozen=True)
class EventValidationPolicy:
    event_kind: str
    timestamp_column: str = "timestamp"
    value_column: str = "value"
    cadence_minutes: int | None = None
    event_id: str | None = None

    def __post_init__(self) -> None:
        if self.event_kind not in SUPPORTED_EVENT_KINDS:
            raise ValueError("customer_event_kind_unsupported")
        if not self.timestamp_column.strip() or not self.value_column.strip():
            raise ValueError("customer_event_column_required")
        if self.cadence_minutes is not None and self.cadence_minutes < 1:
            raise ValueError("customer_event_cadence_invalid")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata_tzinfo(metadata_timezone: str) -> tzinfo:
    normalized = metadata_timezone.strip()
    upper = normalized.upper()
    if upper in {"UTC", "GMT", "Z"}:
        return UTC
    if upper in {"GST", "UAE"}:
        return timezone(timedelta(hours=4))
    if normalized.startswith(("+", "-")):
        try:
            offset = datetime.fromisoformat(f"2000-01-01T00:00:00{normalized}").utcoffset()
        except ValueError as error:
            raise ValueError("customer_event_metadata_timezone_invalid") from error
        if offset is None:
            raise ValueError("customer_event_metadata_timezone_invalid")
        return timezone(offset)
    try:
        return ZoneInfo(normalized)
    except ZoneInfoNotFoundError as error:
        raise ValueError("customer_event_metadata_timezone_invalid") from error


def _parse_timestamp(raw: str, metadata_timezone: str | None) -> datetime:
    value = raw.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        if not metadata_timezone:
            raise ValueError("customer_event_timestamp_timezone_missing")
        parsed = parsed.replace(tzinfo=_metadata_tzinfo(metadata_timezone))
    return parsed.astimezone(UTC)


def _float_value(raw: str) -> float:
    value = float(raw.strip())
    if not math.isfinite(value):
        raise ValueError("customer_event_nonfinite_value")
    return value


def _metadata_value(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, "", []):
            return str(value).strip()
    return ""


def _metadata_checks(metadata: dict[str, Any], event_kind: str) -> list[str]:
    required = (
        "source_owner",
        "version_or_snapshot",
        "valid_time_start",
        "valid_time_end",
        "timezone",
        "units",
        "quality_flags",
        "license_or_reuse_authority",
        "sha256",
    )
    missing = [key for key in required if not _metadata_value(metadata, key)]
    if event_kind in {"coastal_boundary", "inundation_observation"} and not _metadata_value(
        metadata, "vertical_datum"
    ):
        missing.append("vertical_datum")
    source = " ".join(
        _metadata_value(metadata, key)
        for key in ("source_owner", "license_or_reuse_authority", "notes")
    ).casefold()
    if any(term in source for term in _PUBLIC_PROXY_TERMS):
        missing.append("customer_authority_not_public_proxy")
    if metadata.get("customer_authoritative") is not True:
        missing.append("customer_authoritative_confirmation")
    return missing


def validate_customer_event_csv(
    *,
    csv_path: Path,
    metadata_path: Path,
    output_root: Path,
    policy: EventValidationPolicy,
) -> dict[str, Any]:
    """Validate one customer event CSV and write a private receipt."""

    csv_source = csv_path.expanduser().resolve()
    metadata_source = metadata_path.expanduser().resolve()
    destination = _require_private_output_root(output_root)
    if not csv_source.is_file() or not metadata_source.is_file():
        raise ValueError("customer_event_source_missing")
    metadata = json.loads(metadata_source.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("customer_event_metadata_object_required")
    expected_hash = _metadata_value(metadata, "sha256").casefold()
    actual_hash = _sha256(csv_source)
    reasons = _metadata_checks(metadata, policy.event_kind)
    if expected_hash != actual_hash:
        reasons.append("sha256_mismatch")
    metadata_timezone = _metadata_value(metadata, "timezone")
    valid_start_raw = _metadata_value(metadata, "valid_time_start")
    valid_end_raw = _metadata_value(metadata, "valid_time_end")
    try:
        valid_start = _parse_timestamp(valid_start_raw, metadata_timezone)
        valid_end = _parse_timestamp(valid_end_raw, metadata_timezone)
    except (TypeError, ValueError) as error:
        reasons.append(str(error))
        valid_start = valid_end = None
    if valid_start is not None and valid_end is not None and valid_end <= valid_start:
        reasons.append("metadata_event_window_invalid")
    rows: list[dict[str, Any]] = []
    headers: list[str] = []
    try:
        with csv_source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = [str(value) for value in (reader.fieldnames or [])]
            if policy.timestamp_column not in headers or policy.value_column not in headers:
                reasons.append("required_csv_columns_missing")
            else:
                for row_number, row in enumerate(reader, start=2):
                    timestamp = _parse_timestamp(
                        str(row.get(policy.timestamp_column, "")), metadata_timezone
                    )
                    value = _float_value(str(row.get(policy.value_column, "")))
                    rows.append(
                        {
                            "row_number": row_number,
                            "timestamp": timestamp,
                            "value": value,
                        }
                    )
    except (OSError, UnicodeError, csv.Error, TypeError, ValueError) as error:
        reasons.append(str(error))
    if not rows:
        reasons.append("event_rows_missing")
    timestamps = [row["timestamp"] for row in rows]
    values = [row["value"] for row in rows]
    duplicate_count = sum(
        1 for before, after in zip(timestamps, timestamps[1:], strict=False) if after == before
    )
    out_of_order_count = sum(
        1 for before, after in zip(timestamps, timestamps[1:], strict=False) if after < before
    )
    deltas_minutes = [
        int((after - before).total_seconds() / 60.0)
        for before, after in zip(timestamps, timestamps[1:], strict=False)
        if after > before
    ]
    expected_cadence = policy.cadence_minutes
    if expected_cadence is None and deltas_minutes:
        expected_cadence = min(deltas_minutes)
    cadence_mismatch_count = (
        sum(delta != expected_cadence for delta in deltas_minutes)
        if expected_cadence is not None
        else 0
    )
    if duplicate_count:
        reasons.append("duplicate_timestamps")
    if out_of_order_count:
        reasons.append("timestamps_not_sorted")
    if cadence_mismatch_count:
        reasons.append("cadence_gap_or_irregularity")
    if valid_start is not None and valid_end is not None:
        outside_window = sum(
            timestamp < valid_start or timestamp > valid_end for timestamp in timestamps
        )
        if outside_window:
            reasons.append("timestamps_outside_metadata_window")
    invalid_value_count = 0
    if policy.event_kind in {"rainfall", "inundation_observation"}:
        invalid_value_count = sum(value < 0.0 for value in values)
        if invalid_value_count:
            reasons.append("negative_values_not_allowed")
    accepted = not reasons
    result = {
        "schema": SCHEMA,
        "version": "2026-08-23",
        "status": "customer_event_ready_for_engineering_review"
        if accepted
        else "customer_event_requires_action",
        "source": {
            "csv": str(csv_source),
            "metadata": str(metadata_source),
            "csv_sha256": actual_hash,
            "metadata_sha256": _sha256(metadata_source),
            "customer_rows_copied_to_public_repository": False,
        },
        "policy": {
            "event_kind": policy.event_kind,
            "timestamp_column": policy.timestamp_column,
            "value_column": policy.value_column,
            "expected_cadence_minutes": policy.cadence_minutes,
            "event_id": policy.event_id,
        },
        "metadata": {
            "event_id": _metadata_value(metadata, "event_id"),
            "source_owner": _metadata_value(metadata, "source_owner"),
            "version_or_snapshot": _metadata_value(metadata, "version_or_snapshot"),
            "timezone": metadata_timezone,
            "units": _metadata_value(metadata, "units"),
            "vertical_datum": _metadata_value(metadata, "vertical_datum"),
            "customer_authoritative": metadata.get("customer_authoritative") is True,
        },
        "quality": {
            "header_columns": headers,
            "row_count": len(rows),
            "first_timestamp_utc": timestamps[0].isoformat() if timestamps else None,
            "last_timestamp_utc": timestamps[-1].isoformat() if timestamps else None,
            "minimum_value": min(values) if values else None,
            "maximum_value": max(values) if values else None,
            "duplicate_timestamp_count": duplicate_count,
            "out_of_order_count": out_of_order_count,
            "expected_cadence_minutes": expected_cadence,
            "cadence_mismatch_count": cadence_mismatch_count,
            "negative_value_count": invalid_value_count,
        },
        "accepted": accepted,
        "reasons": reasons,
        "admission": {
            "ready_for_engineering_review": accepted,
            "traditional_model_admitted": False,
            "engineering_calibration_admitted": False,
            "gwm_training_admitted": False,
            "city_scale_prediction_claim_allowed": False,
            "note": (
                "Temporal QC does not replace hydraulic calibration, spatial crosswalk, "
                "or independent event validation."
            ),
        },
    }
    destination.mkdir(parents=True, exist_ok=True)
    receipt = destination / "customer_event_validation_receipt.json"
    receipt.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
