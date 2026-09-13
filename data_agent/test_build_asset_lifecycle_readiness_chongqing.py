import json

from scripts.build_asset_lifecycle_readiness_chongqing import build_product


def test_builder_references_products_without_claiming_unique_assets(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "overview.json").write_text(json.dumps({"bundle_id": "b1", "summary": {"visible_building_feature_count": 10}}))
    output = tmp_path / "output"
    product = build_product(source_specs=[{"product_id": "infrastructure", "source_path": source / "overview.json", "record_fields": ["visible_building_feature_count"], "record_semantics": "visible_building_footprints"}], output_dir=output)
    assert product["summary"]["unique_asset_count"] is None
    assert product["source_products"][0]["record_count"] == 10
    assert (output / "lifecycle_gate.json").is_file()
    assert len(list(output.glob("*.json"))) == 6
