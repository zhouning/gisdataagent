"""Diagnostics for MMFE semantic fusion products.

The diagnostic contract is intentionally compact: it tells an agent whether a
semantic product is usable as a validation scaffold, where production gaps
remain, and which semantic/TWM surfaces are missing or weak.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .production_readiness import (
    PRODUCTION_READINESS_SCHEMA,
    production_readiness_from_manifest,
)


MMFE_PRODUCT_DIAGNOSTIC_SCHEMA = "mmfe.semantic_product_diagnostic.v1"
MMFE_PRODUCT_DIAGNOSTIC_VERSION = "0.1"


def diagnose_semantic_product_readiness(
    manifest: dict,
    *,
    value_domain_audits: list[dict] | None = None,
    standard_sources: list[dict] | None = None,
    semantic_relations: list[dict] | None = None,
    state_input: dict | None = None,
    semantic_graph: dict | None = None,
    semantic_trace_cards: dict | None = None,
    timestamp: str | None = None,
) -> dict:
    """Build a readiness diagnostic for an MMFE semantic product."""
    if not isinstance(manifest, dict):
        raise ValueError("semantic product manifest must be a JSON object")

    mmfe_bundle = manifest.get("mmfe_bundle") or {}
    state = state_input or mmfe_bundle.get("twm_state_input") or {}
    value_audits = list(value_domain_audits or mmfe_bundle.get("value_domain_audits") or [])
    sources = list(standard_sources or mmfe_bundle.get("standard_source_rows") or [])
    standard_ingestion = mmfe_bundle.get("standard_source_ingestion_plan") or {}
    standard_ingestion_run = mmfe_bundle.get("standard_source_ingestion_run") or {}
    relations = list(semantic_relations or mmfe_bundle.get("semantic_relations") or [])
    graph = semantic_graph or mmfe_bundle.get("semantic_graph") or {}
    trace_cards = semantic_trace_cards or mmfe_bundle.get("semantic_trace_cards") or {}
    production_readiness = production_readiness_from_manifest(manifest)

    checks = []
    checks.extend(_manifest_checks(manifest))
    checks.extend(_standard_checks(mmfe_bundle, value_audits, sources, state, standard_ingestion, standard_ingestion_run))
    checks.extend(_graph_checks(graph, trace_cards))
    checks.extend(_twm_checks(mmfe_bundle, relations, state))
    checks.extend(_ai_grounding_checks(manifest))
    checks.extend(_production_checks(manifest, state, sources, production_readiness))

    status_counts = Counter(check["status"] for check in checks)
    score = _readiness_score(checks)
    validation_ready = all(
        check["status"] in {"pass", "warn"}
        for check in checks
        if check.get("required_for_validation")
    )
    production_ready = bool(validation_ready) and not any(
        check["severity"] in {"critical", "high"} and check["status"] != "pass"
        for check in checks
    )

    return {
        "schema": MMFE_PRODUCT_DIAGNOSTIC_SCHEMA,
        "version": MMFE_PRODUCT_DIAGNOSTIC_VERSION,
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "product_id": manifest.get("product_id"),
        "product_type": manifest.get("product_type"),
        "summary": {
            "readiness_score": score,
            "validation_ready": validation_ready,
            "production_ready": production_ready,
            "status": _overall_status(validation_ready, production_ready, checks),
            "check_count": len(checks),
            "pass_count": status_counts.get("pass", 0),
            "warn_count": status_counts.get("warn", 0),
            "fail_count": status_counts.get("fail", 0),
        },
        "capabilities": _capability_summary(manifest, mmfe_bundle, relations, state, graph, trace_cards),
        "checks": checks,
        "top_gaps": _top_gaps(checks),
        "recommendations_zh": _recommendations(checks),
    }


def validate_semantic_product_diagnostic(payload: dict) -> dict:
    """Validate the diagnostic contract surface."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be a JSON object"]}
    if payload.get("schema") != MMFE_PRODUCT_DIAGNOSTIC_SCHEMA:
        errors.append(f"schema must be {MMFE_PRODUCT_DIAGNOSTIC_SCHEMA}")
    if not payload.get("product_id"):
        errors.append("product_id is required")
    summary = payload.get("summary") or {}
    if not isinstance(summary.get("readiness_score"), (int, float)):
        errors.append("summary.readiness_score must be numeric")
    if not isinstance(payload.get("checks"), list):
        errors.append("checks must be a list")
    return {"valid": not errors, "errors": errors}


