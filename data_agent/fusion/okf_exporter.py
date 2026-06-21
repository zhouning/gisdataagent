"""OKF sidecar exporter for MMFE semantic fusion products.

The exporter turns a semantic product manifest into an Open Knowledge Format
bundle. The semantic product JSON remains the machine contract; OKF is a
human- and agent-readable review/exchange layer.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .semantic_ontology import build_semantic_ontology_package
from .semantic_product_diagnostics import diagnose_semantic_product_readiness
from .twm_state_input import build_twm_state_input_from_semantic_product


OKF_EXPORT_SCHEMA = "mmfe.okf_export.v1"
OKF_VERSION = "0.1"


def build_okf_bundle_from_semantic_product(
    manifest: dict,
    field_semantics: list[dict] | None = None,
    value_domain_audits: list[dict] | None = None,
    standard_sources: list[dict] | None = None,
    semantic_relations: list[dict] | None = None,
    input_contract: dict | None = None,
    state_input: dict | None = None,
    semantic_graph: dict | None = None,
    semantic_trace_cards: dict | None = None,
    semantic_ontology: dict | None = None,
    semantic_diagnostic: dict | None = None,
    timestamp: str | None = None,
) -> dict[str, str]:
    """Build an OKF bundle as relative-path -> markdown content."""
    now = timestamp or datetime.now(timezone.utc).isoformat()
    mmfe_bundle = manifest.get("mmfe_bundle") or {}
    layers = mmfe_bundle.get("layer_summaries") or []
    field_rows = list(field_semantics or mmfe_bundle.get("field_semantics") or [])
    value_domain_rows = list(value_domain_audits or mmfe_bundle.get("value_domain_audits") or [])
    standard_source_rows = list(standard_sources or mmfe_bundle.get("standard_source_rows") or [])
    relation_rows = list(semantic_relations or mmfe_bundle.get("semantic_relations") or [])
    rules = mmfe_bundle.get("rule_bindings") or []
    optimization = mmfe_bundle.get("optimization_summary") or {}
    standard_summary = mmfe_bundle.get("standard_summary") or {}
    twm_contract = input_contract or mmfe_bundle.get("twm_consumption") or {}
    twm_state_input = state_input or _derive_twm_state_input(manifest, relation_rows, twm_contract)
    graph = semantic_graph or mmfe_bundle.get("semantic_graph") or {}
    trace_cards = semantic_trace_cards or mmfe_bundle.get("semantic_trace_cards") or {}
    ontology = semantic_ontology or mmfe_bundle.get("semantic_ontology") or {}
    if not ontology:
        ontology = build_semantic_ontology_package(
            manifest,
            field_semantics=field_rows,
            value_domain_audits=value_domain_rows,
            standard_sources=standard_source_rows,
            semantic_relations=relation_rows,
            state_input=twm_state_input,
        )
    diagnostic = semantic_diagnostic or mmfe_bundle.get("semantic_diagnostic") or {}
    if not diagnostic:
        diagnostic = diagnose_semantic_product_readiness(
            manifest,
            value_domain_audits=value_domain_rows,
            standard_sources=standard_source_rows,
            semantic_relations=relation_rows,
            state_input=twm_state_input,
            semantic_graph=graph,
            semantic_trace_cards=trace_cards,
        )

    fields_by_layer = defaultdict(list)
    for row in field_rows:
        fields_by_layer[row.get("layer_role")].append(row)

    bundle: dict[str, str] = {
        "index.md": _render_root_index(manifest, layers, rules, optimization, graph, ontology, diagnostic),
        "datasets/semantic_product.md": _render_dataset_doc(
            manifest,
            layers,
            rules,
            optimization,
            standard_summary,
            graph,
            ontology,
            now,
            len(field_rows),
            len(value_domain_rows),
            len(relation_rows),
        ),
    }
    if twm_contract:
        bundle["twm/state_input_contract.md"] = _render_twm_contract_doc(twm_contract, now)
    if twm_state_input:
        bundle["twm/state_input.md"] = _render_twm_state_input_doc(twm_state_input, now)
    if standard_summary:
        bundle["standards/semantic_standard.md"] = _render_standard_doc(standard_summary, layers, now)
    if value_domain_rows:
        bundle["standards/value_domain_audit.md"] = _render_value_domain_audit_doc(value_domain_rows, now)
    if standard_source_rows:
        bundle["standards/source_registry.md"] = _render_standard_source_doc(standard_source_rows, now)
    if graph:
        bundle["graphs/semantic_graph.md"] = _render_graph_doc(graph, now)
    if trace_cards:
        bundle["graphs/semantic_trace_cards.md"] = _render_trace_cards_doc(trace_cards, now)
    if ontology:
        bundle["graphs/semantic_ontology.md"] = _render_semantic_ontology_doc(ontology, now)
    if diagnostic:
        bundle["diagnostics/semantic_product_readiness.md"] = _render_semantic_diagnostic_doc(diagnostic, now)

    for source in manifest.get("sources") or []:
        domain = source.get("semantic_domain") or Path(str(source.get("path") or "source")).stem
        bundle[f"sources/{_slug(domain)}.md"] = _render_source_doc(source, now)

    for layer in layers:
        role = layer.get("role") or layer.get("semantic_domain") or "layer"
        bundle[f"layers/{_slug(role)}.md"] = _render_layer_doc(layer, fields_by_layer[role], now)

    for row in field_rows:
        if row.get("contract_requirement") == "observed" and not row.get("twm_semantic_key"):
            continue
        path = f"fields/{_slug(row.get('layer_role', 'layer'))}/{_slug(row.get('field_name', 'field'))}.md"
        bundle[path] = _render_field_doc(row, now)

    for row in relation_rows:
        path = f"relations/{_slug(row.get('semantic_relation_type', 'relation'))}/{_slug(row.get('relation_id', 'relation'))}.md"
        bundle[path] = _render_relation_doc(row, now)

    for rule in rules:
        bundle[f"rules/{_slug(rule.get('rule_id'))}.md"] = _render_rule_doc(rule, now)

    for objective in optimization.get("objectives") or []:
        bundle[f"objectives/{_slug(objective.get('objective_id'))}.md"] = _render_objective_doc(objective, now)

    for chunk in (manifest.get("ai_metadata") or {}).get("chunks") or []:
        chunk_id = chunk.get("chunk_id")
        if chunk_id:
            bundle[f"ai_chunks/{_slug(chunk_id)}.md"] = _render_ai_chunk_doc(chunk, now)

    for directory in _directories(bundle):
        bundle[f"{directory}/index.md"] = _render_directory_index(directory, bundle)
    bundle["log.md"] = _render_log(manifest, now)
    return bundle


def write_okf_bundle(bundle: dict[str, str], out_dir: str | Path) -> str:
    """Write OKF bundle files and return the output directory."""
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    for rel_path, content in bundle.items():
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return str(root)


def export_semantic_product_okf_bundle(
    manifest: dict,
    out_dir: str | Path,
    field_semantics: list[dict] | None = None,
    value_domain_audits: list[dict] | None = None,
    standard_sources: list[dict] | None = None,
    semantic_relations: list[dict] | None = None,
    input_contract: dict | None = None,
    state_input: dict | None = None,
    semantic_graph: dict | None = None,
    semantic_trace_cards: dict | None = None,
    semantic_ontology: dict | None = None,
    semantic_diagnostic: dict | None = None,
) -> dict:
    """Build, write and validate an OKF bundle from a semantic product manifest."""
    bundle = build_okf_bundle_from_semantic_product(
        manifest,
        field_semantics=field_semantics,
        value_domain_audits=value_domain_audits,
        standard_sources=standard_sources,
        semantic_relations=semantic_relations,
        input_contract=input_contract,
        state_input=state_input,
        semantic_graph=semantic_graph,
        semantic_trace_cards=semantic_trace_cards,
        semantic_ontology=semantic_ontology,
        semantic_diagnostic=semantic_diagnostic,
    )
    out = write_okf_bundle(bundle, out_dir)
    validation = validate_okf_bundle(out)
    return {
        "schema": OKF_EXPORT_SCHEMA,
        "okf_version": OKF_VERSION,
        "valid": validation["valid"],
        "errors": validation["errors"],
        "out_dir": out,
        "file_count": len(bundle),
        "concept_count": validation["concept_count"],
        "index_path": str(Path(out) / "index.md"),
        "dataset_doc": str(Path(out) / "datasets" / "semantic_product.md"),
    }


def load_semantic_product_okf_inputs(mmfe_dir: str | Path) -> dict:
    """Load conventional MMFE semantic product sidecar files from a directory."""
    root = Path(mmfe_dir)
    manifest = _read_json(root / "twm_mmfe_semantic_product.json")
    field_path = root / "twm_mmfe_field_semantics.csv"
    value_domain_audit_path = root / "twm_mmfe_value_domain_audit.csv"
    standard_source_path = root / "twm_mmfe_standard_sources.csv"
    relation_path = root / "twm_mmfe_semantic_relations.csv"
    contract_path = root / "twm_state_input_contract.json"
    state_input_path = root / "twm_state_input.json"
    graph_path = root / "twm_mmfe_semantic_graph.json"
    trace_cards_path = root / "twm_mmfe_semantic_trace_cards.json"
    ontology_path = root / "twm_mmfe_semantic_ontology.json"
    diagnostic_path = root / "twm_mmfe_semantic_diagnostic.json"
    return {
        "manifest": manifest,
        "field_semantics": _read_csv(field_path) if field_path.exists() else None,
        "value_domain_audits": _read_csv(value_domain_audit_path) if value_domain_audit_path.exists() else None,
        "standard_sources": _read_csv(standard_source_path) if standard_source_path.exists() else None,
        "semantic_relations": _read_csv(relation_path) if relation_path.exists() else None,
        "input_contract": _read_json(contract_path) if contract_path.exists() else None,
        "state_input": _read_json(state_input_path) if state_input_path.exists() else None,
        "semantic_graph": _read_json(graph_path) if graph_path.exists() else None,
        "semantic_trace_cards": _read_json(trace_cards_path) if trace_cards_path.exists() else None,
        "semantic_ontology": _read_json(ontology_path) if ontology_path.exists() else None,
        "semantic_diagnostic": _read_json(diagnostic_path) if diagnostic_path.exists() else None,
    }


def validate_okf_bundle(out_dir: str | Path) -> dict:
    """Validate the small OKF v0.1 conformance surface used by this exporter."""
    root = Path(out_dir)
    errors = []
    concept_count = 0
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if path.name in {"index.md", "log.md"}:
            continue
        concept_count += 1
        meta = _parse_frontmatter(path.read_text(encoding="utf-8"))
        if not meta:
            errors.append(f"{rel}: missing frontmatter")
        elif not meta.get("type"):
            errors.append(f"{rel}: missing required type")
    return {"valid": not errors, "concept_count": concept_count, "errors": errors}


def _render_root_index(
    manifest: dict,
    layers: list[dict],
    rules: list[dict],
    optimization: dict,
    graph: dict,
    ontology: dict,
    diagnostic: dict,
) -> str:
    graph_summary = ""
    if graph:
        graph_summary = f"* [Semantic graph](/graphs/semantic_graph.md) - {graph.get('node_count')} nodes and {graph.get('edge_count')} edges.\n"
    ontology_summary = ""
    if ontology:
        summary = ontology.get("summary") or {}
        ontology_summary = (
            "* [Semantic ontology](/graphs/semantic_ontology.md) - "
            f"{summary.get('field_count')} fields, {summary.get('relation_type_count')} relation types, "
            f"{summary.get('relationship_count')} concept relationships.\n"
        )
    diagnostic_summary = ""
    if diagnostic:
        status = (diagnostic.get("summary") or {}).get("status")
        diagnostic_summary = f"* [Readiness diagnostic](/diagnostics/semantic_product_readiness.md) - `{status}`.\n"
    return f"""---
