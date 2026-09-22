"""Contract tests for all-scenario decision-support reports."""

from __future__ import annotations

from data_agent.abu_dhabi_flood_report_service import (
    REPORT_TYPES,
    data_source_matrix,
    simulation_report_html,
    simulation_report_payload,
)


def test_data_admission_report_exposes_source_classes_and_how_actions():
    report = simulation_report_payload("data_admission")
    assert report["schema"].endswith("simulation_report.v1")
    assert {row["source_class"] for row in report["data_sources"]} >= {"customer_authoritative", "public_proxy", "model_derived"}
    action = report["decision_support"]["priority_actions"][0]
    assert action["recommended_action"]
    assert action["verification_run"]


def test_every_report_type_has_a_machine_contract():
    assert set(REPORT_TYPES) == {"data_admission", "design_storm", "swmm_scenario", "citywide_2d", "gwm_rollout", "historical_replay"}
    report = simulation_report_payload("data_admission")
    assert report["model_chain"][:3] == ["Data admission", "EPA SWMM", "ANUGA 2D"]


def test_english_report_contains_no_chinese_for_catalog_report():
    html = simulation_report_html("data_admission", "en-US")
    assert not any("\u3400" <= char <= "\u9fff" for char in html)
    assert "Inputs used by this report" in html
    assert "Recommended action" in html


def test_source_matrix_has_customer_dtm_and_public_dem_replacement_rules():
    rows = {row["name"]: row for row in data_source_matrix()}
    assert rows["客户 dtm_5M.tif"]["source_class"] == "customer_authoritative"
    assert rows["Copernicus DEM GLO-30"]["source_class"] == "public_proxy"
    assert "重跑" in rows["Copernicus DEM GLO-30"]["replacement_rule"]
