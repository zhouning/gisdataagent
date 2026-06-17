"""Build an MMFE semantic fusion bundle from a prepared TWM dataset.

This script treats the TWM validation dataset as a multimodal semantic fusion
case: vector layers, raster/RS evidence, standards, rule hits, review tasks and
optimization summaries are fused into one AI-ready semantic product bundle.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_SEMANTIC_ALIGNMENT_PATH = REPO_ROOT / "data_agent" / "fusion" / "semantic_alignment.py"
_SEMANTIC_ALIGNMENT_SPEC = importlib.util.spec_from_file_location(
    "_mmfe_semantic_alignment",
    _SEMANTIC_ALIGNMENT_PATH,
)
if _SEMANTIC_ALIGNMENT_SPEC is None or _SEMANTIC_ALIGNMENT_SPEC.loader is None:
    raise ImportError(f"cannot load semantic alignment module: {_SEMANTIC_ALIGNMENT_PATH}")
_SEMANTIC_ALIGNMENT = importlib.util.module_from_spec(_SEMANTIC_ALIGNMENT_SPEC)
_SEMANTIC_ALIGNMENT_SPEC.loader.exec_module(_SEMANTIC_ALIGNMENT)

align_layer_fields_to_standard_contract = _SEMANTIC_ALIGNMENT.align_layer_fields_to_standard_contract
build_standard_alignment_summary = _SEMANTIC_ALIGNMENT.build_standard_alignment_summary
audit_field_value_domain = _SEMANTIC_ALIGNMENT.audit_field_value_domain
build_value_domain_audit_summary = _SEMANTIC_ALIGNMENT.build_value_domain_audit_summary

_STANDARD_SOURCES_PATH = REPO_ROOT / "data_agent" / "fusion" / "standard_sources.py"
_STANDARD_SOURCES_SPEC = importlib.util.spec_from_file_location(
    "_mmfe_standard_sources",
    _STANDARD_SOURCES_PATH,
)
if _STANDARD_SOURCES_SPEC is None or _STANDARD_SOURCES_SPEC.loader is None:
    raise ImportError(f"cannot load standard source module: {_STANDARD_SOURCES_PATH}")
_STANDARD_SOURCES = importlib.util.module_from_spec(_STANDARD_SOURCES_SPEC)
_STANDARD_SOURCES_SPEC.loader.exec_module(_STANDARD_SOURCES)

build_standard_source_registry = _STANDARD_SOURCES.build_standard_source_registry
flatten_standard_source_registry = _STANDARD_SOURCES.flatten_standard_source_registry
build_standard_source_ingestion_plan = _STANDARD_SOURCES.build_standard_source_ingestion_plan
validate_standard_source_ingestion_plan = _STANDARD_SOURCES.validate_standard_source_ingestion_plan

_PRODUCTION_READINESS_PATH = REPO_ROOT / "data_agent" / "fusion" / "production_readiness.py"
_PRODUCTION_READINESS_SPEC = importlib.util.spec_from_file_location(
    "_mmfe_production_readiness",
    _PRODUCTION_READINESS_PATH,
)
if _PRODUCTION_READINESS_SPEC is None or _PRODUCTION_READINESS_SPEC.loader is None:
    raise ImportError(f"cannot load production readiness module: {_PRODUCTION_READINESS_PATH}")
_PRODUCTION_READINESS = importlib.util.module_from_spec(_PRODUCTION_READINESS_SPEC)
_PRODUCTION_READINESS_SPEC.loader.exec_module(_PRODUCTION_READINESS)

production_readiness_from_manifest = _PRODUCTION_READINESS.production_readiness_from_manifest

_SEMANTIC_TRACE_PATH = REPO_ROOT / "data_agent" / "fusion" / "semantic_graph_trace.py"
_SEMANTIC_TRACE_SPEC = importlib.util.spec_from_file_location(
    "_mmfe_semantic_graph_trace",
    _SEMANTIC_TRACE_PATH,
)
if _SEMANTIC_TRACE_SPEC is None or _SEMANTIC_TRACE_SPEC.loader is None:
    raise ImportError(f"cannot load semantic graph trace module: {_SEMANTIC_TRACE_PATH}")
_SEMANTIC_TRACE = importlib.util.module_from_spec(_SEMANTIC_TRACE_SPEC)
_SEMANTIC_TRACE_SPEC.loader.exec_module(_SEMANTIC_TRACE)

build_semantic_trace_card_bundle = _SEMANTIC_TRACE.build_semantic_trace_card_bundle

_TWM_STATE_INPUT_PATH = REPO_ROOT / "data_agent" / "fusion" / "twm_state_input.py"
_TWM_STATE_INPUT_SPEC = importlib.util.spec_from_file_location(
    "_mmfe_twm_state_input",
    _TWM_STATE_INPUT_PATH,
)
if _TWM_STATE_INPUT_SPEC is None or _TWM_STATE_INPUT_SPEC.loader is None:
    raise ImportError(f"cannot load TWM state input module: {_TWM_STATE_INPUT_PATH}")
_TWM_STATE_INPUT = importlib.util.module_from_spec(_TWM_STATE_INPUT_SPEC)
_TWM_STATE_INPUT_SPEC.loader.exec_module(_TWM_STATE_INPUT)

build_twm_state_input_from_semantic_product = _TWM_STATE_INPUT.build_twm_state_input_from_semantic_product
validate_twm_state_input = _TWM_STATE_INPUT.validate_twm_state_input

from data_agent.fusion.semantic_product_diagnostics import diagnose_semantic_product_readiness

_SEMANTIC_ONTOLOGY_PATH = REPO_ROOT / "data_agent" / "fusion" / "semantic_ontology.py"
_SEMANTIC_ONTOLOGY_SPEC = importlib.util.spec_from_file_location(
    "_mmfe_semantic_ontology",
    _SEMANTIC_ONTOLOGY_PATH,
)
if _SEMANTIC_ONTOLOGY_SPEC is None or _SEMANTIC_ONTOLOGY_SPEC.loader is None:
    raise ImportError(f"cannot load semantic ontology module: {_SEMANTIC_ONTOLOGY_PATH}")
_SEMANTIC_ONTOLOGY = importlib.util.module_from_spec(_SEMANTIC_ONTOLOGY_SPEC)
_SEMANTIC_ONTOLOGY_SPEC.loader.exec_module(_SEMANTIC_ONTOLOGY)

build_semantic_ontology_package = _SEMANTIC_ONTOLOGY.build_semantic_ontology_package
validate_semantic_ontology_package = _SEMANTIC_ONTOLOGY.validate_semantic_ontology_package


DEFAULT_DATA_DIR = Path("data_agent/test_data/twm_bishan_demo")
DEFAULT_OUT_DIR_NAME = "mmfe_semantic_fusion"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    data_dir = args.data_dir
    out_dir = args.out_dir or data_dir / DEFAULT_OUT_DIR_NAME
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = _read_json(data_dir / "dataset_manifest.json")
    quality = _read_json(data_dir / "data_quality_report.json")
    raster_manifest = _read_json(data_dir / "raster_manifest.json", default={})
    real_imagery_manifest = _read_json(data_dir / "real_imagery_manifest.json", default={})
    pareto_summary = _read_json(data_dir / "optimization" / "pareto_summary.json", default={})
    standard_rules = _read_json(data_dir / "standard_rules.lifecycle.json", default={})
    field_aliases = _read_json(data_dir / "standards" / "one_map_field_aliases.zh.json", default={})
    role_contracts = _read_json(data_dir / "standards" / "one_map_role_contracts.zh.json", default={})
    value_domains = _read_json(data_dir / "standards" / "one_map_value_domains.zh.json", default={})
    data_dictionary = _read_json(data_dir / "data_dictionary.zh.json", default={})
    standard_source_registry = build_standard_source_registry(
        role_contracts,
        standards_dir=data_dir / "standards",
    )
    standard_source_rows = flatten_standard_source_registry(standard_source_registry)

    metadata_rows = _read_csv(data_dir / "tables" / "metadata_vector.csv")
    rule_rows = _read_csv(data_dir / "tables" / "rule_evaluation.csv")
    evidence_rows = _read_csv(data_dir / "tables" / "multimodal_evidence_index.csv")
    review_rows = _read_csv(data_dir / "tables" / "review_tasks.csv")
    standard_field_rows = _read_csv(data_dir / "tables" / "standard_field_catalog.csv")
    relation_tables = _read_relation_tables(data_dir / "relations")
    scenario_metric_rows = _read_csv(data_dir / "optimization" / "scenario_metrics.csv")
    scenario_feasibility_rows = _read_csv(data_dir / "optimization" / "scenario_feasibility.csv")

    standard_roles = _standard_roles(role_contracts)
    aliases = _field_aliases(field_aliases)
    aliases.update(_data_dictionary_field_aliases(data_dictionary))

    layer_summaries = _build_layer_summaries(metadata_rows, manifest, standard_roles)
    field_semantics = _build_field_semantics(
        layer_summaries,
        standard_field_rows,
        aliases,
        standard_roles,
        role_contracts,
        value_domains,
    )
    alignment_summary = build_standard_alignment_summary(field_semantics)
    value_domain_audits = _build_value_domain_audits(
        data_dir,
        layer_summaries,
        field_semantics,
        value_domains,
    )
    value_domain_audit_summary = build_value_domain_audit_summary(value_domain_audits)
    standard_summary = _build_standard_summary(
        standard_field_rows,
        field_aliases,
        role_contracts,
        standard_rules,
        standard_source_registry,
    )
    rule_summary = _build_rule_summary(rule_rows)
    evidence_summary = _build_evidence_summary(evidence_rows, raster_manifest, real_imagery_manifest)
    optimization_summary = _build_optimization_summary(
        pareto_summary,
        scenario_metric_rows,
        scenario_feasibility_rows,
        _read_csv(data_dir / "optimization" / "objective_catalog.csv"),
    )
    review_summary = _build_review_summary(review_rows)
    rule_bindings = _build_rule_bindings(standard_rules)
    semantic_relations = _build_semantic_relations(relation_tables)
    semantic_relation_summary = _build_semantic_relation_summary(semantic_relations)
    knowledge_graph = _build_knowledge_graph(
        layer_summaries,
        field_semantics,
        semantic_relations,
        rule_bindings,
        evidence_summary,
        optimization_summary,
        value_domains,
        standard_source_registry,
    )
    t_wm_consumption = _build_twm_consumption(
        layer_summaries,
        standard_summary,
        alignment_summary,
        semantic_relation_summary,
        rule_summary,
        optimization_summary,
        field_semantics,
    )

    product_id = _product_id(data_dir, manifest, layer_summaries, rule_summary, optimization_summary)
    business_view = _build_business_view(
        product_id,
        manifest,
        layer_summaries,
        standard_summary,
        rule_summary,
        evidence_summary,
        optimization_summary,
        review_summary,
        t_wm_consumption,
    )
    business_view_path = out_dir / "twm_mmfe_business_view.csv"
    _write_csv(business_view_path, business_view)

    field_semantics_path = out_dir / "twm_mmfe_field_semantics.csv"
    _write_csv(field_semantics_path, field_semantics)

    value_domain_audit_path = out_dir / "twm_mmfe_value_domain_audit.csv"
    _write_csv(value_domain_audit_path, value_domain_audits)

    standard_source_path = out_dir / "twm_mmfe_standard_sources.csv"
    _write_csv(standard_source_path, standard_source_rows)

    standard_source_ingestion_plan = build_standard_source_ingestion_plan(standard_source_registry)
    standard_source_ingestion_validation = validate_standard_source_ingestion_plan(standard_source_ingestion_plan)
    standard_source_ingestion_path = out_dir / "twm_mmfe_standard_source_ingestion_plan.json"
    _write_json(standard_source_ingestion_path, standard_source_ingestion_plan)

    semantic_relations_path = out_dir / "twm_mmfe_semantic_relations.csv"
    _write_csv(semantic_relations_path, semantic_relations)

    twm_input_contract_path = out_dir / "twm_state_input_contract.json"
    _write_json(twm_input_contract_path, t_wm_consumption)

    knowledge_graph_path = out_dir / "twm_mmfe_semantic_graph.json"
    _write_json(knowledge_graph_path, knowledge_graph)

    semantic_trace_cards = build_semantic_trace_card_bundle(
        knowledge_graph,
        _semantic_trace_focus_nodes(),
    )
    semantic_trace_cards_path = out_dir / "twm_mmfe_semantic_trace_cards.json"
    _write_json(semantic_trace_cards_path, semantic_trace_cards)

    twm_state_input_path = out_dir / "twm_state_input.json"
    semantic_product = _build_semantic_product(
        product_id=product_id,
        data_dir=data_dir,
        out_dir=out_dir,
        manifest=manifest,
        quality=quality,
        layer_summaries=layer_summaries,
        standard_summary=standard_summary,
        standard_source_registry=standard_source_registry,
        standard_source_rows=standard_source_rows,
        standard_source_ingestion_plan=standard_source_ingestion_plan,
        alignment_summary=alignment_summary,
        value_domain_audit_summary=value_domain_audit_summary,
        value_domain_audits=value_domain_audits,
        semantic_relation_summary=semantic_relation_summary,
        rule_summary=rule_summary,
        evidence_summary=evidence_summary,
        optimization_summary=optimization_summary,
        review_summary=review_summary,
        t_wm_consumption=t_wm_consumption,
        field_semantics=field_semantics,
        semantic_relations=semantic_relations,
        rule_bindings=rule_bindings,
        knowledge_graph=knowledge_graph,
        semantic_trace_cards=semantic_trace_cards,
        business_view_path=business_view_path,
        field_semantics_path=field_semantics_path,
        value_domain_audit_path=value_domain_audit_path,
        standard_source_path=standard_source_path,
        standard_source_ingestion_path=standard_source_ingestion_path,
        semantic_relations_path=semantic_relations_path,
        twm_input_contract_path=twm_input_contract_path,
        twm_state_input_path=twm_state_input_path,
        knowledge_graph_path=knowledge_graph_path,
        semantic_trace_cards_path=semantic_trace_cards_path,
    )
    semantic_product["mmfe_bundle"]["source_production_metadata"] = _build_production_readiness_sources(
        manifest,
        data_dir,
    )
    production_readiness = production_readiness_from_manifest(semantic_product)
    production_readiness_path = out_dir / "twm_mmfe_production_readiness.json"
    _write_json(production_readiness_path, production_readiness)
    semantic_product["business_outputs"]["production_readiness"] = str(production_readiness_path)
    semantic_product["mmfe_bundle"]["production_readiness"] = production_readiness

    twm_state_input = build_twm_state_input_from_semantic_product(
        semantic_product,
        semantic_relations=semantic_relations,
        input_contract=t_wm_consumption,
    )
    twm_state_input_validation = validate_twm_state_input(twm_state_input)
    _write_json(twm_state_input_path, twm_state_input)

    semantic_ontology = build_semantic_ontology_package(
        semantic_product,
        field_semantics=field_semantics,
        value_domain_audits=value_domain_audits,
        standard_sources=standard_source_rows,
        semantic_relations=semantic_relations,
        state_input=twm_state_input,
    )
    semantic_ontology_validation = validate_semantic_ontology_package(semantic_ontology)
    semantic_ontology_path = out_dir / "twm_mmfe_semantic_ontology.json"
    _write_json(semantic_ontology_path, semantic_ontology)
    semantic_product["business_outputs"]["semantic_ontology"] = str(semantic_ontology_path)
    semantic_product["mmfe_bundle"]["semantic_ontology_summary"] = semantic_ontology["summary"]

    semantic_diagnostic = diagnose_semantic_product_readiness(
        semantic_product,
        value_domain_audits=value_domain_audits,
        standard_sources=standard_source_rows,
        semantic_relations=semantic_relations,
        state_input=twm_state_input,
        semantic_graph=knowledge_graph,
        semantic_trace_cards=semantic_trace_cards,
    )
    semantic_diagnostic_path = out_dir / "twm_mmfe_semantic_diagnostic.json"
    _write_json(semantic_diagnostic_path, semantic_diagnostic)

    semantic_product["business_outputs"]["semantic_diagnostic"] = str(semantic_diagnostic_path)
    semantic_product["mmfe_bundle"]["semantic_diagnostic_summary"] = semantic_diagnostic["summary"]
    semantic_product["mmfe_bundle"]["semantic_diagnostic_top_gaps"] = semantic_diagnostic["top_gaps"]
    semantic_product["mmfe_bundle"]["semantic_diagnostic_recommendations_zh"] = semantic_diagnostic[
        "recommendations_zh"
    ]
    semantic_product_path = out_dir / "twm_mmfe_semantic_product.json"
    _write_json(semantic_product_path, semantic_product)

    vector_spec = _build_vector_spec(semantic_product)
    vector_spec_path = out_dir / "twm_mmfe_semantic_vectors.pgvector.json"
    _write_json(vector_spec_path, vector_spec)

    publish_plan = _build_publish_plan(semantic_product)
    publish_plan_path = out_dir / "twm_mmfe_publish_plan.json"
    _write_json(publish_plan_path, publish_plan)

    stac_item = _build_stac_item(semantic_product)
    stac_item_path = out_dir / "twm_mmfe_stac_item.json"
    _write_json(stac_item_path, stac_item)

    readme_path = out_dir / "README.md"
    _write_text(
        readme_path,
        _render_readme(
            semantic_product,
            business_view_path,
            field_semantics_path,
            value_domain_audit_path,
            standard_source_path,
            standard_source_ingestion_path,
            production_readiness_path,
            semantic_relations_path,
            twm_input_contract_path,
            twm_state_input_path,
            knowledge_graph_path,
            semantic_trace_cards_path,
            semantic_ontology_path,
            semantic_diagnostic_path,
            semantic_product_path,
            vector_spec_path,
            publish_plan_path,
            stac_item_path,
        ),
    )

    print(json.dumps({
        "status": "ok",
        "product_id": product_id,
        "out_dir": str(out_dir),
        "business_view": str(business_view_path),
        "field_semantics": str(field_semantics_path),
        "value_domain_audit": str(value_domain_audit_path),
        "standard_sources": str(standard_source_path),
        "standard_source_ingestion_plan": str(standard_source_ingestion_path),
        "standard_source_ingestion_plan_valid": standard_source_ingestion_validation["valid"],
        "production_readiness": str(production_readiness_path),
        "semantic_relations": str(semantic_relations_path),
        "twm_input_contract": str(twm_input_contract_path),
        "twm_state_input": str(twm_state_input_path),
        "twm_state_input_valid": twm_state_input_validation["valid"],
        "knowledge_graph": str(knowledge_graph_path),
        "semantic_trace_cards": str(semantic_trace_cards_path),
        "semantic_ontology": str(semantic_ontology_path),
        "semantic_ontology_valid": semantic_ontology_validation["valid"],
        "semantic_diagnostic": str(semantic_diagnostic_path),
        "semantic_product": str(semantic_product_path),
        "vector_spec": str(vector_spec_path),
        "publish_plan": str(publish_plan_path),
        "stac_item": str(stac_item_path),
        "chunk_count": len(semantic_product["ai_metadata"]["chunks"]),
        "layer_count": len(layer_summaries),
        "field_semantic_count": len(field_semantics),
        "value_domain_audit_count": len(value_domain_audits),
        "standard_source_count": len(standard_source_rows),
        "standard_source_ingestion_ready": standard_source_ingestion_plan["summary"]["ready"],
        "standard_source_ingestion_blocked_task_count": standard_source_ingestion_plan["summary"]["blocked_task_count"],
        "production_readiness_ready": production_readiness["summary"]["production_metadata_ready"],
        "production_readiness_blocked_source_count": production_readiness["summary"]["blocked_source_count"],
        "semantic_relation_count": len(semantic_relations),
        "semantic_trace_card_count": semantic_trace_cards["trace_card_count"],
        "semantic_ontology_relationship_count": semantic_ontology["summary"]["relationship_count"],
        "semantic_diagnostic_status": semantic_diagnostic["summary"]["status"],
        "semantic_diagnostic_validation_ready": semantic_diagnostic["summary"]["validation_ready"],
        "semantic_diagnostic_production_ready": semantic_diagnostic["summary"]["production_ready"],
    }, ensure_ascii=False, indent=2))


def _build_layer_summaries(rows: list[dict], manifest: dict, standard_roles: dict) -> list[dict]:
    aliases = ((manifest.get("aliases") or {}).get("layers") or {})
    summaries = []
    for row in rows:
        layer = row.get("layer_name") or row.get("resource_id", "").split(":")[-1]
        alias = aliases.get(layer, {})
        fields = [field.strip() for field in str(row.get("layer_field", "")).split(",") if field.strip()]
        standard_role = _standard_role_for_layer(layer)
        role_contract = standard_roles.get(standard_role, {})
        summaries.append({
            "role": layer,
            "standard_role": standard_role,
            "resource_id": row.get("resource_id"),
            "path": str(Path(row.get("layer_name", layer)).with_suffix(".geojson")),
            "data_name": row.get("data_name"),
            "alias_zh": alias.get("alias_zh") or row.get("data_alias"),
            "standard_role_alias_zh": role_contract.get("role_alias_zh", ""),
            "description_zh": alias.get("description_zh") or row.get("data_des"),
            "business_role_zh": alias.get("business_role_zh", ""),
            "data_type": row.get("data_type"),
            "data_format": row.get("data_format"),
            "geometry_type": row.get("geometry_type"),
            "crs": row.get("projection") or row.get("wkid"),
            "bbox": _safe_json(row.get("cover_range_coor"), default=[]),
            "field_count": len(fields),
            "fields": fields,
            "fields_sample": fields[:12],
            "quality_score": _safe_float(row.get("score"), 0.0),
            "synthetic": _to_bool(row.get("synthetic")),
            "not_for_production": _to_bool(row.get("not_for_production")),
            "required_fields": role_contract.get("required_fields", []),
            "recommended_fields": role_contract.get("recommended_fields", []),
            "twm_binding": role_contract.get("twm_binding", {}),
        })
    return summaries


def _build_production_readiness_sources(
    manifest: dict,
    data_dir: Path,
) -> list[dict]:
    sources = []
    for index, binding in enumerate(manifest.get("recommended_layer_bindings") or []):
        if not isinstance(binding, dict):
            continue
        role = str(binding.get("role") or f"source_{index + 1}")
        path = str(binding.get("path") or "")
        sources.append({
            "source_id": role,
            "role": role,
            "source_path": path or str(data_dir / role),
            "synthetic": role != "admin_unit",
            "not_for_production": True,
            "lineage": "TWM validation fixture generated for MMFE contract testing",
            "crs": "EPSG:4326",
            "security_classification": "internal",
        })
    return sources


def _build_field_semantics(
    layers: list[dict],
    standard_field_rows: list[dict],
    field_aliases: dict,
    standard_roles: dict,
    role_contracts: dict,
    value_domains: dict,
) -> list[dict]:
    standard_catalog = {row.get("field_name"): row for row in standard_field_rows}
    rows = []
    for layer in layers:
        role_contract = standard_roles.get(layer["standard_role"], {})
        alignments = align_layer_fields_to_standard_contract(
            layer.get("fields", []),
            layer["standard_role"],
            role_contracts,
            field_aliases=field_aliases,
            standard_fields=standard_field_rows,
            value_domains=value_domains,
            layer_role=layer["role"],
            object_type=_object_type_for_role(layer["role"]),
            field_alias_overrides=field_aliases,
        )
        for alignment in alignments:
            field = alignment["field_name"]
            catalog = standard_catalog.get(alignment.get("standard_field") or field, {})
            domain_or_rule = alignment.get("domain_or_rule") or {}
            row = {
                "layer_role": layer["role"],
                "standard_role": layer["standard_role"],
                "object_type": _object_type_for_role(layer["role"]),
                "field_name": field,
                "field_alias_zh": alignment.get("field_alias_zh") or field_aliases.get(field) or catalog.get("field_alias_zh", ""),
                "standard_field": alignment.get("standard_field", ""),
                "standard_version": alignment.get("standard_version") or catalog.get("standard_version") or "",
                "lifecycle_status": alignment.get("lifecycle_status") or catalog.get("lifecycle_status") or "not_in_standard_catalog",
                "contract_requirement": alignment.get("contract_requirement", "observed"),
                "twm_semantic_key": alignment.get("twm_semantic_key", ""),
                "domain_or_rule": json.dumps(domain_or_rule, ensure_ascii=False, sort_keys=True),
                "value_domain": alignment.get("value_domain", ""),
                "value_domain_status": alignment.get("value_domain_status", ""),
                "match_type": alignment.get("match_type", "local_extension"),
                "alignment_match_type": alignment.get("alignment_match_type", ""),
                "confidence": alignment.get("confidence", 0.72),
                "alignment_score": alignment.get("alignment_score", {}).get("score"),
                "alignment_decision": alignment.get("alignment_decision", "review"),
                "requires_review": alignment.get("requires_review", True),
                "evidence_json": json.dumps(alignment.get("evidence", []), ensure_ascii=False, sort_keys=True),
                "standard_reference_json": json.dumps(
                    alignment.get("standard_reference", {}),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "explanation": alignment.get("explanation", ""),
                "not_for_production": True,
            }
            rows.append(row)
    return rows


def _build_standard_summary(
    standard_field_rows: list[dict],
    field_aliases: dict,
    role_contracts: dict,
    standard_rules: dict,
    standard_source_registry: dict,
) -> dict:
    active_fields = [row for row in standard_field_rows if row.get("lifecycle_status") == "active"]
    aliases = _field_aliases(field_aliases)
    roles = _standard_roles(role_contracts)
    source_summary = standard_source_registry.get("summary") or {}
    return {
        "standard_version": _first_non_empty(row.get("standard_version") for row in standard_field_rows),
        "active_field_count": len(active_fields),
        "alias_count": len(aliases),
        "role_contract_count": len(roles),
        "rule_lifecycle_status": standard_rules.get("status") or standard_rules.get("lifecycle_status"),
        "standard_source_count": source_summary.get("source_count", 0),
        "official_verified_source_count": source_summary.get("official_verified_count", 0),
        "fulltext_available_or_downloaded_count": source_summary.get(
            "fulltext_available_or_downloaded_count",
            0,
        ),
        "pending_official_source_count": source_summary.get("pending_official_source_count", 0),
        "authority_level": "validation_scaffold",
        "source_note_zh": "来自自然资源一张图标准材料结构化契约与 TWM 测试包字段目录；用于工程验证，不等同生产权威标准库。",
        "source_registry_summary": source_summary,
    }


def _build_rule_summary(rows: list[dict]) -> dict:
    status_counter = Counter(row.get("finding_status") for row in rows)
    severity_counter = Counter(row.get("severity") for row in rows)
    rule_counter = Counter(row.get("rule_id") for row in rows)
    hit_rows = [row for row in rows if row.get("finding_status") != "pass"]
    critical_hits = [row for row in hit_rows if row.get("severity") in {"critical", "high"}]
    return {
        "rule_eval_count": len(rows),
        "pass_count": status_counter.get("pass", 0),
        "hit_requires_review_count": len(hit_rows),
        "critical_or_high_hit_count": len(critical_hits),
        "status_distribution": dict(status_counter),
        "severity_distribution": dict(severity_counter),
        "rule_distribution": dict(rule_counter),
        "top_review_examples": [
            {
                "project_id": row.get("project_id"),
                "rule_id": row.get("rule_id"),
                "rule_name_zh": row.get("rule_name_zh"),
                "severity": row.get("severity"),
                "basis": row.get("finding_basis"),
            }
            for row in critical_hits[:5]
        ],
    }


def _build_evidence_summary(rows: list[dict], raster_manifest: dict, real_imagery_manifest: dict) -> dict:
    type_counter = Counter(row.get("evidence_type") for row in rows)
    return {
        "evidence_count": len(rows),
        "evidence_type_distribution": dict(type_counter),
        "has_real_imagery": bool(real_imagery_manifest),
        "real_imagery_assets": sorted((real_imagery_manifest.get("assets") or {}).keys()),
        "raster_assets": sorted((raster_manifest.get("assets") or {}).keys()),
        "evidence_note_zh": "证据索引将项目文档、遥感瓦片、规则命中和空间对象连接为可检索证据链。",
    }


def _build_optimization_summary(
    pareto: dict,
    metric_rows: list[dict],
    feasibility_rows: list[dict],
    objective_rows: list[dict],
) -> dict:
    feasibility_counter = Counter(row.get("hard_constraint_status") for row in feasibility_rows)
    objective_counter = Counter(row.get("objective_id") for row in metric_rows)
    hard_constraints = [row.get("objective_id") for row in objective_rows if _to_bool(row.get("hard_constraint"))]
    return {
        "method": pareto.get("method"),
        "objective_count": pareto.get("objective_count") or len(objective_counter),
        "scenario_count": pareto.get("scenario_count") or len({row.get("scenario_id") for row in metric_rows}),
        "legal_feasible_scenario_count": pareto.get("legal_feasible_scenario_count"),
        "blocked_scenario_count": pareto.get("blocked_scenario_count"),
        "comparison_scope": pareto.get("comparison_scope"),
        "non_dominated_scenarios": pareto.get("non_dominated_scenarios", []),
        "ranked_scenarios": pareto.get("ranked_scenarios", []),
        "feasibility_distribution": dict(feasibility_counter),
        "hard_constraint_policy_zh": pareto.get("hard_constraint_policy_zh"),
        "objectives": [
            {
                "objective_id": row.get("objective_id"),
                "objective_name_zh": row.get("objective_name_zh"),
                "category": row.get("category"),
                "direction": row.get("direction"),
                "unit": row.get("unit"),
                "weight": _safe_float(row.get("weight"), 0.0),
                "hard_constraint": _to_bool(row.get("hard_constraint")),
                "description_zh": row.get("description_zh"),
            }
            for row in objective_rows
        ],
        "hard_constraint_objectives": hard_constraints,
    }


def _build_review_summary(rows: list[dict]) -> dict:
    status_counter = Counter(row.get("task_status") or row.get("status") for row in rows)
    priority_counter = Counter(row.get("priority") or row.get("review_priority") for row in rows)
    return {
        "review_task_count": len(rows),
        "status_distribution": dict(status_counter),
        "priority_distribution": dict(priority_counter),
    }


def _build_semantic_relations(relation_tables: dict[str, list[dict]]) -> list[dict]:
    rows = []
    for source_file, relation_rows in sorted(relation_tables.items()):
        for row in relation_rows:
            relation_type = row.get("relation_type", "")
            spec = _relation_semantic_spec(relation_type)
            left_object_id, right_object_id = _relation_object_ids(row, spec)
            overlap_area = _safe_float(row.get("overlap_area_m2"), 0.0)
            overlap_ratio_left = _safe_float(row.get("overlap_ratio_left"), 0.0)
            overlap_ratio_right = _safe_float(row.get("overlap_ratio_right"), 0.0)
            confidence = _safe_float(row.get("confidence"), 0.0)
            semantic_strength = _relation_strength(
                overlap_area,
                overlap_ratio_left,
                confidence,
                evidence_type=spec["evidence_type"],
                match_type=row.get("match_type", ""),
            )
            relation = {
                "relation_id": row.get("relation_id", ""),
                "source_file": source_file,
                "relation_type": relation_type,
                "semantic_relation_type": spec["semantic_relation_type"],
                "source_object_type": spec["source_object_type"],
                "source_object_id": left_object_id,
                "target_object_type": spec["target_object_type"],
                "target_object_id": right_object_id,
                "target_standard_role": spec["target_standard_role"],
                "predicate_zh": spec["predicate_zh"],
                "business_semantic_zh": spec["business_semantic_zh"],
                "twm_usage": spec["twm_usage"],
                "objective_id": spec["objective_id"],
                "rule_id": spec["rule_id"],
                "evidence_type": spec["evidence_type"],
                "evidence_source": f"relations/{source_file}",
                "metric_name": "overlap_area_m2" if row.get("overlap_area_m2") else "match_confidence",
                "metric_value": overlap_area if row.get("overlap_area_m2") else confidence,
                "overlap_area_m2": overlap_area,
                "overlap_ratio_left": overlap_ratio_left,
                "overlap_ratio_right": overlap_ratio_right,
                "confidence": confidence,
                "semantic_strength": semantic_strength,
                "requires_rule_review": spec["requires_rule_review"] and overlap_area > 1,
                "synthetic": _to_bool(row.get("synthetic")),
                "not_for_production": _to_bool(row.get("not_for_production")),
            }
            rows.append(relation)
    return rows


def _build_semantic_relation_summary(relations: list[dict]) -> dict:
    relation_counter = Counter(row["semantic_relation_type"] for row in relations)
    target_counter = Counter(row["target_standard_role"] for row in relations)
    usage_counter = Counter(row["twm_usage"] for row in relations)
    review_relations = [row for row in relations if _to_bool(row.get("requires_rule_review"))]
    return {
        "semantic_relation_count": len(relations),
        "relation_type_distribution": dict(relation_counter),
        "target_role_distribution": dict(target_counter),
        "twm_usage_distribution": dict(usage_counter),
        "rule_review_relation_count": len(review_relations),
        "top_rule_review_examples": [
            {
                "relation_id": row["relation_id"],
                "semantic_relation_type": row["semantic_relation_type"],
                "source_object_id": row["source_object_id"],
                "target_object_id": row["target_object_id"],
                "metric_value": row["metric_value"],
                "rule_id": row["rule_id"],
            }
            for row in review_relations[:8]
        ],
    }


def _build_value_domain_audits(
    data_dir: Path,
    layers: list[dict],
    field_semantics: list[dict],
    value_domains: dict,
) -> list[dict]:
    layer_by_role = {layer["role"]: layer for layer in layers}
    rows = []
    for item in field_semantics:
        domain = item.get("value_domain")
        if not domain:
            continue
        layer = layer_by_role.get(item.get("layer_role"))
        if not layer:
            continue
        source_path = data_dir / layer["path"]
        values = _read_geojson_property_values(source_path, item.get("field_name", ""))
        audit = audit_field_value_domain(
            values,
            domain,
            value_domains,
            layer_role=item.get("layer_role", ""),
            field_name=item.get("field_name", ""),
        )
        observed_values = audit.get("observed_values") or []
        unknown_values = audit.get("unknown_values") or []
        rows.append({
            "layer_role": audit["layer_role"],
            "standard_role": item.get("standard_role", ""),
            "field_name": audit["field_name"],
            "field_alias_zh": item.get("field_alias_zh", ""),
            "standard_field": item.get("standard_field", ""),
            "twm_semantic_key": item.get("twm_semantic_key", ""),
            "domain": audit["domain"],
            "domain_status": audit["domain_status"],
            "audit_status": audit["audit_status"],
            "domain_item_count": audit["domain_item_count"],
            "total_count": audit["total_count"],
            "non_null_count": audit["non_null_count"],
            "null_count": audit["null_count"],
            "distinct_observed_count": audit["distinct_observed_count"],
            "valid_count": audit["valid_count"],
            "unknown_count": audit["unknown_count"],
            "coverage": audit["coverage"],
            "observed_values_json": json.dumps(observed_values, ensure_ascii=False, sort_keys=True),
            "unknown_values_json": json.dumps(unknown_values, ensure_ascii=False, sort_keys=True),
            "unknown_values_truncated": audit["unknown_values_truncated"],
            "source_path": layer["path"],
            "not_for_production": True,
        })
    return rows


def _build_twm_consumption(
    layers: list[dict],
    standards: dict,
    alignment_summary: dict,
    relation_summary: dict,
    rules: dict,
    optimization: dict,
    field_semantics: list[dict],
) -> dict:
    role_bindings = []
    for layer in layers:
        bound_fields = {
            item["twm_semantic_key"]: item["field_name"]
            for item in field_semantics
            if item["layer_role"] == layer["role"] and item.get("twm_semantic_key")
        }
        role_bindings.append({
            "role": layer["role"],
            "standard_role": layer["standard_role"],
            "role_alias_zh": layer.get("standard_role_alias_zh") or layer.get("alias_zh"),
            "object_type": _object_type_for_role(layer["role"]),
            "field_count": layer["field_count"],
            "quality_score": layer["quality_score"],
            "business_role_zh": layer.get("business_role_zh", ""),
            "source_path": layer["path"],
            "twm_binding": bound_fields,
            "semantic_readiness": "ready_for_state_builder",
        })
    return {
        "recommended_twm_input": "semantic_fusion_product",
        "raw_data_usage": "source_of_truth_geometry_and_attributes",
        "semantic_product_usage": "role_binding_quality_lineage_evidence_and_ai_grounding",
        "state_builder_policy": "load_semantic_product_then_dereference_raw_sources",
        "role_bindings": role_bindings,
        "state_builder_inputs": {
            "object_roles": [binding["role"] for binding in role_bindings],
            "standard_roles": sorted({binding["standard_role"] for binding in role_bindings}),
            "standard_active_field_count": standards["active_field_count"],
            "field_semantic_count": len(field_semantics),
            "alignment_decisions": alignment_summary.get("decisions", {}),
            "alignment_review_required": alignment_summary.get("review_required", 0),
            "semantic_relation_count": relation_summary.get("semantic_relation_count", 0),
            "semantic_relation_types": sorted(
                relation_summary.get("relation_type_distribution", {}).keys()
            ),
            "rule_review_relation_count": relation_summary.get("rule_review_relation_count", 0),
            "rule_eval_count": rules["rule_eval_count"],
            "optimization_scenario_count": optimization["scenario_count"],
            "optimization_objectives": [item["objective_id"] for item in optimization.get("objectives", [])],
            "hard_constraint_objectives": optimization.get("hard_constraint_objectives", []),
        },
        "guidance_zh": (
            "后续 TWM 不应只直接读取原始数据文件。原始数据仍作为几何和属性事实源，"
            "但状态构建、规则解释、证据链、AI 检索和优化输入应优先读取 MMFE 语义融合成果。"
        ),
    }


def _build_business_view(
    product_id: str,
    manifest: dict,
    layers: list[dict],
    standards: dict,
    rules: dict,
    evidence: dict,
    optimization: dict,
    review: dict,
    t_wm_consumption: dict,
) -> list[dict]:
    return [
        {
            "product_id": product_id,
            "dataset_id": manifest.get("dataset_id"),
            "dataset_alias_zh": manifest.get("dataset_alias_zh"),
            "semantic_fusion_scope": "twm_multimodal_validation_scaffold",
            "layer_count": len(layers),
            "standard_active_field_count": standards["active_field_count"],
            "rule_eval_count": rules["rule_eval_count"],
            "hit_requires_review_count": rules["hit_requires_review_count"],
            "evidence_count": evidence["evidence_count"],
            "review_task_count": review["review_task_count"],
            "semantic_relation_count": t_wm_consumption["state_builder_inputs"]["semantic_relation_count"],
            "optimization_objective_count": optimization["objective_count"],
            "optimization_scenario_count": optimization["scenario_count"],
            "legal_feasible_scenario_count": optimization["legal_feasible_scenario_count"],
            "field_semantic_count": t_wm_consumption["state_builder_inputs"]["field_semantic_count"],
            "standard_role_count": len(t_wm_consumption["state_builder_inputs"]["standard_roles"]),
            "recommended_twm_input": t_wm_consumption["recommended_twm_input"],
            "not_for_production": manifest.get("not_for_production"),
        }
    ]


def _build_semantic_product(**kwargs) -> dict:
    product_id = kwargs["product_id"]
    data_dir = kwargs["data_dir"]
    out_dir = kwargs["out_dir"]
    manifest = kwargs["manifest"]
    layers = kwargs["layer_summaries"]
    standard_summary = kwargs["standard_summary"]
    standard_source_registry = kwargs["standard_source_registry"]
    standard_source_rows = kwargs["standard_source_rows"]
    standard_source_ingestion_plan = kwargs["standard_source_ingestion_plan"]
    alignment_summary = kwargs["alignment_summary"]
    value_domain_audit_summary = kwargs["value_domain_audit_summary"]
    semantic_relation_summary = kwargs["semantic_relation_summary"]
    rule_summary = kwargs["rule_summary"]
    evidence_summary = kwargs["evidence_summary"]
    optimization_summary = kwargs["optimization_summary"]
    review_summary = kwargs["review_summary"]
    t_wm_consumption = kwargs["t_wm_consumption"]
    field_semantics = kwargs["field_semantics"]
    value_domain_audits = kwargs["value_domain_audits"]
    semantic_relations = kwargs["semantic_relations"]
    rule_bindings = kwargs["rule_bindings"]
    knowledge_graph = kwargs["knowledge_graph"]
    semantic_trace_cards = kwargs["semantic_trace_cards"]
    quality = kwargs["quality"]
    business_view_path = kwargs["business_view_path"]
    field_semantics_path = kwargs["field_semantics_path"]
    value_domain_audit_path = kwargs["value_domain_audit_path"]
    standard_source_path = kwargs["standard_source_path"]
    standard_source_ingestion_path = kwargs["standard_source_ingestion_path"]
    semantic_relations_path = kwargs["semantic_relations_path"]
    twm_input_contract_path = kwargs["twm_input_contract_path"]
    twm_state_input_path = kwargs["twm_state_input_path"]
    knowledge_graph_path = kwargs["knowledge_graph_path"]
    semantic_trace_cards_path = kwargs["semantic_trace_cards_path"]

    chunks = _build_ai_chunks(
        manifest,
        layers,
        standard_summary,
        alignment_summary,
        semantic_relation_summary,
        rule_summary,
        evidence_summary,
        optimization_summary,
        t_wm_consumption,
        field_semantics,
        value_domain_audit_summary,
        standard_source_registry,
    )
    retrieval_text = chunks[0]["text"]
    source_count = len(layers)
    return {
        "product_type": "semantic_fusion_product",
        "version": "1.1-twm-mmfe-bundle",
        "product_id": product_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "business_output": {
            "path": str(business_view_path),
            "format": "CSV",
            "row_count": 1,
            "column_count": len(_read_csv(business_view_path)[0]) if business_view_path.exists() else 0,
            "crs": "EPSG:4326",
        },
        "business_outputs": {
            "summary_view": str(business_view_path),
            "field_semantics": str(field_semantics_path),
            "value_domain_audit": str(value_domain_audit_path),
            "standard_sources": str(standard_source_path),
            "standard_source_ingestion_plan": str(standard_source_ingestion_path),
            "semantic_relations": str(semantic_relations_path),
            "twm_input_contract": str(twm_input_contract_path),
            "twm_state_input": str(twm_state_input_path),
            "semantic_graph": str(knowledge_graph_path),
            "semantic_trace_cards": str(semantic_trace_cards_path),
            "semantic_ontology": "",
            "semantic_diagnostic": "",
        },
        "sources": [
            {
                "path": str(data_dir / layer["path"]),
                "data_type": layer["data_type"],
                "modality": _modality_for_role(layer["role"]),
                "media_type": _media_type_for_layer(layer),
                "adapter_family": _adapter_family_for_layer(layer),
                "row_count": None,
                "crs": layer.get("crs"),
                "semantic_domain": layer["role"],
                "semantic_hints": [
                    layer.get("alias_zh", ""),
                    layer.get("business_role_zh", ""),
                    layer.get("description_zh", ""),
                ],
                "columns": layer.get("fields_sample", []),
            }
            for layer in layers
        ],
        "semantic_mappings": _build_semantic_mappings(layers, standard_summary, field_semantics),
        "field_contracts": _build_bundle_field_contracts(layers, standard_summary, field_semantics),
        "derived_fields": [
            {
                "field": "twm_role_binding",
                "method": "standard_contract_role_binding",
                "description": "Layer role derived from TWM dataset manifest and One Map role contracts.",
            },
            {
                "field": "hard_constraint_status",
                "method": "rule_evaluation_summary",
                "description": "Scenario feasibility derived from PBF and ecological redline hard-constraint filters.",
            },
        ],
        "inferred_fields": [
            {
                "field": "semantic_readiness",
                "method": "mmfe_bundle_inference",
                "description": "Readiness inferred from layer role, standard field coverage, QA and evidence availability.",
            }
        ],
        "feature_semantics": _build_feature_semantics(
            layers,
            rule_summary,
            optimization_summary,
            semantic_relation_summary,
        ),
        "ai_metadata": {
            "retrieval_text": retrieval_text,
            "chunks": chunks,
            "embedding_ready": True,
            "recommended_vector_targets": ["pgvector", "lancedb"],
        },
        "quality": {
            "score": _quality_score(quality, layers),
            "warnings": _quality_warnings(quality, manifest),
        },
        "lineage": {
            "strategy": "twm_multimodal_semantic_bundle",
            "source_dataset": str(data_dir),
            "output_dir": str(out_dir),
            "alignment_steps": [
                "bind TWM layers to semantic roles",
                "score fields against One Map role contracts, Chinese aliases, value domains and TWM binding keys",
                "connect project/rule/evidence/optimization tables",
                "emit AI-ready chunks and publish specs",
            ],
            "temporal_alignment": [
                "current parcel baseline",
                "annual change layer",
                "rule event dates",
                "scenario comparison snapshot",
            ],
            "conflict_resolution": {
                "hard_constraints": "PBF and ecological redline violations block scenario recommendation",
                "production_truth": "not_for_production fixtures never override future authoritative data",
            },
        },
        "mmfe_bundle": {
            "layer_summaries": layers,
            "field_semantics": field_semantics,
            "value_domain_audits": value_domain_audits,
            "value_domain_audit_summary": value_domain_audit_summary,
            "standard_source_registry": standard_source_registry,
            "standard_source_rows": standard_source_rows,
            "standard_source_ingestion_plan": standard_source_ingestion_plan,
            "semantic_relations": semantic_relations,
            "semantic_relation_summary": semantic_relation_summary,
            "standard_summary": standard_summary,
            "alignment_summary": alignment_summary,
            "rule_bindings": rule_bindings,
            "rule_summary": rule_summary,
            "evidence_summary": evidence_summary,
            "optimization_summary": optimization_summary,
            "review_summary": review_summary,
            "twm_consumption": t_wm_consumption,
            "semantic_graph": knowledge_graph,
            "semantic_trace_cards": semantic_trace_cards,
        },
    }


def _build_ai_chunks(
    manifest: dict,
    layers: list[dict],
    standards: dict,
    alignment_summary: dict,
    relation_summary: dict,
    rules: dict,
    evidence: dict,
    optimization: dict,
    t_wm_consumption: dict,
    field_semantics: list[dict],
    value_domain_audit_summary: dict,
    standard_source_registry: dict,
) -> list[dict]:
    chunks = []
    dataset_name = manifest.get("dataset_alias_zh") or manifest.get("dataset_id")
    source_summary = standard_source_registry.get("summary") or {}
    chunks.append({
        "chunk_id": "fusion:product",
        "text": (
            f"{dataset_name} 的 MMFE 语义融合产品。融合了 {len(layers)} 个空间/证据图层、"
            f"{standards['active_field_count']} 个标准字段、{rules['rule_eval_count']} 条规则评估、"
            f"{evidence['evidence_count']} 条多模态证据、{optimization['scenario_count']} 个优化方案、"
            f"{len(field_semantics)} 条字段级语义映射、"
            f"{relation_summary['semantic_relation_count']} 条空间/多模态语义关系。"
            f"TWM 推荐消费方式：{t_wm_consumption['recommended_twm_input']}。"
        ),
        "metadata": {
            "strategy": "twm_multimodal_semantic_bundle",
            "dataset_id": manifest.get("dataset_id"),
            "layer_count": len(layers),
            "standard_active_field_count": standards["active_field_count"],
            "rule_eval_count": rules["rule_eval_count"],
            "evidence_count": evidence["evidence_count"],
            "scenario_count": optimization["scenario_count"],
            "field_semantic_count": len(field_semantics),
            "alignment_accept_count": alignment_summary["decisions"]["accept"],
            "alignment_review_required": alignment_summary.get("review_required", 0),
            "semantic_relation_count": relation_summary["semantic_relation_count"],
        },
    })
    for layer in layers:
        chunks.append({
            "chunk_id": f"fusion:layer:{layer['role']}",
            "text": (
                f"{layer['alias_zh']} ({layer['role']})：{layer['description_zh']} "
                f"标准角色：{layer['standard_role']}；业务角色：{layer.get('business_role_zh', '')}。"
                f"字段数 {layer['field_count']}，"
                f"质量分 {layer['quality_score']}。"
            ),
            "metadata": {
                "role": layer["role"],
                "standard_role": layer["standard_role"],
                "alias_zh": layer["alias_zh"],
                "modality": _modality_for_role(layer["role"]),
                "synthetic": layer["synthetic"],
                "not_for_production": layer["not_for_production"],
            },
        })
    chunks.append({
        "chunk_id": "fusion:rules",
        "text": (
            f"TWM 规则评估共 {rules['rule_eval_count']} 条，"
            f"需要复核 {rules['hit_requires_review_count']} 条，"
            f"critical/high 命中 {rules['critical_or_high_hit_count']} 条。"
        ),
        "metadata": rules,
    })
    chunks.append({
        "chunk_id": "fusion:field-semantics",
        "text": (
            f"字段语义融合共 {len(field_semantics)} 条映射，来源包括标准字段目录、"
            "中文字段别名、值域规则、角色契约 required/recommended 字段和 TWM 状态绑定键。"
            f"自动接受 {alignment_summary['decisions']['accept']} 条，"
            f"需复核 {alignment_summary.get('review_required', 0)} 条。"
        ),
        "metadata": {
            "field_semantic_count": len(field_semantics),
            "alignment_summary": alignment_summary,
            "standard_catalog_match_count": sum(
                1 for item in field_semantics if item.get("match_type") == "standard_field_catalog"
            ),
            "local_extension_count": sum(
                1 for item in field_semantics if item.get("match_type") == "local_extension"
            ),
        },
    })
    chunks.append({
        "chunk_id": "fusion:standard-sources",
        "text": (
            f"标准来源登记共 {source_summary.get('source_count', 0)} 项，"
            f"官方已核验 {source_summary.get('official_verified_count', 0)} 项，"
            f"全文可在线预览/下载或已下载 {source_summary.get('fulltext_available_or_downloaded_count', 0)} 项，"
            f"仍待补齐官方发布源 {source_summary.get('pending_official_source_count', 0)} 项。"
            "该清单用于把 MMFE 字段、值域、本体和规则语义追溯到标准来源。"
        ),
        "metadata": {
            "standard_source_registry_schema": standard_source_registry.get("schema"),
            "summary": source_summary,
            "entries": standard_source_registry.get("entries") or [],
        },
    })
    chunks.append({
        "chunk_id": "fusion:value-domain-audit",
        "text": (
            f"标准值域审计共 {value_domain_audit_summary.get('audit_count', 0)} 个字段值域，"
            f"需复核 {value_domain_audit_summary.get('requires_review_count', 0)} 个。"
            "该审计把字段语义绑定进一步推进到值级标准覆盖率检查。"
        ),
        "metadata": value_domain_audit_summary,
    })
    chunks.append({
        "chunk_id": "fusion:optimization",
        "text": (
            f"多目标优化含 {optimization['objective_count']} 个目标和 "
            f"{optimization['scenario_count']} 个方案；合法可行方案 "
            f"{optimization['legal_feasible_scenario_count']} 个，硬约束阻断 "
            f"{optimization['blocked_scenario_count']} 个。"
        ),
        "metadata": optimization,
    })
    chunks.append({
        "chunk_id": "fusion:semantic-relations",
        "text": (
            f"空间/多模态语义关系共 {relation_summary['semantic_relation_count']} 条，"
            f"其中需规则复核关系 {relation_summary['rule_review_relation_count']} 条。"
            "关系类型覆盖项目-图斑、项目-永久基本农田、项目-生态红线、"
            "项目-用途管制分区、项目-城镇开发边界、项目-遥感瓦片和年度变化-图斑。"
        ),
        "metadata": relation_summary,
    })
    return chunks


def _build_vector_spec(product: dict) -> dict:
    records = []
    for index, chunk in enumerate(product["ai_metadata"]["chunks"]):
        chunk_id = chunk["chunk_id"]
        metadata = dict(chunk.get("metadata") or {})
        metadata.update({
            "product_id": product["product_id"],
            "chunk_id": chunk_id,
            "chunk_index": index,
            "twm_validation_scaffold": True,
        })
        records.append({
            "record_id": f"{product['product_id']}:{chunk_id}",
            "text": chunk["text"],
            "metadata": metadata,
        })
    return {
        "schema": "mmfe.semantic_vector_publish.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "target": "pgvector",
        "collection": "twm_mmfe_semantic_fusion",
        "embedding_model": "deterministic-or-configured-embedder",
        "embedding_required": True,
        "product_id": product["product_id"],
        "source_manifest": {
            "product_type": product["product_type"],
            "version": product["version"],
            "business_output_path": product["business_output"]["path"],
        },
        "records": records,
    }


def _build_publish_plan(product: dict) -> dict:
    return {
        "valid": True,
        "targets": ["iceberg", "stac", "pgvector"],
        "steps": [
            {
                "target": "iceberg",
                "schema": "mmfe.iceberg_publish.v1",
                "depends_on": [],
                "valid": True,
                "spec": {
                    "catalog": "local",
                    "namespace": "gis.fusion",
                    "table": "twm_mmfe_semantic_products",
                    "warehouse_uri": "s3://gis-agent-lakehouse/warehouse",
                    "table_identifier": "local.gis.fusion.twm_mmfe_semantic_products",
                    "product_id": product["product_id"],
                    "business_output": product["business_output"],
                    "spatial_engine": "sedona",
                    "partition_by": ["product_id"],
                },
            },
            {
                "target": "stac",
                "schema": "mmfe.stac_publish.v1",
                "depends_on": ["iceberg"],
                "valid": True,
                "spec": _build_stac_item(product),
            },
            {
                "target": "pgvector",
                "schema": "mmfe.semantic_vector_publish.v1",
                "depends_on": ["iceberg"],
                "valid": True,
                "collection": "twm_mmfe_semantic_fusion",
                "record_count": len(product["ai_metadata"]["chunks"]),
            },
        ],
    }


def _build_stac_item(product: dict) -> dict:
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": product["product_id"],
        "collection": "twm-mmfe-semantic-products",
        "bbox": _dataset_bbox(product),
        "geometry": None,
        "properties": {
            "datetime": product["created_at"],
            "mmfe:product_type": product["product_type"],
            "mmfe:product_version": product["version"],
            "mmfe:layer_count": len(product["mmfe_bundle"]["layer_summaries"]),
            "mmfe:rule_eval_count": product["mmfe_bundle"]["rule_summary"]["rule_eval_count"],
            "mmfe:evidence_count": product["mmfe_bundle"]["evidence_summary"]["evidence_count"],
            "twm:recommended_input": product["mmfe_bundle"]["twm_consumption"]["recommended_twm_input"],
            "twm:not_for_production": True,
        },
        "assets": {
            "business_view": {
                "href": product["business_output"]["path"],
                "type": "text/csv",
                "roles": ["data", "summary"],
            },
            "field_semantics": {
                "href": product["business_outputs"]["field_semantics"],
                "type": "text/csv",
                "roles": ["metadata", "semantic-fields"],
            },
            "value_domain_audit": {
                "href": product["business_outputs"]["value_domain_audit"],
                "type": "text/csv",
                "roles": ["metadata", "value-domain-audit"],
            },
            "standard_sources": {
                "href": product["business_outputs"]["standard_sources"],
                "type": "text/csv",
                "roles": ["metadata", "standard-sources"],
            },
            "standard_source_ingestion_plan": {
                "href": product["business_outputs"].get("standard_source_ingestion_plan")
                or "twm_mmfe_standard_source_ingestion_plan.json",
                "type": "application/json",
                "roles": ["metadata", "standard-source-ingestion-plan"],
            },
            "production_readiness": {
                "href": product["business_outputs"].get("production_readiness")
                or "twm_mmfe_production_readiness.json",
                "type": "application/json",
                "roles": ["metadata", "production-readiness"],
            },
            "semantic_relations": {
                "href": product["business_outputs"]["semantic_relations"],
                "type": "text/csv",
                "roles": ["metadata", "semantic-relations"],
            },
            "twm_input_contract": {
                "href": product["business_outputs"]["twm_input_contract"],
                "type": "application/json",
                "roles": ["metadata", "twm-input-contract"],
            },
            "twm_state_input": {
                "href": product["business_outputs"]["twm_state_input"],
                "type": "application/json",
                "roles": ["data", "twm-state-input"],
            },
            "semantic_graph": {
                "href": product["business_outputs"]["semantic_graph"],
                "type": "application/json",
                "roles": ["metadata", "semantic-graph"],
            },
            "semantic_trace_cards": {
                "href": product["business_outputs"]["semantic_trace_cards"],
                "type": "application/json",
                "roles": ["metadata", "semantic-trace-cards"],
            },
            "semantic_ontology": {
                "href": product["business_outputs"].get("semantic_ontology") or "twm_mmfe_semantic_ontology.json",
                "type": "application/json",
                "roles": ["metadata", "semantic-ontology"],
            },
            "semantic_diagnostic": {
                "href": product["business_outputs"].get("semantic_diagnostic") or "twm_mmfe_semantic_diagnostic.json",
                "type": "application/json",
                "roles": ["metadata", "semantic-diagnostic"],
            },
            "semantic_product": {
                "href": "twm_mmfe_semantic_product.json",
                "type": "application/json",
                "roles": ["metadata", "semantic-product"],
            },
        },
        "links": [],
    }


def _build_semantic_mappings(layers: list[dict], standard_summary: dict, field_semantics: list[dict]) -> list[dict]:
    mappings = []
    for layer in layers:
        mappings.append({
            "source_field": layer["role"],
            "target_field": layer["standard_role"],
            "confidence": 0.95,
            "confidence_band": "high",
            "match_type": "standard_role_contract",
            "explanation": (
                f"{layer['role']} bound to standard role {layer['standard_role']} "
                "through One Map role contract."
            ),
        })
    for item in field_semantics:
        if item.get("match_type") not in {"standard_field_catalog", "standard_alias", "standard_role_contract"}:
            continue
        alignment_score = _safe_json(item.get("alignment_score"), default=None)
        if alignment_score is None:
            alignment_score = {"score": _safe_float(item.get("alignment_score"), 0.0), "decision": item.get("alignment_decision", "")}
        mappings.append({
            "source_field": f"{item['layer_role']}.{item['field_name']}",
            "target_field": f"{item['standard_role']}.{item.get('standard_field') or item['field_name']}",
            "confidence": _safe_float(item["confidence"], 0.0),
            "confidence_band": "high" if _safe_float(item["confidence"], 0.0) >= 0.8 else "medium",
            "match_type": item["match_type"],
            "alignment_score": alignment_score,
            "alignment_decision": item.get("alignment_decision", ""),
            "evidence": _safe_json(item.get("evidence_json"), default=[]),
            "standard_reference": _safe_json(item.get("standard_reference_json"), default={}),
            "explanation": (
                f"{item['field_name']} aligned to {item.get('field_alias_zh') or 'standard field'} "
                f"for role {item['standard_role']}."
            ),
        })
    mappings.append({
        "source_field": "standard_field_catalog",
        "target_field": "field_contracts",
        "confidence": 0.9,
        "confidence_band": "high",
        "match_type": "standard_lifecycle_release",
        "explanation": f"{standard_summary['active_field_count']} active fields provide semantic contracts.",
    })
    return mappings


def _build_bundle_field_contracts(layers: list[dict], standard_summary: dict, field_semantics: list[dict]) -> list[dict]:
    contracts = [
        {
            "field": "twm_role",
            "dtype": "string",
            "semantic_role": "role_binding",
            "nullable_pct": 0.0,
            "source_fields": [layer["role"] for layer in layers],
            "lineage": {"type": "standard_contract"},
        },
        {
            "field": "standard_active_field_count",
            "dtype": "integer",
            "semantic_role": "standard_coverage",
            "nullable_pct": 0.0,
            "value_profile": {"kind": "numeric", "min": standard_summary["active_field_count"]},
            "lineage": {"type": "standard_platform_derivative"},
        },
        {
            "field": "rule_hit_status",
            "dtype": "categorical",
            "semantic_role": "policy_evidence",
            "nullable_pct": 0.0,
            "lineage": {"type": "rule_evaluation"},
        },
    ]
    for field in sorted({item["field_name"] for item in field_semantics if item.get("twm_semantic_key")}):
        matches = [item for item in field_semantics if item["field_name"] == field]
        contracts.append({
            "field": field,
            "dtype": "source_dtype",
            "semantic_role": "twm_state_binding",
            "nullable_pct": None,
            "field_alias_zh": matches[0].get("field_alias_zh", ""),
            "source_fields": [f"{item['layer_role']}.{item['field_name']}" for item in matches],
            "twm_semantic_keys": sorted({item["twm_semantic_key"] for item in matches if item["twm_semantic_key"]}),
            "alignment_decisions": sorted({item.get("alignment_decision", "") for item in matches if item.get("alignment_decision")}),
            "lineage": {"type": "role_contract_binding"},
        })
    return contracts


def _build_feature_semantics(
    layers: list[dict],
    rules: dict,
    optimization: dict,
    relation_summary: dict,
) -> list[dict]:
    features = []
    for index, layer in enumerate(layers[:12]):
        features.append({
            "row_index": index,
            "summary": f"{layer['alias_zh']} -> role={layer['role']}; object_type={_object_type_for_role(layer['role'])}",
            "source_refs": [layer["path"]],
            "quality": "high" if layer["quality_score"] >= 80 else "medium",
        })
    features.append({
        "row_index": "rules",
        "summary": f"Rule hits requiring review: {rules['hit_requires_review_count']}",
        "source_refs": ["tables/rule_evaluation.csv"],
        "quality": "review_required",
    })
    features.append({
        "row_index": "optimization",
        "summary": f"Legal feasible scenarios: {optimization['legal_feasible_scenario_count']}",
        "source_refs": ["optimization/pareto_summary.json"],
        "quality": "high",
    })
    features.append({
        "row_index": "semantic_relations",
        "summary": (
            "Semantic relations: "
            f"{relation_summary.get('semantic_relation_count', 0)} total; "
            f"{relation_summary.get('rule_review_relation_count', 0)} rule-review relations"
        ),
        "source_refs": ["relations/*.csv"],
        "quality": "high",
    })
    return features


def _semantic_trace_focus_nodes() -> list[str]:
    return [
        "field:parcel_current.DLBM",
        "field:parcel_current.QSXZ",
        "field:synthetic_pbf.WDGD",
        "field:synthetic_projects.YDMJ",
        "field:synthetic_eco_redline.LXDM",
        "field:synthetic_planning_zones.GHFQDM",
        "value_domain:gb_t_21010_2017_land_use_code",
        "value_domain:ownership_nature_code",
        "standard_source:gb-t-21010-2017",
        "standard_source:nr-one-map-db-arch-02-survey-monitoring",
        "rule:TWM-FARM-001",
        "rule:TWM-ECO-001",
        "objective:pbf_overlap_m2",
        "objective:eco_overlap_m2",
    ]


def _object_type_for_role(role: str) -> str:
    if role in {"parcel_current", "synthetic_annual_change"}:
        return "parcel"
    if role in {"synthetic_pbf", "synthetic_eco_redline", "synthetic_urban_boundary"}:
        return "control_boundary"
    if role == "synthetic_planning_zones":
        return "planning_zone"
    if role == "synthetic_projects":
        return "project"
    if role == "admin_units":
        return "admin_unit"
    if role == "synthetic_remote_sensing_tiles":
        return "remote_sensing_evidence"
    return "semantic_object"


def _standard_role_for_layer(layer: str) -> str:
    mapping = {
        "parcel_current": "parcel_current",
        "synthetic_annual_change": "parcel_current",
        "synthetic_pbf": "pbf",
        "synthetic_eco_redline": "eco_redline",
        "synthetic_urban_boundary": "urban_boundary",
        "synthetic_planning_zones": "planning_zone",
        "synthetic_projects": "project",
        "admin_units": "admin_unit",
        "synthetic_remote_sensing_tiles": "remote_sensing_evidence",
    }
    return mapping.get(layer, layer)


def _field_requirement(field: str, required: set[str], recommended: set[str]) -> str:
    if field in required:
        return "required"
    if field in recommended:
        return "recommended"
    return "observed"


def _field_aliases(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    aliases = payload.get("field_aliases")
    if isinstance(aliases, dict):
        return aliases
    return payload


def _data_dictionary_field_aliases(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    aliases: dict[str, str] = {}
    fields = payload.get("fields")
    if isinstance(fields, dict):
        for field, meta in fields.items():
            if isinstance(meta, dict) and meta.get("alias_zh"):
                aliases[str(field)] = str(meta["alias_zh"])

    layer_fields = payload.get("layer_fields")
    if isinstance(layer_fields, dict):
        for fields_meta in layer_fields.values():
            if not isinstance(fields_meta, dict):
                continue
            for field, meta in fields_meta.items():
                if isinstance(meta, dict) and meta.get("alias_zh"):
                    aliases.setdefault(str(field), str(meta["alias_zh"]))
    return aliases


def _standard_roles(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    roles = payload.get("roles")
    if isinstance(roles, dict):
        return roles
    return payload


def _relation_semantic_spec(relation_type: str) -> dict:
    specs = {
        "PROJECT_OVERLAPS_PARCEL": {
            "semantic_relation_type": "project_overlaps_parcel",
            "source_object_type": "project",
            "source_field": "project_id",
            "target_object_type": "parcel",
            "target_field": "bsm_norm",
            "target_standard_role": "parcel_current",
            "predicate_zh": "占用现状图斑",
            "business_semantic_zh": "建设项目与现状地类图斑存在空间叠置，可用于项目状态构建、用地构成分析和地类影响计算。",
            "twm_usage": "state_builder_project_parcel_impact",
            "objective_id": "farmland_loss_m2",
            "rule_id": "",
            "evidence_type": "spatial_overlay",
            "requires_rule_review": False,
        },
        "PROJECT_OVERLAPS_PBF": {
            "semantic_relation_type": "project_overlaps_permanent_basic_farmland",
            "source_object_type": "project",
            "source_field": "project_id",
            "target_object_type": "permanent_basic_farmland",
            "target_field": "control_id",
            "target_standard_role": "pbf",
            "predicate_zh": "触碰永久基本农田",
            "business_semantic_zh": "建设项目与永久基本农田保护范围存在正面积叠置，是 TWM 硬约束和方案阻断依据。",
            "twm_usage": "hard_constraint_pbf_overlap",
            "objective_id": "pbf_overlap_m2",
            "rule_id": "TWM-FARM-001",
            "evidence_type": "spatial_overlay",
            "requires_rule_review": True,
        },
        "PROJECT_OVERLAPS_ECO_REDLINE": {
            "semantic_relation_type": "project_overlaps_ecological_redline",
            "source_object_type": "project",
            "source_field": "project_id",
            "target_object_type": "ecological_redline",
            "target_field": "redline_id",
            "target_standard_role": "eco_redline",
            "predicate_zh": "触碰生态保护红线",
            "business_semantic_zh": "建设项目与生态保护红线存在正面积叠置，是生态保护硬约束、规则复核和方案阻断依据。",
            "twm_usage": "hard_constraint_eco_overlap",
            "objective_id": "eco_overlap_m2",
            "rule_id": "TWM-ECO-001",
            "evidence_type": "spatial_overlay",
            "requires_rule_review": True,
        },
        "PROJECT_OVERLAPS_PLANNING_ZONE": {
            "semantic_relation_type": "project_overlaps_planning_zone",
            "source_object_type": "project",
            "source_field": "project_id",
            "target_object_type": "planning_zone",
            "target_field": "plan_zone_id",
            "target_standard_role": "planning_zone",
            "predicate_zh": "落入用途管制分区",
            "business_semantic_zh": "建设项目与用途管制分区存在空间叠置，可用于规划一致性、冲突面积和方案解释。",
            "twm_usage": "planning_consistency_assessment",
            "objective_id": "planning_conflict_m2",
            "rule_id": "TWM-PLAN-001",
            "evidence_type": "spatial_overlay",
            "requires_rule_review": True,
        },
        "PROJECT_OVERLAPS_URBAN_BOUNDARY": {
            "semantic_relation_type": "project_overlaps_urban_development_boundary",
            "source_object_type": "project",
            "source_field": "project_id",
            "target_object_type": "urban_development_boundary",
            "target_field": "boundary_id",
            "target_standard_role": "urban_boundary",
            "predicate_zh": "触碰城镇开发边界",
            "business_semantic_zh": "建设项目与城镇开发边界存在空间叠置，可用于城镇边界内外审查和建设承载解释。",
            "twm_usage": "urban_boundary_consistency",
            "objective_id": "development_area_m2",
            "rule_id": "TWM-URBAN-001",
            "evidence_type": "spatial_overlay",
            "requires_rule_review": True,
        },
        "PROJECT_OBSERVED_BY_RS_TILE": {
            "semantic_relation_type": "project_observed_by_remote_sensing_tile",
            "source_object_type": "project",
            "source_field": "project_id",
            "target_object_type": "remote_sensing_tile",
            "target_field": "tile_id",
            "target_standard_role": "remote_sensing_evidence",
            "predicate_zh": "被遥感瓦片观测覆盖",
            "business_semantic_zh": "建设项目被遥感瓦片覆盖，是多模态影像证据、NDVI/变化强度派生分析和复核证据链入口。",
            "twm_usage": "multimodal_observation_evidence",
            "objective_id": "robustness_score",
            "rule_id": "TWM-EVD-001",
            "evidence_type": "remote_sensing_coverage",
            "requires_rule_review": False,
        },
        "CHANGE_OF_PARCEL": {
            "semantic_relation_type": "annual_change_of_parcel",
            "source_object_type": "annual_change",
            "source_field": "change_id",
            "target_object_type": "parcel",
            "target_field": "bsm_norm",
            "target_standard_role": "parcel_current",
            "predicate_zh": "年度变化关联现状图斑",
            "business_semantic_zh": "年度变化对象与现状图斑通过规范化标识关联，是动态推演和状态快照更新的时间关系。",
            "twm_usage": "dynamic_state_transition",
            "objective_id": "farmland_gain_m2",
            "rule_id": "",
            "evidence_type": "identifier_link",
            "requires_rule_review": False,
        },
    }
    default = {
        "semantic_relation_type": relation_type.lower() or "semantic_relation",
        "source_object_type": "source_object",
        "source_field": "project_id",
        "target_object_type": "target_object",
        "target_field": "",
        "target_standard_role": "",
        "predicate_zh": "关联",
        "business_semantic_zh": "未分类语义关系。",
        "twm_usage": "semantic_context",
        "objective_id": "",
        "rule_id": "",
        "evidence_type": "relation_table",
        "requires_rule_review": False,
    }
    return specs.get(relation_type, default)


def _relation_object_ids(row: dict, spec: dict) -> tuple[str, str]:
    left = row.get(spec.get("source_field", ""), "")
    right = row.get(spec.get("target_field", ""), "")
    if not right:
        for field in ["control_id", "redline_id", "plan_zone_id", "boundary_id", "tile_id", "bsm_norm"]:
            if row.get(field):
                right = row[field]
                break
    return str(left), str(right)


def _relation_strength(
    overlap_area: float,
    overlap_ratio_left: float,
    confidence: float,
    *,
    evidence_type: str = "",
    match_type: str = "",
) -> str:
    if confidence < 0.6:
        return "low_confidence"
    if evidence_type == "identifier_link" and confidence >= 0.95 and match_type.startswith("exact"):
        return "strong"
    if overlap_ratio_left >= 0.5 or overlap_area >= 10000:
        return "strong"
    if overlap_ratio_left >= 0.05 or overlap_area >= 1000:
        return "medium"
    return "weak"


def _build_rule_bindings(standard_rules: dict) -> list[dict]:
    rows = []
    for rule in standard_rules.get("rules") or []:
        target_layer = rule.get("target_layer", "")
        constraint_layer = rule.get("constraint_layer", "")
        rows.append({
            "rule_id": rule.get("rule_id"),
            "rule_name_zh": rule.get("rule_name_zh"),
            "severity": rule.get("severity"),
            "target_layer": target_layer,
            "target_standard_role": _standard_role_for_layer(target_layer) if target_layer else "",
            "constraint_layer": constraint_layer,
            "constraint_standard_role": _standard_role_for_layer(constraint_layer) if constraint_layer else "",
            "logic": rule.get("logic"),
        })
    return rows


def _build_knowledge_graph(
    layers: list[dict],
    field_semantics: list[dict],
    semantic_relations: list[dict],
    rule_bindings: list[dict],
    evidence: dict,
    optimization: dict,
    value_domains: dict,
    standard_source_registry: dict,
) -> dict:
    nodes = []
    edges = []
    seen_nodes = set()
    seen_edges = set()

    def add_node(node_id: str, node_type: str, label: str, **props) -> None:
        if not node_id or node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append({
            "id": node_id,
            "type": node_type,
            "label": label,
            "properties": props,
        })

    def add_edge(source: str, target: str, rel: str, **props) -> None:
        key = (source, target, rel)
        if not source or not target or key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({
            "source": source,
            "target": target,
            "relationship": rel,
            "properties": props,
        })

    add_node("dataset:twm_bishan_demo", "dataset", "国土空间世界模型璧山演示数据包")
    add_node("standard:NR_ONE_MAP_TWM_CORE_2026", "standard", "自然资源一张图 TWM 核心角色标准契约")
    add_node("evidence:multimodal_index", "evidence_index", "多模态证据索引", count=evidence["evidence_count"])
    add_node(
        "optimization:pareto",
        "optimization_summary",
        "TWM 多目标优化 Pareto 摘要",
        objective_count=optimization["objective_count"],
        scenario_count=optimization["scenario_count"],
    )

    for source in standard_source_registry.get("entries") or []:
        source_id = _standard_source_node_id(source)
        add_node(
            source_id,
            "standard_source",
            source.get("title_zh") or source.get("source_name") or source.get("standard_identifier"),
            standard_identifier=source.get("standard_identifier", ""),
            retrieval_status=source.get("retrieval_status", ""),
            access_mode=source.get("access_mode", ""),
            authority=source.get("authority", ""),
            official_url=source.get("official_url", ""),
            not_for_production_gap=source.get("not_for_production_gap", False),
        )
        if source.get("standard_identifier") == "GB/T 21010-2017":
            add_edge("standard:NR_ONE_MAP_TWM_CORE_2026", source_id, "uses_external_standard_source")
        else:
            add_edge("standard:NR_ONE_MAP_TWM_CORE_2026", source_id, "derived_from_source_material")

    for domain_code, domain in _iter_value_domains(value_domains):
        source_id = _value_domain_source_node_id(domain_code)
        add_node(
            f"value_domain:{domain_code}",
            "value_domain",
            domain.get("domain_name_zh") or domain.get("name_zh") or domain_code,
            domain_code=domain_code,
            item_count=len(domain.get("items") or []),
            source_standard=domain.get("source_standard") or domain.get("standard") or "",
            authority_level=domain.get("authority_level") or domain.get("status") or "",
        )
        add_edge(f"value_domain:{domain_code}", "standard:NR_ONE_MAP_TWM_CORE_2026", "declared_in_standard_contract")
        if source_id:
            add_edge(f"value_domain:{domain_code}", source_id, "grounded_by_standard_source")

    for layer in layers:
        layer_id = f"layer:{layer['role']}"
        role_id = f"role:{layer['standard_role']}"
        add_node(
            layer_id,
            "layer",
            layer.get("alias_zh") or layer["role"],
            path=layer["path"],
            object_type=_object_type_for_role(layer["role"]),
            synthetic=layer["synthetic"],
        )
        add_node(
            role_id,
            "standard_role",
            layer.get("standard_role_alias_zh") or layer["standard_role"],
            object_type=_object_type_for_role(layer["role"]),
        )
        add_edge("dataset:twm_bishan_demo", layer_id, "contains_layer")
        add_edge(layer_id, role_id, "binds_to_standard_role", confidence=0.95)
        add_edge(role_id, "standard:NR_ONE_MAP_TWM_CORE_2026", "defined_by_standard")
        for source_id in _role_standard_source_node_ids(layer):
            add_edge(role_id, source_id, "supported_by_standard_source")

    for item in field_semantics:
        if item.get("contract_requirement") not in {"required", "recommended"} and not item.get("twm_semantic_key"):
            continue
        field_id = f"field:{item['layer_role']}.{item['field_name']}"
        add_node(
            field_id,
            "field",
            item.get("field_alias_zh") or item["field_name"],
            field_name=item["field_name"],
            requirement=item["contract_requirement"],
            twm_semantic_key=item.get("twm_semantic_key", ""),
        )
        add_edge(f"layer:{item['layer_role']}", field_id, "has_semantic_field")
        add_edge(field_id, f"role:{item['standard_role']}", "conforms_to_role_contract")
        if item.get("value_domain"):
            add_edge(field_id, f"value_domain:{item['value_domain']}", "uses_value_domain")

    for relation in semantic_relations:
        relation_id = f"relation:{relation['relation_id']}"
        source_id = f"{relation['source_object_type']}:{relation['source_object_id']}"
        target_id = f"{relation['target_object_type']}:{relation['target_object_id']}"
        add_node(
            relation_id,
            "semantic_relation",
            relation.get("predicate_zh") or relation["semantic_relation_type"],
            relation_type=relation["semantic_relation_type"],
            twm_usage=relation["twm_usage"],
            metric_value=relation["metric_value"],
            confidence=relation["confidence"],
            semantic_strength=relation["semantic_strength"],
            rule_id=relation.get("rule_id", ""),
            objective_id=relation.get("objective_id", ""),
        )
        add_node(
            source_id,
            relation["source_object_type"],
            relation["source_object_id"],
        )
        add_node(
            target_id,
            relation["target_object_type"],
            relation["target_object_id"],
            standard_role=relation.get("target_standard_role", ""),
        )
        add_edge(source_id, relation_id, "has_semantic_relation")
        add_edge(
            relation_id,
            target_id,
            relation["semantic_relation_type"],
            confidence=relation["confidence"],
            metric_name=relation["metric_name"],
            metric_value=relation["metric_value"],
            evidence_source=relation["evidence_source"],
        )
        if relation.get("rule_id"):
            add_edge(relation_id, f"rule:{relation['rule_id']}", "supports_rule_evaluation")
        if relation.get("objective_id"):
            add_edge(relation_id, f"objective:{relation['objective_id']}", "supports_optimization_objective")
        add_edge(relation_id, "evidence:multimodal_index", "has_evidence_index_context")

    for rule in rule_bindings:
        rule_id = f"rule:{rule['rule_id']}"
        add_node(
            rule_id,
            "rule",
            rule.get("rule_name_zh") or rule["rule_id"],
            severity=rule.get("severity"),
            logic=rule.get("logic"),
        )
        add_edge(rule_id, "standard:NR_ONE_MAP_TWM_CORE_2026", "governed_by_standard")
        if rule.get("target_layer"):
            add_edge(rule_id, f"layer:{rule['target_layer']}", "checks_target_layer")
        if rule.get("constraint_layer"):
            add_edge(rule_id, f"layer:{rule['constraint_layer']}", "uses_constraint_layer")
        add_edge(rule_id, "evidence:multimodal_index", "produces_review_evidence")

    for objective in optimization.get("objectives", []):
        objective_id = f"objective:{objective['objective_id']}"
        add_node(
            objective_id,
            "optimization_objective",
            objective.get("objective_name_zh") or objective["objective_id"],
            category=objective.get("category"),
            direction=objective.get("direction"),
            hard_constraint=objective.get("hard_constraint"),
        )
        add_edge("optimization:pareto", objective_id, "optimizes")
        if objective["objective_id"] == "pbf_overlap_m2":
            add_edge(objective_id, "layer:synthetic_pbf", "uses_constraint_layer")
        elif objective["objective_id"] == "eco_overlap_m2":
            add_edge(objective_id, "layer:synthetic_eco_redline", "uses_constraint_layer")
        elif objective["objective_id"] == "planning_conflict_m2":
            add_edge(objective_id, "layer:synthetic_planning_zones", "uses_constraint_layer")

    return {
        "schema": "mmfe.semantic_graph.v1",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


def _iter_value_domains(value_domains: dict) -> list[tuple[str, dict]]:
    rows = []
    raw_domains = value_domains.get("domains") if isinstance(value_domains, dict) else {}
    if not isinstance(raw_domains, dict):
        raw_domains = value_domains or {}
    for code, domain in sorted(raw_domains.items()):
        if isinstance(domain, dict):
            rows.append((str(code), domain))
        elif isinstance(domain, list):
            rows.append((str(code), {"items": domain}))
    return rows


def _standard_source_node_id(source: dict) -> str:
    identifier = source.get("standard_identifier") or source.get("source_name") or "source"
    return f"standard_source:{_node_key(identifier)}"


def _value_domain_source_node_id(domain_code: str) -> str:
    if domain_code == "gb_t_21010_2017_land_use_code":
        return "standard_source:gb-t-21010-2017"
    return ""


def _role_standard_source_node_ids(layer: dict) -> list[str]:
    role = layer.get("standard_role")
    if role == "parcel_current":
        return [
            "standard_source:nr-one-map-db-arch-02-survey-monitoring",
            "standard_source:gb-t-21010-2017",
        ]
    if role in {"pbf", "eco_redline"}:
        return ["standard_source:nr-one-map-db-arch-05-safety-baseline"]
    if role in {"planning_zone", "urban_boundary"}:
        return ["standard_source:nr-one-map-db-arch-04-planning"]
    if role == "project":
        return ["standard_source:nr-one-map-db-arch-06-use-control"]
    if role == "remote_sensing_evidence":
        return ["standard_source:nr-one-map-db-arch-10-metadata"]
    return ["standard_source:nr-one-map-db-arch-10-metadata"]


def _node_key(value: str) -> str:
    text = str(value or "").strip().lower()
    replacements = {
        "/": "-",
        " ": "-",
        "_": "-",
        "（": "-",
        "）": "",
        "(": "-",
        ")": "",
        "“": "",
        "”": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = "".join(ch for ch in text if ch.isalnum() or ch in {"-", "."})
    while "--" in text:
        text = text.replace("--", "-")
    return text.strip("-") or "node"


def _modality_for_role(role: str) -> str:
    if "remote_sensing" in role:
        return "remote_sensing_index"
    return "geospatial_vector"


def _adapter_family_for_layer(layer: dict) -> str:
    if layer["role"] == "synthetic_remote_sensing_tiles":
        return "raster_index"
    return "geospatial"


def _media_type_for_layer(layer: dict) -> str:
    if layer.get("data_format") == "GeoJSON":
        return "application/geo+json"
    return "application/octet-stream"


def _quality_score(quality: dict, layers: list[dict]) -> float:
    if isinstance(quality.get("overall_score"), (int, float)):
        return float(quality["overall_score"])
    scores = [layer["quality_score"] for layer in layers if layer.get("quality_score")]
    return round(sum(scores) / len(scores) / 100.0, 4) if scores else 0.85


def _quality_warnings(quality: dict, manifest: dict) -> list[str]:
    warnings = []
    if manifest.get("not_for_production"):
        warnings.append("TWM validation scaffold: not for production use.")
    for item in quality.get("warnings") or []:
        warnings.append(str(item))
    return warnings


def _dataset_bbox(product: dict) -> list[float]:
    boxes = []
    for layer in product["mmfe_bundle"]["layer_summaries"]:
        bbox = layer.get("bbox")
        if isinstance(bbox, list) and len(bbox) == 4:
            boxes.append([float(v) for v in bbox])
    if not boxes:
        return []
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _render_readme(
    product: dict,
    business_view_path: Path,
    field_semantics_path: Path,
    value_domain_audit_path: Path,
    standard_source_path: Path,
    standard_source_ingestion_path: Path,
    production_readiness_path: Path,
    semantic_relations_path: Path,
    twm_input_contract_path: Path,
    twm_state_input_path: Path,
    knowledge_graph_path: Path,
    semantic_trace_cards_path: Path,
    semantic_ontology_path: Path,
    semantic_diagnostic_path: Path,
    semantic_product_path: Path,
    vector_spec_path: Path,
    publish_plan_path: Path,
    stac_item_path: Path,
) -> str:
    bundle = product["mmfe_bundle"]
    diagnostic = bundle.get("semantic_diagnostic_summary") or {}
    standard_ingestion = (bundle.get("standard_source_ingestion_plan") or {}).get("summary") or {}
    production_readiness = (bundle.get("production_readiness") or {}).get("summary") or {}
    return f"""# TWM MMFE Semantic Fusion Bundle

