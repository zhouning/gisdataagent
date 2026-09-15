#!/usr/bin/env python3
"""Publish v52 parameterized business metrics from reviewed source semantics.

This publisher accepts no benchmark, Gold SQL, expected result, model output,
or table-card example question.  It promotes only metric shapes whose fields,
scope, and calculation rules are already documented in the reviewed semantic
layer, then audits their canonical SQL against the currently registered source.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from data_agent.abu_dhabi_semantic_evolution import validate_semantic_evolution
from data_agent.governed_virtual_nl2sql import (
    _render_direct_metric_contract_sql,
    _validate_metric_contracts,
    _validate_row_scope_policies,
    _validate_semantic_answerability_contracts,
    _validate_semantic_caveats,
)
from data_agent.semantic_projection_policy import validate_projection_completeness_policies
from data_agent.semantic_query_ir import validate_derived_projection_policies
from data_agent.virtual_source_operator import _load_environment
from data_agent.virtual_sources import discover_virtual_source, get_virtual_source, query_virtual_source


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
SOURCE_ID = 12
OWNER = "abu-dhabi-site-operator"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v51 = _load_module(
    "liveability_v51_parameterized_metrics_parent",
    ROOT / "scripts/promote_liveability_v51_schema_drift_rebind_20260915.py",
)
base = v51.base
v40 = v51.v40

INPUT_SEMANTIC = ARTIFACT_ROOT / "liveability_data_20260730_semantic_layer_v51_schema_drift_rebind_20260915.json"
INPUT_ONTOLOGY = ARTIFACT_ROOT / "liveability_data_20260730_ontology_v50_schema_drift_rebind_20260915.json"
INPUT_CATALOG = ARTIFACT_ROOT / "liveability_data_20260730_technical_semantic_catalog_v7_schema_drift_rebind_20260915.json"
OUTPUT_SEMANTIC = ARTIFACT_ROOT / "liveability_data_20260730_semantic_layer_v52_governed_parameterized_business_metrics_20260915.json"
OUTPUT_ONTOLOGY = ARTIFACT_ROOT / "liveability_data_20260730_ontology_v51_governed_parameterized_business_metrics_20260915.json"
OUTPUT_CATALOG = ARTIFACT_ROOT / "liveability_data_20260730_technical_semantic_catalog_v8_governed_parameterized_business_metrics_20260915.json"
OUTPUT_SOURCE_AUDIT = ARTIFACT_ROOT / "liveability_v52_governed_parameterized_business_metrics_source_audit_20260915.json"
OUTPUT_PUBLICATION_AUDIT = ARTIFACT_ROOT / "liveability_v52_governed_parameterized_business_metrics_publication_audit_20260915.json"

SEMANTIC_VERSION = "abu-dhabi-liveability_data_20260730-v52-governed-parameterized-business-metrics-20260915"
ONTOLOGY_VERSION = "abu-dhabi-liveability-ontology-v51-governed-parameterized-business-metrics-20260915"
BUNDLE_ID = "abu-dhabi-liveability-current-20260915-governed-parameterized-business-metrics-v52"
METRIC_CONTRACT_VERSION = "abu-dhabi-liveability-metric-contracts-v40-governed-parameterized-business-metrics-20260915"


def _direct(*, ranked: bool = False) -> dict[str, Any]:
    value: dict[str, Any] = {
        "enabled": True,
        "mode": "canonical_bound_parameters" if ranked else "canonical_no_parameters",
        "allowed_numeric_literals": [],
        "allowed_literal_terms": [],
        "allowed_modifiers": [],
        "allowed_result_shapes": ["ranked_top_n"] if ranked else [],
    }
    if ranked:
        value["parameters"] = [
            {"name": "limit", "kind": "ranking_limit", "required": True, "minimum": 1, "maximum": 100}
        ]
        value["ranking_metric_alias"] = "metric_value"
        value["ranking_directions"] = ["desc"]
    return value


def _match(
    zh: list[list[str]], en: list[list[str]], ar: list[list[str]], *, specificity: list[str], forbidden: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "required_term_groups": {"zh": zh, "en": en, "ar": ar},
        "specificity_terms": specificity,
    }
    if forbidden:
        value["forbidden_terms"] = forbidden
    return value


def _contracts() -> list[dict[str, Any]]:
    """Reusable metric definitions, based on reviewed field definitions only."""

    return [
        {
            "contract_id": "LIVEABILITY_ASSESSMENT_COVERAGE_BY_MUNICIPALITY_PACKAGE_V1",
            "review_status": "reviewed_candidate",
            "priority": 220,
            "operation": "grouped_summary",
            "provenance": "reviewed_district_activation_and_administration_fields",
            "match": _match(
                [["评估覆盖", "评估范围", "已评估行政区"], ["行政区", "市政", "交付包", "包"], ["数量", "多少", "统计"]],
                [["assessment coverage", "assessment scope", "assessed districts"], ["municipality", "delivery package", "package"], ["count", "how many", "number"]],
                [["تغطية التقييم", "نطاق التقييم", "المناطق المقيمة"], ["بلدية", "حزمة التسليم", "حزمة"], ["عدد", "كم", "إحصاء"]],
                specificity=["assessment coverage", "评估覆盖", "تغطية التقييم"],
            ),
            "tables": ["public.dim_districts"],
            "dimensions": [
                {"table": "public.dim_districts", "field": "municipality", "alias": "municipality"},
                {"table": "public.dim_districts", "field": "package", "alias": "delivery_package"},
            ],
            "metrics": [{"aggregate": "count", "table": "public.dim_districts", "field": "district_id", "alias": "assessed_district_count"}],
            "filters": [{"table": "public.dim_districts", "field": "is_activated", "operator": "is_true"}],
            "direct_execution": _direct(),
            "canonical_sql_template": """SELECT d.municipality,d.package AS delivery_package,COUNT(d.district_id) AS assessed_district_count
