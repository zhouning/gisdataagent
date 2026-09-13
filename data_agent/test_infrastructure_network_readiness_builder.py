import json

from scripts.build_infrastructure_network_readiness_chongqing import build_product


def test_builder_classifies_roads_without_opening_utility_channels(tmp_path):
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"vector_profiles": [{"asset_id": "chongqing_osm_roads_2021", "source_path": "roads", "feature_count": 3, "fields": ["osm_id"]}], "tabular_profiles": []}))
    product = build_product(audit_path=audit, repo_root=tmp_path, output_dir=tmp_path / "out")
    assert product["summary"]["visible_road_feature_count"] == 3
    assert product["summary"]["available_utility_channel_count"] == 0
