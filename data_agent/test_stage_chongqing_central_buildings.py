"""Tests for deterministic restricted-building source staging."""

from __future__ import annotations

import hashlib
from pathlib import Path

from data_agent.source_adapter_registry import (
    CENTRAL_BUILDINGS_SOURCE_ADAPTER,
    sealed_bundle_identity,
)
from scripts.stage_chongqing_central_buildings import stage_source


def _source(tmp_path: Path) -> Path:
    import fiona
    from fiona.crs import CRS

    path = tmp_path / "buildings.shp"
    schema = {
        "geometry": "Polygon",
        "properties": {"Id": "int", "Floor": "int"},
    }
    polygon = {
        "type": "Polygon",
        "coordinates": [[(106.2, 29.2), (106.3, 29.2), (106.3, 29.3), (106.2, 29.2)]],
    }
    with fiona.open(
        path,
        "w",
        driver="ESRI Shapefile",
        crs=CRS.from_epsg(4326),
        schema=schema,
    ) as sink:
        sink.write({"geometry": polygon, "properties": {"Id": 0, "Floor": 1}})
        sink.write({"geometry": polygon, "properties": {"Id": 0, "Floor": 3}})
        sink.write({"geometry": None, "properties": {"Id": 0, "Floor": 2}})
    return path


def test_building_source_stage_preserves_and_records_defects(tmp_path) -> None:
    source = _source(tmp_path)
    expected_bundle = sealed_bundle_identity(
        source, CENTRAL_BUILDINGS_SOURCE_ADAPTER
    )["bundle_sha256"]
    objects: dict[str, bytes] = {}

    def materializer(payload):
        body = Path(payload["source_path"]).read_bytes()
        sha256 = hashlib.sha256(body).hexdigest()
        created = payload["target_uri"] not in objects
        previous = objects.setdefault(payload["target_uri"], body)
        assert previous == body
        return {
            "materialized": True,
            "verified": True,
            "created": created,
            "target_uri": payload["target_uri"],
            "sha256": sha256,
        }

    first = stage_source(
        source_path=source,
        output_root=tmp_path / "output",
        bucket="test-lakehouse",
        materializer=materializer,
        expected_bundle_sha256=expected_bundle,
        expected_feature_count=3,
    )
    replay = stage_source(
        source_path=source,
        output_root=tmp_path / "output",
        bucket="test-lakehouse",
        materializer=materializer,
        expected_bundle_sha256=expected_bundle,
        expected_feature_count=3,
    )

    profile = first["source_profile"]
    assert profile["feature_count"] == 3
    assert profile["distinct_source_fids"] == 3
    assert profile["distinct_source_ids"] == 1
    assert profile["source_geometry_types"] == {"Polygon": 2}
    assert profile["snapshot_geometry_type"] == "MultiPolygon"
    assert profile["null_geometry"] == 1
    assert profile["duplicate_geometry"] == 1
    assert profile["duplicate_non_null_geometry"] == 1
    assert profile["invalid_geometry"] == 0
    assert profile["floor_min"] == 1
    assert profile["floor_max"] == 3
    assert first["classification"] == "restricted"
    assert first["publication_eligible"] is False
    assert first["source_adapter"]["source_kind"] == "vector"
    assert first["source_adapter"]["fingerprint"] == (
        CENTRAL_BUILDINGS_SOURCE_ADAPTER.fingerprint
    )
    assert first["snapshot"]["physical_sha256"] == replay["snapshot"][
        "physical_sha256"
    ]
    assert replay["snapshot"]["local_created"] is False
    assert replay["snapshot"]["object_created"] is False
    assert len(objects) == 1
