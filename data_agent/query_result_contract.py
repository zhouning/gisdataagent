"""Deterministic evidence contracts for bounded tabular query results."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime
from typing import Any


def normalize_result_value(value: Any) -> Any:
    """Convert dataframe scalar values into stable JSON-compatible values."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    wkb_hex = getattr(value, "wkb_hex", None)
    if wkb_hex is not None:
        return {"geometry_wkb": str(wkb_hex)}
    item = getattr(value, "item", None)
    if callable(item):
        try:
            converted = item()
            if converted is not value:
                return normalize_result_value(converted)
        except (TypeError, ValueError):
            pass
    if isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _numeric6(value: Any) -> Any:
    """Normalize numeric scalars for SQL-equivalent aggregate comparison."""
    normalized = normalize_result_value(value)
    if isinstance(normalized, (int, float)) and not isinstance(normalized, bool):
        return round(float(normalized), 6)
    return normalized


def _fingerprint_payload(columns: list[str], rows: list[list[Any]], *, mode: str) -> str:
    normalized_rows = rows
    if mode in {"position_numeric6", "unordered_position_numeric6"}:
        normalized_rows = [[_numeric6(value) for value in row] for row in rows]
    if mode in {"unordered_position", "unordered_position_numeric6"}:
        normalized_rows = sorted(
            normalized_rows,
            key=lambda row: json.dumps(row, ensure_ascii=False, separators=(",", ":")),
        )
    payload: dict[str, Any] = {"rows": normalized_rows}
    if mode == "ordered":
        payload = {"columns": columns, "rows": normalized_rows}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def tabular_result_contract(result: Any, *, include_rows: bool = False) -> dict[str, Any]:
    """Return a stable ordered-result fingerprint without persisting source rows."""
    if not hasattr(result, "columns") or not hasattr(result, "itertuples"):
        raise TypeError("Database query did not return a tabular result")

    columns = [str(value) for value in result.columns]
    rows = [
        [normalize_result_value(value) for value in row]
        for row in result.itertuples(index=False, name=None)
    ]
    canonical = json.dumps(
        {"columns": columns, "rows": rows},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    payload: dict[str, Any] = {
        "columns": columns,
        "row_count": len(rows),
        "result_fingerprint": hashlib.sha256(canonical).hexdigest(),
        "equivalence_fingerprints": {
            "position_fingerprint": _fingerprint_payload(columns, rows, mode="position"),
            "position_numeric6_fingerprint": _fingerprint_payload(
                columns, rows, mode="position_numeric6"
            ),
            "unordered_position_fingerprint": _fingerprint_payload(
                columns, rows, mode="unordered_position"
            ),
            "unordered_position_numeric6_fingerprint": _fingerprint_payload(
                columns, rows, mode="unordered_position_numeric6"
            ),
        },
    }
    if include_rows:
        payload["rows"] = rows
    return payload
