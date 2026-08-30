"""Tests for byte-preserving Chongqing DEM source staging."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from data_agent.source_adapter_registry import (
    CHONGQING_DEM_SOURCE_ADAPTER,
    sealed_bundle_identity,
)
from scripts.stage_chongqing_dem import stage_source


def _source(tmp_path: Path) -> Path:
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "terrain.tif"
    values = np.array([[1, 2, 32767], [3, 32767, 5]], dtype=np.int16)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=3,
        height=2,
        count=1,
        dtype="int16",
        crs="EPSG:4490",
        transform=from_origin(105.0, 30.0, 0.1, 0.1),
        nodata=32767,
    ) as dataset:
        dataset.write(values, 1)
    path.with_suffix(".tfw").write_text("0.1\n0\n0\n-0.1\n105.05\n29.95\n")
    path.with_name(f"{path.name}.aux.xml").write_text("<PAMDataset/>\n")
    return path


def test_dem_stage_scans_pixels_and_preserves_every_bundle_member(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    identity = sealed_bundle_identity(source, CHONGQING_DEM_SOURCE_ADAPTER)
    primary_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
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
        expected_bundle_sha256=identity["bundle_sha256"],
        expected_primary_sha256=primary_sha256,
        expected_valid_pixel_count=4,
    )
    replay = stage_source(
        source_path=source,
        output_root=tmp_path / "output",
        bucket="test-lakehouse",
        materializer=materializer,
        expected_bundle_sha256=identity["bundle_sha256"],
        expected_primary_sha256=primary_sha256,
        expected_valid_pixel_count=4,
    )

    assert first["source_adapter"]["source_kind"] == "raster"
    assert first["source_bundle"]["bundle_sha256"] != primary_sha256
    assert first["source_profile"]["driver"] == "GTiff"
    assert first["source_profile"]["epsg"] == 4490
    assert first["source_profile"]["full_resolution_scan"] is True
    band = first["source_profile"]["bands"][0]
    assert band["pixel_count"] == 6
    assert band["valid_pixel_count"] == 4
    assert band["nodata_pixel_count"] == 2
    assert band["min"] == 1
    assert band["max"] == 5
    assert band["mean"] == pytest.approx(2.75)
    assert first["bundle_snapshot"]["member_count"] == 3
    assert first["bundle_snapshot"]["all_readback_verified"] is True
    assert first["quality_state"] == {
        "raw_source_integrity": "passed",
        "full_pixel_scan": "passed",
        "cog_conformance": "not_evaluated",
        "ods_admission": "not_evaluated",
        "standard_mapping": "not_evaluated",
        "promotion": "blocked",
        "promotion_blockers": [
            "license_unconfirmed",
            "cog_conformance_not_evaluated",
            "standard_mapping_unapproved",
        ],
    }
    assert all(not item["local_created"] for item in replay["bundle_snapshot"]["members"])
    assert all(not item["object_created"] for item in replay["bundle_snapshot"]["members"])
    assert len(objects) == 3


def test_dem_stage_rejects_wrong_pixel_seal_before_materialization(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    identity = sealed_bundle_identity(source, CHONGQING_DEM_SOURCE_ADAPTER)
    calls = 0

    def materializer(_payload):
        nonlocal calls
        calls += 1
        raise AssertionError("materializer must not run")

    with pytest.raises(RuntimeError, match="valid pixel count"):
        stage_source(
            source_path=source,
            output_root=tmp_path / "output",
            bucket="test-lakehouse",
            materializer=materializer,
            expected_bundle_sha256=identity["bundle_sha256"],
            expected_primary_sha256=identity["members"][0]["sha256"],
            expected_valid_pixel_count=5,
        )
    assert calls == 0
