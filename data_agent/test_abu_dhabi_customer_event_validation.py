from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from data_agent.uwm.abu_dhabi_flood.customer_event_validation import (
    EventValidationPolicy,
    validate_customer_event_csv,
)


def _write_inputs(
    tmp_path: Path, *, values: tuple[float, ...] = (1.0, 2.0, 3.0)
) -> tuple[Path, Path]:
    csv_path = tmp_path / "rainfall.csv"
    csv_path.write_text(
        "timestamp,value\n2024-04-15T00:00:00Z,1\n2024-04-15T00:15:00Z,2\n2024-04-15T00:30:00Z,3\n",
        encoding="utf-8",
    )
    metadata = {
        "event_id": "april-2024",
        "source_owner": "Abu Dhabi authority",
        "version_or_snapshot": "v1",
        "valid_time_start": "2024-04-15T00:00:00Z",
        "valid_time_end": "2024-04-15T00:30:00Z",
        "timezone": "UTC",
        "units": "mm per interval",
        "quality_flags": "provided_by_customer",
        "license_or_reuse_authority": "customer_authorized",
        "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "customer_authoritative": True,
    }
    metadata_path = tmp_path / "rainfall.metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return csv_path, metadata_path


def test_valid_customer_rainfall_is_ready_for_engineering_review(tmp_path: Path):
    csv_path, metadata_path = _write_inputs(tmp_path)
    result = validate_customer_event_csv(
        csv_path=csv_path,
        metadata_path=metadata_path,
        output_root=tmp_path / "private-output",
        policy=EventValidationPolicy(event_kind="rainfall", cadence_minutes=15),
    )
    assert result["accepted"] is True
    assert result["status"] == "customer_event_ready_for_engineering_review"
    assert result["quality"]["row_count"] == 3
    assert result["quality"]["cadence_mismatch_count"] == 0
    assert result["admission"]["traditional_model_admitted"] is False
    assert (tmp_path / "private-output/customer_event_validation_receipt.json").is_file()


def test_negative_rainfall_and_irregular_cadence_are_rejected(tmp_path: Path):
    csv_path, metadata_path = _write_inputs(tmp_path)
    csv_path.write_text(
        "timestamp,value\n"
        "2024-04-15T00:00:00Z,1\n"
        "2024-04-15T00:30:00Z,-2\n"
        "2024-04-15T01:00:00Z,3\n",
        encoding="utf-8",
    )
    result = validate_customer_event_csv(
        csv_path=csv_path,
        metadata_path=metadata_path,
        output_root=tmp_path / "private-output",
        policy=EventValidationPolicy(event_kind="rainfall", cadence_minutes=15),
    )
    assert result["accepted"] is False
    assert "sha256_mismatch" in result["reasons"]
    assert "negative_values_not_allowed" in result["reasons"]
    assert "cadence_gap_or_irregularity" in result["reasons"]


def test_public_proxy_and_non_authoritative_metadata_are_rejected(tmp_path: Path):
    csv_path, metadata_path = _write_inputs(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["source_owner"] = "Open-Meteo public proxy"
    metadata["sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    metadata["customer_authoritative"] = False
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    result = validate_customer_event_csv(
        csv_path=csv_path,
        metadata_path=metadata_path,
        output_root=tmp_path / "private-output",
        policy=EventValidationPolicy(event_kind="rainfall", cadence_minutes=15),
    )
    assert result["accepted"] is False
    assert "customer_authority_not_public_proxy" in result["reasons"]
    assert "customer_authoritative_confirmation" in result["reasons"]


def test_dubai_timezone_metadata_normalizes_naive_customer_timestamps(tmp_path: Path):
    csv_path = tmp_path / "tide.csv"
    csv_path.write_text(
        "timestamp,value\n2024-04-15T04:00:00,1.0\n2024-04-15T04:15:00,1.1\n",
        encoding="utf-8",
    )
    metadata = {
        "event_id": "april-2024",
        "source_owner": "Abu Dhabi authority",
        "version_or_snapshot": "v1",
        "valid_time_start": "2024-04-15T04:00:00+04:00",
        "valid_time_end": "2024-04-15T04:15:00+04:00",
        "timezone": "Asia/Dubai",
        "units": "m",
        "vertical_datum": "local datum",
        "quality_flags": "provided_by_customer",
        "license_or_reuse_authority": "customer_authorized",
        "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "customer_authoritative": True,
    }
    metadata_path = tmp_path / "tide.metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    result = validate_customer_event_csv(
        csv_path=csv_path,
        metadata_path=metadata_path,
        output_root=tmp_path / "private-output",
        policy=EventValidationPolicy(event_kind="coastal_boundary", cadence_minutes=15),
    )
    assert result["accepted"] is True
    assert result["quality"]["first_timestamp_utc"] == "2024-04-15T00:00:00+00:00"


def test_event_validator_rejects_public_repository_output(tmp_path: Path):
    csv_path, metadata_path = _write_inputs(tmp_path)
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="outside_public_repository"):
        validate_customer_event_csv(
            csv_path=csv_path,
            metadata_path=metadata_path,
            output_root=repository / "customer-event-output",
            policy=EventValidationPolicy(event_kind="rainfall"),
        )