FROM public.dim_districts d
WHERE d.is_activated IS TRUE
GROUP BY d.municipality,d.package
ORDER BY d.municipality,d.package
LIMIT 1000""",
        },
        {
            "contract_id": "LIVEABILITY_CURRENT_QUANTITATIVE_SCORE_RANKING_V1",
            "review_status": "reviewed_candidate",
            "priority": 235,
            "operation": "grouped_summary",
            "provenance": "reviewed_quantitative_score_stage_vocabulary_and_current_version_scope",
            "match": _match(
                [["定量宜居度", "定量宜居评分", "总体宜居度得分"], ["现状", "当前", "Existing"], ["前", "最高", "排名"]],
                [["quantitative liveability score", "quantitative livability score", "overall liveability score"], ["existing", "current"], ["top", "highest", "rank"]],
                [["درجة جودة الحياة الكمية", "درجة جودة الحياة الإجمالية"], ["الحالي", "Existing"], ["الأعلى", "ترتيب", "الأكثر"]],
                specificity=["quantitative liveability score", "定量宜居度", "درجة جودة الحياة الكمية"],
            ),
            "tables": ["public.fact_district_scores", "public.dim_calc_versions", "public.dim_districts"],
            "dimensions": [
                {"table": "public.dim_districts", "field": "name_en", "alias": "district_name"},
                {"table": "public.dim_districts", "field": "municipality", "alias": "municipality"},
            ],
            "metrics": [{"aggregate": "avg", "table": "public.fact_district_scores", "field": "overall_score", "alias": "metric_value"}],
            "filters": [
                {"table": "public.fact_district_scores", "field": "stage", "operator": "eq", "values": ["current"]},
                {"table": "public.dim_calc_versions", "field": "current_flag", "operator": "is_true"},
                {"table": "public.dim_districts", "field": "is_activated", "operator": "is_true"},
            ],
            "metric_order_by": [{"alias": "metric_value", "direction": "desc"}],
            "direct_execution": _direct(ranked=True),
            "canonical_sql_template": """SELECT d.name_en AS district_name,d.municipality,AVG(s.overall_score) AS metric_value
FROM public.fact_district_scores s
JOIN public.dim_calc_versions v ON v.calc_version_id=s.calc_version_id
JOIN public.dim_districts d ON d.district_id=s.district_id
WHERE s.stage='current' AND v.current_flag IS TRUE AND d.is_activated IS TRUE
GROUP BY d.district_id,d.name_en,d.municipality
ORDER BY metric_value DESC NULLS LAST,d.district_id
LIMIT {{limit}}""",
        },
        {
            "contract_id": "LIVEABILITY_CURRENT_POPULATION_BY_MUNICIPALITY_V1",
            "review_status": "reviewed_candidate",
            "priority": 225,
            "operation": "grouped_summary",
            "provenance": "reviewed_current_population_caliber_and_district_municipality_scope",
            "match": _match(
                [["当前人口", "现状人口"], ["市政", "行政区", "municipality"], ["总", "合计", "汇总"]],
                [["current population", "current total population"], ["municipality", "municipalities"], ["total", "sum", "by"]],
                [["السكان الحالي", "إجمالي السكان الحالي"], ["بلدية", "بلديات"], ["إجمالي", "مجموع", "حسب"]],
                specificity=["current population", "当前人口", "السكان الحالي"],
            ),
            "tables": ["public.fact_population", "public.dim_districts"],
            "dimensions": [{"table": "public.dim_districts", "field": "municipality", "alias": "municipality"}],
            "metrics": [{"aggregate": "sum", "table": "public.fact_population", "field": "total_population", "alias": "current_population"}],
            "filters": [
                {"table": "public.fact_population", "field": "age_cat", "operator": "eq", "values": ["Total"]},
                {"table": "public.fact_population", "field": "scad_table_name", "operator": "eq", "values": ["Population_Current_SCAD_20240703"]},
                {"table": "public.dim_districts", "field": "is_activated", "operator": "is_true"},
            ],
            "direct_execution": _direct(),
            "canonical_sql_template": """SELECT d.municipality,SUM(p.total_population) AS current_population