okf_version: "{OKF_VERSION}"
type: OKF Bundle Index
title: MMFE OKF Bundle
description: Human- and agent-readable OKF sidecar for an MMFE semantic fusion product.
tags: [okf, mmfe, semantic-fusion]
timestamp: {manifest.get('created_at') or datetime.now(timezone.utc).isoformat()}
---

# MMFE OKF Bundle

This OKF bundle is a sidecar view of semantic fusion product
`{manifest.get('product_id')}`. The authoritative machine contract remains the
semantic product JSON; this bundle is for review, traversal, Git diffs and
agent-readable context.

# Contents

* [Dataset summary](/datasets/semantic_product.md) - semantic fusion product overview.
{graph_summary}{ontology_summary}{diagnostic_summary}* [Sources](sources/) - source concepts.
* [Layers](layers/) - {len(layers)} semantic layer concepts.
* [Rules](rules/) - {len(rules)} governance and policy rule concepts.
* [Objectives](objectives/) - {len(optimization.get('objectives') or [])} optimization objective concepts.
* [Fields](fields/) - required, recommended and semantically bound field concepts.
* [AI chunks](ai_chunks/) - retrieval chunks from the semantic product.
"""


def _render_dataset_doc(
    manifest: dict,
    layers: list[dict],
    rules: list[dict],
    optimization: dict,
    standard_summary: dict,
    graph: dict,
    ontology: dict,
    timestamp: str,
    field_count: int,
    value_domain_audit_count: int,
    relation_count: int,
) -> str:
    ontology_summary = ontology.get("summary") or {}
    return _frontmatter(
        {
            "type": "MMFE Semantic Product",
            "title": manifest.get("product_id") or "MMFE semantic product",
            "description": "MMFE semantic fusion product exported as OKF.",
            "resource": (manifest.get("business_output") or {}).get("path"),
            "tags": ["mmfe", "semantic-product"],
            "timestamp": timestamp,
            "product_id": manifest.get("product_id"),
        }
    ) + f"""
