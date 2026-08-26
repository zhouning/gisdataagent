"""Bind accepted customer rainfall and coastal boundary series into SWMM."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .customer_event_validation import _parse_timestamp
from .customer_gdb_network import _require_private_output_root

SCHEMA = "gwm.abu_dhabi_flood.customer_swmm_forcing_binding.v1"
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_UNIT_ALIASES = {
    "mm": "volume",
    "mm per interval": "volume",
    "mm/interval": "volume",
    "mm per hour": "intensity",
    "mm/hour": "intensity",
    "mm/hr": "intensity",
}


def _swmm_interval(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _section_bounds(lines: list[str], name: str) -> tuple[int, int]:
    wanted = name.casefold()
    starts = [
        index
        for index, line in enumerate(lines)
        if (match := _SECTION_RE.match(line)) and match.group(1).casefold() == wanted
    ]
    if len(starts) != 1:
        raise ValueError(f"swmm_binding_section_count_invalid:{name}")
    start = starts[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if _SECTION_RE.match(lines[index])),
        len(lines),
    )
    return start, end


def _active_rows(lines: list[str]) -> list[tuple[int, list[str]]]:
    rows = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(";;") or stripped.startswith("#"):
            continue
        rows.append((index, stripped.split()))
    return rows


def _replace_option(lines: list[str], option: str, value: str) -> None:
    start, end = _section_bounds(lines, "OPTIONS")
    option_upper = option.upper()
    for index in range(start + 1, end):
        stripped = lines[index].strip()
        if (
            stripped
            and not stripped.startswith(";")
            and stripped.split()[0].upper() == option_upper
        ):
            lines[index] = f"{option}  {value}\n"
            return
    raise ValueError(f"swmm_binding_option_missing:{option}")


def _replace_timeseries(
    lines: list[str],
    *,
    source_timeseries_id: str,
    timeseries_id: str,
    rows: list[tuple[datetime, float]],
) -> int:
    start, end = _section_bounds(lines, "TIMESERIES")
    matching = []
    for index, tokens in _active_rows(lines[start + 1 : end]):
        if tokens and tokens[0] == source_timeseries_id:
            matching.append(start + 1 + index)
    if not matching:
        raise ValueError("swmm_binding_source_timeseries_missing")
    replacement = [
        f"{timeseries_id}  {timestamp.strftime('%m/%d/%Y')}  "
        f"{timestamp.strftime('%H:%M')}  {value:.9f}\n"
        for timestamp, value in rows
    ]
    first = matching[0]
    matching_set = set(matching)
    new_section = []
    for index in range(start + 1, end):
        if index == first:
            new_section.extend(replacement)
        if index not in matching_set:
            new_section.append(lines[index])
    lines[start + 1 : end] = new_section
    return len(matching)


def _replace_raingage(
    lines: list[str],
    *,
    raingage_id: str,
    timeseries_id: str,
    source_timeseries_id: str,
    format_name: str,
    interval: str,
) -> None:
    start, end = _section_bounds(lines, "RAINGAGES")
    for index, tokens in _active_rows(lines[start + 1 : end]):
        if tokens and tokens[0] == raingage_id:
            lines[start + 1 + index] = (
                f"{raingage_id}  {format_name}  {interval}  1.0  TIMESERIES  {timeseries_id}\n"
            )
            return
    if source_timeseries_id and any(
        tokens and tokens[0] == source_timeseries_id
        for _, tokens in _active_rows(lines[start + 1 : end])
    ):
        raise ValueError("swmm_binding_raingage_id_not_found")
    raise ValueError("swmm_binding_raingage_missing")


def _option_value(lines: list[str], option: str) -> str:
    start, end = _section_bounds(lines, "OPTIONS")
    wanted = option.upper()
    for index in range(start + 1, end):
        tokens = lines[index].strip().split()
        if tokens and tokens[0].upper() == wanted and len(tokens) >= 2:
            return tokens[1]
    raise ValueError(f"swmm_binding_option_missing:{option}")


def _model_window(lines: list[str]) -> tuple[datetime, datetime]:
    def parse(date_value: str, time_value: str) -> datetime:
        for pattern in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
            try:
                return datetime.strptime(f"{date_value} {time_value}", pattern).replace(tzinfo=UTC)
            except ValueError:
                continue
        raise ValueError("swmm_binding_model_datetime_invalid")

    start = parse(_option_value(lines, "START_DATE"), _option_value(lines, "START_TIME"))
    end = parse(_option_value(lines, "END_DATE"), _option_value(lines, "END_TIME"))
    if end <= start:
        raise ValueError("swmm_binding_model_window_invalid")
    return start, end


def _append_timeseries(
    lines: list[str],
    *,
    timeseries_id: str,
    rows: list[tuple[datetime, float]],
) -> None:
    start, end = _section_bounds(lines, "TIMESERIES")
    for _, tokens in _active_rows(lines[start + 1 : end]):
        if tokens and tokens[0] == timeseries_id:
            raise ValueError("swmm_binding_timeseries_id_already_exists")
    lines[end:end] = [
        f"{timeseries_id}  {timestamp.strftime('%m/%d/%Y')}  "
        f"{timestamp.strftime('%H:%M')}  {value:.9f}\n"
        for timestamp, value in rows
    ]


def _replace_outfall_boundary(
    lines: list[str],
    *,
    outfall_id: str,
    timeseries_id: str,
) -> None:
    start, end = _section_bounds(lines, "OUTFALLS")
    for index, tokens in _active_rows(lines[start + 1 : end]):
        if tokens and tokens[0] == outfall_id:
            if len(tokens) < 2:
                raise ValueError("swmm_binding_outfall_row_invalid")
            gated = tokens[4] if len(tokens) >= 5 else "NO"
            route = "  " + "  ".join(tokens[5:]) if len(tokens) > 5 else ""
            lines[start + 1 + index] = (
                f"{outfall_id}  {tokens[1]}  TIMESERIES  {timeseries_id}  {gated}{route}\n"
            )
            return
    raise ValueError("swmm_binding_outfall_id_not_found")


def _read_series(
    csv_path: Path,
    *,
    timestamp_column: str,
    value_column: str,
    timezone_name: str,
) -> list[tuple[datetime, float]]:
    result: list[tuple[datetime, float]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if timestamp_column not in (reader.fieldnames or []) or value_column not in (
            reader.fieldnames or []
        ):
            raise ValueError("swmm_binding_rainfall_columns_missing")
        for row in reader:
            timestamp = _parse_timestamp(str(row.get(timestamp_column, "")), timezone_name)
            value = float(str(row.get(value_column, "")).strip())
            if not math.isfinite(value):
                raise ValueError("swmm_binding_rainfall_value_nonfinite")
            result.append((timestamp, value))
    if not result:
        raise ValueError("swmm_binding_rainfall_rows_missing")
    if any(after <= before for before, after in zip(result, result[1:], strict=False)):
        raise ValueError("swmm_binding_rainfall_timestamps_not_strictly_increasing")
    return result


def bind_customer_rainfall_to_swmm(
    *,
    swmm_input: Path,
    rainfall_csv: Path,
    validation_receipt: Path,
    output_root: Path,
    output_name: str = "customer_swmm_with_customer_rainfall.inp",
    source_timeseries_id: str = "TS_PUBLIC",
    timeseries_id: str = "TS_CUSTOMER",
    raingage_id: str = "RG_PUBLIC",
    timestamp_column: str = "timestamp",
    value_column: str = "value",
) -> dict[str, Any]:
    """Bind one accepted rainfall event into a private SWMM input."""

    input_path = swmm_input.expanduser().resolve()
    rainfall_path = rainfall_csv.expanduser().resolve()
    receipt_path = validation_receipt.expanduser().resolve()
    destination = _require_private_output_root(output_root)
    if not input_path.is_file() or not rainfall_path.is_file() or not receipt_path.is_file():
        raise ValueError("swmm_binding_source_missing")
    validation = json.loads(receipt_path.read_text(encoding="utf-8"))
    if validation.get("schema") != "gwm.abu_dhabi_flood.customer_event_validation.v1":
        raise ValueError("swmm_binding_validation_schema_invalid")
    if validation.get("accepted") is not True:
        raise ValueError("swmm_binding_event_validation_not_accepted")
    if validation.get("policy", {}).get("event_kind") != "rainfall":
        raise ValueError("swmm_binding_event_kind_must_be_rainfall")
    source_hash = _sha256(rainfall_path)
    if validation.get("source", {}).get("csv_sha256") != source_hash:
        raise ValueError("swmm_binding_rainfall_hash_mismatch")
    metadata = validation.get("metadata", {})
    units = str(metadata.get("units", "")).strip().casefold()
    format_name = _UNIT_ALIASES.get(units)
    if format_name is None:
        raise ValueError("swmm_binding_rainfall_units_not_supported")
    timezone_name = str(metadata.get("timezone", "")).strip()
    if not timezone_name:
        raise ValueError("swmm_binding_rainfall_timezone_missing")
    rows = _read_series(
        rainfall_path,
        timestamp_column=timestamp_column,
        value_column=value_column,
        timezone_name=timezone_name,
    )
    cadence_minutes = validation.get("quality", {}).get("expected_cadence_minutes")
    if not isinstance(cadence_minutes, int) or cadence_minutes < 1:
        raise ValueError("swmm_binding_rainfall_cadence_missing")
    if any(
        int((after[0] - before[0]).total_seconds() / 60.0) != cadence_minutes
        for before, after in zip(rows, rows[1:], strict=False)
    ):
        raise ValueError("swmm_binding_rainfall_cadence_changed_after_validation")
    lines = input_path.read_text(encoding="ascii").splitlines(keepends=True)
    _replace_raingage(
        lines,
        raingage_id=raingage_id,
        timeseries_id=timeseries_id,
        source_timeseries_id=source_timeseries_id,
        format_name=format_name.upper(),
        interval=_swmm_interval(cadence_minutes),
    )
    replaced_rows = _replace_timeseries(
        lines,
        source_timeseries_id=source_timeseries_id,
        timeseries_id=timeseries_id,
        rows=rows,
    )
    first_timestamp = rows[0][0]
    end_timestamp = rows[-1][0] + timedelta(minutes=cadence_minutes)
    for option, timestamp in (
        ("START_DATE", first_timestamp),
        ("REPORT_START_DATE", first_timestamp),
        ("END_DATE", end_timestamp),
    ):
        _replace_option(lines, option, timestamp.strftime("%m/%d/%Y"))
    for option, timestamp in (
        ("START_TIME", first_timestamp),
        ("REPORT_START_TIME", first_timestamp),
        ("END_TIME", end_timestamp),
    ):
        _replace_option(lines, option, timestamp.strftime("%H:%M:%S"))
    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / output_name
    output_path.write_text("".join(lines), encoding="ascii")
    result = {
        "schema": SCHEMA,
        "version": "2026-08-23",
        "status": "customer_rainfall_bound_to_swmm_input_diagnostic_only",
        "source": {
            "swmm_input": input_path.name,
            "swmm_input_sha256": _sha256(input_path),
            "rainfall_csv": rainfall_path.name,
            "rainfall_csv_sha256": source_hash,
            "validation_receipt": receipt_path.name,
        },
        "binding": {
            "raingage_id": raingage_id,
            "source_timeseries_id": source_timeseries_id,
            "timeseries_id": timeseries_id,
            "swmm_format": format_name.upper(),
            "interval_minutes": cadence_minutes,
            "first_timestamp_utc": first_timestamp.isoformat(),
            "end_timestamp_utc_exclusive": end_timestamp.isoformat(),
            "source_timeseries_rows_replaced": replaced_rows,
            "output_input": output_path.name,
            "output_input_sha256": _sha256(output_path),
        },
        "claim_boundary": [
            "customer_event_temporal_qc_passed_before_binding",
            "network_engineering_parameters_and_boundaries_are_not_calibrated_here",
            "binding_does_not_admit_traditional_model_or_gwm_training",
        ],
        "admission": {
            "traditional_model_admitted": False,
            "engineering_calibration_admitted": False,
            "gwm_training_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
    }
    receipt_output = destination / "customer_swmm_forcing_binding_receipt.json"
    receipt_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def bind_customer_boundary_to_swmm(
    *,
    swmm_input: Path,
    boundary_csv: Path,
    validation_receipt: Path,
    output_root: Path,
    outfall_id: str,
    output_name: str = "customer_swmm_with_customer_boundary.inp",
    timeseries_id: str = "TS_BOUNDARY",
    timestamp_column: str = "timestamp",
    value_column: str = "value",
) -> dict[str, Any]:
    """Bind an accepted coastal boundary series to one SWMM outfall."""

    input_path = swmm_input.expanduser().resolve()
    boundary_path = boundary_csv.expanduser().resolve()
    receipt_path = validation_receipt.expanduser().resolve()
    destination = _require_private_output_root(output_root)
    if not input_path.is_file() or not boundary_path.is_file() or not receipt_path.is_file():
        raise ValueError("swmm_binding_source_missing")
    validation = json.loads(receipt_path.read_text(encoding="utf-8"))
    if validation.get("schema") != "gwm.abu_dhabi_flood.customer_event_validation.v1":
        raise ValueError("swmm_binding_validation_schema_invalid")
    if validation.get("accepted") is not True:
        raise ValueError("swmm_binding_event_validation_not_accepted")
    if validation.get("policy", {}).get("event_kind") != "coastal_boundary":
        raise ValueError("swmm_binding_event_kind_must_be_coastal_boundary")
    source_hash = _sha256(boundary_path)
    if validation.get("source", {}).get("csv_sha256") != source_hash:
        raise ValueError("swmm_binding_boundary_hash_mismatch")
    units = str(validation.get("metadata", {}).get("units", "")).strip().casefold()
    if units not in {"m", "meter", "metre", "meters", "metres"}:
        raise ValueError("swmm_binding_boundary_units_must_be_metres")
    vertical_datum = str(validation.get("metadata", {}).get("vertical_datum", "")).strip()
    if not vertical_datum:
        raise ValueError("swmm_binding_boundary_vertical_datum_missing")
    timezone_name = str(validation.get("metadata", {}).get("timezone", "")).strip()
    rows = _read_series(
        boundary_path,
        timestamp_column=timestamp_column,
        value_column=value_column,
        timezone_name=timezone_name,
    )
    cadence_minutes = validation.get("quality", {}).get("expected_cadence_minutes")
    if not isinstance(cadence_minutes, int) or cadence_minutes < 1:
        raise ValueError("swmm_binding_boundary_cadence_missing")
    if any(
        int((after[0] - before[0]).total_seconds() / 60.0) != cadence_minutes
        for before, after in zip(rows, rows[1:], strict=False)
    ):
        raise ValueError("swmm_binding_boundary_cadence_changed_after_validation")
    lines = input_path.read_text(encoding="ascii").splitlines(keepends=True)
    model_start, model_end = _model_window(lines)
    boundary_end = rows[-1][0] + timedelta(minutes=cadence_minutes)
    if rows[0][0] < model_start or boundary_end > model_end:
        raise ValueError("swmm_binding_boundary_window_outside_model")
    _replace_outfall_boundary(
        lines,
        outfall_id=outfall_id,
        timeseries_id=timeseries_id,
    )
    _append_timeseries(lines, timeseries_id=timeseries_id, rows=rows)
    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / output_name
    output_path.write_text("".join(lines), encoding="ascii")
    result = {
        "schema": SCHEMA,
        "version": "2026-08-23",
        "status": "customer_boundary_bound_to_swmm_outfall_diagnostic_only",
        "source": {
            "swmm_input": input_path.name,
            "swmm_input_sha256": _sha256(input_path),
            "boundary_csv": boundary_path.name,
            "boundary_csv_sha256": source_hash,
            "validation_receipt": receipt_path.name,
        },
        "binding": {
            "outfall_id": outfall_id,
            "timeseries_id": timeseries_id,
            "swmm_boundary_type": "TIMESERIES",
            "vertical_datum": vertical_datum,
            "interval_minutes": cadence_minutes,
            "first_timestamp_utc": rows[0][0].isoformat(),
            "end_timestamp_utc_exclusive": boundary_end.isoformat(),
            "model_window_start_utc": model_start.isoformat(),
            "model_window_end_utc": model_end.isoformat(),
            "output_input": output_path.name,
            "output_input_sha256": _sha256(output_path),
        },
        "claim_boundary": [
            "customer_boundary_temporal_qc_and_vertical_datum_present",
            "outfall_mapping_is_explicit_but_hydraulic_calibration_is_pending",
            "binding_does_not_admit_traditional_model_or_gwm_training",
        ],
        "admission": {
            "traditional_model_admitted": False,
            "engineering_calibration_admitted": False,
            "gwm_training_admitted": False,
            "city_scale_prediction_claim_allowed": False,
        },
    }
    receipt_output = destination / "customer_swmm_boundary_binding_receipt.json"
    receipt_output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
