from scripts.build_spatial_scope_registry_chongqing import build_product


def test_builder_requires_source_files_and_can_publish_empty_fixture(tmp_path):
    source = tmp_path / "admin.geojson"
    manifest = tmp_path / "manifest.json"
    source.write_text('{"type":"FeatureCollection","features":[],"crs":{"properties":{"name":"EPSG:4326"}}}')
    manifest.write_text('{"dataset_id":"fixture","limitations":[]}')
    product = build_product(source_path=source, manifest_path=manifest, output_dir=tmp_path / "out")
    assert product["summary"]["spatial_unit_count"] == 0