def _manifest_checks(manifest: dict) -> list[dict]:
    return [
        _check(
            "manifest_contract",
            "语义产品 Manifest 合同",
            "pass" if manifest.get("product_type") == "semantic_fusion_product" and manifest.get("product_id") else "fail",
            "critical",
            "manifest 必须提供 semantic_fusion_product 类型和稳定 product_id。",
            required_for_validation=True,
            evidence={
                "product_type": manifest.get("product_type"),
                "product_id": manifest.get("product_id"),
                "version": manifest.get("version"),
            },
        ),
        _check(
            "business_output",
            "业务输出可定位",
            "pass" if (manifest.get("business_output") or {}).get("path") else "warn",
            "medium",
            "语义产品应保留可由 GIS/数据湖消费的业务输出路径。",
            evidence=manifest.get("business_output") or {},
        ),
    ]


def _standard_checks(
    mmfe_bundle: dict,
    value_domain_audits: list[dict],
    standard_sources: list[dict],
    state_input: dict,
    standard_ingestion: dict | None = None,
    standard_ingestion_run: dict | None = None,
) -> list[dict]:
    standard_readiness = state_input.get("standard_readiness") or {}
    source_summary = (
        standard_readiness.get("standard_sources")
        or (mmfe_bundle.get("standard_source_registry") or {}).get("summary")
        or {}
    )
    value_summary = standard_readiness.get("value_domain_audit") or mmfe_bundle.get("value_domain_audit_summary") or {}
    missing_domains = standard_readiness.get("missing_value_domains") or (
        mmfe_bundle.get("alignment_summary") or {}
    ).get("missing_value_domains") or {}
    value_audit_count = _safe_int(value_summary.get("audit_count"), len(value_domain_audits))
    value_review_count = _safe_int(value_summary.get("requires_review_count"), 0)
    source_count = _safe_int(source_summary.get("source_count"), len(standard_sources))
    official_count = _safe_int(source_summary.get("official_verified_count"), 0)
    pending_count = _safe_int(source_summary.get("pending_official_source_count"), 0)
    ingestion_summary = (
        standard_ingestion.get("summary")
        if isinstance(standard_ingestion, dict) and isinstance(standard_ingestion.get("summary"), dict)
        else {}
    )
    ingestion_ready = bool(ingestion_summary.get("ready"))
    ingestion_run_summary = (
        standard_ingestion_run.get("summary")
        if isinstance(standard_ingestion_run, dict) and isinstance(standard_ingestion_run.get("summary"), dict)
        else {}
    )
    ingestion_run_valid = bool(isinstance(standard_ingestion_run, dict) and standard_ingestion_run.get("valid"))
    ingested_task_count = _safe_int(ingestion_run_summary.get("ingested_task_count"), 0)
    extracted_task_count = _safe_int(ingestion_run_summary.get("extracted_task_count"), 0)
    citation_anchor_count = _safe_int(ingestion_run_summary.get("citation_anchor_count"), 0)
    quality_pass_count = _safe_int(ingestion_run_summary.get("citation_anchor_quality_pass_count"), 0)
    quality_warn_count = _safe_int(ingestion_run_summary.get("citation_anchor_quality_warn_count"), 0)
    quality_ok_count = quality_pass_count + quality_warn_count
    ingestion_quality_ready = (
        ingestion_run_valid
        and ingested_task_count > 0
        and extracted_task_count > 0
        and citation_anchor_count > 0
        and quality_ok_count > 0
    )

    return [
        _check(
            "value_domain_audit",
            "字段值域审计",
            "pass" if value_audit_count > 0 and value_review_count == 0 and not missing_domains else "fail",
            "high",
            "TWM/AI 下游需要关键编码字段通过值域审计，且不能存在缺失值域。",
            required_for_validation=True,
            evidence={
                "audit_count": value_audit_count,
                "requires_review_count": value_review_count,
                "missing_value_domains": missing_domains,
            },
        ),
        _check(
            "standard_source_registry",
            "标准来源登记",
            "pass" if source_count > 0 and official_count > 0 else "fail",
            "high",
            "语义标准需要可审计来源；至少应有一个已核验官方来源支撑核心值域。",
            required_for_validation=True,
            evidence={
                "source_count": source_count,
                "official_verified_count": official_count,
                "pending_official_source_count": pending_count,
            },
        ),
        _check(
            "official_source_completeness",
            "生产级官方标准完整性",
            "pass" if pending_count == 0 and source_count > 0 else "warn",
            "high",
            "生产前应把专家材料契约替换或补齐为主管部门公开发布源、正式版本和全文证据。",
            evidence={
                "pending_official_source_count": pending_count,
                "production_gap_zh": source_summary.get("production_gap_zh"),
            },
        ),
        _check(
            "standard_source_ingestion",
            "标准来源采集抽取计划",
            "pass" if ingestion_ready and ingestion_quality_ready else "warn",
            "high",
            "生产前应把标准来源登记推进为可审计采集、归档、校验和条款/字段/值域抽取任务。",
            evidence={
                "ready": ingestion_ready,
                "task_count": ingestion_summary.get("ready_task_count", 0)
                + ingestion_summary.get("blocked_task_count", 0),
                "blocked_task_count": ingestion_summary.get("blocked_task_count", 0),
                "official_source_missing_count": ingestion_summary.get("official_source_missing_count", 0),
                "checksum_missing_count": ingestion_summary.get("checksum_missing_count", 0),
                "fulltext_extraction_missing_count": ingestion_summary.get(
                    "fulltext_extraction_missing_count", 0
                ),
                "run_valid": ingestion_run_valid,
                "ingested_task_count": ingested_task_count,
                "extracted_task_count": extracted_task_count,
                "citation_anchor_count": citation_anchor_count,
                "citation_anchor_quality_pass_count": quality_pass_count,
                "citation_anchor_quality_warn_count": quality_warn_count,
            },
        ),
    ]


