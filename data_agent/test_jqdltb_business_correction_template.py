from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_chongqing_jqdltb_business_correction_template import (
    build_template,
    validate_artifact,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
DIAGNOSTIC = (
    ROOT / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)


def _source(path: Path, *, include_all: bool = True) -> None:
    keys = ["486", "487", "576", "579", "861", "1063"]
    if not include_all:
        keys = keys[:-1]
    features = [
        {
            "type": "Feature",
            "properties": {
                "TBBH": key,
                "TBMJ": 0,
                "TBDLMJ": 0,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]],
            },
        }
        for key in keys
    ]
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:4523"}},
                "features": features,
            }
        ),
        encoding="utf-8",
    )


def test_template_contains_exact_nonpositive_keys_and_empty_values(tmp_path: Path) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source)

    template = build_template(
        source_path=source,
        baseline_path=BASELINE,
        diagnostic_path=DIAGNOSTIC,
    )

    assert template["status"] == "draft_template_not_approved"
    assert [row["TBBH"] for row in template["records"]] == [
        "1063",
        "486",
        "487",
        "576",
        "579",
        "861",
    ]
    assert all(row["TBMJ"] is None and row["TBDLMJ"] is None for row in template["records"])
    assert template["observed_nonpositive_counts"] == {"TBMJ": 6, "TBDLMJ": 6}


def test_template_fails_closed_when_source_count_drifts(tmp_path: Path) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source, include_all=False)

    with pytest.raises(ValueError, match="non-positive counts differ"):
        build_template(
            source_path=source,
            baseline_path=BASELINE,
            diagnostic_path=DIAGNOSTIC,
        )


def test_filled_artifact_is_ready_for_registration_and_is_hashed(tmp_path: Path) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source)
    artifact = tmp_path / "corrections.json"
    template = build_template(
        source_path=source,
        baseline_path=BASELINE,
        diagnostic_path=DIAGNOSTIC,
    )
    rows = []
    for row in template["records"]:
        rows.append(
            {
                "TBBH": row["TBBH"],
                "TBMJ": 10,
                "TBDLMJ": 10,
            }
        )
    artifact.write_text(json.dumps({"records": rows}), encoding="utf-8")

    report = validate_artifact(
        artifact_path=artifact,
        source_path=source,
        baseline_path=BASELINE,
        diagnostic_path=DIAGNOSTIC,
    )

    assert report["status"] == "ready_for_resource_version_registration"
    assert report["records"] == 6
    assert report["authority_state_created"] is False
    assert report["data_product_version_created"] is False
    assert len(report["artifact_sha256"]) == 64


def test_filled_artifact_rejects_missing_or_nonpositive_values(tmp_path: Path) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source)
    artifact = tmp_path / "corrections.json"
    artifact.write_text(
        json.dumps(
            {
                "records": [
                    {"TBBH": key, "TBMJ": 10, "TBDLMJ": 10}
                    for key in ["486", "487", "576", "579", "861", "1063"]
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["records"][0]["TBDLMJ"] = 0
    artifact.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="finite positive number"):
        validate_artifact(
            artifact_path=artifact,
            source_path=source,
            baseline_path=BASELINE,
            diagnostic_path=DIAGNOSTIC,
        )
