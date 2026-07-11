import pytest

from data_agent.test_build_traditional_livability_s7_gated_fulu import _facility, _s1, _s7
from data_agent.uwm.traditional_livability_s7_gated_product import build_gated_s7_product
from data_agent.uwm.traditional_livability_s7_gated_service import (
    S7RunConflict,
    S7RunInvalid,
    TraditionalLivabilityS7GatedService,
)


def _service(tmp_path):
    build_gated_s7_product(
        s7_snapshot=_s7(), s1_snapshot=_s1(), facility_product=_facility(), output_dir=tmp_path
    )
    return TraditionalLivabilityS7GatedService.from_product_dir(tmp_path)


def test_service_loads_gate_and_compatibility_result(tmp_path):
    service = _service(tmp_path)
    assert service.demand_gate()["state"] == "need_unresolved"
    assert service.current_result()["recommendation_status"] == "conditional_candidate_ranking_available"


def test_authoritative_mode_is_blocked_when_need_unresolved(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(S7RunConflict, match="authoritative_need_not_confirmed"):
        service.run(mode="authoritative", acknowledgement=False)


def test_conditional_mode_requires_acknowledgement(tmp_path):
    service = _service(tmp_path)
    with pytest.raises(S7RunInvalid, match="conditional_not_a_recommendation_ack_required"):
        service.run(mode="conditional", acknowledgement=False)
    result = service.run(mode="conditional", acknowledgement=True)
    assert result["not_a_site_recommendation"] is True