def _graph_checks(semantic_graph: dict, trace_cards: dict) -> list[dict]:
    node_count = _safe_int(semantic_graph.get("node_count"), len(semantic_graph.get("nodes") or []))
    edge_count = _safe_int(semantic_graph.get("edge_count"), len(semantic_graph.get("edges") or []))
    trace_count = _safe_int(trace_cards.get("trace_card_count"), len(trace_cards.get("cards") or []))
    standard_trace_paths = _safe_int(trace_cards.get("standard_source_path_count"), 0)
    graph_has_standard = any(
        isinstance(node, dict) and node.get("type") == "standard_source"
        for node in semantic_graph.get("nodes") or []
    )
    graph_has_value_domain = any(
        isinstance(node, dict) and node.get("type") == "value_domain"
        for node in semantic_graph.get("nodes") or []
    )
    return [
        _check(
            "semantic_graph",
            "语义图结构",
            "pass" if node_count > 0 and edge_count > 0 and graph_has_standard and graph_has_value_domain else "fail",
            "high",
            "语义融合结果应形成包含字段、值域、标准来源、规则/目标等节点的图合同。",
            required_for_validation=True,
            evidence={
                "node_count": node_count,
                "edge_count": edge_count,
                "has_standard_source_node": graph_has_standard,
                "has_value_domain_node": graph_has_value_domain,
            },
        ),
        _check(
            "semantic_trace_cards",
            "语义溯源卡片",
            "pass" if trace_count > 0 and standard_trace_paths > 0 else "fail",
            "medium",
            "Agent 需要 trace card 把字段、值域、标准、规则和目标解释给下游使用者。",
            required_for_validation=True,
            evidence={
                "trace_card_count": trace_count,
                "standard_source_path_count": standard_trace_paths,
            },
        ),
    ]


