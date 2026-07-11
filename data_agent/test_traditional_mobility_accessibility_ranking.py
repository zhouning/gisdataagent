from data_agent.test_traditional_mobility_accessibility import source_fixture
from data_agent.uwm.traditional_mobility_accessibility import build_mobility_accessibility_product


def ranking_fixture():
    sources = source_fixture()
    sources["surface"]["admin_service_rows"] = [
        {"admin_unit_id":"high","service_accessibility_score":0.8,"nearest_essential_service_distance_m":300.0,"nearest_essential_service_travel_time_min_proxy":4.0,"essential_service_count":5,"service_point_count":12,"road_segment_count":30,"road_length_km":10.0,"mean_road_speed_kmh":25.0},
        {"admin_unit_id":"low-far","service_accessibility_score":0.2,"nearest_essential_service_distance_m":1800.0,"nearest_essential_service_travel_time_min_proxy":25.0,"essential_service_count":1,"service_point_count":2,"road_segment_count":5,"road_length_km":2.0,"mean_road_speed_kmh":20.0},
        {"admin_unit_id":"low-near","service_accessibility_score":0.2,"nearest_essential_service_distance_m":900.0,"nearest_essential_service_travel_time_min_proxy":12.0,"essential_service_count":0,"service_point_count":0,"road_segment_count":8,"road_length_km":3.0,"mean_road_speed_kmh":22.0},
        {"admin_unit_id":"missing","service_accessibility_score":None,"nearest_essential_service_distance_m":None,"nearest_essential_service_travel_time_min_proxy":None,"essential_service_count":None,"service_point_count":None,"road_segment_count":None,"road_length_km":None,"mean_road_speed_kmh":None},
    ]
    sources["surface"]["admin_unit_count"] = 4
    return sources


def test_gap_rank_orders_low_score_then_long_distance():
    product = build_mobility_accessibility_product(**ranking_fixture())
    rows = {row["admin_unit_id"]: row for row in product["admin_units"]}

    assert rows["low-far"]["accessibility_gap_rank"] == 1
    assert rows["low-near"]["accessibility_gap_rank"] == 2
    assert rows["high"]["accessibility_gap_rank"] == 3


def test_missing_scores_are_excluded_and_sent_to_data_review():
    product = build_mobility_accessibility_product(**ranking_fixture())
    row = next(row for row in product["admin_units"] if row["admin_unit_id"] == "missing")

    assert row["accessibility_gap_rank"] is None
    assert row["ranking_exclusion_reason"] == "service_accessibility_score_missing"
    assert "collect_missing_accessibility_evidence" in row["review_priority_reasons"]
    assert product["summary"]["ranked_admin_unit_count"] == 3
    assert product["summary"]["ranking_excluded_admin_unit_count"] == 1


def test_review_reasons_are_transparent_and_do_not_prescribe_projects():
    product = build_mobility_accessibility_product(**ranking_fixture())
    rows = {row["admin_unit_id"]: row for row in product["admin_units"]}

    assert "relative_low_accessibility_score" in rows["low-far"]["review_priority_reasons"]
    assert "long_nearest_service_distance_proxy" in rows["low-far"]["review_priority_reasons"]
    assert "zero_essential_service_count" in rows["low-near"]["review_priority_reasons"]
    assert rows["low-far"]["approved_connectivity_project"] is False
    assert rows["low-far"]["expected_time_saving_min"] is None


def test_product_declares_relative_not_authoritative_thresholds():
    product = build_mobility_accessibility_product(**ranking_fixture())

    assert product["ranking_method"]["method"] == "relative_ordering_within_bound_product"
    assert product["ranking_method"]["authoritative_thresholds_used"] is False
    assert product["ranking_method"]["engineering_investment_priority"] is False
