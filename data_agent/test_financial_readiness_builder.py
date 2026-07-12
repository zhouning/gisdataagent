from scripts.build_financial_readiness_chongqing import build_product


def test_builder_keeps_empty_repository_fail_closed(tmp_path):
    product = build_product(repo_root=tmp_path, output_dir=tmp_path / "out")
    assert product["summary"]["evidence_asset_count"] == 0
    assert product["summary"]["available_financial_channel_count"] == 0
    assert product["summary"]["computed_financial_output_count"] == 0