FROM public.fact_population p
JOIN public.dim_districts d ON d.district_id=p.district_id
WHERE p.age_cat='Total' AND p.scad_table_name='Population_Current_SCAD_20240703'
AND d.is_activated IS TRUE
GROUP BY d.municipality
ORDER BY d.municipality
LIMIT 1000""",
        },
        {
            "contract_id": "LIVEABILITY_CURRENT_POPULATION_RANKING_V1",
            "review_status": "reviewed_candidate",
            "priority": 230,
            "operation": "grouped_summary",
            "provenance": "reviewed_current_population_caliber_and_district_grain",
            "match": _match(
                [["当前人口", "现状人口"], ["行政区", "片区"], ["前", "最高", "排名"]],
                [["current population", "current total population"], ["district", "districts"], ["top", "highest", "rank"]],
                [["السكان الحالي", "إجمالي السكان الحالي"], ["منطقة", "مناطق"], ["الأعلى", "ترتيب", "الأكثر"]],
                specificity=["current population", "当前人口", "السكان الحالي"],
            ),
            "tables": ["public.fact_population", "public.dim_districts"],
            "dimensions": [
                {"table": "public.dim_districts", "field": "name_en", "alias": "district_name"},
                {"table": "public.dim_districts", "field": "municipality", "alias": "municipality"},
            ],
            "metrics": [{"aggregate": "sum", "table": "public.fact_population", "field": "total_population", "alias": "metric_value"}],
            "filters": [
                {"table": "public.fact_population", "field": "age_cat", "operator": "eq", "values": ["Total"]},
                {"table": "public.fact_population", "field": "scad_table_name", "operator": "eq", "values": ["Population_Current_SCAD_20240703"]},
                {"table": "public.dim_districts", "field": "is_activated", "operator": "is_true"},
            ],
            "metric_order_by": [{"alias": "metric_value", "direction": "desc"}],
            "direct_execution": _direct(ranked=True),
            "canonical_sql_template": """SELECT d.name_en AS district_name,d.municipality,SUM(p.total_population) AS metric_value
FROM public.fact_population p
JOIN public.dim_districts d ON d.district_id=p.district_id
WHERE p.age_cat='Total' AND p.scad_table_name='Population_Current_SCAD_20240703'
AND d.is_activated IS TRUE
GROUP BY d.district_id,d.name_en,d.municipality
ORDER BY metric_value DESC NULLS LAST,d.district_id
LIMIT {{limit}}""",
        },
        {
            "contract_id": "LIVEABILITY_ULTIMATE_POPULATION_BY_MUNICIPALITY_V1",
            "review_status": "reviewed_candidate",
            "priority": 225,
            "operation": "grouped_summary",
            "provenance": "reviewed_ultimate_population_definition_and_district_municipality_scope",
            "match": _match(
                [["终局人口", "最终人口", "建设完成后人口"], ["市政", "行政区", "municipality"], ["总", "合计", "汇总"]],
                [["ultimate population", "build-out population"], ["municipality", "municipalities"], ["total", "sum", "by"]],
                [["السكان النهائي", "سكان البناء الكامل"], ["بلدية", "بلديات"], ["إجمالي", "مجموع", "حسب"]],
                specificity=["ultimate population", "build-out population", "终局人口", "السكان النهائي"],
            ),
            "tables": ["public.fact_population_ultimate", "public.dim_districts"],
            "dimensions": [{"table": "public.dim_districts", "field": "municipality", "alias": "municipality"}],
            "metrics": [{"aggregate": "sum", "table": "public.fact_population_ultimate", "field": "total_population", "alias": "ultimate_population"}],
            "filters": [{"table": "public.dim_districts", "field": "is_activated", "operator": "is_true"}],
            "direct_execution": _direct(),
            "canonical_sql_template": """SELECT d.municipality,SUM(p.total_population) AS ultimate_population
