from copy import deepcopy

from data_agent.spatial_dataset_bundle import (
    build_shapefile_bundle_inventory,
    validate_shapefile_bundle_inventory,
)


def test_shapefile_bundle_hashes_all_sidecars_without_source_paths(tmp_path):
    stem = tmp_path / "districts"
    for suffix, content in (
        (".shp", b"shape"),
        (".shx", b"index"),
        (".dbf", b"attributes"),
        (".prj", b"crs"),
        (".cpg", b"UTF-8"),
        (".shp.xml", b"metadata"),
    ):
        stem.with_suffix(suffix).write_bytes(content)

    inventory = build_shapefile_bundle_inventory(
        stem.with_suffix(".shp"),
        source_label="chongqing-cultural-districts",
    )

    assert validate_shapefile_bundle_inventory(inventory) == []
    assert inventory["spatial_inventory"] is None
    assert {item["component"] for item in inventory["components"]} == {
        ".cpg",
        ".dbf",
        ".prj",
        ".shp",
        ".shp.xml",
        ".shx",
    }
    assert str(tmp_path) not in str(inventory)


def test_checked_bundle_validation_detects_tampering(tmp_path):
    stem = tmp_path / "districts"
    for suffix in (".shp", ".shx", ".dbf", ".prj"):
        stem.with_suffix(suffix).write_bytes(suffix.encode())
    inventory = build_shapefile_bundle_inventory(
        stem.with_suffix(".shp"), source_label="golden-slice"
    )
    tampered = deepcopy(inventory)
    tampered["components"][0]["size_bytes"] += 1

    assert "spatial dataset bundle SHA-256 does not match" in (
        validate_shapefile_bundle_inventory(tampered)
    )