# Summary

This concept describes MMFE semantic fusion product `{manifest.get('product_id')}`.

| Item | Count |
| --- | ---: |
| Sources | {len(manifest.get('sources') or [])} |
| Layers | {len(layers)} |
| Field semantic mappings | {field_count} |
| Value-domain audits | {value_domain_audit_count} |
| Semantic relations | {relation_count} |
| Active standard fields | {standard_summary.get('active_field_count', '')} |
| Rule bindings | {len(rules)} |
| Optimization objectives | {optimization.get('objective_count', '')} |
| Optimization scenarios | {optimization.get('scenario_count', '')} |
| Semantic graph nodes | {graph.get('node_count', '')} |
| Semantic graph edges | {graph.get('edge_count', '')} |
| Ontology fields | {ontology_summary.get('field_count', '')} |
| Ontology value domains | {ontology_summary.get('value_domain_count', '')} |
| Ontology relation types | {ontology_summary.get('relation_type_count', '')} |
| Ontology concept relationships | {ontology_summary.get('relationship_count', '')} |

# Sources

{_markdown_list(_source_link(source) for source in manifest.get('sources') or [])}

# Layers

{_markdown_list(_layer_link(layer) for layer in layers)}

# Rules

{_markdown_list(_rule_link(rule) for rule in rules)}

# Optimization Objectives

{_markdown_list(_objective_link(objective) for objective in optimization.get('objectives') or [])}
"""


def _render_source_doc(source: dict, timestamp: str) -> str:
    domain = source.get("semantic_domain") or Path(str(source.get("path") or "source")).stem
    hints = [str(item) for item in source.get("semantic_hints") or [] if item]
    columns = source.get("columns") or []
    return _frontmatter(
        {
            "type": "MMFE Source",
            "title": domain,
            "description": hints[2] if len(hints) > 2 else (hints[0] if hints else ""),
            "resource": source.get("path"),
            "tags": ["source", source.get("modality"), source.get("adapter_family")],
            "timestamp": timestamp,
            "semantic_domain": domain,
        }
    ) + f"""
# Source Profile

| Property | Value |
| --- | --- |
| Path | `{source.get('path')}` |
| Data type | `{source.get('data_type')}` |
| Modality | `{source.get('modality')}` |
| Media type | `{source.get('media_type')}` |
| Adapter family | `{source.get('adapter_family')}` |
| CRS | `{source.get('crs')}` |
| Semantic domain | `{domain}` |

# Semantic Hints

{_markdown_list(hints)}

# Columns

{_markdown_list(f"`{column}`" for column in columns[:50])}
"""


def _render_layer_doc(layer: dict, field_rows: list[dict], timestamp: str) -> str:
    role = layer.get("role") or layer.get("semantic_domain") or "layer"
    required = [row for row in field_rows if row.get("contract_requirement") == "required"]
    recommended = [row for row in field_rows if row.get("contract_requirement") == "recommended"]
    bound = [row for row in field_rows if row.get("twm_semantic_key")]
    return _frontmatter(
        {
            "type": "MMFE Layer",
            "title": layer.get("alias_zh") or role,
            "description": layer.get("description_zh"),
            "resource": layer.get("path"),
            "tags": ["layer", layer.get("standard_role"), _safe_obj_type(layer)],
            "timestamp": timestamp,
            "role": role,
            "standard_role": layer.get("standard_role"),
            "object_type": _safe_obj_type(layer),
            "synthetic": layer.get("synthetic"),
            "not_for_production": layer.get("not_for_production"),
        }
    ) + f"""
# Role Binding

| Property | Value |
| --- | --- |
| Physical role | `{role}` |
| Standard role | `{layer.get('standard_role')}` |
| Business role | {layer.get('business_role_zh') or ''} |
| Object type | `{_safe_obj_type(layer)}` |
| Source path | `{layer.get('path')}` |
| CRS | `{layer.get('crs')}` |
| Field count | {layer.get('field_count')} |
| Quality score | {layer.get('quality_score')} |

# TWM Binding

{_dict_table(layer.get('twm_binding') or {})}

# Required Fields

{_field_table(required)}

# Recommended Fields

{_field_table(recommended)}

# Semantically Bound Fields

{_field_table(bound)}
"""


def _render_field_doc(row: dict, timestamp: str) -> str:
    layer = row.get("layer_role")
    field = row.get("field_name")
    return _frontmatter(
        {
            "type": "MMFE Field",
            "title": row.get("field_alias_zh") or field,
            "description": f"{field} field in {layer}.",
            "tags": ["field", row.get("standard_role"), row.get("contract_requirement")],
            "timestamp": timestamp,
            "layer_role": layer,
            "field_name": field,
            "standard_role": row.get("standard_role"),
            "standard_field": row.get("standard_field"),
            "twm_semantic_key": row.get("twm_semantic_key"),
            "alignment_decision": row.get("alignment_decision"),
        }
    ) + f"""
# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [{layer}](/layers/{_slug(layer)}.md) |
| Field name | `{field}` |
| Alias | {row.get('field_alias_zh') or ''} |
| Standard field | `{row.get('standard_field') or field}` |
| Standard role | `{row.get('standard_role')}` |
| Object type | `{row.get('object_type')}` |
| Requirement | `{row.get('contract_requirement')}` |
| Semantic key | `{row.get('twm_semantic_key') or ''}` |
| Lifecycle status | `{row.get('lifecycle_status')}` |
| Standard version | `{row.get('standard_version')}` |
| Match type | `{row.get('match_type')}` |
| Confidence | {row.get('confidence')} |
| Alignment score | {row.get('alignment_score') or ''} |
| Alignment decision | `{row.get('alignment_decision') or ''}` |
| Requires review | `{row.get('requires_review') or ''}` |
| Value domain | `{row.get('value_domain') or ''}` |
| Value domain status | `{row.get('value_domain_status') or ''}` |

# Domain Or Rule

```json
{_pretty_json(_safe_json(row.get('domain_or_rule'), {}))}
```

# Alignment Evidence

```json
{_pretty_json(_safe_json(row.get('evidence_json'), []))}
```
"""


def _render_relation_doc(row: dict, timestamp: str) -> str:
    relation_id = row.get("relation_id")
    relation_type = row.get("semantic_relation_type") or row.get("relation_type")
    title = f"{row.get('predicate_zh') or relation_type}: {row.get('source_object_id')} -> {row.get('target_object_id')}"
    return _frontmatter(
        {
            "type": "MMFE Semantic Relation",
            "title": title,
            "description": row.get("business_semantic_zh"),
            "tags": ["relation", row.get("target_standard_role"), row.get("twm_usage")],
            "timestamp": timestamp,
            "relation_id": relation_id,
            "semantic_relation_type": relation_type,
            "source_object_type": row.get("source_object_type"),
            "target_object_type": row.get("target_object_type"),
            "rule_id": row.get("rule_id"),
            "objective_id": row.get("objective_id"),
        }
    ) + f"""
# Semantic Relation

| Property | Value |
| --- | --- |
| Relation ID | `{relation_id}` |
| Relation type | `{relation_type}` |
| Predicate | {row.get('predicate_zh') or ''} |
| Source object | `{row.get('source_object_type')}` / `{row.get('source_object_id')}` |
| Target object | `{row.get('target_object_type')}` / `{row.get('target_object_id')}` |
| Target standard role | `{row.get('target_standard_role') or ''}` |
| TWM usage | `{row.get('twm_usage') or ''}` |
| Metric | `{row.get('metric_name') or ''}` = {row.get('metric_value') or ''} |
| Overlap area m2 | {row.get('overlap_area_m2') or ''} |
| Left overlap ratio | {row.get('overlap_ratio_left') or ''} |
| Right overlap ratio | {row.get('overlap_ratio_right') or ''} |
| Confidence | {row.get('confidence') or ''} |
| Semantic strength | `{row.get('semantic_strength') or ''}` |
| Requires rule review | `{row.get('requires_rule_review') or ''}` |
| Rule | `{row.get('rule_id') or ''}` |
| Objective | `{row.get('objective_id') or ''}` |
| Evidence source | `{row.get('evidence_source') or ''}` |

# Business Meaning

{row.get('business_semantic_zh') or ''}
"""


def _render_rule_doc(rule: dict, timestamp: str) -> str:
    return _frontmatter(
        {
            "type": "MMFE Rule",
            "title": rule.get("rule_name_zh") or rule.get("rule_id"),
            "description": rule.get("logic"),
            "tags": ["rule", rule.get("severity"), "mmfe"],
            "timestamp": timestamp,
            "rule_id": rule.get("rule_id"),
            "severity": rule.get("severity"),
        }
    ) + f"""
# Rule

| Property | Value |
| --- | --- |
| Rule ID | `{rule.get('rule_id')}` |
| Name | {rule.get('rule_name_zh')} |
| Severity | `{rule.get('severity')}` |
| Target layer | {_optional_layer_link(rule.get('target_layer'))} |
| Target standard role | `{rule.get('target_standard_role')}` |
| Constraint layer | {_optional_layer_link(rule.get('constraint_layer'))} |
| Constraint standard role | `{rule.get('constraint_standard_role')}` |

# Logic

```text
{rule.get('logic') or ''}
```
"""


def _render_objective_doc(objective: dict, timestamp: str) -> str:
    return _frontmatter(
        {
            "type": "Optimization Objective",
            "title": objective.get("objective_name_zh") or objective.get("objective_id"),
            "description": objective.get("description_zh"),
            "tags": ["optimization", objective.get("category")],
            "timestamp": timestamp,
            "objective_id": objective.get("objective_id"),
            "hard_constraint": objective.get("hard_constraint"),
        }
    ) + f"""
# Objective

| Property | Value |
| --- | --- |
| Objective ID | `{objective.get('objective_id')}` |
| Name | {objective.get('objective_name_zh')} |
| Category | `{objective.get('category')}` |
| Direction | `{objective.get('direction')}` |
| Unit | `{objective.get('unit')}` |
| Weight | {objective.get('weight')} |
| Hard constraint | {objective.get('hard_constraint')} |

# Description

{objective.get('description_zh') or ''}
"""


def _render_twm_contract_doc(contract: dict, timestamp: str) -> str:
    bindings = contract.get("role_bindings") or []
    return _frontmatter(
        {
            "type": "TWM State Input Contract",
            "title": "TWM state input contract",
            "description": "Consumption contract for TWM state building from MMFE semantic products.",
            "tags": ["twm", "state-builder", "mmfe", "contract"],
            "timestamp": timestamp,
            "recommended_twm_input": contract.get("recommended_twm_input"),
        }
    ) + f"""
# Consumption Policy

| Property | Value |
| --- | --- |
| Recommended TWM input | `{contract.get('recommended_twm_input')}` |
| Raw data usage | `{contract.get('raw_data_usage')}` |
| Semantic product usage | `{contract.get('semantic_product_usage')}` |
| State builder policy | `{contract.get('state_builder_policy')}` |

{contract.get('guidance_zh') or ''}

# Role Bindings

