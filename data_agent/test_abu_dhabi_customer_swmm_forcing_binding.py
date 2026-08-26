from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from data_agent.uwm.abu_dhabi_flood.customer_event_validation import (
    EventValidationPolicy,
    validate_customer_event_csv,
)
from data_agent.uwm.abu_dhabi_flood.customer_swmm_forcing_binding import (
    bind_customer_boundary_to_swmm,
    bind_customer_rainfall_to_swmm,
)


def _inputs(tmp_path: Path, *, units: str = "mm per interval") -> tuple[Path, Path, Path]:
    csv_path = tmp_path / "rainfall.csv"
    csv_path.write_text(
        "timestamp,value\n2024-04-15T00:00:00Z,1\n2024-04-15T00:15:00Z,2\n2024-04-15T00:30:00Z,3\n",
        encoding="utf-8",
    )
    metadata_path = tmp_path / "rainfall.metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "source_owner": "Abu Dhabi authority",
                "version_or_snapshot": "v1",
                "valid_time_start": "2024-04-15T00:00:00Z",
                "valid_time_end": "2024-04-15T00:30:00Z",
                "timezone": "UTC",
                "units": units,
                "quality_flags": "customer_qc",
                "license_or_reuse_authority": "customer_authorized",
                "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                "customer_authoritative": True,
            }
        ),
        encoding="utf-8",
    )
    swmm_path = tmp_path / "model.inp"
    swmm_path.write_text(
        "[OPTIONS]\n"
        "START_DATE  04/15/2024\nSTART_TIME  00:00:00\n"
        "REPORT_START_DATE  04/15/2024\nREPORT_START_TIME  00:00:00\n"
        "END_DATE  04/18/2024\nEND_TIME  06:00:00\n\n"
        "[RAINGAGES]\nRG_PUBLIC  INTENSITY  01:00  1.0  TIMESERIES  TS_PUBLIC\n\n"
        '[OUTFALLS]\nO1  0.0  FREE  ""  NO\n\n'
        "[TIMESERIES]\nTS_PUBLIC  04/15/2024  00:00  1\n"
        "TS_PUBLIC  04/15/2024  01:00  2\n",
        encoding="ascii",
    )
    return csv_path, metadata_path, swmm_path


def _validated_receipt(tmp_path: Path, csv_path: Path, metadata_path: Path) -> Path:
    validation = validate_customer_event_csv(
        csv_path=csv_path,
        metadata_path=metadata_path,
        output_root=tmp_path / "validation",
        policy=EventValidationPolicy(event_kind="rainfall", cadence_minutes=15),
    )
    assert validation["accepted"] is True
    return tmp_path / "validation/customer_event_validation_receipt.json"


def test_accepted_customer_rainfall_is_bound_as_swmm_volume_series(tmp_path: Path):
    csv_path, metadata_path, swmm_path = _inputs(tmp_path)
    validation_receipt = _validated_receipt(tmp_path, csv_path, metadata_path)
    result = bind_customer_rainfall_to_swmm(
        swmm_input=swmm_path,
        rainfall_csv=csv_path,
        validation_receipt=validation_receipt,
        output_root=tmp_path / "bound",
    )
    assert result["status"] == "customer_rainfall_bound_to_swmm_input_diagnostic_only"
    output = tmp_path / "bound/customer_swmm_with_customer_rainfall.inp"
    text = output.read_text(encoding="ascii")
    assert "RG_PUBLIC  VOLUME  00:15  1.0  TIMESERIES  TS_CUSTOMER" in text
    assert "TS_CUSTOMER  04/15/2024  00:15  2.000000000" in text
    assert "END_TIME  00:45:00" in text
    assert result["admission"]["traditional_model_admitted"] is False


def test_binding_rejects_unaccepted_event_or_unsupported_units(tmp_path: Path):
    csv_path, metadata_path, swmm_path = _inputs(tmp_path, units="inch")
    validation_receipt = _validated_receipt(tmp_path, csv_path, metadata_path)
    with pytest.raises(ValueError, match="swmm_binding_rainfall_units_not_supported"):
        bind_customer_rainfall_to_swmm(
            swmm_input=swmm_path,
            rainfall_csv=csv_path,
            validation_receipt=validation_receipt,
            output_root=tmp_path / "bound",
        )


def test_binding_rejects_public_repository_output(tmp_path: Path):
    csv_path, metadata_path, swmm_path = _inputs(tmp_path)
    validation_receipt = _validated_receipt(tmp_path, csv_path, metadata_path)
    repository = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="outside_public_repository"):
        bind_customer_rainfall_to_swmm(
            swmm_input=swmm_path,
            rainfall_csv=csv_path,
            validation_receipt=validation_receipt,
            output_root=repository / "customer-swmm-output",
        )


def test_accepted_customer_boundary_is_bound_to_swmm_outfall(tmp_path: Path):
    csv_path = tmp_path / "tide.csv"
    csv_path.write_text(
        "timestamp,value\n2024-04-15T00:00:00Z,1.0\n2024-04-15T00:15:00Z,1.1\n",
        encoding="utf-8",
    )
    metadata_path = tmp_path / "tide.metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "source_owner": "Abu Dhabi authority",
                "version_or_snapshot": "v1",
                "valid_time_start": "2024-04-15T00:00:00Z",
                "valid_time_end": "2024-04-15T00:15:00Z",
                "timezone": "UTC",
                "units": "m",
                "vertical_datum": "local datum",
                "quality_flags": "customer_qc",
                "license_or_reuse_authority": "customer_authorized",
                "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                "customer_authoritative": True,
            }
        ),
        encoding="utf-8",
    )
    validation = validate_customer_event_csv(
        csv_path=csv_path,
        metadata_path=metadata_path,
        output_root=tmp_path / "boundary-validation",
        policy=EventValidationPolicy(event_kind="coastal_boundary", cadence_minutes=15),
    )
    assert validation["accepted"] is True
    receipt = tmp_path / "boundary-validation/customer_event_validation_receipt.json"
    _, _, swmm_path = _inputs(tmp_path)
    result = bind_customer_boundary_to_swmm(
        swmm_input=swmm_path,
        boundary_csv=csv_path,
        validation_receipt=receipt,
        output_root=tmp_path / "boundary-bound",
        outfall_id="O1",
    )
    output = tmp_path / "boundary-bound/customer_swmm_with_customer_boundary.inp"
    text = output.read_text(encoding="ascii")
    assert result["status"] == "customer_boundary_bound_to_swmm_outfall_diagnostic_only"
    assert "O1  0.0  TIMESERIES  TS_BOUNDARY  NO" in text
    assert "TS_BOUNDARY  04/15/2024  00:15  1.100000000" in text
    assert result["admission"]["engineering_calibration_admitted"] is False
