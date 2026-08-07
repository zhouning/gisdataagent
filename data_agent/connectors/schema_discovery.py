"""Deterministic schema discovery for JSON and GeoJSON records."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

_TYPE_ORDER = {
    "null": 0,
    "boolean": 1,
    "integer": 2,
    "number": 3,
    "string": 4,
    "array": 5,
    "object": 6,
}


def json_document_columns(
    document: Any,
    *,
    record_limit: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    """Return bounded record-schema columns from JSON or GeoJSON documents."""

    records = _document_records(document)
    sample = records[:record_limit]
    return json_record_columns(sample), len(records), len(records) > len(sample)


def json_record_columns(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Infer stable, nested field paths without retaining source values."""

    flattened: list[dict[str, Any]] = []
    for record in records:
        fields: dict[str, Any] = {}
        _flatten_mapping(record, "", fields)
        flattened.append(fields)

    field_names = sorted({name for fields in flattened for name in fields})
    columns = []
    for name in field_names:
        values = [fields.get(name) for fields in flattened]
        present = [name in fields for fields in flattened]
        value_types = sorted(
            {_json_type(value) for value, exists in zip(values, present, strict=True) if exists},
            key=lambda value: (_TYPE_ORDER[value], value),
        )
        columns.append(
            {
                "name": name,
                "type": "|".join(value_types) if value_types else "null",
                "nullable": any(
                    not exists or value is None
                    for value, exists in zip(values, present, strict=True)
                ),
            }
        )
    return columns


def _document_records(document: Any) -> list[Mapping[str, Any]]:
    if isinstance(document, Mapping):
        features = document.get("features")
        if document.get("type") == "FeatureCollection" and isinstance(features, list):
            return [feature for feature in features if isinstance(feature, Mapping)]
        return [document]
    if isinstance(document, list):
        return [record for record in document if isinstance(record, Mapping)]
    return []


def _flatten_mapping(value: Mapping[str, Any], prefix: str, output: dict[str, Any]) -> None:
    for raw_key in sorted(value, key=str):
        key = str(raw_key)
        path = f"{prefix}.{key}" if prefix else key
        item = value[raw_key]
        if isinstance(item, Mapping) and item:
            _flatten_mapping(item, path, output)
        else:
            output[_bounded_path(path)] = item


def _bounded_path(path: str) -> str:
    if len(path) <= 256:
        return path
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
    return f"{path[:238]}:{digest}"


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"