Product: `{product['product_id']}`

This bundle shows how the prepared TWM validation dataset is consumed as an
MMFE multimodal semantic fusion product. The output is not one flattened GIS
table. It is a semantic bundle that connects layers, standards, policy rules,
evidence, review tasks and optimization summaries.

## Outputs

- `{business_view_path.name}`: human-readable one-row business summary.
- `{field_semantics_path.name}`: field-level standard aliases, role contracts and TWM binding keys.
- `{value_domain_audit_path.name}`: value-level standard domain audit for semantically bound fields.
- `{standard_source_path.name}`: auditable registry of standard authorities, source URLs and acquisition status.
- `{standard_source_ingestion_path.name}`: auditable acquisition and extraction plan for standard sources.
- `{production_readiness_path.name}`: source-level production-readiness metadata contract.
- `{semantic_relations_path.name}`: project/parcel/control-line/remote-sensing semantic relations.
- `{twm_input_contract_path.name}`: state-builder contract for TWM consumption.
- `{twm_state_input_path.name}`: TWM-ready state input package derived from the MMFE semantic product.
- `{knowledge_graph_path.name}`: lightweight semantic graph of layers, fields, rules, evidence and objectives.
- `{semantic_trace_cards_path.name}`: compact semantic trace cards for fields, value domains, standards, rules and objectives.
- `{semantic_ontology_path.name}`: compact semantic ontology package for roles, object types, fields, domains, rules and objectives.
- `{semantic_diagnostic_path.name}`: readiness diagnostic for Agent/TWM validation and production gaps.
- `{semantic_product_path.name}`: MMFE semantic fusion product manifest.
- `{vector_spec_path.name}`: pgvector/LanceDB-ready semantic records.
- `{publish_plan_path.name}`: Iceberg/STAC/vector publish plan.
- `{stac_item_path.name}`: STAC discovery item.