| Role | Standard Role | Object Type | Source | TWM Binding |
| --- | --- | --- | --- | --- |
{_role_binding_rows(bindings)}
"""


def _render_twm_state_input_doc(state_input: dict, timestamp: str) -> str:
    summary = state_input.get("semantic_relation_summary") or {}
    components = state_input.get("state_components") or {}
    optimization = state_input.get("optimization_interface") or {}
    production = state_input.get("production_policy") or {}
    source = state_input.get("source_product") or {}
    return _frontmatter(
        {
            "type": "TWM State Input",
            "title": "TWM state input",
            "description": "Downstream state-builder input derived from an MMFE semantic product.",
            "tags": ["twm", "state-builder", "mmfe", "semantic-relations"],
            "timestamp": timestamp,
            "schema": state_input.get("schema"),
            "product_id": source.get("product_id"),
            "not_for_production": production.get("not_for_production"),
        }
    ) + f"""
# State Input Summary

| Property | Value |
| --- | --- |
| Schema | `{state_input.get('schema')}` |
| Product ID | `{source.get('product_id')}` |
| State builder policy | `{state_input.get('state_builder_policy')}` |
| Role count | {len(state_input.get('object_role_registry') or [])} |
| Relation count | {summary.get('total_relation_count')} |
| Relation type count | {summary.get('registered_relation_type_count')} |
| Objective binding count | {len(optimization.get('objective_bindings') or [])} |
| Not for production | `{production.get('not_for_production')}` |

# Production Policy

{production.get('policy_zh') or ''}

# State Components

{_state_component_table(components)}

# Semantic Relation Registry

{_relation_registry_table(state_input.get('semantic_relation_registry') or [])}

# Optimization Bindings

{_objective_binding_table(optimization.get('objective_bindings') or [])}

# Warnings

{_markdown_list(state_input.get('warnings') or [])}
"""


def _render_standard_doc(summary: dict, layers: list[dict], timestamp: str) -> str:
    return _frontmatter(
        {
            "type": "Standard Contract",
            "title": "MMFE semantic standard contract",
            "description": summary.get("source_note_zh"),
            "tags": ["standard", "mmfe"],
            "timestamp": timestamp,
            "standard_version": summary.get("standard_version"),
            "authority_level": summary.get("authority_level"),
        }
    ) + f"""
# Standard Summary

| Property | Value |
| --- | --- |
| Standard version | `{summary.get('standard_version')}` |
| Active field count | {summary.get('active_field_count')} |
| Alias count | {summary.get('alias_count')} |
| Role contract count | {summary.get('role_contract_count')} |
| Authority level | `{summary.get('authority_level')}` |

{summary.get('source_note_zh') or ''}

# Bound Layers

{_markdown_list(_layer_link(layer) for layer in layers)}
"""


def _render_value_domain_audit_doc(rows: list[dict], timestamp: str) -> str:
    status_counts = defaultdict(int)
    for row in rows:
        status_counts[row.get("audit_status") or "unknown"] += 1
    return _frontmatter(
        {
            "type": "Value Domain Audit",
            "title": "MMFE value-domain audit",
            "description": "Observed field values checked against standard value domains.",
            "tags": ["standard", "value-domain", "mmfe"],
            "timestamp": timestamp,
            "audit_count": len(rows),
        }
    ) + f"""
# Value-Domain Audit Summary

| Property | Value |
| --- | ---: |
| Audit count | {len(rows)} |
| Review-required audits | {sum(1 for row in rows if row.get('audit_status') != 'valid')} |

# Status Distribution

{_counter_table(row.get('audit_status') for row in rows)}

# Audited Fields

{_value_domain_audit_table(rows)}
"""


def _render_standard_source_doc(rows: list[dict], timestamp: str) -> str:
    return _frontmatter(
        {
            "type": "Standard Source Registry",
            "title": "MMFE standard source registry",
            "description": "Auditable source registry for standards used by MMFE semantic fusion.",
            "tags": ["standard", "source-registry", "mmfe"],
            "timestamp": timestamp,
            "source_count": len(rows),
        }
    ) + f"""
# Standard Source Summary

| Property | Value |
| --- | ---: |
| Source count | {len(rows)} |
| Officially verified | {sum(1 for row in rows if _is_official_source(row))} |
| Full text available or downloaded | {sum(1 for row in rows if row.get('retrieval_status') in {'official_fulltext_available', 'downloaded_fulltext'})} |
| Pending official source evidence | {sum(1 for row in rows if row.get('retrieval_status') in {'local_expert_material_available', 'official_source_pending'})} |

# Retrieval Status

{_counter_table(row.get('retrieval_status') for row in rows)}

# Sources

{_standard_source_table(rows)}
"""


def _render_graph_doc(graph: dict, timestamp: str) -> str:
    return _frontmatter(
        {
            "type": "MMFE Semantic Graph",
            "title": "MMFE semantic graph",
            "description": "Lightweight graph extracted from the MMFE semantic product.",
            "tags": ["graph", "mmfe", "semantic-fusion"],
            "timestamp": timestamp,
            "node_count": graph.get("node_count"),
            "edge_count": graph.get("edge_count"),
        }
    ) + f"""
# Graph Summary

| Property | Value |
| --- | ---: |
| Nodes | {graph.get('node_count')} |
| Edges | {graph.get('edge_count')} |

# Node Types

{_counter_table(node.get('type') for node in graph.get('nodes') or [])}

# Relationship Types

{_counter_table(edge.get('relationship') for edge in graph.get('edges') or [])}
"""


def _render_trace_cards_doc(trace_cards: dict, timestamp: str) -> str:
    cards = trace_cards.get("cards") or []
    return _frontmatter(
        {
            "type": "MMFE Semantic Trace Cards",
            "title": "MMFE semantic trace cards",
            "description": "Compact semantic graph trace cards for key MMFE nodes.",
            "tags": ["graph", "trace", "mmfe", "semantic-fusion"],
            "timestamp": timestamp,
            "trace_card_count": trace_cards.get("trace_card_count"),
        }
    ) + f"""
# Trace Summary

| Property | Value |
| --- | ---: |
| Trace cards | {trace_cards.get('trace_card_count')} |
| Standard-source paths | {trace_cards.get('standard_source_path_count')} |
| Source graph nodes | {trace_cards.get('source_graph_node_count')} |
| Source graph edges | {trace_cards.get('source_graph_edge_count')} |

# Focus Types

