from data_agent.test_build_traditional_livability_s6_s1_fulu import _facility_product, _s6_resources
from data_agent.uwm.traditional_livability_s6_s1_product import build_s6_s1_product_bundle
from scripts.verify_traditional_livability_s6_s1_fulu import verify_product


def test_verifier_accepts_evidence_bounded_unavailable_profile_bundle(tmp_path):
    build_s6_s1_product_bundle(
        facility_product=_facility_product(), s6_resources=_s6_resources(), output_dir=tmp_path
    )
    result = verify_product(tmp_path)
    assert result["passed"] is True
    assert result["checks"]["profiles_unavailable_without_authority"] is True
    assert result["checks"]["no_fabricated_values"] is True
    assert result["verification_digest"].startswith("sha256:")
