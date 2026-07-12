from scripts.build_public_feedback_readiness_chongqing import build_product


def test_builder_keeps_empty_repository_without_public_feedback_claims(tmp_path):
    product = build_product(repo_root=tmp_path, output_dir=tmp_path / "out")
    assert product["summary"]["capability_count"] == 0
    assert product["summary"]["available_feedback_channel_count"] == 0
    assert product["summary"]["published_feedback_observation_count"] == 0
