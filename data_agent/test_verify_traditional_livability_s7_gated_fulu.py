from data_agent.test_build_traditional_livability_s7_gated_fulu import _facility, _s1, _s7
from data_agent.uwm.traditional_livability_s7_gated_product import build_gated_s7_product
from scripts.verify_traditional_livability_s7_gated_fulu import verify_product


def test_verifier_accepts_conditional_only_real_product(tmp_path):
    build_gated_s7_product(
        s7_snapshot=_s7(), s1_snapshot=_s1(), facility_product=_facility(), output_dir=tmp_path
    )
    result = verify_product(tmp_path)
    assert result["passed"] is True
    assert result["checks"]["conditional_only"] is True
    assert result["checks"]["no_fabricated_values"] is True
    assert result["verification_digest"].startswith("sha256:")
