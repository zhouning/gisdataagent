#!/usr/bin/env python3
"""Publish v45 plot-detail and runtime-audited district relationships.

The publisher starts from the immutable v44/v43 pair, runs bounded read-only
aggregate checks against source 12, and only then writes the new immutable
semantic, ontology, source-audit, and publication-audit artifacts.  Source
rows, benchmark questions, Gold SQL/results, and model output are never
persisted.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.abu_dhabi_semantic_evolution import validate_semantic_evolution
from data_agent.governed_virtual_nl2sql import (
    _validate_metric_contracts,
    _validate_row_scope_policies,
    _validate_semantic_answerability_contracts,
    _validate_semantic_caveats,
)
from data_agent.semantic_projection_policy import validate_projection_completeness_policies
from data_agent.semantic_query_ir import validate_derived_projection_policies
from data_agent.virtual_source_operator import _load_environment
from data_agent.virtual_sources import get_virtual_source, query_virtual_source

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
SOURCE_ID = 12
OWNER = "abu-dhabi-site-operator"
INPUT_SEMANTIC = ARTIFACT_ROOT / (
    "liveability_data_20260730_semantic_layer_v44_remaining_answerability_policies_20260912.json"
)
INPUT_ONTOLOGY = ARTIFACT_ROOT / (
    "liveability_data_20260730_ontology_v43_remaining_answerability_policies_20260912.json"
)
OUTPUT_SEMANTIC = ARTIFACT_ROOT / (
    "liveability_data_20260730_semantic_layer_v45_plot_detail_audited_relationships_20260912.json"
)
OUTPUT_ONTOLOGY = ARTIFACT_ROOT / (
    "liveability_data_20260730_ontology_v44_plot_detail_audited_relationships_20260912.json"
)
OUTPUT_SOURCE_AUDIT = ARTIFACT_ROOT / (
    "liveability_v45_plot_relationship_source_audit_20260912.json"
)
OUTPUT_PUBLICATION_AUDIT = ARTIFACT_ROOT / (
    "liveability_v45_plot_detail_audited_relationships_publication_audit_20260912.json"
)
BUNDLE = ARTIFACT_ROOT / "abu_dhabi_current_artifact_bundle.json"

SEMANTIC_VERSION = (
    "abu-dhabi-liveability_data_20260730-v45-plot-detail-audited-relationships-20260912"
)
ONTOLOGY_VERSION = (
    "abu-dhabi-liveability-ontology-v44-plot-detail-audited-relationships-20260912"
)
BUNDLE_ID = "abu-dhabi-liveability-current-20260912-plot-detail-audited-relationships-v45"
SOURCE_AUDIT_SCHEMA = "gda.liveability-v45-plot-relationship-source-audit.v1"

TABLES = {
    "dim_parks_calc_plots": "public.dim_parks_calc_plots",
    "dim_udm_plots": "public.dim_udm_plots",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"artifact_object_required:{path.name}")
    return value


def _raw(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any]) -> str:
    if path.exists():
        raise RuntimeError(f"immutable_output_already_exists:{path.name}")
    raw = _raw(value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return _sha256_bytes(raw)


def _write_mutable(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_raw(value))
    temporary.replace(path)


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def _normalize_sql(sql: str) -> str:
    return "\n".join(line.strip() for line in sql.strip().splitlines())


def _plot_audit_sql(table: str) -> str:
    return _normalize_sql(
        f"""
        WITH district_keys AS (
            SELECT DISTINCT district_id
            FROM public.dim_districts
        )
        SELECT COUNT(*) AS row_count,
               COUNT(*) FILTER (WHERE p.liv_district_id IS NOT NULL) AS fk_non_null_count,
               COUNT(*) FILTER (
                   WHERE p.liv_district_id IS NOT NULL AND d.district_id IS NOT NULL
               ) AS matched_count,
               COUNT(*) FILTER (
                   WHERE p.liv_district_id IS NOT NULL AND d.district_id IS NULL
               ) AS orphan_count,
               COUNT(*) FILTER (WHERE p.liv_district_id IS NULL) AS fk_null_count,
               COUNT(*) - COUNT(DISTINCT p.id) AS duplicate_id_count
        FROM {table} AS p
        LEFT JOIN district_keys AS d ON d.district_id = p.liv_district_id
        """
    )


async def _run_plot_probe(source: dict[str, Any], table_key: str, table: str) -> dict[str, Any]:
    sql = _plot_audit_sql(table)
    result = await query_virtual_source(
        source,
        limit=10,
        extra_params={"sql": sql, "geom_column": ""},
        register_result=False,
    )
    query_sha256 = _sha256_bytes(sql.encode("utf-8"))
    if isinstance(result, dict):
        raise RuntimeError(
            f"plot_relationship_probe_failed:{table_key}:"
            f"{result.get('message') or result.get('status') or 'query_failed'}"
        )
    records = result.to_dict(orient="records")
    if len(records) != 1:
        raise RuntimeError(f"plot_relationship_probe_shape_invalid:{table_key}")
    aggregate = {}
    for key, value in records[0].items():
        if value is None:
            aggregate[key] = None
        else:
            try:
                aggregate[key] = int(value)
            except (TypeError, ValueError):
                aggregate[key] = value
    required = {
        "row_count",
        "fk_non_null_count",
        "matched_count",
        "orphan_count",
        "fk_null_count",
        "duplicate_id_count",
    }
    if set(aggregate) != required:
        raise RuntimeError(f"plot_relationship_probe_columns_invalid:{table_key}")
    if any(int(aggregate[key] or 0) != 0 for key in ("fk_null_count", "orphan_count", "duplicate_id_count")):
        raise RuntimeError(f"plot_relationship_probe_quality_failed:{table_key}")
    return {
        "table": table,
        "sql_sha256": query_sha256,
        "aggregate": aggregate,
        "source_rows_persisted": False,
    }


async def _audit_source(semantic: Mapping[str, Any]) -> dict[str, Any]:
    _load_environment()
    source = get_virtual_source(SOURCE_ID, OWNER)
    if source is None:
        raise RuntimeError("registered_source_unavailable")
    binding = semantic.get("source_binding") or {}
    snapshot = source.get("discovery_snapshot") or {}
    observed = {
        "source_id": int(source.get("id") or -1),
        "database_name": snapshot.get("database_name"),
        "discovery_fingerprint": source.get("discovery_fingerprint"),
        "profile_fingerprint": source.get("profile_fingerprint"),
    }
    expected = {
        "source_id": SOURCE_ID,
        "database_name": binding.get("database_name"),
        "discovery_fingerprint": binding.get("discovery_fingerprint"),
        "profile_fingerprint": binding.get("profile_fingerprint"),
    }
    if observed != expected:
        raise RuntimeError(f"source_binding_mismatch:{json.dumps({'expected': expected, 'observed': observed}, sort_keys=True)}")
    probes = {
        key: await _run_plot_probe(source, key, table)
        for key, table in TABLES.items()
    }
    return {
        "schema": SOURCE_AUDIT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed",
        "source": {
            **observed,
            "owner": OWNER,
            "allowed_schemas": list(binding.get("allowed_schemas") or []),
            "execution_mode": "registered_governed_virtual_read_only",
        },
        "relationships": {
            key: {
                "left": f"{table}.liv_district_id",
                "right": "public.dim_districts.district_id",
                "kind": "equality",
                "operator": "=",
                "cardinality": "many_to_one",
                "probe": probes[key],
            }
            for key, table in TABLES.items()
        },
        "claim_boundary": {
            "aggregate_probes_only": True,
            "benchmark_questions_used": False,
            "gold_sql_used": False,
            "gold_results_used": False,
            "model_outputs_used": False,
            "source_rows_persisted": False,
        },
    }


def _fk(table: str) -> dict[str, Any]:
    return {
        "name": f"{table}_liv_district_id_fkey",
        "columns": ["liv_district_id"],
        "referred_schema": "public",
        "referred_table": "dim_districts",
        "referred_columns": ["district_id"],
    }


def _relation(table: str, evidence_sha256: str) -> dict[str, Any]:
    return {
        "left": f"{table}.liv_district_id",
        "right": "public.dim_districts.district_id",
        "kind": "equality",
        "operator": "=",
        "cardinality": "many_to_one",
        "review_status": "reviewed_runtime_validated",
        "execution_authorized": True,
        "evidence_path": _relative(OUTPUT_SOURCE_AUDIT),
        "evidence_sha256": evidence_sha256,
    }


def _detail_contracts() -> list[dict[str, Any]]:
    common = {
        "review_status": "reviewed_candidate",
        "priority": 535,
        "operation": "detail_ordered",
        "provenance": "source_verified_plot_detail_projection",
        "match": {
            "required_term_groups": {
                "zh": [["地块", "宗地", "公园地块"], ["详情", "详细信息", "属性", "信息"]],
                "en": [["parcel", "plot", "land parcel", "park plot"], ["detail", "details", "attribute", "attributes", "information"]],
                "ar": [["قطعة أرض", "قطعة", "plot"], ["تفاصيل", "خصائص", "معلومات"]],
            }
        },
    }
    return [
        {
            **copy.deepcopy(common),
            "contract_id": "LIVEABILITY_PLOT_DETAIL_DIM_PARKS_CALC_PLOTS_V1",
            "tables": [TABLES["dim_parks_calc_plots"]],
            "dimensions": [
                {"table": TABLES["dim_parks_calc_plots"], "field": field, "alias": field}
                for field in (
                    "id", "plotnumber", "old_plotnumber", "liv_district_id", "districteng",
                    "districtnameeng", "municipality", "primaryuseeng", "area", "status"
                )
            ],
            "metrics": [],
            "order_by": ["id"],
        },
        {
            **copy.deepcopy(common),
            "contract_id": "LIVEABILITY_PLOT_DETAIL_DIM_UDM_PLOTS_V1",
            "tables": [TABLES["dim_udm_plots"]],
            "dimensions": [
                {"table": TABLES["dim_udm_plots"], "field": field, "alias": field}
                for field in (
                    "id", "plotnumber", "old_plotnumber", "liv_district_id", "districteng",
                    "municipalityeng", "primaryuseeng", "calculatedarea", "plannedarea", "status"
                )
            ],
            "metrics": [],
            "order_by": ["id"],
        },
    ]


def _representative_contract() -> dict[str, Any]:
    contract = {
        "contract_id": "LIVEABILITY_REPRESENTATIVE_AREA_BASELINE_UNAVAILABLE_V1",
        "review_status": "reviewed",
        "disposition": "clarify",
        "priority": 505,
        "match": {
            "required_term_groups": {
                "zh": [
                    ["代表性区域", "代表区域", "基准区域", "对照区域", "代表性行政区", "基准规则", "参考规则"],
                    ["基准", "比较", "排名", "排序", "最好", "最差", "代表", "参考"],
                ],
                "en": [
                    ["representative area", "representative areas", "representative district", "representative districts", "benchmark area", "comparison area", "baseline rule", "reference rule"],
                    ["baseline", "reference", "compare", "comparison", "rank", "ranking", "representative", "benchmark"],
                ],
                "ar": [
                    ["منطقة ممثلة", "مناطق ممثلة", "منطقة مرجعية", "منطقة مقارنة", "قاعدة خط الأساس", "قاعدة مرجعية"],
                    ["خط الأساس", "مرجع", "مقارنة", "ترتيب", "الأفضل", "الأسوأ", "ممثل"],
                ],
            },
            "required_context_pattern_groups": {
                "zh": [{"context_id": "representative_scope", "patterns": [r"在[^，。；;]*?(?:区域|行政区|地区)", r"跨[^，。；;]*?(?:区域|行政区|地区)", r"按[^，。；;]*?(?:排名|排序).*?(?:基准|规则)"]}],
                "en": [{"context_id": "representative_scope", "patterns": [r"\bin\s+[A-Za-z][A-Za-z -]*\s+region\b", r"\bwithin\s+[^,.!?;]+\s+(?:region|district|area)\b", r"\bbaseline\s+rule\s+defined\s+for\s+district\s+ranking\b", r"\bacross\s+districts?\b"]}],
                "ar": [{"context_id": "representative_scope", "patterns": [r"في\s+[^،؛.!؟]*(?:منطقة|إقليم)", r"عبر\s+[^،؛.!؟]*(?:المناطق|الأحياء|القطاعات)", r"قاعدة\s+خط\s+الأساس"]}],
            },
        },
        "messages": {
            "zh": "当前语义层没有经审核的代表性区域或比较基准定义。请指定区域、基准规则或比较范围，不能从区域名称或单一指标自动推断代表性。",
            "en": "The semantic layer has no reviewed representative-area or comparison-baseline definition. Specify the area, baseline rule, or comparison scope instead of inferring representativeness from a name or one metric.",
            "ar": "لا تتضمن طبقة الدلالات تعريفاً معتمداً للمنطقة الممثلة أو خط أساس المقارنة. يرجى تحديد المنطقة أو قاعدة خط الأساس أو نطاق المقارنة بدلاً من الاستنتاج التلقائي.",
        },
        "evidence": {
            "basis": "reviewed_semantic_layer_and_source_governance_metadata",
            "source_bound": True,
            "benchmark_questions_used": False,
            "gold_sql_used": False,
            "gold_results_used": False,
            "model_outputs_used": False,
            "source_rows_persisted": False,
        },
    }
    return contract


def _parcel_contract() -> dict[str, Any]:
    return {
        "contract_id": "LIVEABILITY_PARCEL_IDENTIFIER_REQUIRED_V1",
        "review_status": "reviewed",
        "disposition": "clarify",
        "priority": 520,
        "match": {
            "required_term_groups": {
                "zh": [["地块", "宗地", "parcel", "plot"], ["属性", "详情", "信息", "面积", "用途", "状态", "业主", "位置", "记录"]],
                "en": [["parcel", "plot", "land parcel"], ["attribute", "attributes", "detail", "details", "information", "area", "land use", "owner", "status", "record"]],
                "ar": [["قطعة أرض", "قطعة", "parcel", "plot"], ["خصائص", "تفاصيل", "معلومات", "مساحة", "استخدام الأرض", "مالك", "حالة", "سجل"]],
            },
            "required_context_pattern_groups": {
                "zh": [{"context_id": "parcel_identifier", "patterns": [r"(?:地块|宗地)\s*(?:编号|号|ID|标识)\s*[:：#-]?\s*[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9_./-]*"]}],
                "en": [{"context_id": "parcel_identifier", "patterns": [r"\b(?:parcel|plot|land\s+parcel)\s*(?:id|number|no\.?|identifier)\s*[:#-]?\s*(?!or\b|and\b|including\b|with\b|for\b|to\b|using\b)[A-Za-z0-9][A-Za-z0-9_./-]*\b"]}],
                "ar": [{"context_id": "parcel_identifier", "patterns": [r"(?:قطعة\s*أرض|قطعة|parcel|plot)\s*(?:معرّف|معرف|رقم|id)\s*[:#-]?\s*[A-Za-z0-9][A-Za-z0-9_./-]*"]}],
            },
        },
        "messages": {
            "zh": "请提供明确的 Parcel ID 或 Plot Number（地块/宗地编号）。未指定标识值时不能安全地返回全部地块记录。",
            "en": "Provide an explicit Parcel ID or Plot Number. Without an identifier value, the system cannot safely return all parcel records.",
            "ar": "يرجى تقديم معرّف قطعة الأرض أو رقم المخطط بوضوح. من دون قيمة معرّف لا يمكن إرجاع جميع السجلات بأمان.",
        },
        "evidence": {
            "basis": "reviewed_semantic_layer_and_source_governance_metadata",
            "source_bound": True,
            "benchmark_questions_used": False,
            "gold_sql_used": False,
            "gold_results_used": False,
            "model_outputs_used": False,
            "source_rows_persisted": False,
        },
    }


def _upsert_answerability_contracts(semantic: dict[str, Any], ontology: dict[str, Any]) -> None:
    existing = {
        str(item["contract_id"]): copy.deepcopy(item)
        for item in semantic.get("semantic_answerability_contracts") or []
        if isinstance(item, dict) and item.get("contract_id")
    }
    qa = existing.get("LIVEABILITY_QA_DATA_SOURCE_REQUIRED_V1")
    if qa:
        additions = {
            "zh": ["社区中心", "社区枢纽", "婚礼厅", "Majlis", "议事厅", "清真寺", "诊所", "设施类别"],
            "en": ["community hub", "community hubs", "wedding hall", "wedding halls", "majlis", "mosque", "mosques", "clinic", "clinics", "facility type"],
        }
        groups = qa.setdefault("match", {}).setdefault("required_term_groups", {})
        for language, terms in additions.items():
            if len(groups.get(language) or []) >= 2:
                groups[language][1] = list(dict.fromkeys([*groups[language][1], *terms]))
    existing[_representative_contract()["contract_id"]] = _representative_contract()
    existing[_parcel_contract()["contract_id"]] = _parcel_contract()
    contracts = list(existing.values())
    semantic["semantic_answerability_contracts"] = copy.deepcopy(contracts)
    ontology["runtime_answerability_contracts"] = copy.deepcopy(contracts)
    ontology["semantic_answerability_contracts"] = copy.deepcopy(contracts)


def _sync_relationships_and_fks(semantic: dict[str, Any], ontology: dict[str, Any], evidence_sha256: str) -> None:
    relations = [_relation(table, evidence_sha256) for table in TABLES.values()]
    for binding in semantic.get("table_bindings") or []:
        table = str(binding.get("physical_table") or "")
        if table in TABLES.values():
            binding["foreign_keys"] = [*(binding.get("foreign_keys") or []), _fk(table.rsplit(".", 1)[-1])]
    for concept in ontology.get("concepts") or []:
        table = str(concept.get("physical_binding") or "")
        if table in TABLES.values():
            metadata = dict(concept.get("technical_metadata") or {})
            metadata["foreign_keys"] = [*(metadata.get("foreign_keys") or []), _fk(table.rsplit(".", 1)[-1])]
            concept["technical_metadata"] = metadata
    for key in ("relationships",):
        current = semantic.get(key) or []
        semantic[key] = [*current, *relations]
        current = ontology.get(key) or []
        ontology[key] = [*current, *copy.deepcopy(relations)]
    ontology["relations"] = [*(ontology.get("relations") or []), *copy.deepcopy(relations)]


def _sync_detail_contracts(semantic: dict[str, Any], ontology: dict[str, Any]) -> list[dict[str, Any]]:
    contracts = list(semantic.get("metric_contracts") or [])
    by_id = {str(item.get("contract_id")): item for item in contracts if isinstance(item, dict)}
    for contract in _detail_contracts():
        by_id[contract["contract_id"]] = contract
    contracts = list(by_id.values())
    semantic["metric_contracts"] = copy.deepcopy(contracts)
    ontology["runtime_metric_contracts"] = copy.deepcopy(contracts)
    return _detail_contracts()


def _set_evolution(semantic: dict[str, Any], ontology: dict[str, Any], source_audit_sha256: str) -> None:
    parent_semantic_version = str(semantic.get("semantic_version") or "").strip()
    parent_ontology_version = str(
        ontology.get("ontology_enrichment_version") or ontology.get("overlay_id") or ""
    ).strip()
    if not parent_semantic_version or not parent_ontology_version:
        raise RuntimeError("parent_version_missing")
    evidence = {
        "path": _relative(OUTPUT_SOURCE_AUDIT),
        "sha256": source_audit_sha256,
        "benchmark_questions_used": False,
        "gold_sql_used": False,
        "gold_results_used": False,
        "model_outputs_used": False,
    }
    evolution = copy.deepcopy(semantic.get("semantic_evolution") or {})
    evolution.update(
        {
            "schema": "gda.abu-dhabi-semantic-evolution.v1",
            "change_id": "abu-dhabi-liveability-20260912-v45-plot-detail-audited-relationships",
            "parent_semantic_version": parent_semantic_version,
            "parent_ontology_version": parent_ontology_version,
            "source_evidence": [*(evolution.get("source_evidence") or []), evidence],
            "changes": [
                *(evolution.get("changes") or []),
                "added source-validated liv_district_id foreign keys and many-to-one relationships for both plot tables",
                "added bounded plot-detail ordered projections with explicit dimensions and no aggregate metrics",
                "hardened representative-area context and single-character parcel identifier matching",
            ],
            "benchmark_questions_used": False,
            "gold_sql_used": False,
            "gold_results_used": False,
            "model_outputs_used": False,
            "source_rows_persisted": False,
        }
    )
    semantic["semantic_evolution"] = evolution
    ontology["semantic_evolution"] = copy.deepcopy(evolution)


def publish() -> dict[str, Any]:
    semantic = copy.deepcopy(_load(INPUT_SEMANTIC))
    ontology = copy.deepcopy(_load(INPUT_ONTOLOGY))
    source_audit = asyncio.run(_audit_source(semantic))
    source_audit_sha256 = _sha256_bytes(_raw(source_audit))

    _upsert_answerability_contracts(semantic, ontology)
    _sync_relationships_and_fks(semantic, ontology, source_audit_sha256)
    detail_contracts = _sync_detail_contracts(semantic, ontology)
    _set_evolution(semantic, ontology, source_audit_sha256)

    semantic["semantic_version"] = SEMANTIC_VERSION
    semantic["artifact_bundle_id"] = BUNDLE_ID
    semantic["ontology_overlay"] = _relative(OUTPUT_ONTOLOGY)
    semantic["gold_compatible_semantic_versions"] = list(
        dict.fromkeys([*(semantic.get("gold_compatible_semantic_versions") or []), SEMANTIC_VERSION])
    )
    ontology["ontology_enrichment_version"] = ONTOLOGY_VERSION
    ontology["overlay_id"] = ONTOLOGY_VERSION
    ontology["artifact_bundle_id"] = BUNDLE_ID

    publication = {
        "status": "published_v45",
        "purpose": "plot_detail_and_audited_district_relationships",
        "source_audit_path": _relative(OUTPUT_SOURCE_AUDIT),
        "source_audit_sha256": source_audit_sha256,
        "relationship_tables": list(TABLES.values()),
        "detail_contract_ids": [item["contract_id"] for item in detail_contracts],
        "benchmark_questions_used": False,
        "gold_sql_used": False,
        "gold_results_used": False,
        "model_outputs_used": False,
        "source_rows_persisted": False,
    }
    semantic["plot_detail_audited_relationships_publication"] = copy.deepcopy(publication)
    ontology["plot_detail_audited_relationships_publication"] = copy.deepcopy(publication)
    semantic["remaining_answerability_policy_publication"] = {
        **(semantic.get("remaining_answerability_policy_publication") or {}),
        "superseded_by": SEMANTIC_VERSION,
    }
    ontology["remaining_answerability_policy_publication"] = {
        **(ontology.get("remaining_answerability_policy_publication") or {}),
        "superseded_by": ONTOLOGY_VERSION,
    }

    _validate_metric_contracts(semantic)
    _validate_row_scope_policies(semantic)
    _validate_semantic_answerability_contracts(semantic)
    _validate_semantic_caveats(semantic)
    validate_projection_completeness_policies(semantic)
    validate_derived_projection_policies(semantic)
    validate_semantic_evolution(semantic, ontology)
    if ontology.get("runtime_answerability_contracts") != semantic.get("semantic_answerability_contracts"):
        raise RuntimeError("ontology_runtime_answerability_contracts_out_of_sync")
    if ontology.get("semantic_answerability_contracts") != semantic.get("semantic_answerability_contracts"):
        raise RuntimeError("ontology_semantic_answerability_contracts_out_of_sync")
    if ontology.get("runtime_metric_contracts") != semantic.get("metric_contracts"):
        raise RuntimeError("ontology_runtime_metric_contracts_out_of_sync")

    # All checks are complete before any immutable output is created.
    source_audit_sha256 = _write_new(OUTPUT_SOURCE_AUDIT, source_audit)
    semantic_sha256 = _write_new(OUTPUT_SEMANTIC, semantic)
    ontology_sha256 = _write_new(OUTPUT_ONTOLOGY, ontology)
    publication_audit = {
        "schema": "gda.liveability-v45-plot-detail-audited-relationships-publication-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "semantic_version": SEMANTIC_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "source_audit_sha256": source_audit_sha256,
        "semantic_sha256": semantic_sha256,
        "ontology_sha256": ontology_sha256,
        "source": source_audit["source"],
        "relationships": source_audit["relationships"],
        "detail_contract_ids": [item["contract_id"] for item in detail_contracts],
        "publication": publication,
    }
    publication_audit_sha256 = _write_new(OUTPUT_PUBLICATION_AUDIT, publication_audit)
    bundle = copy.deepcopy(_load(BUNDLE))
    bundle.update(
        {
            "artifact_bundle_id": BUNDLE_ID,
            "bundle_id": BUNDLE_ID,
            "semantic_version": SEMANTIC_VERSION,
            "ontology_version": ONTOLOGY_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
        }
    )
    artifacts = bundle.setdefault("artifacts", {})
    artifacts["semantic"] = {"role": "runtime_semantic_layer", "path": _relative(OUTPUT_SEMANTIC), "sha256": semantic_sha256}
    artifacts["ontology"] = {"role": "ontology_overlay", "path": _relative(OUTPUT_ONTOLOGY), "sha256": ontology_sha256}
    artifacts["plot_relationship_source_audit"] = {"role": "source_relationship_aggregate_audit", "path": _relative(OUTPUT_SOURCE_AUDIT), "sha256": source_audit_sha256}
    artifacts["plot_detail_audited_relationships_publication_audit"] = {"role": "plot_detail_and_relationship_publication_audit", "path": _relative(OUTPUT_PUBLICATION_AUDIT), "sha256": publication_audit_sha256}
    _write_mutable(BUNDLE, bundle)
    return {
        "status": "published",
        "semantic": str(OUTPUT_SEMANTIC),
        "ontology": str(OUTPUT_ONTOLOGY),
        "source_audit": str(OUTPUT_SOURCE_AUDIT),
        "publication_audit": str(OUTPUT_PUBLICATION_AUDIT),
        "bundle": str(BUNDLE),
        "detail_contract_ids": [item["contract_id"] for item in detail_contracts],
        "relationship_tables": list(TABLES.values()),
    }


if __name__ == "__main__":
    print(json.dumps(publish(), ensure_ascii=False, indent=2))