def _twm_checks(mmfe_bundle: dict, semantic_relations: list[dict], state_input: dict) -> list[dict]:
    relation_summary = state_input.get("semantic_relation_summary") or mmfe_bundle.get("semantic_relation_summary") or {}
    optimization = state_input.get("optimization_interface") or mmfe_bundle.get("optimization_summary") or {}
    components = state_input.get("state_components") or {}
    relation_count = _safe_int(relation_summary.get("total_relation_count"), len(semantic_relations))
    relation_type_count = _safe_int(relation_summary.get("registered_relation_type_count"), 0)
    objective_count = _safe_int(optimization.get("objective_count"), len(optimization.get("objectives") or []))
    objective_bindings = list(optimization.get("objective_bindings") or [])
    bound_objectives = [item for item in objective_bindings if _safe_int(item.get("relation_count"), 0) > 0]
    hard_constraints = components.get("hard_constraints") or {}
    hard_relation_count = _safe_int(hard_constraints.get("relation_count"), 0)

    return [
        _check(
            "semantic_relations",
            "语义关系统计",
            "pass" if relation_count > 0 and relation_type_count > 0 else "fail",
            "critical",
            "TWM 状态构建需要对象间空间/多模态/时序语义关系。",
            required_for_validation=True,
            evidence={
                "total_relation_count": relation_count,
                "registered_relation_type_count": relation_type_count,
            },
        ),
        _check(
            "twm_state_input",
            "TWM 状态输入合同",
            "pass" if state_input.get("schema") == "mmfe.twm_state_input.v1" else "fail",
            "critical",
            "MMFE 产物应能派生 TWM state input 合同。",
            required_for_validation=True,
            evidence={
                "schema": state_input.get("schema"),
                "role_count": len(state_input.get("object_role_registry") or []),
                "component_count": len(components),
            },
        ),
        _check(
            "hard_constraints",
            "硬约束关系绑定",
            "pass" if hard_relation_count > 0 and hard_constraints.get("hard_constraint") else "fail",
            "critical",
            "TWM 的法定底线类硬约束必须绑定到语义关系和规则。",
            required_for_validation=True,
            evidence={
                "relation_count": hard_relation_count,
                "objective_ids": hard_constraints.get("objective_ids") or [],
                "rule_ids": hard_constraints.get("rule_ids") or [],
            },
        ),
        _check(
            "multi_objective_interface",
            "多目标优化接口",
            "pass" if objective_count > 0 and bound_objectives else "fail",
            "critical",
            "TWM 核心不只是融合数据，还必须把状态关系绑定到多目标优化目标。",
            required_for_validation=True,
            evidence={
                "objective_count": objective_count,
                "bound_objective_count": len(bound_objectives),
                "hard_constraint_objectives": optimization.get("hard_constraint_objectives") or [],
            },
        ),
    ]


def _ai_grounding_checks(manifest: dict) -> list[dict]:
    ai_metadata = manifest.get("ai_metadata") or {}
    chunks = ai_metadata.get("chunks") or []
    return [
        _check(
            "ai_grounding_chunks",
            "AI 检索语义块",
            "pass" if chunks and ai_metadata.get("embedding_ready") else "warn",
            "medium",
            "Agent/RAG/向量库消费需要稳定 chunk 和 embedding_ready 标记。",
            evidence={
                "chunk_count": len(chunks),
                "embedding_ready": bool(ai_metadata.get("embedding_ready")),
                "recommended_vector_targets": ai_metadata.get("recommended_vector_targets") or [],
            },
        )
    ]


