import json

from scripts.build_planning_version_registry_chongqing import build_product


def test_builder_selects_only_supported_planning_assets(tmp_path):
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"vector_profiles": [{"asset_id": "bishan_land_use_dltb_local", "feature_count": 3, "source_path": "x", "layer": "DLTB"}, {"asset_id": "unrelated", "feature_count": 9, "source_path": "y"}], "tabular_profiles": []}))
    product = build_product(audit_path=audit, output_dir=tmp_path / "out")
    assert product["summary"]["version_asset_count"] == 1
    assert product["version_assets"][0]["asset_id"] == "bishan_land_use_dltb_local"
