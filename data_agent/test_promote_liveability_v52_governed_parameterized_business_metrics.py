"""Regression coverage for generic v52 parameterized metric contracts."""

import copy
import importlib.util
import json
from pathlib import Path

from data_agent.governed_virtual_nl2sql import (
    _render_direct_metric_contract_sql,
    _validate_metric_contracts,
    detect_question_language,
    resolve_direct_metric_contract,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/promote_liveability_v52_governed_parameterized_business_metrics_20260915.py"
SEMANTIC = ROOT / "docs/customer/abu_dhabi_liveability_site_validation/liveability_data_20260730_semantic_layer_v51_schema_drift_rebind_20260915.json"
ONTOLOGY = ROOT / "docs/customer/abu_dhabi_liveability_site_validation/liveability_data_20260730_ontology_v50_schema_drift_rebind_20260915.json"

spec = importlib.util.spec_from_file_location("liveability_v52_parameterized_metrics", SCRIPT)
assert spec and spec.loader
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def _semantic() -> dict:
    semantic = json.loads(SEMANTIC.read_text(encoding="utf-8"))
    ontology = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    publisher._upsert_contracts(semantic, ontology)
    _validate_metric_contracts(semantic)
    return semantic


def test_v52_bound_top_n_contracts_are_generic_and_render_only_a_typed_limit() -> None:
    semantic = _semantic()
    cases = {
        "List the top 7 districts by current quantitative liveability score.": (
            "LIVEABILITY_CURRENT_QUANTITATIVE_SCORE_RANKING_V1",
            7,
        ),
        "Show the five districts with the highest current total population.": (
            "LIVEABILITY_CURRENT_POPULATION_RANKING_V1",
            5,
        ),
        "Rank the top 12 districts by ultimate population.": (
            "LIVEABILITY_ULTIMATE_POPULATION_RANKING_V1",
            12,
        ),
        "Which ten districts have the highest QoL score in the latest cycle?": (
            "LIVEABILITY_LATEST_QOL_DISTRICT_RANKING_V1",
            10,
        ),
    }
    for question, (contract_id, limit) in cases.items():
        resolution = resolve_direct_metric_contract(
            question, detect_question_language(question), semantic
        )
        assert resolution["status"] == "matched", resolution
        assert resolution["contract_id"] == contract_id
        assert resolution["resolved_parameters"] == {"limit": limit}
        rendered = _render_direct_metric_contract_sql(
            resolution["contract"], resolution["resolved_parameters"]
        )
        assert "{{limit}}" not in rendered
        assert f"LIMIT {limit}" in rendered


def test_v52_parameter_contract_rejects_unbound_or_out_of_range_limits() -> None:
    semantic = _semantic()
    for question, expected_reason in (
        (
            "Which districts have the highest current quantitative liveability score?",
            "unbound_parameter:limit",
        ),
        (
            "Show the top 1001 districts by current quantitative liveability score.",
            "unbound_parameter:limit",
        ),
    ):
        resolution = resolve_direct_metric_contract(question, "en", semantic)
        assert resolution["status"] == "fallback"
        assert resolution["contract_id"] == "LIVEABILITY_CURRENT_QUANTITATIVE_SCORE_RANKING_V1"
        assert resolution["fallback_reason"] == expected_reason


def test_v52_business_contracts_have_declared_calculation_and_scope() -> None:
    semantic = _semantic()
    contracts = {item["contract_id"]: item for item in semantic["metric_contracts"]}
    assert contracts["LIVEABILITY_CURRENT_FPP_GAP_BY_TYPE_V1"]["metric_composition"]["formula"] == (
        "sum(needed_current) - sum(existing_count)"
    )
    assert contracts["LIVEABILITY_LATEST_QOL_DISTRICT_RANKING_V1"]["metric_composition"]["cycle_field"] == "cycle_id"
    assert contracts["LIVEABILITY_REFURBISHMENT_INSPECTED_CONDITION_BY_TYPE_V1"]["filters"] == [
        {
            "table": "public.fact_refurb_approved",
            "field": "inspection_status",
            "operator": "eq",
            "values": ["Inspected"],
        }
    ]
    answerability = {
        item["contract_id"]: item for item in semantic["semantic_answerability_contracts"]
    }
    assert "latest cycle" in answerability["LIVEABILITY_OVERALL_QOL_FORMULA_UNREVIEWED_V1"]["match"]["forbidden_terms"]["en"]


def test_v52_publisher_does_not_reference_external_evaluation_or_gold_artifacts() -> None:
    source = SCRIPT.read_text(encoding="utf-8").casefold()
    blocked = ("liveability_kb", "gold_contract", "expected_result", "benchmark_path")
    assert not any(marker in source for marker in blocked)
    assert '"gold_sql_used": false' in source