def _production_checks(
    manifest: dict,
    state_input: dict,
    standard_sources: list[dict],
    production_readiness: dict | None = None,
) -> list[dict]:
    production_policy = state_input.get("production_policy") or {}
    contains_synthetic = bool(production_policy.get("contains_synthetic_sources"))
    not_for_production = bool(production_policy.get("not_for_production")) or _manifest_not_for_production(manifest)
    pending_sources = sum(1 for row in standard_sources if _to_bool(row.get("not_for_production_gap")))
    readiness = production_readiness if isinstance(production_readiness, dict) else {}
    readiness_summary = readiness.get("summary") if isinstance(readiness.get("summary"), dict) else {}
    metadata_ready = bool(readiness_summary.get("production_metadata_ready"))
    readiness_present = readiness.get("schema") == PRODUCTION_READINESS_SCHEMA
    return [
        _check(
            "production_authority",
            "生产权威数据条件",
            "pass" if metadata_ready and not contains_synthetic and not not_for_production else "warn",
            "critical",
            "当前验证数据可用于开发验证，但生产决策必须替换为真实权威自然资源数据。",
            evidence={
                "contains_synthetic_sources": contains_synthetic,
                "not_for_production": not_for_production,
                "authoritative_data_required_for_production": production_policy.get(
                    "authoritative_data_required_for_production", True
                ),
                "production_metadata_ready": metadata_ready,
            },
        ),
        _check(
            "production_metadata_contract",
            "生产数据源元数据合同",
            "pass" if metadata_ready else "warn",
            "critical",
            "生产发布需要每个关键数据源提供权威单位、授权/许可、更新时间、 lineage、CRS/比例尺、标准版本和密级。",
            evidence={
                "schema": readiness.get("schema", ""),
                "contract_present": readiness_present,
                "source_count": readiness_summary.get("source_count", 0),
                "ready_source_count": readiness_summary.get("ready_source_count", 0),
                "blocked_source_count": readiness_summary.get("blocked_source_count", 0),
                "missing_field_count": readiness_summary.get("missing_field_count", 0),
                "invalid_field_count": readiness_summary.get("invalid_field_count", 0),
                "synthetic_source_count": readiness_summary.get("synthetic_source_count", 0),
                "not_for_production_source_count": readiness_summary.get("not_for_production_source_count", 0),
            },
        ),
        _check(
            "production_standard_gaps",
            "生产标准来源缺口",
            "pass" if pending_sources == 0 else "warn",
            "high",
            "生产前应补齐所有标准材料的官方发布源和正式全文证据。",
            evidence={"pending_standard_gap_count": pending_sources},
        ),
    ]


def _capability_summary(
    manifest: dict,
    mmfe_bundle: dict,
    semantic_relations: list[dict],
    state_input: dict,
    semantic_graph: dict,
    trace_cards: dict,
) -> dict:
    optimization = state_input.get("optimization_interface") or mmfe_bundle.get("optimization_summary") or {}
    ai_metadata = manifest.get("ai_metadata") or {}
    return {
        "layer_count": len(mmfe_bundle.get("layer_summaries") or []),
        "field_semantic_count": len(mmfe_bundle.get("field_semantics") or []),
        "semantic_relation_count": _safe_int(
            (state_input.get("semantic_relation_summary") or {}).get("total_relation_count"),
            len(semantic_relations),
        ),
        "semantic_graph_node_count": _safe_int(semantic_graph.get("node_count"), len(semantic_graph.get("nodes") or [])),
        "semantic_graph_edge_count": _safe_int(semantic_graph.get("edge_count"), len(semantic_graph.get("edges") or [])),
        "trace_card_count": _safe_int(trace_cards.get("trace_card_count"), len(trace_cards.get("cards") or [])),
        "objective_count": _safe_int(optimization.get("objective_count"), len(optimization.get("objectives") or [])),
        "hard_constraint_objectives": optimization.get("hard_constraint_objectives") or [],
        "ai_chunk_count": len(ai_metadata.get("chunks") or []),
        "embedding_ready": bool(ai_metadata.get("embedding_ready")),
    }


