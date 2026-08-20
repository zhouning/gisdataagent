from __future__ import annotations

from pathlib import Path

import pytest

from data_agent.uwm.abu_dhabi_flood.makani_probe import (
    EXPECTED_SOURCE_BINDING,
    PROBE_SPECS,
    TARGET_RESOURCE_NAMES,
    build_probe_artifact,
    validate_aggregate_result,
    validate_discovery_export,
)


def _discovery() -> dict:
    resources = [
        {
            "name": name,
            "columns": [{"name": "geom", "type": "geometry(GEOMETRY,EPSG:32640)"}],
            "primary_key": ["fid"],
            "foreign_keys": [],
        }
        for name in TARGET_RESOURCE_NAMES
    ]
    return {
        "status": "ok",
        "source_id": EXPECTED_SOURCE_BINDING["source_id"],
        "source_name": EXPECTED_SOURCE_BINDING["source_name"],
        "discovery_fingerprint": EXPECTED_SOURCE_BINDING["discovery_fingerprint"],
        "profile_fingerprint": EXPECTED_SOURCE_BINDING["profile_fingerprint"],
        "discovery_status": "succeeded",
        "last_discovery_at": "2026-08-17T12:38:28Z",
        "discovery_snapshot": {
            "database_name": EXPECTED_SOURCE_BINDING["database_name"],
            "authorized_schemas": ["layer"],
            "contains_source_rows": False,
            "truncated": False,
            "resources": resources,
        },
    }


def _result(spec, row_count: int = 1) -> dict:
    rows = [[0 for _ in spec.expected_columns] for _ in range(row_count)]
    return {
        "status": "ok",
        "bounded_limit": spec.maximum_rows,
        "columns": list(spec.expected_columns),
        "row_count": row_count,
        "rows": rows,
        "result_fingerprint": "a" * 64,
        "equivalence_fingerprints": {"position_fingerprint": "b" * 64},
    }


def test_discovery_validation_is_metadata_only_and_fails_on_binding_drift() -> None:
    validated = validate_discovery_export(_discovery())
    assert validated["contains_source_rows"] is False
    assert [item["name"] for item in validated["resources"]] == list(
        TARGET_RESOURCE_NAMES
    )

    drifted = _discovery()
    drifted["discovery_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="binding_drift"):
        validate_discovery_export(drifted)


def test_aggregate_result_requires_exact_columns_rows_and_limit() -> None:
    spec = PROBE_SPECS[1]
    validated = validate_aggregate_result(spec, _result(spec))
    assert validated["aggregate_rows_only"] is True
    assert validated["source_feature_rows_persisted"] is False

    wrong_columns = _result(spec)
    wrong_columns["columns"] = ["unitid"]
    with pytest.raises(ValueError, match="columns_changed"):
        validate_aggregate_result(spec, wrong_columns)

    too_many = _result(spec, spec.maximum_rows + 1)
    with pytest.raises(ValueError, match="row_bound_exceeded"):
        validate_aggregate_result(spec, too_many)


def test_artifact_keeps_admission_closed_and_raw_rows_excluded() -> None:
    discovery = validate_discovery_export(_discovery())
    results = [
        {"probe_id": spec.probe_id, "source_feature_rows_persisted": False}
        for spec in PROBE_SPECS
    ]
    artifact = build_probe_artifact(
        discovery,
        results,
        sql_contracts=[],
        generated_at="2026-08-18T00:00:00Z",
    )
    assert artifact["privacy"]["raw_identifiers_persisted"] is False
    assert artifact["admission"]["admitted"] is False


def test_sql_contracts_are_read_only_scoped_and_exclude_sensitive_columns() -> None:
    root = Path(__file__).resolve().parents[1] / "scripts/sql/abu_dhabi_flood"
    forbidden = ("created_user", "last_edited_user", "comments", "asset_image")
    for spec in PROBE_SPECS:
        sql = (root / spec.sql_filename).read_text(encoding="utf-8")
        assert sql.lstrip().upper().startswith("WITH")
        assert "layer.st_" in sql
        assert not any(value in sql.casefold() for value in forbidden)
        assert not any(
            token in sql.upper()
            for token in (" INSERT ", " UPDATE ", " DELETE ", " DROP ", " ALTER ")
        )