FROM public.fact_population_ultimate p
JOIN public.dim_districts d ON d.district_id=p.district_id
WHERE d.is_activated IS TRUE
GROUP BY d.municipality
ORDER BY d.municipality
LIMIT 1000""",
        },
        {
            "contract_id": "LIVEABILITY_ULTIMATE_POPULATION_RANKING_V1",
            "review_status": "reviewed_candidate",
            "priority": 230,
            "operation": "grouped_summary",
            "provenance": "reviewed_ultimate_population_definition_and_district_grain",
            "match": _match(
                [["终局人口", "最终人口", "建设完成后人口"], ["行政区", "片区"], ["前", "最高", "排名"]],
                [["ultimate population", "build-out population"], ["district", "districts"], ["top", "highest", "rank"]],
                [["السكان النهائي", "سكان البناء الكامل"], ["منطقة", "مناطق"], ["الأعلى", "ترتيب", "الأكثر"]],
                specificity=["ultimate population", "build-out population", "终局人口", "السكان النهائي"],
            ),
            "tables": ["public.fact_population_ultimate", "public.dim_districts"],
            "dimensions": [
                {"table": "public.dim_districts", "field": "name_en", "alias": "district_name"},
                {"table": "public.dim_districts", "field": "municipality", "alias": "municipality"},
            ],
            "metrics": [{"aggregate": "sum", "table": "public.fact_population_ultimate", "field": "total_population", "alias": "metric_value"}],
            "filters": [{"table": "public.dim_districts", "field": "is_activated", "operator": "is_true"}],
            "metric_order_by": [{"alias": "metric_value", "direction": "desc"}],
            "direct_execution": _direct(ranked=True),
            "canonical_sql_template": """SELECT d.name_en AS district_name,d.municipality,SUM(p.total_population) AS metric_value
FROM public.fact_population_ultimate p
JOIN public.dim_districts d ON d.district_id=p.district_id
WHERE d.is_activated IS TRUE
GROUP BY d.district_id,d.name_en,d.municipality
ORDER BY metric_value DESC NULLS LAST,d.district_id
LIMIT {{limit}}""",
        },
        {
            "contract_id": "LIVEABILITY_COMMUNITY_FACILITY_PREFERENCE_BY_DISTRICT_V1",
            "review_status": "reviewed_candidate",
            "priority": 230,
            "operation": "grouped_summary",
            "provenance": "reviewed_community_engagement_rank_semantics_and_current_version_scope",
            "match": _match(
                [["社区设施", "居民最需要的设施", "社区偏好"], ["每个行政区", "各行政区", "按行政区"], ["最受欢迎", "第一", "排名第一"]],
                [["community facility", "community facilities", "community preference"], ["each district", "by district", "per district"], ["most requested", "rank 1", "top preference"]],
                [["مرفق مجتمعي", "تفضيل المجتمع", "احتياجات المرافق المجتمعية"], ["كل منطقة", "حسب المنطقة"], ["الأكثر طلباً", "المرتبة الأولى", "رتبة 1"]],
                specificity=["community preference", "most requested", "社区偏好", "تفضيل المجتمع"],
            ),
            "tables": ["public.fact_ce_ranking_scores", "public.dim_calc_versions", "public.dim_districts"],
            "dimensions": [
                {"table": "public.dim_districts", "field": "name_en", "alias": "district_name"},
                {"table": "public.dim_districts", "field": "municipality", "alias": "municipality"},
                {"table": "public.fact_ce_ranking_scores", "field": "item_name", "alias": "facility_preference"},
            ],
            "metrics": [{"aggregate": "max", "table": "public.fact_ce_ranking_scores", "field": "votes", "alias": "preference_votes"}],
            "filters": [
                {"table": "public.fact_ce_ranking_scores", "field": "theme", "operator": "eq", "values": ["community_facilities_needs"]},
                {"table": "public.fact_ce_ranking_scores", "field": "rank", "operator": "eq", "values": [1]},
                {"table": "public.dim_calc_versions", "field": "current_flag", "operator": "is_true"},
                {"table": "public.dim_districts", "field": "is_activated", "operator": "is_true"},
            ],
            "direct_execution": _direct(),
            "canonical_sql_template": """SELECT d.name_en AS district_name,d.municipality,c.item_name AS facility_preference,
MAX(c.votes) AS preference_votes
FROM public.fact_ce_ranking_scores c
JOIN public.dim_calc_versions v ON v.calc_version_id=c.calc_version_id
JOIN public.dim_districts d ON d.district_id=c.district_id
WHERE c.theme='community_facilities_needs' AND c.rank=1
AND v.current_flag IS TRUE AND d.is_activated IS TRUE
GROUP BY d.district_id,d.name_en,d.municipality,c.item_name
ORDER BY d.municipality,d.name_en,c.item_name
LIMIT 1000""",
        },
        {
            "contract_id": "LIVEABILITY_LATEST_QOL_DISTRICT_RANKING_V1",
            "review_status": "reviewed_candidate",
            "priority": 240,
            "operation": "grouped_summary",
            "provenance": "reviewed_qol_latest_cycle_and_district_score_definition",
            "match": _match(
                [["QoL", "生活质量", "生活品质满意度"], ["最新周期", "当前周期", "latest cycle"], ["行政区", "片区"], ["前", "最高", "排名"]],
                [["QoL", "quality of life", "qol satisfaction"], ["latest cycle", "current cycle"], ["district", "districts"], ["top", "highest", "rank"]],
                [["جودة الحياة", "QoL"], ["أحدث دورة", "الدورة الحالية"], ["منطقة", "مناطق"], ["الأعلى", "ترتيب", "الأكثر"]],
                specificity=["latest cycle", "latest QoL", "最新周期", "أحدث دورة"],
                forbidden={"zh": ["城市", "全市"], "en": ["citywide", "Abu Dhabi City"], "ar": ["على مستوى المدينة", "مدينة أبوظبي"]},
            ),
            "tables": ["public.fact_qol_district_scores", "public.dim_districts"],
            "dimensions": [
                {"table": "public.dim_districts", "field": "name_en", "alias": "district_name"},
                {"table": "public.dim_districts", "field": "municipality", "alias": "municipality"},
            ],
            "metrics": [{"aggregate": "avg", "table": "public.fact_qol_district_scores", "field": "overall_score", "alias": "metric_value"}],
            "filters": [{"table": "public.dim_districts", "field": "is_activated", "operator": "is_true"}],
            "metric_order_by": [{"alias": "metric_value", "direction": "desc"}],
            "direct_execution": _direct(ranked=True),
            "metric_composition": {"kind": "latest_cycle", "cycle_table": "public.fact_qol_district_scores", "cycle_field": "cycle_id", "null_measure_policy": "exclude_null_overall_score"},
            "canonical_sql_template": """SELECT d.name_en AS district_name,d.municipality,AVG(q.overall_score) AS metric_value