{_dict_counter_table(trace_cards.get('focus_type_distribution') or {})}

# Trace Cards

{_trace_card_table(cards)}
"""


def _render_semantic_ontology_doc(ontology: dict, timestamp: str) -> str:
    concepts = ontology.get("concepts") or {}
    summary = ontology.get("summary") or {}
    return _frontmatter(
        {
            "type": "MMFE Semantic Ontology",
            "title": "MMFE semantic ontology",
            "description": "Compact ontology package derived from an MMFE semantic product.",
            "tags": ["ontology", "mmfe", "semantic-fusion"],
            "timestamp": timestamp,
            "schema": ontology.get("schema"),
            "relationship_count": summary.get("relationship_count"),
        }
    ) + f"""
# Ontology Summary

| Property | Value |
| --- | ---: |
| Standard roles | {summary.get('standard_role_count')} |
| Object types | {summary.get('object_type_count')} |
| Fields | {summary.get('field_count')} |
| Semantic keys | {summary.get('semantic_key_count')} |
| Value domains | {summary.get('value_domain_count')} |
| Audited value domains | {summary.get('audited_value_domain_count')} |
| Standard sources | {summary.get('standard_source_count')} |
| Official standard sources | {summary.get('official_standard_source_count')} |
| Relation types | {summary.get('relation_type_count')} |
| Rules | {summary.get('rule_count')} |
| Optimization objectives | {summary.get('optimization_objective_count')} |
| Concept relationships | {summary.get('relationship_count')} |
| Accepted fields | {summary.get('accepted_field_count')} |
| Review fields | {summary.get('review_field_count')} |
| Governed fields | {summary.get('governed_field_count')} |
| Runtime bindings | {summary.get('runtime_binding_count')} |
| TWM required runtime roles | {summary.get('twm_required_runtime_role_count')} |
| Official verified sources | {summary.get('official_verified_source_count')} |
| Production gaps | {summary.get('production_gap_count')} |

# Standard Roles

{_ontology_role_table(concepts.get('standard_roles') or [])}

# Value Domains

{_ontology_value_domain_table(concepts.get('value_domains') or [])}

# Relation Types

{_ontology_relation_type_table(concepts.get('relation_types') or [])}

# Rules

{_ontology_rule_table(concepts.get('rules') or [])}

# Optimization Objectives

{_ontology_objective_table(concepts.get('optimization_objectives') or [])}
"""


def _render_semantic_diagnostic_doc(diagnostic: dict, timestamp: str) -> str:
    summary = diagnostic.get("summary") or {}
    capabilities = diagnostic.get("capabilities") or {}
    return _frontmatter(
        {
            "type": "MMFE Semantic Product Diagnostic",
            "title": "MMFE semantic product readiness diagnostic",
            "description": "Readiness diagnostic for Agent/TWM validation and production gaps.",
            "tags": ["diagnostic", "readiness", "mmfe", "twm"],
            "timestamp": timestamp,
            "schema": diagnostic.get("schema"),
            "product_id": diagnostic.get("product_id"),
            "status": summary.get("status"),
            "validation_ready": summary.get("validation_ready"),
            "production_ready": summary.get("production_ready"),
        }
    ) + f"""
# Readiness Summary

| Property | Value |
| --- | --- |
| Status | `{summary.get('status')}` |
| Readiness score | {summary.get('readiness_score')} |
| Validation ready | `{summary.get('validation_ready')}` |
| Production ready | `{summary.get('production_ready')}` |
| Checks | {summary.get('check_count')} |
| Passed | {summary.get('pass_count')} |
| Warnings | {summary.get('warn_count')} |
| Failed | {summary.get('fail_count')} |

# Capability Summary

| Capability | Value |
| --- | ---: |
| Layers | {capabilities.get('layer_count')} |
| Field semantics | {capabilities.get('field_semantic_count')} |
| Semantic relations | {capabilities.get('semantic_relation_count')} |
| Semantic graph nodes | {capabilities.get('semantic_graph_node_count')} |
| Semantic graph edges | {capabilities.get('semantic_graph_edge_count')} |
| Trace cards | {capabilities.get('trace_card_count')} |
| Objectives | {capabilities.get('objective_count')} |
| AI chunks | {capabilities.get('ai_chunk_count')} |

# Checks

{_diagnostic_check_table(diagnostic.get('checks') or [])}

# Top Gaps

{_diagnostic_gap_table(diagnostic.get('top_gaps') or [])}

# Recommendations

{_markdown_list(diagnostic.get('recommendations_zh') or [])}
"""


def _render_ai_chunk_doc(chunk: dict, timestamp: str) -> str:
    chunk_id = chunk.get("chunk_id")
    return _frontmatter(
        {
            "type": "MMFE AI Chunk",
            "title": chunk_id,
            "description": "AI retrieval chunk from an MMFE semantic product.",
            "tags": ["ai-chunk", "retrieval", "mmfe"],
            "timestamp": timestamp,
            "chunk_id": chunk_id,
        }
    ) + f"""
# Text

{chunk.get('text') or ''}

# Metadata

```json
{_pretty_json(chunk.get('metadata') or {})}
```
"""


def _render_directory_index(directory: str, bundle: dict[str, str]) -> str:
    entries = []
    prefix = f"{directory}/"
    seen = set()
    for path in sorted(bundle):
        if not path.startswith(prefix) or path == f"{directory}/index.md":
            continue
        rest = path[len(prefix):]
        if "/" in rest:
            child = f"{rest.split('/', 1)[0]}/"
            if child not in seen:
                seen.add(child)
                entries.append((child, child.rstrip("/"), "Subdirectory"))
            continue
        meta = _parse_frontmatter(bundle[path])
        entries.append((rest, meta.get("title") or Path(path).stem, meta.get("description") or meta.get("type") or ""))
    title = directory.replace("_", " ").title()
    lines = [f"# {title}", ""]
    for rel_path, title, description in entries:
        lines.append(f"* [{title}]({rel_path}) - {description}")
    lines.append("")
    return "\n".join(lines)


def _render_log(manifest: dict, timestamp: str) -> str:
    return f"""# Bundle Update Log

