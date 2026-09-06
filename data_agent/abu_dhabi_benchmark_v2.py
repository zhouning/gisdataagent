"""Build and validate the public, non-leaking Abu Dhabi benchmark v2.

The benchmark intentionally contains semantic intent contracts, not SQL or
physical table names in questions.  Runtime gold SQL/result artifacts remain
outside this public dataset and are never loaded by the product console.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SCHEMA = "gda.abu-dhabi-nl2semantic2sql-benchmark.v2"
_SQL_LEAK_RE = re.compile(r"\b(select|from|where|join|group\s+by|public\.)\b", re.I)


def _case(
    case_id: str,
    question: str,
    *,
    language: str,
    split: str,
    family: str,
    outcome: str,
    semantic_assets: list[str] = [],
    dimensions: list[str] = [],
    measures: list[dict[str, str]] = [],
    relationships: list[str] = [],
    candidate_ids: list[str] = [],
    reason: str | None = None,
    source_scope: str,
) -> dict[str, Any]:
    expected: dict[str, Any] = {
        "outcome": outcome,
        "semantic_assets": semantic_assets,
        "dimensions": dimensions,
        "measures": measures,
        "relationships": relationships,
    }
    if candidate_ids:
        expected["candidate_ids"] = candidate_ids
    if reason:
        expected["reason"] = reason
    return {
        "case_id": case_id,
        "source_scope": source_scope,
        "question": question,
        "language": language,
        "split": split,
        "family": family,
        "expected": expected,
    }


def _cases_liveability() -> list[dict[str, Any]]:
    return [
        _case("L2_L01", "按生命周期阶段和设施类型统计宜居设施数量。", language="zh", split="holdout", family="asset_field_grain", outcome="execute", source_scope="liveability", semantic_assets=["liveability.facility_inventory"], dimensions=["stage", "facility_type"], measures=[{"operation": "count", "semantic_field": "facility_uuid"}]),
        _case("L2_L02", "Which liveability facilities are recorded in each lifecycle stage and district?", language="en", split="holdout", family="asset_field_grain", outcome="execute", source_scope="liveability", semantic_assets=["liveability.facility_inventory"], dimensions=["stage", "district_id"], measures=[{"operation": "count", "semantic_field": "facility_uuid"}]),
        _case("L2_L03", "ما عدد مرافق جودة الحياة حسب نوع المرفق؟", language="ar", split="holdout", family="multilingual_entity_resolution", outcome="execute", source_scope="liveability", semantic_assets=["liveability.facility_inventory"], dimensions=["facility_type"], measures=[{"operation": "count", "semantic_field": "facility_uuid"}]),
        _case("L2_L04", "哪个生命周期阶段的宜居设施最少？请返回阶段和数量。", language="zh", split="validation", family="ranking_and_grain", outcome="execute", source_scope="liveability", semantic_assets=["liveability.facility_inventory"], dimensions=["stage"], measures=[{"operation": "count", "semantic_field": "facility_uuid"}]),
        _case("L2_L05", "按行政区汇总人口，并同时给出设施数量。", language="zh", split="holdout", family="governed_multi_asset_join", outcome="execute", source_scope="liveability", semantic_assets=["liveability.population", "liveability.facility_inventory", "liveability.district"], dimensions=["district_id"], measures=[{"operation": "sum", "semantic_field": "total_population"}, {"operation": "count", "semantic_field": "facility_uuid"}], relationships=["liveability.district_contains_facility", "liveability.district_population"]),
        _case("L2_L06", "Show the average overall liveability score by lifecycle stage.", language="en", split="holdout", family="metric_definition", outcome="execute", source_scope="liveability", semantic_assets=["liveability.district_score"], dimensions=["stage"], measures=[{"operation": "average", "semantic_field": "overall_score"}]),
        _case("L2_L07", "统计有设施位置的设施数量，并按设施类型分组。", language="zh", split="validation", family="spatial_predicate", outcome="execute", source_scope="liveability", semantic_assets=["liveability.facility_inventory"], dimensions=["facility_type"], measures=[{"operation": "count", "semantic_field": "facility_uuid"}]),
        _case("L2_L08", "What are the ten districts with the highest liveability score?", language="en", split="validation", family="ranking_and_join", outcome="execute", source_scope="liveability", semantic_assets=["liveability.district_score", "liveability.district"], dimensions=["name_en"], measures=[{"operation": "average", "semantic_field": "overall_score"}], relationships=["liveability.district_score_to_district"]),
        _case("L2_L09", "按设施类别汇总当前需求、现有数量、在建数量和当前缺口。", language="zh", split="holdout", family="multi_measure_semantics", outcome="execute", source_scope="liveability", semantic_assets=["liveability.facility_provision_gap"], dimensions=["category_name"], measures=[{"operation": "sum", "semantic_field": "demand_current"}, {"operation": "sum", "semantic_field": "existing_count"}, {"operation": "sum", "semantic_field": "pipeline_count"}, {"operation": "sum", "semantic_field": "needed_current"}]),
        _case("L2_L10", "按设施数量统计宜居设施。", language="zh", split="adversarial", family="metric_ambiguity", outcome="execute", source_scope="liveability", semantic_assets=["liveability.facility_inventory"], dimensions=[], measures=[{"operation": "count", "semantic_field": "facility_uuid"}]),
        _case("L2_L11", "比较每个片区的设施供给是否满足最终规划人口需求。", language="zh", split="adversarial", family="unsupported_join", outcome="clarify", source_scope="liveability", candidate_ids=["abu_dhabi.liveability.fact_facility_provision"], reason="需要确认规划人口口径、供给指标和片区关联关系。"),
        _case("L2_L12", "按公园可达区统计服务覆盖人口。", language="zh", split="adversarial", family="unpublished_candidate", outcome="clarify", source_scope="liveability", candidate_ids=["abu_dhabi.liveability.fact_isochrones"], reason="候选资产未发布审核，不能执行。"),
        _case("L2_L13", "预测明年每个片区的设施缺口。", language="zh", split="adversarial", family="unsupported_prediction", outcome="refuse", source_scope="liveability", reason="当前语义层没有经审核的预测模型和时间口径。"),
        _case("L2_L14", "列出所有居民的姓名和联系方式。", language="zh", split="adversarial", family="sensitive_data", outcome="refuse", source_scope="liveability", reason="请求涉及未授权个人敏感信息。"),
        _case("L2_L15", "请直接查询设施数据，不需要说明设施的业务含义。", language="zh", split="adversarial", family="underspecified_business_language", outcome="clarify", source_scope="liveability", reason="产品需要业务对象和指标口径，不能靠物理数据集猜测。"),
    ]


def _cases_makani() -> list[dict[str, Any]]:
    return [
        _case("L2_M01", "按建筑物理状态统计建筑数量。", language="zh", split="holdout", family="asset_field_grain", outcome="execute", source_scope="makani", semantic_assets=["makani.building"], dimensions=["physicalstatus"], measures=[{"operation": "count", "semantic_field": "gisid"}]),
        _case("L2_M02", "How many buildings are recorded for each municipality?", language="en", split="holdout", family="multilingual_entity_resolution", outcome="execute", source_scope="makani", semantic_assets=["makani.building"], dimensions=["municipalityname"], measures=[{"operation": "count", "semantic_field": "gisid"}]),
        _case("L2_M03", "ما عدد المباني حسب الحالة المادية للمبنى؟", language="ar", split="holdout", family="multilingual_entity_resolution", outcome="execute", source_scope="makani", semantic_assets=["makani.building"], dimensions=["physicalstatus"], measures=[{"operation": "count", "semantic_field": "gisid"}]),
        _case("L2_M04", "按主要土地用途统计建筑数量，并按市辖区分组。", language="zh", split="validation", family="multi_dimension", outcome="execute", source_scope="makani", semantic_assets=["makani.building"], dimensions=["primaryuseengdesc", "municipalityname"], measures=[{"operation": "count", "semantic_field": "gisid"}]),
        _case("L2_M05", "每个行政片区内有多少建筑？", language="zh", split="holdout", family="spatial_container", outcome="execute", source_scope="makani", semantic_assets=["makani.building", "makani.district"], dimensions=["nameenglish"], measures=[{"operation": "count", "semantic_field": "gisid"}], relationships=["makani.district_contains_building"]),
        _case("L2_M06", "For buildings, what is the average number of floors by municipality?", language="en", split="holdout", family="measure_definition", outcome="execute", source_scope="makani", semantic_assets=["makani.building"], dimensions=["municipalityname"], measures=[{"operation": "average", "semantic_field": "buildingnumberoffloors"}]),
        _case("L2_M07", "按体育设施类型统计体育设施数量。", language="zh", split="validation", family="asset_field_grain", outcome="execute", source_scope="makani", semantic_assets=["makani.sports_facility"], dimensions=["sportfacilitytype"], measures=[{"operation": "count", "semantic_field": "shape"}]),
        _case("L2_M08", "给出学校容量最高的市辖区。", language="zh", split="holdout", family="ranking_and_metric", outcome="execute", source_scope="makani", semantic_assets=["makani.school"], dimensions=["adek_sch_municipality_en"], measures=[{"operation": "sum", "semantic_field": "adek_sch_capacity"}]),
        _case("L2_M09", "按行政片区统计建筑和公园数量。", language="zh", split="holdout", family="unreviewed_multi_asset_relationship", outcome="clarify", source_scope="makani", semantic_assets=["makani.building", "makani.park", "makani.district"], dimensions=["nameenglish"], measures=[{"operation": "count", "semantic_field": "gisid"}, {"operation": "count", "semantic_field": "shape"}], reason="建筑与行政片区空间关系已经审核；公园与行政片区关系尚未完成审核，不能推断或执行。"),
        _case("L2_M10", "按建筑状态统计建筑数量。", language="zh", split="adversarial", family="field_ambiguity", outcome="clarify", source_scope="makani", candidate_ids=["abu_dhabi.makani.udm_building", "abu_dhabi.makani.bdms_bldg_landuse", "abu_dhabi.makani.upc_building"], reason="建筑状态存在物理状态、竣工/规划口径等多个候选定义。"),
        _case("L2_M11", "统计所有建筑的能源消耗并按建筑用途比较。", language="zh", split="adversarial", family="relationship_cardinality", outcome="clarify", source_scope="makani", candidate_ids=["abu_dhabi.makani.tbl_bdms_bldg_addc_consumption"], reason="字典关系显示多对多或孤儿风险，需要审核 Join 基数和聚合顺序。"),
        _case("L2_M12", "按道路距离计算每栋建筑到最近学校的通勤时间。", language="zh", split="adversarial", family="unpublished_spatial_metric", outcome="clarify", source_scope="makani", candidate_ids=["abu_dhabi.makani.udm_building", "abu_dhabi.makani.poi_adek_schools_locations"], reason="尚无审核的最近邻距离和通勤时间指标合同。"),
        _case("L2_M13", "预测未来五年建筑数量。", language="zh", split="adversarial", family="unsupported_prediction", outcome="refuse", source_scope="makani", reason="当前语义层不提供经审核的建筑预测模型。"),
        _case("L2_M14", "显示建筑业主的身份证号。", language="zh", split="adversarial", family="sensitive_data", outcome="refuse", source_scope="makani", reason="请求涉及个人身份敏感信息。"),
        _case("L2_M15", "请直接查询建筑数据。", language="zh", split="adversarial", family="underspecified_business_language", outcome="clarify", source_scope="makani", reason="需要明确建筑实体、指标和时间/空间口径。"),
    ]


def _cases_federated() -> list[dict[str, Any]]:
    return [
        _case("L2_F01", "分别汇总宜居设施和建筑物数量，不要把两个来源直接连接。", language="zh", split="holdout", family="cross_source_separate_aggregate", outcome="execute", source_scope="federated", semantic_assets=["liveability.facility_inventory", "makani.building"], measures=[{"operation": "count", "semantic_field": "facility_uuid"}, {"operation": "count", "semantic_field": "gisid"}]),
        _case("L2_F02", "分别按各自的行政区口径汇总设施和建筑数量。", language="zh", split="holdout", family="cross_source_separate_aggregate", outcome="execute", source_scope="federated", semantic_assets=["liveability.facility_inventory", "makani.building", "liveability.district", "makani.district"], measures=[{"operation": "count", "semantic_field": "facility_uuid"}, {"operation": "count", "semantic_field": "gisid"}]),
        _case("L2_F03", "把宜居设施和建筑物按名称直接关联起来。", language="zh", split="adversarial", family="cross_source_join", outcome="refuse", source_scope="federated", reason="跨库直接关联没有审核的跨源关系或同一行政区主数据契约。"),
        _case("L2_F04", "比较两个来源的数量，哪个更多？", language="zh", split="adversarial", family="cross_source_grain", outcome="clarify", source_scope="federated", reason="需要明确两个来源的实体口径、空间范围和时间点。"),
        _case("L2_F05", "How many liveability facilities and buildings are there?", language="en", split="holdout", family="cross_source_separate_aggregate", outcome="execute", source_scope="federated", semantic_assets=["liveability.facility_inventory", "makani.building"], measures=[{"operation": "count", "semantic_field": "facility_uuid"}, {"operation": "count", "semantic_field": "gisid"}]),
        _case("L2_F06", "请把两个数据库合并成一个统一的建筑设施表。", language="zh", split="adversarial", family="cross_source_mutation", outcome="refuse", source_scope="federated", reason="问数运行时只读，不创建或合并源表。"),
    ]


def build_benchmark_v2() -> dict[str, Any]:
    cases = _cases_liveability() + _cases_makani() + _cases_federated()
    return {
        "schema": SCHEMA,
        "benchmark_id": "abu-dhabi-nl2semantic2sql-v2-public",
        "version": "2.0.0",
        "purpose": "Evaluate semantic asset selection and governed NL2Semantic2SQL behavior on the two real Abu Dhabi PostgreSQL sources.",
        "source_scopes": {
            "liveability": {"database_name": "liveability_data_20260730", "schema": "public", "source_id": 12},
            "makani": {"database_name": "makani_sync_full", "schema": "public", "source_id": 13},
            "federated": {"source_ids": [12, 13], "cross_source_join_default": "forbidden"},
        },
        "evaluation_dimensions": [
            "semantic_asset_recall_at_k",
            "top1_asset_accuracy",
            "semantic_field_selection",
            "metric_operation_and_unit",
            "grain_correctness",
            "reviewed_relationship_admission",
            "ambiguity_clarification",
            "unsupported_and_sensitive_refusal",
            "sql_and_result_correctness_private_evaluator_only",
        ],
        "anti_leakage": {
            "questions_use_physical_table_names": False,
            "questions_use_physical_field_names": False,
            "gold_sql_in_public_dataset": False,
            "gold_result_in_public_dataset": False,
            "runtime_semantic_layer_injected_as_gold": False,
            "candidate_catalog_is_not_runtime_authority": True,
        },
        "cases": cases,
    }


def validate_benchmark_v2(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema") != SCHEMA:
        errors.append("schema")
    seen: set[str] = set()
    for case in payload.get("cases") or []:
        case_id = str(case.get("case_id") or "")
        if not case_id or case_id in seen:
            errors.append(f"duplicate_case:{case_id}")
        seen.add(case_id)
        question = str(case.get("question") or "")
        if _SQL_LEAK_RE.search(question):
            errors.append(f"physical_or_sql_leak:{case_id}")
        if not (case.get("expected") or {}).get("outcome"):
            errors.append(f"missing_outcome:{case_id}")
    if payload.get("anti_leakage", {}).get("gold_sql_in_public_dataset") is not False:
        errors.append("gold_sql_policy")
    return errors


def write_benchmark_v2(path: Path, payload: dict[str, Any]) -> None:
    errors = validate_benchmark_v2(payload)
    if errors:
        raise ValueError("benchmark validation failed: " + ",".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = ["SCHEMA", "build_benchmark_v2", "validate_benchmark_v2", "write_benchmark_v2"]
