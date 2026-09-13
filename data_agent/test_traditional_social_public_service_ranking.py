from data_agent.test_traditional_social_public_service import source_fixture
from data_agent.uwm.traditional_social_public_service import build_social_public_service_product


def test_social_view_ranks_zero_facility_then_lower_diversity():
    product = build_social_public_service_product(**source_fixture())
    rows = {row["admin_unit_id"]: row["social_infrastructure"] for row in product["admin_units"]}

    assert rows["C"]["relative_gap_rank"] == 1
    assert rows["C"]["relative_gap_reasons"][0] == "zero_supported_facilities"
    assert rows["B"]["relative_gap_rank"] == 2
    assert rows["A"]["relative_gap_rank"] == 3


def test_public_service_view_ranks_units_without_government_services_first():
    product = build_social_public_service_product(**source_fixture())
    rows = {row["admin_unit_id"]: row["government_public_service"] for row in product["admin_units"]}

    assert rows["C"]["relative_gap_rank"] == 1
    assert rows["B"]["relative_gap_rank"] == 2
    assert rows["A"]["relative_gap_rank"] == 3
    assert rows["B"]["relative_proxy_not_authoritative_standard"] is True
    assert rows["B"]["observed_capacity_match"] is False
    assert rows["B"]["policy_outcome_claim"] is False


def test_rank_ties_are_stable_by_admin_identifier():
    sources = source_fixture()
    sources["facilities"] = []
    for row in sources["admin_units"]:
        row["service_accessibility_score"] = None
    product = build_social_public_service_product(**sources)

    assert [row["admin_unit_id"] for row in sorted(product["admin_units"], key=lambda row: row["social_infrastructure"]["relative_gap_rank"])] == ["A", "B", "C"]


def test_missing_accessibility_is_reason_not_zero_score():
    product = build_social_public_service_product(**source_fixture())
    row = next(row for row in product["admin_units"] if row["admin_unit_id"] == "C")

    assert row["service_accessibility_score"] is None
    assert "accessibility_evidence_missing" in row["social_infrastructure"]["relative_gap_reasons"]
    assert row["social_infrastructure"]["authoritative_service_deficit"] is None