## {timestamp[:10]}
* **Creation**: Exported OKF sidecar bundle from MMFE semantic product `{manifest.get('product_id')}`.
"""


def _directories(bundle: dict[str, str]) -> list[str]:
    dirs = set()
    for path in bundle:
        parent = Path(path).parent.as_posix()
        while parent and parent != ".":
            dirs.add(parent)
            parent = Path(parent).parent.as_posix()
    return sorted(dirs)


def _frontmatter(data: dict) -> str:
    lines = ["---"]
    for key, value in data.items():
        if value is None or value == "":
            continue
        lines.append(f"{key}: {_yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_yaml_scalar(item) for item in value if item) + "]"
    return _yaml_scalar(value)


def _yaml_scalar(value: Any) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _parse_frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    meta = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"')
    return meta


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _markdown_list(items) -> str:
    rows = [item for item in items if item]
    if not rows:
        return "_None._"
    return "\n".join(f"* {item}" for item in rows)


def _source_link(source: dict) -> str:
    domain = source.get("semantic_domain") or Path(str(source.get("path") or "source")).stem
    return f"[{domain}](/sources/{_slug(domain)}.md)"


def _layer_link(layer: dict) -> str:
    role = layer.get("role") or "layer"
    return f"[{layer.get('alias_zh') or role}](/layers/{_slug(role)}.md)"


def _rule_link(rule: dict) -> str:
    return f"[{rule.get('rule_name_zh') or rule.get('rule_id')}](/rules/{_slug(rule.get('rule_id'))}.md)"


def _objective_link(objective: dict) -> str:
    return (
        f"[{objective.get('objective_name_zh') or objective.get('objective_id')}]"
        f"(/objectives/{_slug(objective.get('objective_id'))}.md)"
    )


def _optional_layer_link(layer: str | None) -> str:
    if not layer:
        return ""
    if layer.startswith("synthetic_") or layer in {"parcel_current", "admin_units"}:
        return f"[{layer}](/layers/{_slug(layer)}.md)"
    return f"`{layer}`"


def _field_table(rows: list[dict]) -> str:
    if not rows:
        return "_None._"
    lines = ["| Field | Alias | Requirement | Semantic key |", "| --- | --- | --- | --- |"]
    for row in rows:
        field = row.get("field_name")
        layer = row.get("layer_role")
        lines.append(
            f"| [{field}](/fields/{_slug(layer)}/{_slug(field)}.md) "
            f"| {row.get('field_alias_zh') or ''} "
            f"| `{row.get('contract_requirement')}` "
            f"| `{row.get('twm_semantic_key') or ''}` |"
        )
    return "\n".join(lines)


def _dict_table(values: dict) -> str:
    if not values:
        return "_No explicit semantic binding fields._"
    lines = ["| Semantic key | Source field |", "| --- | --- |"]
    for key, value in values.items():
        lines.append(f"| `{key}` | `{value}` |")
    return "\n".join(lines)


def _role_binding_rows(bindings: list[dict]) -> str:
    rows = []
    for binding in bindings:
        binding_text = ", ".join(f"{key}={value}" for key, value in (binding.get("twm_binding") or {}).items())
        role = binding.get("role")
        rows.append(
            f"| [{role}](/layers/{_slug(role)}.md) "
            f"| `{binding.get('standard_role')}` "
            f"| `{binding.get('object_type')}` "
            f"| `{binding.get('source_path')}` "
            f"| {binding_text or ''} |"
        )
    return "\n".join(rows)


def _state_component_table(components: dict) -> str:
    if not components:
        return "_None._"
    lines = ["| Component | Relations | Objectives | Rules |", "| --- | ---: | --- | --- |"]
    for name, component in components.items():
        lines.append(
            f"| `{name}` "
            f"| {component.get('relation_count', 0)} "
            f"| {', '.join(f'`{item}`' for item in component.get('objective_ids') or [])} "
            f"| {', '.join(f'`{item}`' for item in component.get('rule_ids') or [])} |"
        )
    return "\n".join(lines)


def _relation_registry_table(registry: list[dict]) -> str:
    if not registry:
        return "_None._"
    lines = [
        "| Relation Type | Count | TWM Usage | Objectives | Rules |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for item in registry:
        lines.append(
            f"| `{item.get('semantic_relation_type')}` "
            f"| {item.get('relation_count', 0)} "
            f"| {', '.join(f'`{usage}`' for usage in item.get('twm_usages') or [])} "
            f"| {', '.join(f'`{objective}`' for objective in item.get('objective_ids') or [])} "
            f"| {', '.join(f'`{rule}`' for rule in item.get('rule_ids') or [])} |"
        )
    return "\n".join(lines)


def _objective_binding_table(bindings: list[dict]) -> str:
    if not bindings:
        return "_None._"
    lines = [
        "| Objective | Hard Constraint | Relations | Relation Types |",
        "| --- | --- | ---: | --- |",
    ]
    for item in bindings:
        lines.append(
            f"| `{item.get('objective_id')}` "
            f"| `{item.get('hard_constraint')}` "
            f"| {item.get('relation_count', 0)} "
            f"| {', '.join(f'`{rel}`' for rel in item.get('relation_types') or [])} |"
        )
    return "\n".join(lines)


def _value_domain_audit_table(rows: list[dict]) -> str:
    if not rows:
        return "_None._"
    lines = [
        "| Layer | Field | Domain | Status | Coverage | Unknown |",
        "| --- | --- | --- | --- | ---: | ---: |",
    ]
    for row in rows:
        layer = row.get("layer_role") or ""
        field = row.get("field_name") or ""
        lines.append(
            f"| [{layer}](/layers/{_slug(layer)}.md) "
            f"| `{field}` "
            f"| `{row.get('domain') or ''}` "
            f"| `{row.get('audit_status') or ''}` "
            f"| {row.get('coverage') or ''} "
            f"| {row.get('unknown_count') or 0} |"
        )
    return "\n".join(lines)


def _ontology_role_table(rows: list[dict]) -> str:
    if not rows:
        return "_None._"
    lines = [
        "| Role | Standard Role | Object Type | Fields | Review Fields |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for row in rows:
        role = row.get("role") or row.get("standard_role") or ""
        lines.append(
            f"| [{role}](/layers/{_slug(role)}.md) "
            f"| `{row.get('standard_role') or ''}` "
            f"| `{row.get('object_type') or ''}` "
            f"| {row.get('field_count') or 0} "
            f"| {row.get('review_field_count') or 0} |"
        )
    return "\n".join(lines)


def _ontology_value_domain_table(rows: list[dict]) -> str:
    if not rows:
        return "_None._"
    lines = [
        "| Domain | Audited Fields | Coverage Mean | Unknown Values | Standard Sources |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.get('domain') or ''}` "
            f"| {row.get('audited_field_count') or 0} "
            f"| {row.get('coverage_mean') if row.get('coverage_mean') is not None else ''} "
            f"| {row.get('unknown_value_count') or 0} "
            f"| {', '.join(f'`{item}`' for item in row.get('standard_source_ids') or [])} |"
        )
    return "\n".join(lines)


def _ontology_relation_type_table(rows: list[dict]) -> str:
    if not rows:
        return "_None._"
    lines = [
        "| Relation Type | Count | TWM Usage | Objectives | Rules |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.get('relation_type') or ''}` "
            f"| {row.get('relation_count') or 0} "
            f"| {', '.join(f'`{item}`' for item in row.get('twm_usages') or [])} "
            f"| {', '.join(f'`{item}`' for item in row.get('objective_ids') or [])} "
            f"| {', '.join(f'`{item}`' for item in row.get('rule_ids') or [])} |"
        )
    return "\n".join(lines)


def _ontology_rule_table(rows: list[dict]) -> str:
    if not rows:
        return "_None._"
    lines = [
        "| Rule | Severity | Target | Constraint | Relation Types |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        rule_id = row.get("rule_id") or ""
        lines.append(
            f"| [{rule_id}](/rules/{_slug(rule_id)}.md) "
            f"| `{row.get('severity') or ''}` "
            f"| `{row.get('target_layer') or ''}` "
            f"| `{row.get('constraint_layer') or ''}` "
            f"| {', '.join(f'`{Path(item).name}`' for item in row.get('relation_type_ids') or [])} |"
        )
    return "\n".join(lines)


def _ontology_objective_table(rows: list[dict]) -> str:
    if not rows:
        return "_None._"
    lines = [
        "| Objective | Category | Direction | Hard Constraint | Relation Types |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        objective_id = row.get("objective_id") or ""
        lines.append(
            f"| [{objective_id}](/objectives/{_slug(objective_id)}.md) "
            f"| `{row.get('category') or ''}` "
            f"| `{row.get('direction') or ''}` "
            f"| `{row.get('hard_constraint')}` "
            f"| {', '.join(f'`{Path(item).name}`' for item in row.get('relation_type_ids') or [])} |"
        )
    return "\n".join(lines)


def _standard_source_table(rows: list[dict]) -> str:
    if not rows:
        return "_None._"
    lines = [
        "| Source | Identifier | Status | Access | Authority | Official URL |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        official_url = row.get("official_url") or ""
        link = f"[official]({official_url})" if official_url else ""
        lines.append(
            f"| {row.get('title_zh') or row.get('source_name') or ''} "
            f"| `{row.get('standard_identifier') or ''}` "
            f"| `{row.get('retrieval_status') or ''}` "
            f"| `{row.get('access_mode') or ''}` "
            f"| {row.get('authority') or ''} "
            f"| {link} |"
        )
    return "\n".join(lines)


def _is_official_source(row: dict) -> bool:
    status = str(row.get("retrieval_status") or "")
    return status.startswith("official_") or bool(row.get("official_url"))


def _counter_table(values) -> str:
    counts = defaultdict(int)
    for value in values:
        if value:
            counts[value] += 1
    if not counts:
        return "_None._"
    lines = ["| Value | Count |", "| --- | ---: |"]
    for value, count in sorted(counts.items()):
        lines.append(f"| `{value}` | {count} |")
    return "\n".join(lines)


def _dict_counter_table(values: dict) -> str:
    if not values:
        return "_None._"
    lines = ["| Value | Count |", "| --- | ---: |"]
    for value, count in sorted(values.items()):
        lines.append(f"| `{value}` | {count} |")
    return "\n".join(lines)


def _trace_card_table(cards: list[dict]) -> str:
    if not cards:
        return "_None._"
    lines = [
        "| Node | Type | Standard Paths | Value Domains | Rules | Objectives | Summary |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for card in cards:
        node = card.get("node") or {}
        lines.append(
            f"| `{node.get('id') or ''}` "
            f"| `{node.get('type') or ''}` "
            f"| {len(card.get('standard_source_paths') or [])} "
            f"| {len(card.get('value_domain_paths') or [])} "
            f"| {len(card.get('rule_paths') or [])} "
            f"| {len(card.get('objective_paths') or [])} "
            f"| {card.get('summary_zh') or ''} |"
        )
    return "\n".join(lines)


def _diagnostic_check_table(checks: list[dict]) -> str:
    if not checks:
        return "_None._"
    lines = [
        "| Check | Status | Severity | Required | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for check in checks:
        evidence = check.get("evidence") or {}
        compact = ", ".join(
            f"{key}={value}"
            for key, value in list(evidence.items())[:4]
            if value not in (None, "", [], {})
        )
        lines.append(
            f"| `{check.get('check_id')}` "
            f"| `{check.get('status')}` "
            f"| `{check.get('severity')}` "
            f"| `{check.get('required_for_validation')}` "
            f"| {compact} |"
        )
    return "\n".join(lines)


def _diagnostic_gap_table(gaps: list[dict]) -> str:
    if not gaps:
        return "_None._"
    lines = [
        "| Gap | Status | Severity | Message |",
        "| --- | --- | --- | --- |",
    ]
    for gap in gaps:
        lines.append(
            f"| `{gap.get('check_id')}` "
            f"| `{gap.get('status')}` "
            f"| `{gap.get('severity')}` "
            f"| {gap.get('message_zh') or ''} |"
        )
    return "\n".join(lines)


def _safe_json(text: str | None, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _pretty_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _safe_obj_type(layer: dict) -> str:
    if layer.get("object_type"):
        return layer["object_type"]
    role = layer.get("role")
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
    return layer.get("standard_role") or "semantic_object"


def _derive_twm_state_input(manifest: dict, relations: list[dict], contract: dict) -> dict:
    try:
        return build_twm_state_input_from_semantic_product(
            manifest,
            semantic_relations=relations,
            input_contract=contract,
        )
    except Exception:
        return {}


def _slug(value: str | None) -> str:
    text = str(value or "item").strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text)
    return text.strip("-") or "item"
