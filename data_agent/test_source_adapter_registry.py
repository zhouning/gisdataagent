"""Contract tests for the declarative source adapter registry."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent.source_adapter_registry import (
    CENTRAL_BUILDINGS_SOURCE_ADAPTER,
    CHONGQING_DEM_SOURCE_ADAPTER,
    SOURCE_ADAPTERS,
    SourceAdapterDefinition,
    SourceKind,
    resolve_source_adapter,
    sealed_bundle_identity,
)
from data_agent.standards_platform.application.acceptance import bundle_identity


def test_registry_covers_distinct_vector_and_raster_contracts() -> None:
    assert set(SOURCE_ADAPTERS) == {
        "chongqing-central-buildings-shapefile",
        "chongqing-aster-gdem-geotiff",
    }
    assert CENTRAL_BUILDINGS_SOURCE_ADAPTER.source_kind is SourceKind.VECTOR
    assert CHONGQING_DEM_SOURCE_ADAPTER.source_kind is SourceKind.RASTER
    assert CENTRAL_BUILDINGS_SOURCE_ADAPTER.fingerprint == (
        CENTRAL_BUILDINGS_SOURCE_ADAPTER.fingerprint
    )
    assert len(CENTRAL_BUILDINGS_SOURCE_ADAPTER.fingerprint) == 64
    with pytest.raises(ValidationError, match="frozen"):
        CENTRAL_BUILDINGS_SOURCE_ADAPTER.classification = "public"  # type: ignore[misc]


def test_resolution_is_fail_closed_for_extension_driver_and_unknown_id(
    tmp_path: Path,
) -> None:
    source = tmp_path / "terrain.tif"
    source.write_bytes(b"tiff")
    assert (
        resolve_source_adapter(
            CHONGQING_DEM_SOURCE_ADAPTER.adapter_id,
            source,
            observed_driver="GTiff",
        )
        is CHONGQING_DEM_SOURCE_ADAPTER
    )
    with pytest.raises(ValueError, match="does not allow source extension"):
        resolve_source_adapter(CHONGQING_DEM_SOURCE_ADAPTER.adapter_id, source.with_suffix(".csv"))
    with pytest.raises(ValueError, match="does not allow source driver"):
        resolve_source_adapter(
            CHONGQING_DEM_SOURCE_ADAPTER.adapter_id,
            source,
            observed_driver="AAIGrid",
        )
    with pytest.raises(ValueError, match="unknown source adapter"):
        resolve_source_adapter("missing-adapter", source)


def test_shapefile_policy_preserves_existing_bundle_identity(tmp_path: Path) -> None:
    source = tmp_path / "buildings.shp"
    source.write_bytes(b"shp")
    source.with_suffix(".shx").write_bytes(b"shx")
    source.with_suffix(".dbf").write_bytes(b"dbf")
    source.with_suffix(".prj").write_bytes(b"prj")
    source.with_name(f"{source.name}.xml").write_bytes(b"xml")

    existing = bundle_identity(source)
    governed = sealed_bundle_identity(source, CENTRAL_BUILDINGS_SOURCE_ADAPTER)
    assert governed["bundle_sha256"] == existing["bundle_sha256"]
    assert [member["name"] for member in governed["members"]] == [
        "buildings.shp",
        "buildings.shx",
        "buildings.dbf",
        "buildings.prj",
        "buildings.shp.xml",
    ]


def test_raster_bundle_seals_sidecars_and_rejects_unlisted_members(
    tmp_path: Path,
) -> None:
    source = tmp_path / "terrain.tif"
    source.write_bytes(b"tiff")
    source.with_suffix(".tfw").write_bytes(b"world")
    source.with_name(f"{source.name}.aux.xml").write_bytes(b"aux")

    identity = sealed_bundle_identity(source, CHONGQING_DEM_SOURCE_ADAPTER)
    assert [member["name"] for member in identity["members"]] == [
        "terrain.tif",
        "terrain.tfw",
        "terrain.tif.aux.xml",
    ]
    assert identity["bundle_sha256"] != identity["members"][0]["sha256"]

    source.with_name("terrain.tif.unknown").write_bytes(b"unknown")
    with pytest.raises(ValueError, match="unlisted same-stem bundle members"):
        sealed_bundle_identity(source, CHONGQING_DEM_SOURCE_ADAPTER)


def test_bundle_policy_requires_core_shapefile_members(tmp_path: Path) -> None:
    source = tmp_path / "buildings.shp"
    source.write_bytes(b"shp")
    with pytest.raises(FileNotFoundError, match="shape-index"):
        sealed_bundle_identity(source, CENTRAL_BUILDINGS_SOURCE_ADAPTER)


def test_restricted_adapter_cannot_enable_direct_promotion() -> None:
    document = CHONGQING_DEM_SOURCE_ADAPTER.model_dump(mode="json")
    document["promotion_policy"]["eligible"] = True
    with pytest.raises(ValidationError, match="cannot be directly promotion eligible"):
        SourceAdapterDefinition.model_validate(document)
