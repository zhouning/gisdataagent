from scripts.build_development_control_chongqing import build_product


def test_builder_catalogs_real_sources_without_executable_site_dcr(tmp_path):
    product = build_product(repo_root=tmp_path, output_dir=tmp_path / "out")

    assert product["summary"]["rule_asset_count"] == 0
    assert product["summary"]["executable_site_rule_count"] == 0
    assert product["summary"]["available_dcr_channel_count"] == 0
