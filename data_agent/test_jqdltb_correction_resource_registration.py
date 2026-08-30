from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.build_chongqing_jqdltb_business_correction_template import build_template
from scripts.register_chongqing_jqdltb_correction_resource import (
    RESOURCE_URN,
    register_correction_resource_version,
)

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config/freezes/ar0-jqdltb-transformation-contract-2026-08-22.json"
DIAGNOSTIC = (
    ROOT / "benchmarks/standard_mapping_chongqing_v0_1/source_quality_repair_diagnostic.json"
)


class _WriteResult:
    def __init__(self, created: bool = True) -> None:
        self.created = created


class _Gateway:
    def __init__(self) -> None:
        self.resources = []
        self.versions = []

    def register_resource(self, value):
        self.resources.append(value)
        return _WriteResult()

    def register_resource_version(self, value):
        self.versions.append(value)
        return _WriteResult()


def _source(path: Path) -> None:
    rows = [
        {
            "type": "Feature",
            "properties": {"TBBH": key, "TBMJ": 0, "TBDLMJ": 0},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]],
            },
        }
        for key in ["486", "487", "576", "579", "861", "1063"]
    ]
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": "EPSG:4523"}},
                "features": rows,
            }
        ),
        encoding="utf-8",
    )


def _filled_artifact(tmp_path: Path, source: Path) -> Path:
    template = build_template(
        source_path=source,
        baseline_path=BASELINE,
        diagnostic_path=DIAGNOSTIC,
    )
    artifact = tmp_path / "corrections.json"
    artifact.write_text(
        json.dumps(
            {
                "records": [
                    {"TBBH": row["TBBH"], "TBMJ": 10, "TBDLMJ": 10}
                    for row in template["records"]
                ]
            }
        ),
        encoding="utf-8",
    )
    return artifact


def test_registration_requires_filled_artifact_before_gateway_writes(tmp_path: Path) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source)
    template = tmp_path / "empty-template.json"
    template.write_text(
        json.dumps(
            build_template(
                source_path=source,
                baseline_path=BASELINE,
                diagnostic_path=DIAGNOSTIC,
            )
        ),
        encoding="utf-8",
    )
    gateway = _Gateway()

    with pytest.raises(ValueError, match="finite positive number"):
        register_correction_resource_version(
            artifact_path=template,
            source_path=source,
            baseline_path=BASELINE,
            diagnostic_path=DIAGNOSTIC,
            gateway=gateway,
        )
    assert gateway.resources == []
    assert gateway.versions == []


def test_registration_binds_exact_artifact_hash_and_source_identity(tmp_path: Path) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source)
    artifact = _filled_artifact(tmp_path, source)
    gateway = _Gateway()

    result = register_correction_resource_version(
        artifact_path=artifact,
        source_path=source,
        baseline_path=BASELINE,
        diagnostic_path=DIAGNOSTIC,
        gateway=gateway,
        owner_ref="team:freedo",
        created_at=datetime(2026, 8, 30, 13, tzinfo=UTC),
    )

    assert result["status"] == "resource_version_registered"
    assert result["resource_urn"] == RESOURCE_URN
    assert result["records"] == 6
    assert result["approval_case_created"] is False
    assert result["strategy_created"] is False
    assert result["data_product_version_created"] is False
    assert len(gateway.resources) == 1
    assert len(gateway.versions) == 1
    resource = gateway.resources[0]
    version = gateway.versions[0]
    assert resource.resource_urn == RESOURCE_URN
    assert resource.governance_ref["approval_state"] == "unapproved"
    assert version.content_sha256 == result["artifact_sha256"]
    assert version.authority_version_ref["artifact_sha256"] == result["artifact_sha256"]
    assert version.authority_version_ref["source_resource_version_id"] == (
        "34441c77-2cf0-5ca2-83bf-81dd6a488d5b"
    )


def test_registration_rejects_untyped_owner_before_gateway_writes(tmp_path: Path) -> None:
    source = tmp_path / "JQDLTB.geojson"
    _source(source)
    artifact = _filled_artifact(tmp_path, source)
    gateway = _Gateway()

    with pytest.raises(ValueError, match="typed human or team"):
        register_correction_resource_version(
            artifact_path=artifact,
            source_path=source,
            baseline_path=BASELINE,
            diagnostic_path=DIAGNOSTIC,
            gateway=gateway,
            owner_ref="freedo",
        )
    assert gateway.resources == []
    assert gateway.versions == []