FROM public.fact_qol_district_scores q
JOIN public.dim_districts d ON d.district_id=q.district_id
WHERE q.cycle_id=(SELECT MAX(cycle_id) FROM public.fact_qol_district_scores)
AND q.overall_score IS NOT NULL AND d.is_activated IS TRUE
GROUP BY d.district_id,d.name_en,d.municipality
ORDER BY metric_value DESC NULLS LAST,d.district_id
LIMIT {{limit}}""",
        },
        {
            "contract_id": "LIVEABILITY_REFURBISHMENT_INSPECTED_CONDITION_BY_TYPE_V1",
            "review_status": "reviewed_candidate",
            "priority": 220,
            "operation": "grouped_summary",
            "provenance": "reviewed_refurbishment_condition_score_and_inspection_status_definition",
            "match": _match(
                [["翻新", "资产状况", "条件得分"], ["已检查", "已检验", "inspected"], ["类型", "类别"], ["平均", "均值"]],
                [["refurbishment", "asset condition", "condition score"], ["inspected"], ["type", "by type"], ["average", "mean"]],
                [["التجديد", "حالة الأصل", "درجة الحالة"], ["تم الفحص", "مفحوص"], ["نوع", "حسب النوع"], ["متوسط"]],
                specificity=["asset condition", "refurbishment", "资产状况", "حالة الأصل"],
            ),
            "tables": ["public.fact_refurb_approved"],
            "dimensions": [
                {"table": "public.fact_refurb_approved", "field": "survey_year", "alias": "survey_year"},
                {"table": "public.fact_refurb_approved", "field": "refurb_type", "alias": "refurbishment_type"},
            ],
            "metrics": [{"aggregate": "avg", "table": "public.fact_refurb_approved", "field": "score", "alias": "average_condition_score"}],
            "filters": [{"table": "public.fact_refurb_approved", "field": "inspection_status", "operator": "eq", "values": ["Inspected"]}],
            "direct_execution": _direct(),
            "canonical_sql_template": """SELECT r.survey_year,r.refurb_type AS refurbishment_type,
AVG(r.score) AS average_condition_score
FROM public.fact_refurb_approved r
WHERE r.inspection_status='Inspected' AND r.score IS NOT NULL
GROUP BY r.survey_year,r.refurb_type
ORDER BY r.survey_year,r.refurb_type
LIMIT 1000""",
        },
        {
            "contract_id": "LIVEABILITY_CURRENT_FPP_GAP_BY_TYPE_V1",
            "review_status": "reviewed_candidate",
            "priority": 215,
            "operation": "grouped_summary",
            "provenance": "reviewed_current_facility_requirement_and_existing_supply_definition",
            "match": _match(
                [["设施供给缺口", "当前设施缺口", "FPP缺口"], ["类型", "类别"], ["当前", "现状"]],
                [["facility provision gap", "current facility gap", "FPP gap"], ["type", "category"], ["current", "existing"]],
                [["فجوة توفير المرافق", "فجوة المرافق الحالية", "فجوة FPP"], ["نوع", "فئة"], ["حالي", "قائم"]],
                specificity=["facility provision gap", "FPP gap", "设施供给缺口", "فجوة توفير المرافق"],
            ),
            "tables": ["public.fact_facility_provision", "public.dim_districts"],
            "dimensions": [
                {"table": "public.dim_districts", "field": "municipality", "alias": "municipality"},
                {"table": "public.fact_facility_provision", "field": "category_name", "alias": "facility_category"},
                {"table": "public.fact_facility_provision", "field": "subcategory_name", "alias": "facility_type"},
            ],
            "metrics": [
                {"aggregate": "sum", "table": "public.fact_facility_provision", "field": "needed_current", "alias": "current_required_count"},
                {"aggregate": "sum", "table": "public.fact_facility_provision", "field": "existing_count", "alias": "existing_supply_count"},
            ],
            "filters": [{"table": "public.dim_districts", "field": "is_activated", "operator": "is_true"}],
            "metric_composition": {"kind": "difference", "formula": "sum(needed_current) - sum(existing_count)", "unit": "items", "stage": "current"},
            "canonical_sql_template": """SELECT d.municipality,f.category_name AS facility_category,f.subcategory_name AS facility_type,
