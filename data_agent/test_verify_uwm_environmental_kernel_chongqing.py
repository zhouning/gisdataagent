from data_agent.test_build_uwm_environmental_kernel_chongqing import fixture_root
from scripts.build_uwm_environmental_kernel_chongqing import build_product
from scripts.verify_uwm_environmental_kernel_chongqing import verify_product


def test_verifier_confirms_bundle_and_zero_fabricated_values(tmp_path):
    output = tmp_path / "product"
    build_product(source_root=fixture_root(tmp_path), output_dir=output)

    result = verify_product(output)

    assert result["valid"] is True
    assert result["fabricated_value_count"] == 0
    assert result["not_a_causal_effect_estimate"] is True
    assert result["intervention_status"] == "action_response_closed"