def _readiness_score(checks: list[dict]) -> float:
    if not checks:
        return 0.0
    weights = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}
    status_factor = {"pass": 1.0, "warn": 0.55, "fail": 0.0}
    total_weight = 0.0
    weighted = 0.0
    for check in checks:
        weight = weights.get(check.get("severity"), 1.0)
        total_weight += weight
        weighted += weight * status_factor.get(check.get("status"), 0.0)
    return round(weighted / total_weight, 4) if total_weight else 0.0


def _overall_status(validation_ready: bool, production_ready: bool, checks: list[dict]) -> str:
    if production_ready:
        return "production_ready"
    if validation_ready:
        return "validation_ready_with_production_gaps"
    if any(check["severity"] == "critical" and check["status"] == "fail" for check in checks):
        return "blocked"
    return "needs_review"


def _top_gaps(checks: list[dict]) -> list[dict]:
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    status_rank = {"fail": 0, "warn": 1, "pass": 2}
    gaps = [
        {
            "check_id": check["check_id"],
            "name_zh": check["name_zh"],
            "status": check["status"],
            "severity": check["severity"],
            "message_zh": check["message_zh"],
            "evidence": check.get("evidence") or {},
        }
        for check in checks
        if check["status"] != "pass"
    ]
    return sorted(gaps, key=lambda item: (status_rank[item["status"]], severity_rank[item["severity"]]))[:8]


def _recommendations(checks: list[dict]) -> list[str]:
    by_id = {check["check_id"]: check for check in checks}
    recommendations = []
    if _not_pass(by_id, "value_domain_audit"):
        recommendations.append("补齐缺失值域或修复未知编码，确保关键字段值域审计全部通过。")
    if _not_pass(by_id, "standard_source_registry") or _not_pass(by_id, "official_source_completeness"):
        recommendations.append("继续从政府/标准公开平台补齐自然资源一张图相关标准的官方来源和全文证据。")
    if _not_pass(by_id, "standard_source_ingestion"):
        recommendations.append("把标准来源登记推进为采集计划：归档全文、记录 checksum，并抽取条款、字段、值域和引用锚点。")
    if _not_pass(by_id, "semantic_graph") or _not_pass(by_id, "semantic_trace_cards"):
        recommendations.append("重新生成 MMFE semantic graph 与 trace cards，保证字段可追溯到值域、标准、规则和目标。")
    if _not_pass(by_id, "twm_state_input") or _not_pass(by_id, "multi_objective_interface"):
        recommendations.append("先修复 TWM state input 与多目标优化目标绑定，再进入 TWM 推演/优化验证。")
    if _not_pass(by_id, "production_authority"):
        recommendations.append("当前可作为验证脚手架继续开发；进入生产时必须替换为真实权威自然资源数据。")
    if _not_pass(by_id, "production_metadata_contract"):
        recommendations.append("为每个生产关键数据源补齐权威单位、授权/许可、更新时间、lineage、CRS/比例尺、标准版本和密级元数据。")
    return recommendations


def _check(
    check_id: str,
    name_zh: str,
    status: str,
    severity: str,
    message_zh: str,
    *,
    required_for_validation: bool = False,
    evidence: dict | None = None,
) -> dict:
    return {
        "check_id": check_id,
        "name_zh": name_zh,
        "status": status,
        "severity": severity,
        "required_for_validation": required_for_validation,
        "message_zh": message_zh,
        "evidence": evidence or {},
    }


def _not_pass(checks_by_id: dict[str, dict], check_id: str) -> bool:
    return (checks_by_id.get(check_id) or {}).get("status") != "pass"


def _manifest_not_for_production(manifest: dict) -> bool:
    if _to_bool(manifest.get("not_for_production")):
        return True
    warnings = (manifest.get("quality") or {}).get("warnings") or []
    return any("not for production" in str(warning).lower() for warning in warnings)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