SUM(f.needed_current) AS current_required_count,SUM(f.existing_count) AS existing_supply_count,
SUM(f.needed_current)-SUM(f.existing_count) AS current_provision_gap
FROM public.fact_facility_provision f
JOIN public.dim_districts d ON d.district_id=f.district_id
WHERE d.is_activated IS TRUE
GROUP BY d.municipality,f.category_name,f.subcategory_name
ORDER BY current_provision_gap DESC NULLS LAST,d.municipality,f.category_name,f.subcategory_name
LIMIT 1000""",
        },
    ]


def _assert_no_unreviewed_drift(catalog: Mapping[str, Any], snapshot: Mapping[str, Any]) -> list[str]:
    old = v40._catalog_resources(catalog)
    current = v40._resources(snapshot)
    if set(old) != set(current):
        raise RuntimeError("discovery_resource_set_changed_requires_review")
    record_count_changes: list[str] = []
    for table in sorted(old):
        previous, observed = old[table], current[table]
        if v40._catalog_columns(previous) != v40._snapshot_columns(observed):
            raise RuntimeError(f"discovery_field_change_requires_review:{table}")
        for key in ("foreign_keys", "primary_key", "indexes"):
            if v40._metadata_signature(previous, key) != v40._metadata_signature(observed, key):
                raise RuntimeError(f"discovery_metadata_change_requires_review:{table}:{key}")
        if previous.get("estimated_record_count") != observed.get("estimated_record_count"):
            # Cardinality changes are expected as source data is refreshed;
            # they are evidence for a rebind, not a schema change.
            record_count_changes.append(table)
    return record_count_changes


def _upsert_contracts(semantic: dict[str, Any], ontology: dict[str, Any]) -> list[str]:
    merged = {str(item.get("contract_id")): copy.deepcopy(item) for item in semantic.get("metric_contracts") or [] if isinstance(item, dict) and item.get("contract_id")}
    additions = _contracts()
    for contract in additions:
        merged[contract["contract_id"]] = contract
    semantic["metric_contracts"] = list(merged.values())
    ontology["runtime_metric_contracts"] = copy.deepcopy(semantic["metric_contracts"])

    # The previous clarification was correct before the reviewed QoL score
    # and current-cycle rule were promoted. It remains in force for requests
    # outside the explicit latest-cycle QoL contracts above.
    answerability = copy.deepcopy(semantic.get("semantic_answerability_contracts") or [])
    for contract in answerability:
        if contract.get("contract_id") == "LIVEABILITY_OVERALL_QOL_FORMULA_UNREVIEWED_V1":
            forbidden = contract.setdefault("match", {}).setdefault("forbidden_terms", {})
            for language, terms in {
                "zh": ["最新周期", "当前周期"],
                "en": ["latest cycle", "current cycle"],
                "ar": ["أحدث دورة", "الدورة الحالية"],
            }.items():
                forbidden[language] = list(dict.fromkeys([*(forbidden.get(language) or []), *terms]))
    semantic["semantic_answerability_contracts"] = answerability
    ontology["runtime_answerability_contracts"] = copy.deepcopy(answerability)
    ontology["semantic_answerability_contracts"] = copy.deepcopy(answerability)
    semantic["governed_parameterized_metric_registry"] = {
        "schema": "gda.governed-parameterized-metric-registry.v1",
        "review_status": "reviewed",
        "contracts": [
            {"contract_id": item["contract_id"], "parameter_kinds": [parameter["kind"] for parameter in (item.get("direct_execution") or {}).get("parameters") or []]}
            for item in additions
        ],
        "claim_boundary": {"benchmark_questions_used": False, "gold_sql_used": False, "gold_results_used": False, "model_outputs_used": False, "source_rows_persisted": False},
    }
    ontology["governed_parameterized_metric_registry"] = copy.deepcopy(semantic["governed_parameterized_metric_registry"])
    return [item["contract_id"] for item in additions]


async def _audit_contract_queries(semantic: dict[str, Any]) -> dict[str, Any]:
    audit = await v51.v50._audit_contract_queries(semantic)
    source = get_virtual_source(SOURCE_ID, OWNER)
    if source is None:
        raise RuntimeError("registered_source_unavailable")
    probes = dict(audit.get("contract_probes") or {})
    for contract in _contracts():
        policy = contract.get("direct_execution") or {}
        if policy.get("mode") == "canonical_bound_parameters":
            sql = _render_direct_metric_contract_sql(contract, {"limit": 10})
        else:
            sql = str(contract["canonical_sql_template"])
        result = await query_virtual_source(source, limit=1000, extra_params={"sql": sql, "geom_column": ""}, register_result=False)
        if isinstance(result, dict):
            raise RuntimeError(f"business_metric_probe_failed:{contract['contract_id']}:{result.get('message') or result.get('status') or 'query_failed'}")
        expected = [str(item.get("alias") or "") for item in [*(contract.get("dimensions") or []), *(contract.get("metrics") or [])] if str(item.get("alias") or "")]
        columns = [str(column) for column in result.columns]
        if not set(expected) <= set(columns):
            raise RuntimeError(f"business_metric_probe_columns_invalid:{contract['contract_id']}")
        probes[contract["contract_id"]] = {"statement_sha256": base._sha256(sql.encode("utf-8")), "row_count": int(len(result.index)), "columns": columns, "source_rows_persisted": False}
    audit.update({
        "schema": "gda.liveability-v52-governed-parameterized-business-metrics-source-audit.v1",
        "contract_probes": probes,
        "claim_boundary": {"read_only_query_execution": True, "persisted_evidence": "statement_digest_result_row_count_and_column_names_only", "source_rows_persisted": False, "benchmark_questions_used": False, "gold_sql_used": False, "gold_results_used": False, "model_outputs_used": False},
    })
    return audit


def _set_evolution(semantic: dict[str, Any], ontology: dict[str, Any], audit_sha256: str) -> None:
    evolution = copy.deepcopy(semantic.get("semantic_evolution") or {})
    parent_semantic = str(semantic.get("semantic_version") or "")
    parent_ontology = str(ontology.get("ontology_enrichment_version") or ontology.get("overlay_id") or "")
    if not parent_semantic or not parent_ontology:
        raise RuntimeError("parent_version_missing")
    evolution.update({
        "schema": "gda.abu-dhabi-semantic-evolution.v1",
        "change_id": "abu-dhabi-liveability-20260915-v52-governed-parameterized-business-metrics",
        "parent_semantic_version": parent_semantic,
        "parent_ontology_version": parent_ontology,
        "source_evidence": [*(evolution.get("source_evidence") or []), {"path": base._relative(OUTPUT_SOURCE_AUDIT), "sha256": audit_sha256, "benchmark_questions_used": False, "gold_sql_used": False, "gold_results_used": False, "model_outputs_used": False}],
        "changes": [*(evolution.get("changes") or []), "added source-audited business metric contracts for coverage, population, quantitative scores, community preference, QoL, refurbishment condition, and current FPP gap", "added bounded Top-N parameter compilation that only substitutes a validated integer into a reviewed canonical template", "narrowed the prior QoL clarification only where the reviewed latest-cycle contract defines the score and cycle rule"],
        "benchmark_questions_used": False,
        "gold_sql_used": False,
        "gold_results_used": False,
        "model_outputs_used": False,
        "source_rows_persisted": False,
    })
    semantic["semantic_evolution"] = evolution
    ontology["semantic_evolution"] = copy.deepcopy(evolution)


def publish() -> dict[str, Any]:
    _load_environment()
    discovery = asyncio.run(discover_virtual_source(SOURCE_ID, OWNER))
    if discovery.get("status") != "ok":
        raise RuntimeError("fresh_discovery_failed")
    binding, snapshot = v51._binding_and_snapshot()
    catalog = v51._load(INPUT_CATALOG)
    record_count_changes = _assert_no_unreviewed_drift(catalog, snapshot)
    semantic = v51._rebind(v51._load(INPUT_SEMANTIC), binding["discovery_fingerprint"], binding["profile_fingerprint"])
    ontology = v51._rebind(v51._load(INPUT_ONTOLOGY), binding["discovery_fingerprint"], binding["profile_fingerprint"])
    catalog = v51._rebind(catalog, binding["discovery_fingerprint"], binding["profile_fingerprint"])
    semantic["source_binding"] = copy.deepcopy(binding)
    ontology["source_evidence"] = {**(ontology.get("source_evidence") or {}), **binding, "contains_source_rows": False}
    catalog["source_evidence"] = {**(catalog.get("source_evidence") or {}), **binding, "contains_source_rows": False}
    contract_ids = _upsert_contracts(semantic, ontology)
    source_audit = asyncio.run(_audit_contract_queries(semantic))
    source_audit["discovery_metadata_refresh"] = {
        "estimated_record_count_changed_tables": record_count_changes,
        "structural_drift_detected": False,
        "source_rows_persisted": False,
    }
    source_audit_sha256 = base._sha256(base._raw(source_audit))
    _set_evolution(semantic, ontology, source_audit_sha256)
    semantic.update({"semantic_version": SEMANTIC_VERSION, "metric_contract_version": METRIC_CONTRACT_VERSION, "artifact_bundle_id": BUNDLE_ID, "ontology_overlay": base._relative(OUTPUT_ONTOLOGY), "technical_catalog": base._relative(OUTPUT_CATALOG)})
    semantic["gold_compatible_semantic_versions"] = list(dict.fromkeys([*(semantic.get("gold_compatible_semantic_versions") or []), SEMANTIC_VERSION]))
    ontology.update({"ontology_enrichment_version": ONTOLOGY_VERSION, "overlay_id": ONTOLOGY_VERSION, "artifact_bundle_id": BUNDLE_ID})
    catalog["artifact_bundle_id"] = BUNDLE_ID
    publication = {"status": "published_v52", "purpose": "governed_parameterized_business_metrics", "contract_ids": contract_ids, "source_audit_path": base._relative(OUTPUT_SOURCE_AUDIT), "source_audit_sha256": source_audit_sha256, "benchmark_questions_used": False, "gold_sql_used": False, "gold_results_used": False, "model_outputs_used": False, "source_rows_persisted": False}
    semantic["governed_parameterized_business_metrics_publication"] = copy.deepcopy(publication)
    ontology["governed_parameterized_business_metrics_publication"] = copy.deepcopy(publication)
    _validate_metric_contracts(semantic)
    _validate_row_scope_policies(semantic)
    _validate_semantic_answerability_contracts(semantic)
    _validate_semantic_caveats(semantic)
    validate_projection_completeness_policies(semantic)
    validate_derived_projection_policies(semantic)
    validate_semantic_evolution(semantic, ontology)
    if ontology.get("runtime_metric_contracts") != semantic.get("metric_contracts"):
        raise RuntimeError("ontology_runtime_metric_contracts_out_of_sync")
    if ontology.get("runtime_answerability_contracts") != semantic.get("semantic_answerability_contracts"):
        raise RuntimeError("ontology_runtime_answerability_contracts_out_of_sync")
    catalog_sha = base._write_new(OUTPUT_CATALOG, catalog)
    source_audit_sha = base._write_new(OUTPUT_SOURCE_AUDIT, source_audit)
    semantic_sha = base._write_new(OUTPUT_SEMANTIC, semantic)
    ontology_sha = base._write_new(OUTPUT_ONTOLOGY, ontology)
    publication_audit = {"schema": "gda.liveability-v52-governed-parameterized-business-metrics-publication-audit.v1", "generated_at": datetime.now(UTC).isoformat(), "status": "complete", "semantic_version": SEMANTIC_VERSION, "ontology_version": ONTOLOGY_VERSION, "semantic_sha256": semantic_sha, "ontology_sha256": ontology_sha, "catalog_sha256": catalog_sha, "source_audit_sha256": source_audit_sha, "publication": publication}
    publication_sha = base._write_new(OUTPUT_PUBLICATION_AUDIT, publication_audit)
    bundle = copy.deepcopy(base._load(base.BUNDLE))
    bundle.update({"artifact_bundle_id": BUNDLE_ID, "bundle_id": BUNDLE_ID, "semantic_version": SEMANTIC_VERSION, "ontology_version": ONTOLOGY_VERSION, "generated_at": datetime.now(UTC).isoformat(), "source": binding})
    artifacts = bundle.setdefault("artifacts", {})
    artifacts["semantic"] = {"role": "runtime_semantic_layer", "path": base._relative(OUTPUT_SEMANTIC), "sha256": semantic_sha}
    artifacts["ontology"] = {"role": "ontology_overlay", "path": base._relative(OUTPUT_ONTOLOGY), "sha256": ontology_sha}
    artifacts["catalog"] = {"role": "technical_metadata_catalog", "path": base._relative(OUTPUT_CATALOG), "sha256": catalog_sha}
    artifacts["governed_parameterized_business_metrics_source_audit"] = {"role": "source_aggregate_audit", "path": base._relative(OUTPUT_SOURCE_AUDIT), "sha256": source_audit_sha}
    artifacts["governed_parameterized_business_metrics_publication_audit"] = {"role": "metric_publication_audit", "path": base._relative(OUTPUT_PUBLICATION_AUDIT), "sha256": publication_sha}
    bundle.setdefault("claim_boundary", {}).update({"v52_benchmark_questions_used": False, "v52_gold_sql_used": False, "v52_gold_results_used": False, "v52_model_outputs_used": False, "v52_source_rows_persisted": False})
    base._write_bundle(bundle)
    return {"status": "published", "source": binding, "semantic": base._relative(OUTPUT_SEMANTIC), "ontology": base._relative(OUTPUT_ONTOLOGY), "catalog_sha256": catalog_sha, "source_audit": base._relative(OUTPUT_SOURCE_AUDIT), "publication_audit": base._relative(OUTPUT_PUBLICATION_AUDIT), "contract_ids": contract_ids}


if __name__ == "__main__":
    print(json.dumps(publish(), ensure_ascii=False, indent=2))
