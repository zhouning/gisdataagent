import json
from pathlib import Path

from scripts.build_nl2sql_coverage_plan import build_plan
from scripts.build_nl2sql_release_scorecard import build_scorecard

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"


def _paths(prefix: str):
    return (
        ARTIFACTS / f"{prefix}_v4_scenario_free_form_benchmark_v4.json",
        ARTIFACTS / f"{prefix}_semantic_layer_v4_scenarios.json",
    )


def test_release_scorecard_proves_frozen_contract_integrity_and_separates_coverage():
    benchmark, semantic = _paths("makani_sync_full")
    report = ARTIFACTS / "makani_sync_full_gemini37flash_product_v4_baseline_native_holdout_20260825.json"
    scorecard = build_scorecard(benchmark, semantic, report_path=report)

    assert scorecard["benchmark"]["structural_checks"]["all_case_contracts_valid"] is True
    assert scorecard["benchmark"]["structural_checks"]["gold_and_safety_contracts_complete"] is True
    assert scorecard["coverage"]["benchmark_table_coverage"] == 0.989637
    assert scorecard["coverage"]["business_query_execution_table_coverage"] == 1.0
    assert scorecard["quality"]["business_query_accuracy"] == 1.0
    assert scorecard["quality"]["all_case_pass_rate"] == 0.7874015748031497
    assert scorecard["quality"]["accuracy_claimable"] is False
    assert scorecard["status"] == "attention_required"


def test_release_scorecard_rejects_historical_report_for_revised_benchmark():
    benchmark = ARTIFACTS / "makani_sync_full_free_form_benchmark_v3_revised.json"
    semantic = ARTIFACTS / "makani_sync_full_semantic_layer_v4_full_coverage.json"
    catalog = ARTIFACTS / "makani_sync_full_technical_semantic_catalog_v3.json"
    report = ARTIFACTS / "makani_sync_full_gemini37flash_baseline_full_2328_20260829.json"
    scorecard = build_scorecard(
        benchmark,
        semantic,
        catalog_path=catalog,
        report_path=report,
    )

    assert scorecard["quality"]["report_case_count"] == 2328
    assert scorecard["quality"]["report_benchmark_input_matches"] is False
    assert scorecard["quality"]["report_applies_to_full_benchmark"] is False
    assert scorecard["quality"]["report_scope_complete"] is False
    assert scorecard["quality"]["accuracy_claimable"] is False
    assert scorecard["release_gates"]["attached_report_matches_benchmark_input"] is False


def test_coverage_plan_lists_each_reviewed_field_without_claiming_gold():
    benchmark, semantic = _paths("makani_sync_full")
    plan = build_plan(benchmark, semantic)

    assert plan["claim_boundary"]["is_benchmark_score"] is False
    assert plan["claim_boundary"]["is_gold_set"] is False
    assert plan["summary"]["discovered_table_count"] == 772
    assert plan["summary"]["execution_eligible_table_count"] == 604
    assert plan["summary"]["reviewed_field_count"] == 14672
    assert plan["summary"]["reviewed_fields_without_complete_three_language_cases"] == 13783
    assert len(plan["fields"]) == 14672


def test_scorecard_machine_terminology_has_customer_facing_explanation():
    scorecard_path = ARTIFACTS / "makani_nl2sql_release_scorecard_20260825.json"
    scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
    assert scorecard["terminology"]["pending_semantic_review_asset"] == "待完成业务语义审核的数据资产题"
    assert "历史机器字段" in scorecard["terminology"]["deprecated_label"]
