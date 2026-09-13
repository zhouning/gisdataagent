import json

from scripts.build_parcel_state_readiness_chongqing import build_product


def test_builder_selects_dltb_and_supporting_assets_without_state_rows(tmp_path):
    audit = tmp_path / "audit.json"
    audit.write_text(json.dumps({"vector_profiles": [{"asset_id": "bishan_land_use_dltb_local", "source_path": "dltb", "feature_count": 3, "fields": ["BSM", "DLBM"]}], "tabular_profiles": []}))
    product = build_product(audit_path=audit, output_dir=tmp_path / "out")
    assert product["summary"]["audited_feature_count"] == 3
    assert product["summary"]["materialized_state_node_count"] == 0
