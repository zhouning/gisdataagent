from data_agent.test_build_traditional_mobility_accessibility_chongqing import source_root
from scripts.build_traditional_mobility_accessibility_chongqing import build_product
from scripts.verify_traditional_mobility_accessibility_chongqing import verify_product


def test_verifier_checks_bundle_channels_and_fabrication(tmp_path):
    output = tmp_path / "product"
    build_product(source_root=source_root(tmp_path), output_dir=output)
    result = verify_product(output)
    assert result["valid"] is True
    assert result["fabricated_value_count"] == 0
    assert result["unavailable_channel_numeric_violation_count"] == 0
    assert result["admin_unit_count"] == 2