## What Was Fused

- Layers: {len(bundle['layer_summaries'])}
- Active standard fields: {bundle['standard_summary']['active_field_count']}
- Standard sources: {bundle['standard_summary']['standard_source_count']}
- Officially verified standard sources: {bundle['standard_summary']['official_verified_source_count']}
- Standard sources pending official release evidence: {bundle['standard_summary']['pending_official_source_count']}
- Standard source ingestion ready: {standard_ingestion.get('ready')}
- Standard source ingestion blocked tasks: {standard_ingestion.get('blocked_task_count')}
- Production metadata ready: {production_readiness.get('production_metadata_ready')}
- Production metadata blocked sources: {production_readiness.get('blocked_source_count')}
- Field semantic mappings: {len(bundle['field_semantics'])}
- Value-domain audits: {bundle['value_domain_audit_summary']['audit_count']}
- Semantic relations: {len(bundle['semantic_relations'])}
- Rule evaluations: {bundle['rule_summary']['rule_eval_count']}
- Review-required rule hits: {bundle['rule_summary']['hit_requires_review_count']}
- Evidence records: {bundle['evidence_summary']['evidence_count']}
- Optimization scenarios: {bundle['optimization_summary']['scenario_count']}
- Legal feasible scenarios: {bundle['optimization_summary']['legal_feasible_scenario_count']}
- Semantic graph: {bundle['semantic_graph']['node_count']} nodes, {bundle['semantic_graph']['edge_count']} edges
- Semantic trace cards: {bundle['semantic_trace_cards']['trace_card_count']}
- Semantic ontology relationships: {(bundle.get('semantic_ontology_summary') or {}).get('relationship_count')}
- Semantic diagnostic status: {diagnostic.get('status')}
- Validation ready: {diagnostic.get('validation_ready')}
- Production ready: {diagnostic.get('production_ready')}

## TWM Consumption Guidance

{bundle['twm_consumption']['guidance_zh']}
"""


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _read_relation_tables(relations_dir: Path) -> dict[str, list[dict]]:
    if not relations_dir.exists():
        return {}
    return {
        path.name: _read_csv(path)
        for path in sorted(relations_dir.glob("*.csv"))
    }


def _read_geojson_property_values(path: Path, field_name: str) -> list[Any]:
    if not path.exists() or not field_name:
        return []
    payload = _read_json(path, default={})
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        return []
    values = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") or {}
        if isinstance(properties, dict):
            values.append(properties.get(field_name))
    return values


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _product_id(data_dir: Path, manifest: dict, layers: list[dict], rules: dict, optimization: dict) -> str:
    basis = "|".join([
        manifest.get("dataset_id", ""),
        manifest.get("version", ""),
        str(data_dir),
        str(len(layers)),
        str(rules.get("rule_eval_count")),
        str(optimization.get("scenario_count")),
    ])
    return "sfp-twm-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def _safe_json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _to_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _first_non_empty(values) -> str:
    for value in values:
        if value:
            return value
    return ""


if __name__ == "__main__":
    main()
